import json

from pixel_office.telemetry.codex_rollout import parse_line
from pixel_office.telemetry.tailer import TranscriptTailer

TS = "2026-07-10T04:26:12.537Z"


def _wrap(ptype, **payload):
    payload["type"] = ptype
    return {"timestamp": TS, "type": "event_msg", "payload": payload}


def test_task_lifecycle():
    assert parse_line(_wrap("task_started"))[0] == "TaskStarted"
    assert parse_line(_wrap("task_complete", turn_id="t1"))[0] == "TaskComplete"


def test_function_call_tool_name_only():
    kind, ts, sess, meta = parse_line(_wrap("function_call", name="shell",
                                            arguments='{"cmd":"SECRET"}'))
    assert kind == "FunctionCall" and meta == {"tool": "shell"}
    assert sess is None and ts == TS


def test_ignored_and_garbage():
    assert parse_line(_wrap("token_count")) is None
    assert parse_line({"timestamp": TS, "payload": "notdict"}) is None
    assert parse_line({}) is None


def test_codex_tailer_end_to_end(tmp_path):
    f = tmp_path / "rollout-2026-07-10-abc.jsonl"
    f.write_text(json.dumps(_wrap("task_started")) + "\n"
                 + json.dumps(_wrap("function_call", name="shell", arguments="x")) + "\n"
                 + json.dumps(_wrap("task_complete")) + "\n")
    events = TranscriptTailer(f, host_id="h1", cli="codex").poll()
    assert [e.kind for e in events] == ["TaskStarted", "FunctionCall", "TaskComplete"]
    assert events[0].cli == "codex"
    assert events[0].session_id == "rollout-2026-07-10-abc"  # stable fallback identity
