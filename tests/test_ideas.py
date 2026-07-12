"""The idea → outcome → reputation engine — honest attribution, zero tokens."""
from pixel_office.company import ideas
from pixel_office.company.creativity import new_idea_record


def _delivered(proposer, kr, snapshot, delivered_at):
    r = new_idea_record(proposer, "acquisition", kr, content="try X")
    r.status = ideas.DELIVERED
    r.kr_snapshot = snapshot
    r.delivered_at = delivered_at
    return r


def test_new_record_always_has_system_floor_assumption_and_skeleton():
    r = new_idea_record("alice", "flow", "kr1", objective="grow signups")
    assert r.system_assumptions and "unverified" in r.system_assumptions[0]
    assert r.content and r.status == "proposed" and r.outcome_points == 0.0
    # empty content → deterministic skeleton mentioning the lens; no fabricated assumptions
    assert "flow" in r.content and r.proposer_assumptions == ()


def test_proposer_assumptions_kept_only_when_actually_provided():
    r = new_idea_record("a", "flow", "kr1", content="idea", proposer_assumptions=("users want dark mode", ""))
    assert r.proposer_assumptions == ("users want dark mode",)   # blank dropped, real kept


def test_exclusive_rise_after_delivery_is_associated_with_points():
    r = _delivered("alice", "kr1", snapshot=10.0, delivered_at=2)
    n = ideas.settle([r], {"kr1": 13.0}, now_tick=4)
    assert n == 1 and r.status == ideas.ASSOCIATED
    assert r.associated_delta == 3.0 and r.outcome_points == 3.0


def test_two_ideas_on_same_moved_kr_get_no_individual_points():
    a = _delivered("alice", "kr1", 10.0, 2)
    b = _delivered("bob", "kr1", 10.0, 2)
    ideas.settle([a, b], {"kr1": 15.0}, now_tick=4)
    assert a.status == ideas.AMBIGUOUS and b.status == ideas.AMBIGUOUS
    assert a.outcome_points == 0.0 and b.outcome_points == 0.0    # splitting a delta = invented rule


def test_rise_not_strictly_after_delivery_does_not_associate():
    r = _delivered("alice", "kr1", 10.0, delivered_at=4)
    ideas.settle([r], {"kr1": 20.0}, now_tick=4)      # same tick as delivery → not "after"
    assert r.status == ideas.DELIVERED and r.outcome_points == 0.0


def test_same_delivery_tick_rise_is_rebaselined_not_credited_later():
    # a KR that jumped DURING the delivery tick must not be credited on a later tick —
    # the baseline is re-set to the post-delivery-tick level.
    r = _delivered("alice", "kr1", 10.0, delivered_at=4)
    ideas.settle([r], {"kr1": 20.0}, now_tick=4)      # KR jumped to 20 the delivery tick
    assert r.kr_snapshot == 20.0 and r.status == ideas.DELIVERED   # re-baselined, not credited
    ideas.settle([r], {"kr1": 20.0}, now_tick=5)      # no FURTHER rise
    assert r.status == ideas.DELIVERED and r.outcome_points == 0.0
    ideas.settle([r], {"kr1": 26.0}, now_tick=6)      # a genuine LATER rise (20 → 26)
    assert r.status == ideas.ASSOCIATED and r.outcome_points == 6.0   # credits only the later delta


def test_two_inflight_ideas_on_one_kr_earn_no_individual_credit_even_with_diff_snapshots():
    a = _delivered("alice", "kr1", 10.0, 2)
    b = _delivered("bob", "kr1", 20.0, 2)              # higher snapshot; not yet "risen"
    ideas.settle([a, b], {"kr1": 15.0}, now_tick=4)    # only a is above its snapshot
    # b is still in-flight against the SAME KR → a's rise isn't exclusively attributable
    assert a.status == ideas.AMBIGUOUS and a.outcome_points == 0.0
    assert b.status == ideas.DELIVERED                 # b hasn't risen; stays open


def test_window_expiry_is_inconclusive_zero_points():
    r = _delivered("alice", "kr1", 10.0, delivered_at=0)
    ideas.settle([r], {"kr1": 10.0}, now_tick=ideas.VALIDATION_WINDOW_TICKS)   # no rise
    assert r.status == ideas.INCONCLUSIVE and r.outcome_points == 0.0


def test_reputation_counts_only_exclusive_associations():
    a = _delivered("alice", "kr1", 10.0, 1); a.status = ideas.ASSOCIATED; a.outcome_points = 2.0
    b = _delivered("bob", "kr2", 5.0, 1); b.status = ideas.AMBIGUOUS; b.outcome_points = 0.0
    c = _delivered("alice", "kr3", 1.0, 1); c.status = ideas.ASSOCIATED; c.outcome_points = 1.5
    rep = ideas.proposer_reputation([a, b, c])
    assert rep == {"alice": 3.5}                       # bob's ambiguous outcome earns nothing


def test_evict_only_removes_terminal_records_preserving_active_and_links():
    recs = []
    for i in range(ideas.MAX_IDEAS + 5):
        r = new_idea_record(f"e{i}", "flow", "kr1")
        r.status = ideas.INCONCLUSIVE if i < 10 else ideas.PURSUED
        r.task_id = i
        recs.append(r)
    ideas.evict(recs)
    assert len(recs) == ideas.MAX_IDEAS
    assert all(r.status != ideas.PURSUED or r.task_id is not None for r in recs)  # links intact
    # all 195 active PURSUED records survive; only the oldest terminal ones were dropped
    assert sum(1 for r in recs if r.status == ideas.PURSUED) == (ideas.MAX_IDEAS + 5) - 10
