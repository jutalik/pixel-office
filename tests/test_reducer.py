import itertools
from datetime import datetime, timezone

import pytest

from pixel_office.telemetry.contract import RawEvent
from pixel_office.telemetry.reducer import (
    derive_liveness, initial_state, reduce, reduce_all, view,
)


def ev(seq, kind, source="tailer", ts=None, agent_id="a1", parent=None, sec=None):
    if ts is None:
        ts = f"2026-07-10T00:00:{(sec if sec is not None else seq):02d}Z"
    return RawEvent(host_id="h1", cli="claude", session_id="s1", agent_id=agent_id,
                    seq=seq, ts=ts, source=source, kind=kind, parent_agent_id=parent)


def _activity(state, agent_id="a1"):
    return state.agents[("h1", "claude", "s1", agent_id)].activity


# ---- single-stream basics ----------------------------------------------------

def test_basic_progression():
    st = reduce_all([ev(1, "UserPromptSubmit"), ev(2, "PreToolUse"), ev(3, "PermissionRequest")])
    assert _activity(st) == "waiting"


def test_done_from_terminal_only():
    st = reduce_all([ev(1, "UserPromptSubmit"), ev(2, "PostToolUse")])
    assert _activity(st) == "working"
    st = reduce_all([ev(1, "UserPromptSubmit"), ev(2, "Stop")])
    assert _activity(st) == "done"


def test_never_fabricates_done_without_terminal():
    st = reduce_all([ev(i, "PreToolUse") for i in range(1, 20)])
    assert _activity(st) != "done"


def test_order_invariance_single_stream():
    events = [ev(1, "UserPromptSubmit"), ev(2, "PreToolUse"),
              ev(3, "PostToolUse"), ev(4, "Stop")]
    finals = {_activity(reduce_all(list(p))) for p in itertools.permutations(events)}
    assert finals == {"done"}


def test_latest_seq_wins_within_stream():
    late = ev(5, "PermissionRequest")
    early = ev(2, "PreToolUse")
    assert _activity(reduce_all([late, early])) == "waiting"
    assert _activity(reduce_all([early, late])) == "waiting"


def test_exact_duplicate_is_idempotent():
    e = ev(3, "PreToolUse")
    assert _activity(reduce_all([e])) == _activity(reduce_all([e, e, e])) == "working"


def test_same_seq_conflicting_content_is_order_invariant():
    # a buggy adapter reusing a seq must still reduce deterministically
    a = ev(5, "PreToolUse", ts="2026-07-10T00:00:05Z")
    b = ev(5, "PermissionRequest", ts="2026-07-10T00:00:06Z")
    assert _activity(reduce_all([a, b])) == _activity(reduce_all([b, a])) == "waiting"


# ---- cross-source merge (the Phase-0 review regressions) ----------------------

def test_case_a_stale_tailer_never_overrides_hook_done():
    # hook saw the real terminal Stop; the tailer's last pulse is older but has a
    # HIGHER seq in its own independent stream. done must win.
    events = [
        ev(1, "UserPromptSubmit", source="hook", ts="2026-07-10T00:00:01Z"),
        ev(2, "Stop", source="hook", ts="2026-07-10T00:00:04Z"),
        ev(5, "PreToolUse", source="tailer", ts="2026-07-10T00:00:03Z"),
    ]
    for p in itertools.permutations(events):
        assert _activity(reduce_all(list(p))) == "done"


def test_hook_precedence_when_equally_fresh():
    tailer = ev(5, "PreToolUse", source="tailer", ts="2026-07-10T00:00:05Z")
    hook = ev(5, "PermissionRequest", source="hook", ts="2026-07-10T00:00:05Z")
    assert _activity(reduce_all([tailer, hook])) == "waiting"
    assert _activity(reduce_all([hook, tailer])) == "waiting"


def test_dead_hook_stream_hands_over_to_tailer():
    # hook stream stops at t=0; tailer keeps observing well past the grace window
    events = [
        ev(1, "PreToolUse", source="hook", ts="2026-07-10T00:00:00Z"),
        ev(1, "UserPromptSubmit", source="tailer", ts="2026-07-10T00:01:00Z"),
        ev(2, "Stop", source="tailer", ts="2026-07-10T00:02:00Z"),
    ]
    assert _activity(reduce_all(events)) == "done"


def test_trailing_tailer_write_does_not_downgrade_done():
    # transcript flush lands just after the hook Stop (within grace): done sticks
    events = [
        ev(9, "Stop", source="hook", ts="2026-07-10T00:00:10Z"),
        ev(7, "PostToolUse", source="tailer", ts="2026-07-10T00:00:11Z"),
    ]
    for p in itertools.permutations(events):
        assert _activity(reduce_all(list(p))) == "done"


def test_two_agents_same_seq_both_survive_across_sources():
    st = reduce_all([
        ev(1, "PreToolUse", source="hook", agent_id="a1"),
        ev(1, "UserPromptSubmit", source="tailer", agent_id="sub1", parent="a1"),
    ])
    assert _activity(st, "a1") == "working"
    assert _activity(st, "sub1") == "working"


def test_two_agents_same_seq_same_source_both_survive():
    st = reduce_all([
        ev(1, "PreToolUse", source="hook", agent_id="a1"),
        ev(1, "SubagentStart", source="hook", agent_id="sub1", parent="a1"),
    ])
    assert _activity(st, "a1") == "working"
    assert _activity(st, "sub1") == "working"


def test_parent_claims_merge_order_invariantly():
    # conflicting parent claims (adapter bug) must still reduce deterministically
    a = ev(1, "PreToolUse", source="hook", agent_id="sub1", parent="pX")
    b = ev(1, "UserPromptSubmit", source="tailer", agent_id="sub1", parent="pY")
    p1 = reduce_all([a, b]).agents[("h1", "claude", "s1", "sub1")].parent_agent_id
    p2 = reduce_all([b, a]).agents[("h1", "claude", "s1", "sub1")].parent_agent_id
    assert p1 == p2 == "pX"  # deterministic min()


def test_subagent_tracked_separately_with_parent():
    st = reduce_all([
        ev(1, "UserPromptSubmit", agent_id="a1"),
        ev(2, "SubagentStart", agent_id="sub1", parent="a1"),
        ev(3, "SubagentStop", agent_id="sub1", parent="a1"),
    ])
    assert _activity(st, "a1") == "working"
    assert _activity(st, "sub1") == "done"
    assert st.agents[("h1", "claude", "s1", "sub1")].parent_agent_id == "a1"


# ---- boundedness & immutability -----------------------------------------------

def test_state_is_bounded_per_agent_and_source():
    st = initial_state()
    for i in range(1, 1001):
        st = reduce(st, ev(i, "PreToolUse", source="tailer", ts="2026-07-10T00:00:00Z"))
        st = reduce(st, ev(i, "PreToolUse", source="hook", ts="2026-07-10T00:00:00Z"))
    assert len(st.agents) == 1
    rec = st.agents[("h1", "claude", "s1", "a1")]
    assert len(rec.frontiers) == 2  # O(agents x sources), no per-seq history
    assert not hasattr(st, "_seq_source")


def test_state_mappings_are_immutable():
    st = reduce_all([ev(1, "PreToolUse")])
    with pytest.raises(TypeError):
        st.agents["INJECT"] = "corrupt"
    rec = st.agents[("h1", "claude", "s1", "a1")]
    with pytest.raises(TypeError):
        rec.frontiers["hook"] = "corrupt"


# ---- liveness / view -----------------------------------------------------------

def _t(sec):
    return datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc).replace(second=0) \
        .replace(minute=sec // 60, second=sec % 60)


def test_liveness_transitions():
    ts = "2026-07-10T00:00:00Z"
    kw = dict(stale_after_s=30, disconnected_after_s=120)
    assert derive_liveness(ts, _t(10), **kw) == "live"
    assert derive_liveness(ts, _t(45), **kw) == "stale"
    assert derive_liveness(ts, _t(180), **kw) == "disconnected"
    assert derive_liveness(ts, _t(1), connected=False) == "disconnected"
    assert derive_liveness("garbage", _t(1)) == "unknown"


def test_clock_skew_future_ts_is_live():
    assert derive_liveness("2026-07-10T00:05:00Z", _t(0)) == "live"


def test_view_shape_and_liveness():
    st = reduce_all([ev(1, "PreToolUse")])
    rows = view(st, _t(1))
    assert rows[0]["activity"] == "working" and rows[0]["liveness"] == "live"
    assert rows[0]["last_source"] == "tailer"


def test_view_connected_sessions_membership():
    st = reduce_all([ev(1, "PreToolUse")])
    rows = view(st, _t(1), connected_sessions={("h1", "claude", "s1")})
    assert rows[0]["liveness"] == "live"
    rows = view(st, _t(1), connected_sessions=set())
    assert rows[0]["liveness"] == "disconnected"


def test_view_rejects_malformed_connected_sessions():
    st = reduce_all([ev(1, "PreToolUse")])
    with pytest.raises(TypeError):
        view(st, _t(1), connected_sessions={"s1"})  # bare strings are a footgun
