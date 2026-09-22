"""按住按钮的契约：松开必须送达，否则按下占用的麦克风永远交不回来。"""

import pytest

from wrs_agent.env.wrs import load_wrs


@pytest.fixture
def hold():
    """真实 WRS 面板，只走事件分发，不开浏览器也不渲染。"""
    load_wrs()
    from wrs.viewer.web_ui import UIPanel

    log = []
    panel = UIPanel()
    panel.add_hold_button(
        "talk",
        label="按住说话",
        on_press=lambda: log.append("press"),
        on_release=lambda: log.append("release"),
    )
    return panel, log


def send(panel, value, event_id="e1", control_id="talk"):
    """浏览器上报的物理按键状态：True 按下，False 松开。"""
    return panel._handle_event({
        "type": "ui_event", "panel_id": "default", "session": panel._session,
        "event_id": event_id, "id": control_id, "value": value,
    })


def test_press_and_release_reach_their_own_callbacks(hold):
    panel, log = hold
    assert send(panel, True)["ok"]
    assert send(panel, False, "e2")["ok"]
    assert log == ["press", "release"]


def test_release_lands_on_a_control_disabled_mid_press(hold):
    """按住期间禁用按钮，松开仍要送到；但禁用后不能重新按下。"""
    panel, log = hold
    send(panel, True)
    panel.set_enabled("talk", False)
    assert send(panel, False, "e2")["ok"]
    assert not send(panel, True, "e3")["ok"]
    assert log == ["press", "release"]


def test_repeated_event_id_does_not_replay_a_press(hold):
    panel, log = hold
    first = send(panel, True)
    assert send(panel, True) is first
    assert log == ["press"]


def test_hold_takes_no_value_and_rejects_non_bool(hold):
    panel, log = hold
    assert not send(panel, "yes")["ok"]
    assert not send(panel, None, "e2")["ok"]
    with pytest.raises(ValueError, match="do not have a value"):
        panel.set_value("talk", True)
    assert log == []


def test_hold_requires_callable_callbacks(hold):
    panel, _ = hold
    with pytest.raises(TypeError, match="callable"):
        panel.add_hold_button("bad", on_press="nope")


def test_panel_anchors_are_reachable_from_the_loaded_module():
    """09_viewer 用 load_wrs() 的返回值取锚点常量，这条属性链必须存在。"""
    wrs = load_wrs()
    assert wrs.viewer.web_ui.Anchor.TOP_LEFT in wrs.viewer.web_ui.Anchor.ALL
