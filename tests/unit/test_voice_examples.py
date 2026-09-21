"""Input examples preserve control priority; these tests never open audio devices."""

import asyncio
import runpy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from examples.voice.commands import addressed_text
from wrs_agent import ActionState, System


@pytest.fixture
def listener():
    return runpy.run_path("examples/voice/08_listen_goals.py")


@pytest.mark.parametrize("text,expected", [
    ("机器人，移动到 B。", "移动到 B"),
    ("机器人，停止。", "停止"),
    ("停止。", "停止"),
    ("停止播报", "停止播报"),
    ("状态", "状态"),
    ("移动到 B", None),
    ("正在上移。", None),
    ("语音任务系统已启动。", None),
    ("机器人，", None),
])
def test_goal_requires_address_but_control_does_not(text, expected):
    assert addressed_text(text) == expected


@pytest.mark.parametrize("text", ["停止", "停止播报", "机器人，停止", "状态"])
async def test_control_bypasses_model_observer_and_robot_queries(listener, text):
    system = SimpleNamespace(send_text=AsyncMock(return_value=SimpleNamespace(
        disposition="stop", accepted=True, phase="STOPPING", overview=None)))
    assert await listener["submit_text"](system, text, None, observing=True) is None
    system.send_text.assert_awaited_once_with(addressed_text(text))


@pytest.mark.parametrize("text", ["机器人，不要停止", "机器人，‘停止’", "机器人，好的"])
async def test_ambiguous_or_quoted_control_never_becomes_a_goal(listener, text):
    await listener["submit_text"](SimpleNamespace(), text, None)


@pytest.mark.parametrize("boot,epoch", [("new-instance", 1), ("old-instance", 2)])
async def test_late_recording_cannot_authorize_goal(listener, boot, epoch):
    current = SimpleNamespace(boot_id=boot, control_epoch=epoch)
    captured = SimpleNamespace(boot_id="old-instance", control_epoch=1)
    system = SimpleNamespace(snapshot=AsyncMock(return_value=current))
    assert await listener["submit_text"](system, "机器人，移动到 B", captured) is None


def idle_system(**updates):
    current = SimpleNamespace(boot_id="robot", control_epoch=1,
                              admission="OPEN", stop_confirmed=True)
    overview = dict(task_id=None, state="IDLE", planning="IDLE")
    overview.update(updates)
    return current, SimpleNamespace(
        snapshot=AsyncMock(return_value=current),
        status=AsyncMock(return_value=overview),
        send_text=AsyncMock(return_value=SimpleNamespace(accepted=True, request_id="goal-1")),
        allow_actions=AsyncMock(return_value=SimpleNamespace(accepted=True)),
    )


@pytest.mark.parametrize("updates,observing", [
    ({"planning": "WAITING"}, False),
    ({"task_id": "active", "state": "RUNNING"}, False),
    ({}, True),
])
async def test_busy_input_does_not_queue_another_goal(listener, updates, observing):
    captured, system = idle_system(**updates)
    assert await listener["submit_text"](
        system, "机器人，移动到 B", captured, observing=observing,
    ) is None
    system.send_text.assert_not_awaited()


@pytest.mark.parametrize("admission,confirmed", [("UNKNOWN", True), ("HELD", False)])
async def test_unconfirmed_robot_cannot_be_reopened_by_voice(listener, admission, confirmed):
    captured, system = idle_system()
    captured.admission, captured.stop_confirmed = admission, confirmed
    assert await listener["submit_text"](system, "机器人，移动到 B", captured) is None
    system.allow_actions.assert_not_awaited()
    system.send_text.assert_not_awaited()


async def test_fresh_goal_after_confirmed_stop_does_not_wait_for_planner(listener):
    captured, system = idle_system(task_id="old", state="CANCELLED")
    captured.admission = "HELD"
    result = await listener["submit_text"](system, "机器人，移动到 B", captured)
    assert result == "goal-1"
    system.allow_actions.assert_awaited_once_with(node="wrs")
    system.send_text.assert_awaited_once_with("移动到 B")


async def test_observation_timeout_does_not_cancel_execution(listener, capsys):
    handle = SimpleNamespace(wait=AsyncMock(side_effect=TimeoutError))
    system = SimpleNamespace(planning=lambda request_id: handle)
    await listener["show_result"](system, "goal-1")
    assert "远端任务未取消" in capsys.readouterr().out


@pytest.mark.parametrize("path", [
    "examples/tts/01_start_node.py", "examples/voice/05_start_wrs_voice.py",
])
@pytest.mark.parametrize("state", [ActionState.FAILED, ActionState.UNKNOWN])
async def test_failed_greeting_does_not_announce_readiness(monkeypatch, capsys, path, state):
    entry = runpy.run_path(path)
    action = SimpleNamespace(wait=AsyncMock(return_value=SimpleNamespace(
        state=state, reason="output_not_confirmed")))
    system = SimpleNamespace(action=AsyncMock(return_value=action))

    @asynccontextmanager
    async def launch(**kwargs):
        assert kwargs["tts_backend"] == "qwen"
        assert entry["GREETING"] in kwargs["tts_prepared_texts"]
        yield system

    monkeypatch.setattr(System, "launch", launch)
    with pytest.raises(RuntimeError, match="启动播报未完成"):
        await entry["main"]()
    system.action.assert_awaited_once_with("speak", text=entry["GREETING"])
    assert "就绪：" not in capsys.readouterr().out


async def test_successful_greeting_uses_normal_action_and_keeps_node_running(monkeypatch):
    entry = runpy.run_path("examples/tts/01_start_node.py")
    finished, closed = asyncio.Event(), asyncio.Event()

    async def wait(**kwargs):
        finished.set()
        return SimpleNamespace(state=ActionState.SUCCEEDED, reason="")

    @asynccontextmanager
    async def launch(**kwargs):
        try:
            yield SimpleNamespace(action=AsyncMock(return_value=SimpleNamespace(wait=wait)))
        finally:
            closed.set()

    monkeypatch.setattr(System, "launch", launch)
    server = asyncio.create_task(entry["main"]())
    try:
        await asyncio.wait_for(finished.wait(), 1)
        assert not server.done()
    finally:
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)
    assert closed.is_set()


async def test_missing_glm_config_exits_before_launching_nodes(monkeypatch):
    entry = runpy.run_path("examples/voice/07_start_glm_voice.py")
    def unexpected_launch(**kwargs):
        raise AssertionError("Missing configuration must not start any node")

    monkeypatch.setitem(entry["main"].__globals__, "LocalStack", unexpected_launch)
    monkeypatch.delenv("GLM_MODEL", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GLM 配置错误"):
        await entry["main"]()


def test_sync_launch_forwards_speech_configuration_without_loading_models(monkeypatch):
    from wrs_agent import sync

    captured = {}

    @asynccontextmanager
    async def launch(**kwargs):
        captured.update(kwargs)
        yield SimpleNamespace()

    monkeypatch.setattr(System, "launch", launch)
    with sync.launch(tts_backend="qwen", tts_python="dedicated-python",
                     tts_prepared_texts=["语音播报节点已启动。"]):
        pass
    assert captured["tts_backend"] == "qwen"
    assert captured["tts_python"] == "dedicated-python"
    assert captured["tts_prepared_texts"] == ["语音播报节点已启动。"]
