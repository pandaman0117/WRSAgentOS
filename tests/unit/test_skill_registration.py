"""Registration boundaries and pure validation of newly supplied skill definitions."""

import asyncio
from dataclasses import replace

import pytest

from wrs_agent import step
from wrs_agent.bindings import DEFAULT, load_bindings
from wrs_agent.nodes.tts.backend import make_mock_tts
from wrs_agent.schemas import Empty, SkillCheck
from wrs_agent.skills import Skill, resolve_routes


def definition(name):
    return Skill(
        name=name,
        description="Local reviewed action",
        resources=["speaker"],
        preconditions=[],
        verification="test",
        arguments=Empty,
    )


async def test_dynamic_registration_is_atomic_copies_metadata_and_never_replaces(tmp_path):
    executor = make_mock_tts(tmp_path / "speech.db", duration=0)
    added = definition("mark").bind(lambda *args: True)
    try:
        revision = executor.skill_revision
        executor.add_skills(added)
        assert executor.skill_revision == revision + 1
        added.spec.resources.append("changed-outside")
        assert executor.features().specs["mark"].resources == ["speaker"]
        before = executor.features()
        with pytest.raises(ValueError, match="duplicate_skill"):
            executor.add_skills(definition("new").bind(lambda *a: True), added)
        assert executor.features() == before and "new" not in executor.skills
        with pytest.raises(ValueError, match="invalid_skill_registration"):
            executor.add_skills(definition("unbound"))
        with pytest.raises(ValueError, match="duplicate_skill"):
            executor.add_skills(added, added)
        with pytest.raises(RuntimeError, match="outside_owner"):
            await asyncio.to_thread(executor.add_skills, definition("thread").bind(lambda *a: True))
        assert executor.features() == before
        check = SkillCheck(boot_id=executor.boot_id, steps=[step("mark").model_copy(
            update={"version": 1},
        )])
        assert executor.validate(check).count == 1
        assert executor.executions == 0 and not executor.leases and not executor.records
        with pytest.raises(ValueError, match="instance_changed"):
            executor.validate(check.model_copy(update={"boot_id": "old"}))
    finally:
        await executor.close()
    with pytest.raises(RuntimeError, match="outside_owner"):
        executor.add_skills(definition("closed").bind(lambda *a: True))


async def test_registration_rejects_capacity_before_mutation(tmp_path):
    executor = make_mock_tts(tmp_path / "speech.db", duration=0)
    try:
        with pytest.raises(ValueError, match="invalid_skill_count"):
            executor.add_skills(*(definition(f"mark{i}").bind(lambda *a: True) for i in range(64)))
        assert executor.features().skills == {"speak": 1}
    finally:
        await executor.close()


def test_nodes_only_config_and_optional_unknown_to_client_skill_override(tmp_path):
    nodes, routes = load_bindings()
    assert routes == {} and nodes["wrs"]["actions"]
    config = tmp_path / "nodes.toml"
    config.write_text(
        DEFAULT.read_text(encoding="utf-8") + '\n[skills]\ncustom_action = "wrs"\n',
        encoding="utf-8",
    )
    assert load_bindings(config)[1] == {"custom_action": "wrs"}
    routes, ambiguous = resolve_routes({"left": ["move"], "right": ["move"], "tts": ["speak"]})
    assert routes == {"speak": "tts"} and ambiguous == {"move"}
    routes, ambiguous = resolve_routes({"right": ["move"]}, {"move": "left"})
    assert routes["move"] == "left" and not ambiguous  # Explicit pins never fail over.


def test_client_and_agent_launcher_do_not_import_concrete_skill_packages(tmp_path):
    import subprocess

    from wrs_agent.processes import NO_WINDOW, python_command

    code = (
        "import sys; import wrs_agent; import wrs_agent.nodes.serve; "
        "from wrs_agent.nodes.agent import AgentNode; "
        "assert not any(n.startswith(('wrs_agent.skills.robot', 'wrs_agent.skills.speech')) "
        "for n in sys.modules)"
    )
    script = tmp_path / "import_client.py"
    script.write_text(code, encoding="utf-8")
    result = subprocess.run(
        python_command(script), capture_output=True, text=True,
        timeout=10, creationflags=NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr


def test_skill_has_one_parameter_source_and_detached_wire_metadata():
    from wrs_agent.skills.robot import PickArgs

    resources = ["arm"]
    skill = Skill(
        name="select", arguments=Empty, handler=lambda *args: True,
        description="Select an object", resources=resources, verification="test",
    )
    resources.append("external")
    changed = replace(skill, arguments=PickArgs, version=2)
    assert changed.spec.parameters == PickArgs.model_json_schema()
    assert changed.spec.version == 2 and changed.spec.resources == ["arm"]
    wire = changed.spec
    wire.parameters.clear()
    wire.resources.append("external")
    assert changed.spec.parameters == PickArgs.model_json_schema()
    assert changed.spec.resources == ["arm"]
    assert "required_features" not in changed.spec.model_dump()
    assert "interrupt_mode" not in changed.spec.model_dump()
    assert skill.spec.parameters == Empty.model_json_schema() and skill.version == 1


def test_shared_contract_binding_keeps_each_implementation_independent():
    definition_only = definition("mark")
    first, second = (lambda *args: True), (lambda *args: False)
    a, b = definition_only.bind(first), definition_only.bind(second)
    assert definition_only.handler is None
    assert a.handler is first and b.handler is second
    assert a.spec == b.spec == definition_only.spec
    with pytest.raises(ValueError, match="invalid_skill_handler"):
        definition_only.bind(None)
    with pytest.raises(ValueError, match="invalid_skill_arguments"):
        replace(definition_only, arguments=dict)
