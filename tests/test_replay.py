import json
from datetime import datetime, timezone
from pathlib import Path

from pixel_office.telemetry.contract import RawEvent
from pixel_office.telemetry.reducer import reduce_all, view

FIX = Path(__file__).parent / "fixtures"


def _load_events(name):
    events = []
    for line in (FIX / name).read_text().splitlines():
        line = line.strip()
        if line:
            events.append(RawEvent.from_dict(json.loads(line)))
    return events


def test_claude_basic_replay_matches_golden():
    events = _load_events("claude_basic.jsonl")
    state = reduce_all(events)
    now = datetime(2026, 7, 10, 0, 1, 0, tzinfo=timezone.utc)
    got = view(state, now, stale_after_s=30, disconnected_after_s=120)
    got_activity = {(r["session_id"], r["agent_id"]): r["activity"] for r in got}

    expected = json.loads((FIX / "claude_basic.expected.json").read_text())
    exp_activity = {(e["session_id"], e["agent_id"]): e["activity"] for e in expected}
    assert got_activity == exp_activity


def test_replay_strips_prompt_meta_from_fixture():
    # the fixture deliberately includes a prompt in meta; it must never survive ingest
    events = _load_events("claude_basic.jsonl")
    for e in events:
        assert "prompt" not in e.meta
