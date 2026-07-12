"""The idea → outcome → reputation engine — honest attribution, zero tokens."""
from pixel_office.company import ideas
from pixel_office.company.creativity import new_idea_record


def _delivered(proposer, kr, snapshot, delivered_at):
    r = new_idea_record(proposer, "acquisition", kr, content="try X")
    r.status = ideas.DELIVERED
    r.kr_snapshot = snapshot
    r.delivered_at = delivered_at
    return r


def test_learning_from_a_failed_idea_captures_the_falsified_assumption():
    from pixel_office.company.creativity import learning_from, new_idea_record
    idea = new_idea_record("alice", "acquisition", "kr1", proposer_assumptions=("paid ads convert",))
    idea.status = ideas.FAILED_HYPOTHESIS
    lr = learning_from(idea, tick=5)
    assert lr.lens == "acquisition" and lr.target_kr_id == "kr1"
    assert lr.unconfirmed == "paid ads convert"        # the proposer's own words, not invented


def test_parse_live_idea_keeps_real_source_drops_fabricated_provenance():
    from pixel_office.company.creativity import parse_live_idea
    c, a, g = parse_live_idea("Ship a digest. Source: https://arxiv.org/abs/2401.1. Assumption: readers open it")
    assert c == "Ship a digest" and a == ("readers open it",) and g == "https://arxiv.org/abs/2401.1"
    # a non-reference "source" is NOT accepted as provenance (no invented grounding)
    _, _, g2 = parse_live_idea("Try X. Source: my own intuition. Assumption: it helps")
    assert g2 == ""


def test_split_assumption_keeps_only_what_the_cli_returned():
    from pixel_office.company.creativity import split_assumption
    c, a = split_assumption("Add a weekly digest email. Assumption: users check email weekly")
    assert c == "Add a weekly digest email" and a == ("users check email weekly",)
    c2, a2 = split_assumption("Just an idea with no assumption line")
    assert a2 == () and "idea" in c2                      # nothing fabricated when absent


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


def test_baseline_adjusted_credits_only_the_excess_above_prior_trend():
    # the KR was already climbing 2/tick before delivery; only the EXCESS counts.
    r = _delivered("alice", "kr1", 10.0, delivered_at=1)
    r.baseline_rate = 2.0
    # after 3 ticks the KR "would have" reached 16 anyway; it reached 20 → excess 4
    ideas.settle([r], {"kr1": 20.0}, now_tick=4)
    assert r.status == ideas.ASSOCIATED and r.outcome_points == 4.0   # 20 - (10 + 2*3)
    assert r.raw_delta == 10.0                                        # raw rise shown for transparency


def test_secular_growth_alone_does_not_earn_credit():
    # the KR only grew at its baseline rate → no excess → preregistered miss = failed
    r = _delivered("alice", "kr1", 10.0, delivered_at=0)
    r.baseline_rate = 2.0
    r.success_threshold = 0.5                     # preregistered → a miss is a falsification
    W = ideas.VALIDATION_WINDOW_TICKS            # r.evaluation_window defaults to this
    ideas.settle([r], {"kr1": 10.0 + 2.0 * W}, now_tick=W)  # exactly the baseline trajectory
    assert r.status == ideas.FAILED_HYPOTHESIS and r.outcome_points == 0.0


def test_below_threshold_excess_is_failed_hypothesis():
    r = _delivered("alice", "kr1", 10.0, delivered_at=0)
    r.baseline_rate = 0.0
    r.success_threshold = 5.0                     # need +5 above baseline
    ideas.settle([r], {"kr1": 13.0}, now_tick=ideas.VALIDATION_WINDOW_TICKS)  # only +3 → misses bar
    assert r.status == ideas.FAILED_HYPOTHESIS and r.outcome_points == 0.0


def test_falling_kr_earns_nothing_even_if_it_beats_a_negative_baseline():
    # a KR that actually FELL must never be credited, even if it fell less than a
    # declining baseline predicted (beating a negative baseline is not a real win).
    r = _delivered("alice", "kr1", 100.0, delivered_at=1)
    r.baseline_rate = -10.0
    ideas.settle([r], {"kr1": 95.0}, now_tick=2)   # raw delta -5, but 95 > (100-10)=90
    assert r.status == ideas.DELIVERED and r.outcome_points == 0.0   # cur < snapshot → no credit


def test_no_established_baseline_is_not_creditable():
    # without a pre-delivery trend we can't say an idea beat the baseline → no credit
    # (0 is not conservative for a growing KR — it would credit secular growth).
    r = _delivered("alice", "kr1", 10.0, delivered_at=1)
    r.baseline_ok = False
    ideas.settle([r], {"kr1": 500.0}, now_tick=3)   # huge rise, but no baseline established
    assert r.status != ideas.ASSOCIATED and r.outcome_points == 0.0


def test_contention_is_durable_a_lone_survivor_gets_no_exclusive_credit():
    # two ideas overlap on kr1; even after one settles ambiguous and the other is later
    # alone, the survivor must NOT get exclusive points — the KR was confounded.
    a = _delivered("alice", "kr1", 10.0, delivered_at=1)
    b = _delivered("bob", "kr1", 20.0, delivered_at=1)   # higher snapshot, not yet risen
    ideas.settle([a, b], {"kr1": 15.0}, now_tick=2)      # a beats, b doesn't → a AMBIGUOUS
    assert a.status == ideas.AMBIGUOUS and b.status == ideas.DELIVERED and b.contended
    ideas.settle([a, b], {"kr1": 30.0}, now_tick=3)      # now b is alone AND rises...
    assert b.status == ideas.AMBIGUOUS and b.outcome_points == 0.0   # ...but stays non-exclusive


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
