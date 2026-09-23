import threading

import pytest
from conftest import action, control, eventually

from wrs_agent.actions import SkillFailure
from wrs_agent.env import wrs as adapter
from wrs_agent.errors import AgentError
from wrs_agent.skills import validate_skill


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"dz": 0.0},
        {"dx": 0.101},
        {"dy": -0.101},
        {"dx": 0.08, "dy": 0.08},
        {"dz": float("nan")},
        {"dz": float("inf")},
        {"dz": "0.02"},
        {"frame": "screen", "dz": 0.02},
    ],
)
def test_relative_move_rejects_invalid_or_unbounded_offset(args):
    with pytest.raises(AgentError, match="invalid_arguments"):
        validate_skill("move_relative", 1, args)


def test_relative_move_has_meter_defaults_and_combined_bound():
    args = validate_skill("move_relative", 1, {"dx": 0.06, "dz": 0.08})
    assert (args.dx, args.dy, args.dz) == (0.06, 0.0, 0.08)


async def test_unreachable_ik_is_effect_free_failure_and_deduplicated(tmp_path, monkeypatch):
    calls = []

    class Model:
        def read(self):
            return {
                "qs": [0.0] * 6,
                "tcp_name": "flange",
                "tcp_pos": [0.0] * 3,
                "tcp_rotmat": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "observed_at_ns": 1,
                "valid": True,
            }

        def begin_relative(self, delta, count):
            calls.append(delta)
            raise SkillFailure("relative_target_unreachable")

    monkeypatch.setattr(adapter, "VirtualModel", Model)
    env = await adapter.make_wrs_environment(tmp_path / "unreachable.sqlite3")
    try:
        before = env.snapshot()
        request = action(env, "move_relative", {"dz": 0.02})
        await env.submit(request)
        await env.runner
        result = env.status(request.action_id)
        assert result.state == "FAILED" and result.reason == "relative_target_unreachable"
        assert (await env.submit(request)).status == result
        after = env.snapshot()
        assert after.data == before.data and after.state_version == before.state_version
        assert after.stop_confirmed and after.admission == "OPEN"
        assert calls == [(0.0, 0.0, 0.02)]
    finally:
        await env.close()


async def test_stop_during_ik_never_applies_its_late_solution(tmp_path, monkeypatch):
    entered, released = threading.Event(), threading.Event()
    updates = []

    class Model:
        def read(self):
            return {
                "qs": [0.0] * 6,
                "tcp_name": "flange",
                "tcp_pos": [0.0] * 3,
                "tcp_rotmat": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "observed_at_ns": 1,
                "valid": True,
            }

        def begin_relative(self, delta, count):
            entered.set()
            assert released.wait(3)

        def step(self, index):
            updates.append(index)
            return self.read()

    monkeypatch.setattr(adapter, "VirtualModel", Model)
    env = await adapter.make_wrs_environment(tmp_path / "cancel.sqlite3")
    try:
        request = action(env, "move_relative", {"dz": 0.02})
        await env.submit(request)
        await eventually(entered.is_set, bool)
        receipt = await env.hold(control(env))
        assert receipt.accepted and receipt.phase == "STOPPING"
        assert not env.snapshot().stop_confirmed
        released.set()
        await env.runner
        assert env.status(request.action_id).state == "CANCELLED"
        assert env.snapshot().stop_confirmed and updates == []
        assert env.snapshot().data.robot.pose == "home"
    finally:
        released.set()
        await env.close()
