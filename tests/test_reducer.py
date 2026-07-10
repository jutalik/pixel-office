import itertools
from datetime import datetime, timezone

from pixel_office.telemetry.contract import RawEvent
from pixel_office.telemetry.reducer import (
    AgentState, derive_liveness, reduce_all, view,
)


def ev(seq, kind, source="tailer", ts=None, agent_id="a1", parent=None):
    return RawEvent(host_id="h1", cli="claude", session_id="s1", agent_id=agent_id,
                    seq=seq, ts=ts or f"2026-07-10T00:00:{seq:02d}Z", source=source,
                    kind=kind, parent_agent_id=parent)


def _activity(state, agent_id="a1"):
    return state.agents[("h1", "claude", "s1", agent_id)].activity


def test_basic_progression():
    st = reduce_all([ev(1, "UserPromptSubmit"), ev(2, "PreToolUse"), ev(3, "PermissionRequest")])
    assert _activity(st) == "waiting"


def test_done_from_terminal_only():
    st = reduce_all([ev(1, "UserPromptSubmit"), ev(2, "PostToolUse")])
    assert _activity(st) == "working"
    st = reduce_all([ev(1, "UserPromptSubmit"), ev(2, "Stop")])
    assert _activity(st) == "done"


def test_never_fabricates_done_without_stop():
    st = reduce_all([ev(i, "PreToolUse") for i in range(1, 20)])
    assert _activity(st) != "done"


def test_order_invariance():
    events = [ev(1, "UserPromptSubmit"), ev(2, "PreToolUse"),
              ev(3, "PostToolUse"), ev(4, "Stop")]
    finals = {_activity(reduce_all(list(perm))) for perm in itertools.permutations(events)}
    assert finals == {"done"}


def test_latest_seq_wins_regardless_of_order():
    late = ev(5, "PermissionRequest")   # waiting
    early = ev(2, "PreToolUse")         # working
    assert _activity(reduce_all([late, early])) == "waiting"
    assert _activity(reduce_all([early, late])) == "waiting"


def test_hook_beats_tailer_same_seq():
    tailer = ev(5, "PreToolUse", source="tailer")     # working
    hook = ev(5, "PermissionRequest", source="hook")  # waiting
    assert _activity(reduce_all([tailer, hook])) == "waiting"
    assert _activity(reduce_all([hook, tailer])) == "waiting"


def test_exact_duplicate_is_idempotent():
    e = ev(3, "PreToolUse")
    assert _activity(reduce_all([e])) == _activity(reduce_all([e, e, e])) == "working"


def test_subagent_tracked_separately():
    st = reduce_all([
        ev(1, "UserPromptSubmit", agent_id="a1"),
        ev(2, "SubagentStart", agent_id="sub1", parent="a1"),
        ev(3, "SubagentStop", agent_id="sub1", parent="a1"),
    ])
    assert _activity(st, "a1") == "working"
    assert _activity(st, "sub1") == "done"
    assert st.agents[("h1", "claude", "s1", "sub1")].parent_agent_id == "a1"


def test_liveness_transitions():
    a = AgentState("h1", "claude", "s1", "a1", "working", 1, "2026-07-10T00:00:00Z", "tailer")
    assert derive_liveness(a, datetime(2026, 7, 10, 0, 0, 10, tzinfo=timezone.utc),
                           stale_after_s=30, disconnected_after_s=120) == "live"
    assert derive_liveness(a, datetime(2026, 7, 10, 0, 0, 45, tzinfo=timezone.utc),
                           stale_after_s=30, disconnected_after_s=120) == "stale"
    assert derive_liveness(a, datetime(2026, 7, 10, 0, 3, 0, tzinfo=timezone.utc),
                           stale_after_s=30, disconnected_after_s=120) == "disconnected"
    assert derive_liveness(a, datetime(2026, 7, 10, 0, 0, 1, tzinfo=timezone.utc),
                           connected=False) == "disconnected"


def test_clock_skew_future_ts_is_live():
    a = AgentState("h1", "claude", "s1", "a1", "working", 1, "2026-07-10T00:05:00Z", "tailer")
    now = datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc)  # event is "in the future"
    assert derive_liveness(a, now) == "live"


def test_view_shape():
    st = reduce_all([ev(1, "PreToolUse")])
    rows = view(st, datetime(2026, 7, 10, 0, 0, 1, tzinfo=timezone.utc))
    assert rows[0]["activity"] == "working" and rows[0]["liveness"] == "live"
