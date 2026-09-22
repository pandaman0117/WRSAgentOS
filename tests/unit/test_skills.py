from dataclasses import replace

import pytest
from conftest import action

from wrs_agent.actions import ActionExecutor
from wrs_agent.bindings import load_bindings
from wrs_agent.errors import AgentError
from wrs_agent.runtime import validate_plan
from wrs_agent.schemas import CapabilitySnapshot, Empty, Plan, Step
from wrs_agent.skills import SKILLS, Skill, SkillSpec, VirtualWorld, lookup_skills

BINDINGS = load_bindings()[1]
MOTION = ("observe", "move_named_pose", "move_relative")


def caps():
    return {
        "wrs": CapabilitySnapshot(skills={"observe": 1, "move_named_pose": 1}),
        "tts": CapabilitySnapshot(backend="mock_tts", skills={"speak": 1}),
    }


def motion_caps():
    """WRS 节点实际注册的三个技能。"""
    return {"wrs": CapabilitySnapshot(skills={n: SKILLS[n].spec.version for n in MOTION})}


def test_lookup_offers_every_available_skill_and_filters_by_capability():
    """选哪个技能由模型判断，所以可用的都要交出去，不能替它猜。"""
    offered = {s.name for s in lookup_skills(caps(), BINDINGS)}
    assert offered == {"observe", "move_named_pose", "speak"}
    motion = lookup_skills(motion_caps(), dict.fromkeys(MOTION, "wrs"))
    assert {s.name for s in motion} == set(MOTION)
    assert lookup_skills({}, BINDINGS) == []


def test_relative_motion_describes_all_six_directions():
    """方向语义必须在 description 里，那是模型真正会读的地方。"""
    description = SKILLS["move_relative"].spec.description
    assert all(word in description for word in ("up/down", "left/right", "forward/back"))


def test_registry_is_returned_by_copy():
    first = lookup_skills(caps(), BINDINGS)
    first[0].preconditions.append("untrusted")
    assert "untrusted" not in lookup_skills(caps(), BINDINGS)[0].preconditions


def test_whole_plan_rejects_unsupported_before_partial_execution():
    plan = Plan(
        steps=[
            Step(step_id="say", skill="speak", args={"text": "starting"}),
            Step(step_id="pick", skill="pick", args={"object": "A"}),
        ]
    )
    with pytest.raises(ValueError, match="skill_not_on_node"):
        validate_plan(plan, caps(), BINDINGS)


def test_verification_must_depend_on_the_motion_it_verifies():
    """A live GLM plan proposed exactly this: the observe step carried no dependency, so the
    arm's order came from lock arrival rather than the plan."""
    plan = Plan(
        steps=[
            Step(step_id="move_to_B", skill="move_named_pose", args={"pose": "B"}),
            Step(step_id="verify", skill="observe"),
        ]
    )
    with pytest.raises(ValueError, match="unordered_resource_conflict"):
        validate_plan(plan)
    ordered = Plan(
        steps=[
            Step(step_id="move_to_B", skill="move_named_pose", args={"pose": "B"}),
            Step(step_id="verify", skill="observe", depends_on=["move_to_B"]),
        ]
    )
    assert validate_plan(ordered) == ordered


def test_conflict_names_the_two_steps_and_the_resource():
    """「有两个步骤占用同一资源」不可操作：12 步的计划里没人知道该给谁加 depends_on。"""
    plan = Plan(
        steps=[
            Step(step_id="say", skill="speak", args={"text": "starting"}),
            Step(step_id="move_to_B", skill="move_named_pose", args={"pose": "B"}),
            Step(step_id="verify", skill="observe"),
        ]
    )
    with pytest.raises(AgentError) as caught:
        validate_plan(plan)
    message = caught.value.error.message
    assert "move_to_B" in message and "verify" in message and "arm" in message
    # 只点名真正冲突的那一对；speak 占的是 speaker，和它们本来就能并行。
    assert "say" not in message and len(message) <= 240


def test_ordering_follows_the_whole_chain_not_just_direct_dependencies():
    """observe and verify never name each other, yet the chain already orders the arm."""
    plan = Plan(
        steps=[
            Step(step_id="look", skill="observe"),
            Step(step_id="pick", skill="pick", args={"object": "A"}, depends_on=["look"]),
            Step(
                step_id="check",
                skill="verify",
                args={"object": "A", "target": "B"},
                depends_on=["pick"],
            ),
        ]
    )
    assert validate_plan(plan) == plan


def test_separate_resources_still_run_without_an_imposed_order():
    """Speech holds the speaker, not the arm, so the runtime may overlap them by design."""
    plan = Plan(
        steps=[
            Step(step_id="say", skill="speak", args={"text": "starting"}),
            Step(step_id="look", skill="observe"),
        ]
    )
    assert validate_plan(plan) == plan


def test_skill_contracts_describe_abilities_without_deployment_defaults():
    assert all(s.description and s.instructions for s in (e.spec for e in SKILLS.values()))
    assert all("node" not in s.model_dump() for s in (entry.spec for entry in SKILLS.values()))
    assert SKILLS["pick"].spec.recovery == ["observe_once"]


@pytest.mark.parametrize("name", ["robot", "speech"])
def test_bundled_guides_are_available_as_package_resources(name):
    from importlib.resources import files

    content = files("wrs_agent.skills").joinpath(name, "SKILL.md").read_text(encoding="utf-8")
    assert content.startswith(f"---\nname: {name}\ndescription: ")
    assert len(content.split("---", 2)) == 3
    assert all(
        s.instructions == content
        for s in (entry.spec for entry in SKILLS.values())
        if (s.name == "speak") == (name == "speech")
    )


def test_missing_binding_cannot_fall_back_to_a_skill_default():
    assert lookup_skills(caps(), {}) == []
    plan = Plan(steps=[Step(step_id="move", skill="move_named_pose", args={"pose": "B"})])
    with pytest.raises(ValueError, match="provider_not_found"):
        validate_plan(plan, caps(), {})


def test_skill_lookup_and_plan_validation_use_the_same_explicit_binding():
    available = {"robot_lab": caps()["wrs"]}
    bindings = {"move_named_pose": "robot_lab"}
    assert [s.name for s in lookup_skills(available, bindings)] == ["move_named_pose"]
    plan = Plan(steps=[Step(step_id="move", skill="move_named_pose", args={"pose": "B"})])
    assert validate_plan(plan, available, bindings) == plan


async def test_local_registration_drives_validation_capabilities_and_execution(tmp_path):
    calls = []

    def mark(state, args, stop, progress):
        assert isinstance(args, Empty)
        calls.append("mark")
        state.pose = "B"
        return state.pose == "B"

    spec = SkillSpec(
        name="mark",
        description="Reviewed local test handler",
        parameters=Empty.model_json_schema(),
        required_capabilities=["mark"],
        resources=["arm"],
        preconditions=[],
        verification="test_state",
        interrupt_mode="controlled_stop",
    )
    env = ActionExecutor(
        tmp_path / "registered.sqlite3",
        state=VirtualWorld({}),
        skills={"mark": Skill(spec, Empty, mark)},
        backend="test",
        duration=0.01,
    )
    try:
        assert env.capabilities().skills == {"mark": 1}
        assert env.capabilities().resources == ["arm"]
        assert not (await env.submit(action(env, "pick", {"object": "A"}))).accepted
        assert not (await env.submit(action(env, "mark", {"unexpected": "argument"}))).accepted
        assert calls == []
        request = action(env, "mark", {})
        assert (await env.submit(request)).accepted
        await env.runner
        assert env.status(request.action_id).state == "SUCCEEDED"
        assert (await env.submit(request)).accepted
        assert calls == ["mark"] and env.snapshot().data.robot.pose == "B"
    finally:
        await env.close()


@pytest.mark.parametrize("mismatch", ["name", "schema", "handler"])
def test_invalid_registration_rejected_before_opening_journal(tmp_path, mismatch):
    entry = SKILLS["observe"]
    if mismatch == "name":
        entry = replace(entry, spec=entry.spec.model_copy(update={"name": "wrong"}))
    elif mismatch == "schema":
        entry = replace(entry, arguments=SKILLS["pick"].arguments)
    else:
        entry = replace(entry, handler=None)
    path = tmp_path / "must-not-open.sqlite3"
    with pytest.raises(ValueError, match="invalid_skill_registration"):
        ActionExecutor(path, state=VirtualWorld({}), skills={"observe": entry}, backend="test")
    assert not path.exists()
