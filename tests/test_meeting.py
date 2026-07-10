"""Company Layer Phase 4 — meetings as parallel memos → one synthesis."""
from pixel_office.company.meeting import (
    GoalUpdate, Meeting, Outcome, admission_test, apply_outcome,
)
from pixel_office.company.okr import KeyResult, OKRTree


def test_admission_test():
    # a real blocking cross-role decision that can't be async → admitted
    assert admission_test(has_specific_decision=True, attendee_count=3,
                          delay_cost=100, meeting_cost=10, async_resolvable=False) is True
    # one owner / async-resolvable → not a meeting (do it async)
    assert admission_test(has_specific_decision=True, attendee_count=1,
                          delay_cost=100, meeting_cost=10, async_resolvable=False) is False
    assert admission_test(has_specific_decision=True, attendee_count=3,
                          delay_cost=100, meeting_cost=10, async_resolvable=True) is False
    # cheap delay → not worth the meeting
    assert admission_test(has_specific_decision=True, attendee_count=3,
                          delay_cost=5, meeting_cost=10, async_resolvable=False) is False


def _positions(attendee, packet):
    return f"{attendee} votes ship"


def _synth(positions, packet):
    return Outcome(decisions=["ship v2"], actions=[{"dri": "eng", "task": "deploy", "deadline": "fri"}],
                   goal_updates=[GoalUpdate("kr1", 8)])


def test_meeting_runs_parallel_memos_then_one_synthesis():
    m = Meeting("v2 launch", "ship v2 now?", attendees=["eng", "pm"], packet={"metric": "fast"})
    out = m.run(position_fn=_positions, synthesize_fn=_synth)
    assert m.status == "completed"
    assert set(m.positions) == {"eng", "pm"}           # each submitted one position
    assert out.decisions == ["ship v2"] and out.actions[0]["dri"] == "eng"


def test_meeting_emits_honest_lifecycle_stages():
    stages = []
    m = Meeting("t", "d", attendees=["a", "b"])
    m.run(position_fn=lambda a, p: "ok", synthesize_fn=lambda pos, p: Outcome(),
          sink=lambda emp, stage: stages.append((emp, stage)))
    # gather (Working) then return (Done) — a workflow timeline, not fake dialogue
    assert stages == [("a", "Working"), ("b", "Working"), ("a", "Done"), ("b", "Done")]


def test_meeting_fails_open_on_bad_functions():
    m = Meeting("t", "d", attendees=["a"])
    out = m.run(position_fn=lambda a, p: 1 / 0, synthesize_fn=lambda pos, p: 1 / 0)
    assert m.status == "completed" and "deferred" in out.decisions[0]   # never raises


def test_meeting_outcome_auto_updates_okrs():
    okrs = OKRTree(objective="grow")
    okrs.add_kr(KeyResult("kr1", "weekly posts", target=10, cadence="weekly"))
    n = apply_outcome(okrs, _synth({}, {}))
    assert n == 1 and okrs.key_results[0].current == 8    # weekly KR auto-updated
    # a bad update is skipped, not fatal (bad id, None, or non-numeric)
    assert apply_outcome(okrs, Outcome(goal_updates=[GoalUpdate("ghost", 1)])) == 0
    assert apply_outcome(okrs, Outcome(goal_updates=[GoalUpdate("kr1", None)])) == 0
    assert okrs.key_results[0].current == 8   # unchanged by the malformed update
