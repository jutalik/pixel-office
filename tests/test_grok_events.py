import json

from pixel_office.telemetry.grok_events import parse_line
from pixel_office.telemetry.reducer import reduce_all
from pixel_office.telemetry.tailer import TranscriptTailer

TS = "2026-07-10T04:29:36.500Z"


def test_lifecycle_kinds():
    assert parse_line({"type": "turn_started", "ts": TS, "session_id": "s"})[0] == "TurnStarted"
    assert parse_line({"type": "turn_ended", "ts": TS, "outcome": "ok"})[0] == "TurnEnded"
    assert parse_line({"type": "permission_requested", "ts": TS, "tool_name": "bash"})[0] \
        == "PermissionRequested"


def test_tool_name_captured():
    kind, ts, sess, meta = parse_line({"type": "tool_started", "ts": TS, "tool_name": "shell"})
    assert kind == "ToolStarted" and meta == {"tool": "shell"} and ts == TS


def test_phase_changed_is_noise():
    assert parse_line({"type": "phase_changed", "ts": TS, "phase": "x"}) is None


def test_grok_tailer_derives_waiting(tmp_path):
    # grok is the one CLI whose TAILER can show `waiting` (records permission prompts)
    sess_dir = tmp_path / "sessions" / "enc-cwd" / "uuid-abc"
    sess_dir.mkdir(parents=True)
    f = sess_dir / "events.jsonl"
    f.write_text(
        json.dumps({"type": "turn_started", "ts": TS, "session_id": "uuid-abc"}) + "\n"
        + json.dumps({"type": "permission_requested", "ts": TS, "tool_name": "bash"}) + "\n")
    events = TranscriptTailer(f, host_id="h1", cli="grok").poll()
    assert [e.kind for e in events] == ["TurnStarted", "PermissionRequested"]
    assert reduce_all(events).agents[("h1", "grok", "uuid-abc", "main")].activity == "waiting"


def test_grok_session_fallback_is_parent_dir(tmp_path):
    # events.jsonl is not unique — identity must come from the parent uuid dir
    sess_dir = tmp_path / "sessions" / "enc" / "the-uuid"
    sess_dir.mkdir(parents=True)
    f = sess_dir / "events.jsonl"
    f.write_text(json.dumps({"type": "loop_started", "ts": TS, "loop_index": 0}) + "\n")
    ev = TranscriptTailer(f, host_id="h1", cli="grok").poll()[0]
    assert ev.session_id == "the-uuid"  # not "events"
