"""Local intent policy. Only final, confident, explicit commands take the stop path."""

import re
import unicodedata


def decide_event(event):
    if event.quoted or event.negated or event.confidence < 0.9:
        return "clarify"
    return {
        "vad": "ignore",
        "ack": "ignore",
        "query": "answer",
        "append": "enqueue",
        "revise": "update",
        "stop": "hold",
        "barge_in": "cancel_tts",
    }[event.kind]


_STOP = {
    "停",
    "停止",
    "停下",
    "停一下",
    "暂停",
    "停止任务",
    "停止机器人",
    "别动",
    "不要动",
    "stop",
    "pause",
}
_TTS = {"停止播报", "停止说话", "别说了", "取消播报", "stop speaking"}
_QUERY = {"状态", "当前状态", "做到哪一步了", "现在到哪了", "status"}
_ACK = {"嗯", "好", "好的", "对", "嗯对", "谢谢", "ok", "okay", "thanks"}


def text_intent(event):
    """Small allowlist, not an ASR engine or general-purpose language classifier."""
    if not event.is_final:
        return "ignore", "partial_transcript"
    if event.confidence < 0.9:
        return "clarify", "low_confidence"
    text = unicodedata.normalize("NFKC", event.text).strip().lower()
    if any(c in text for c in '"“”‘’「」『』`'):
        return "clarify", "quoted_text"
    text = text.rstrip("。.!！?？,，;； ")
    if text in _TTS:
        return "cancel_tts", ""
    if text in _STOP:
        return "stop", ""
    # Stop first, but never automatically execute the suffix as a replacement.
    first, *rest = re.split(r"[,，;；。!！]", text, maxsplit=1)
    if first.strip() in _STOP and rest:
        return "stop", "replacement_requires_explicit_plan"
    if not text or text in _ACK:
        return "ignore", "acknowledgement"
    if text in _QUERY:
        return "query", ""
    if re.search(r"不要|别|不能|不许|\b(?:not|never|don.t)\b", text):
        return "clarify", "negated_text"
    if re.search(r"停|暂停|取消|\b(?:stop|pause|cancel)\b", text):
        return "clarify", "ambiguous_control"
    if re.search(r"改成|改放|换成|做完|完成后|然后再|\b(?:instead|afterwards)\b", text):
        return "clarify", "use_task_replace_or_enqueue"
    return "goal", ""
