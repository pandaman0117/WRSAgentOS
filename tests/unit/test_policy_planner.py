import pytest

from wrs_agent.policy import decide_event
from wrs_agent.schemas import Interaction


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("vad", "ignore"),
        ("ack", "ignore"),
        ("query", "answer"),
        ("append", "enqueue"),
        ("revise", "update"),
        ("stop", "hold"),
        ("barge_in", "cancel_tts"),
    ],
)
def test_intents(kind, expected):
    assert decide_event(Interaction(event_id="event", kind=kind)) == expected


@pytest.mark.parametrize("flags", [{"quoted": True}, {"negated": True}, {"confidence": 0.3}])
def test_ambiguous_stop(flags):
    assert decide_event(Interaction(event_id="event", kind="stop", **flags)) == "clarify"
