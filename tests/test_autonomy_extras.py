import pixel_office.company.metrics as metrics
from pixel_office.company import ideas
from pixel_office.company.autonomy import AutonomyLoop, default_planner, workflow_planner
from pixel_office.company.factory import build_company
from pixel_office.company.okr import KeyResult
from pixel_office.company.runtime import TaskResult


def test_idea_becomes_outcome_associated_only_after_target_kr_rises_post_delivery():
    c = build_company({"what": "x", "goal": "grow",
                       "roles": [{"title": "Growth Marketer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "reach 1000 signups", target=1000))
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, True, "ok")
    loop = AutonomyLoop(c, max_dispatch=2, initiative_every_s=1e9)   # propose once (first tick)
    loop._last_review = loop._last_meeting = loop._last_metrics = 1e18
    loop._last_radar = loop._last_hr = 1e18
    loop._kr_hist = [(-1, {"kr1": 0.0})]   # a prior FLAT reading → a baseline can be established
    loop.tick(0)                      # propose + pursue (idea task queued)
    loop.tick(1)                      # idea task delivered; snapshot the target KR + baseline
    idea = c.ideas[0]
    assert idea.status == ideas.DELIVERED and idea.kr_snapshot == 0.0
    assert idea.outcome_points == 0.0             # delivering alone earns NOTHING
    c.okrs.key_results[0].current = 40            # rose well ABOVE baseline + the preregistered bar
    loop.tick(2)                      # settle → outcome-associated (correlational)
    assert idea.status == ideas.ASSOCIATED and idea.outcome_points == 40.0
    view = c.ideas_view()
    assert view["reputation"] and view["reputation"][0]["proposer"] == idea.proposer_id
    assert "outcome" in [a["kind"] for a in c.activity_view(50)]


def test_live_idea_gen_failure_does_not_fabricate_an_employee_proposal():
    # in --live, if the CLI returns nothing, NO idea is recorded under the employee —
    # a deterministic skeleton must never be attributed as their authored proposal.
    c = build_company({"what": "x", "goal": "grow",
                       "roles": [{"title": "Growth Marketer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "reach 1000 signups", target=1000))
    loop = AutonomyLoop(c, max_dispatch=2, initiative_every_s=1e9,
                        idea_gen_fn=lambda o, f, l, t: "")   # live gen that yields nothing
    loop._last_review = loop._last_meeting = loop._last_metrics = 1e18
    loop._last_radar = loop._last_hr = 1e18
    loop.tick(0)
    assert c.ideas == []                                  # nothing fabricated
    assert "idea" not in [a["kind"] for a in c.activity_view(50)]


def test_live_idea_gen_content_and_assumption_are_recorded():
    c = build_company({"what": "x", "goal": "grow",
                       "roles": [{"title": "Growth Marketer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "reach 1000 signups", target=1000))
    loop = AutonomyLoop(c, max_dispatch=2, initiative_every_s=1e9,
                        idea_gen_fn=lambda o, f, l, t: "Launch a referral link. Assumption: users share")
    loop._last_review = loop._last_meeting = loop._last_metrics = 1e18
    loop._last_radar = loop._last_hr = 1e18
    loop.tick(0)
    assert c.ideas and c.ideas[0].content == "Launch a referral link"
    assert c.ideas[0].proposer_assumptions == ("users share",)   # only the CLI's own words


def test_failed_hypothesis_is_preserved_as_learning_not_points():
    # an idea delivered but whose KR never beats baseline → FAILED_HYPOTHESIS → a
    # LearningRecord (falsified assumption), never points or progress.
    c = build_company({"what": "x", "goal": "grow",
                       "roles": [{"title": "Growth Marketer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "reach 1000 signups", target=1000))
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, True, "ok")   # idea delivers
    loop = AutonomyLoop(c, max_dispatch=2, initiative_every_s=1e9)   # propose once
    loop._last_review = loop._last_meeting = loop._last_metrics = 1e18
    loop._last_radar = loop._last_hr = 1e18
    for tk in range(9):
        loop.tick(tk)                         # KR never rises → window elapses → failed
    idea = c.ideas[0]
    assert idea.status == ideas.FAILED_HYPOTHESIS and idea.outcome_points == 0.0
    assert c.learnings and c.learnings[0].target_kr_id == "kr1"      # the miss became a lesson
    assert (("kr1", idea.lens) in c.falsified_lenses())             # future proposals steer away
    assert c.ideas_view()["reputation"] == []                       # zero standing from a failure


def test_idea_whose_task_fails_is_dropped_with_zero_points():
    c = build_company({"what": "x", "goal": "grow",
                       "roles": [{"title": "Growth Marketer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "reach 1000 signups", target=1000))
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, False, "blocked")
    loop = AutonomyLoop(c, max_dispatch=2, initiative_every_s=1e9)
    loop._last_review = loop._last_meeting = loop._last_metrics = 1e18
    loop._last_radar = loop._last_hr = 1e18
    loop.tick(0); loop.tick(1)
    idea = c.ideas[0]
    c.okrs.key_results[0].current = 50            # even if the KR later rises...
    loop.tick(2)
    assert idea.status == ideas.DROPPED and idea.outcome_points == 0.0   # ...a failed idea earns nothing


def _team_company(kr_text="ship 5 signups", metric="signups"):
    c = build_company({"what": "x", "roles": [
        {"title": "Backend Engineer", "count": 1}, {"title": "QA Engineer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", kr_text, target=5, metric=metric))
    return c


def test_growth_loop_moves_okr_from_real_metrics(monkeypatch):
    c = _team_company()
    c.product_url = "http://product"
    monkeypatch.setattr(metrics, "fetch_metrics", lambda url, timeout=4.0: {"signups": 3})
    AutonomyLoop(c, metrics_every_s=0).tick(0)
    assert c.okrs.key_results[0].current == 3          # a REAL metric advanced the KR


def test_meeting_holds_but_fabricates_no_progress():
    c = _team_company()
    c.okrs.add_kr(KeyResult("kr2", "cut latency", target=5))   # 2nd stalled KR = real blocker
    AutonomyLoop(c, meeting_every_s=0).tick(0)
    mv = c.meeting_view()
    assert mv and len(mv["attendees"]) >= 2
    assert c.okrs.key_results[0].current == 0          # the meeting invented NO goal movement
    assert "meeting" in [a["kind"] for a in c.activity_view(50)]


def test_single_stalled_kr_is_resolved_async_no_meeting():
    # honesty: one stalled KR is handled by a review memo (async), NOT an all-hands.
    c = _team_company()
    AutonomyLoop(c, meeting_every_s=0).tick(0)
    assert c.meeting_view() is None                    # admission denied — nothing needs the room


def test_meeting_action_items_become_bounded_backlog():
    c = _team_company()
    c.okrs.add_kr(KeyResult("kr2", "cut latency", target=5))   # real blocker → meeting fires
    AutonomyLoop(c, meeting_every_s=0, max_dispatch=2).tick(0)
    assert any(t.task_class == "meeting-action" for t in c.backlog)   # actions → real work


def test_review_auto_unblocks_a_halted_workflow():
    c = build_company({"what": "x", "stack": "api-service", "roles": [
        {"title": "Backend Engineer", "count": 1}, {"title": "QA Engineer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "ship the payments feature", target=10))
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, False, "x")   # fail → block
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop._last_review = loop._last_meeting = loop._last_metrics = loop._last_initiative = 1e18
    loop.tick(0)
    assert c.workflows["kr1"].blocked
    loop._last_review = None                             # let the review cadence fire
    loop.tick(1)
    assert not c.workflows["kr1"].blocked                # review un-blocked it for retry


def test_done_workflow_kr_stops_generating_meetings_and_memos():
    c = build_company({"what": "x", "stack": "api-service", "roles": [
        {"title": "Backend Engineer", "count": 1}, {"title": "QA Engineer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "ship the payments feature", target=10))
    c.start_workflow("kr1", "ship-feature")
    c.workflows["kr1"].done = True                       # playbook done, but KR metric still 0
    # a done-workflow KR is excluded from the workable-stalled set → no meeting fires
    AutonomyLoop(c, meeting_every_s=0).tick(0)
    assert c.meeting_view() is None


def test_milestone_celebrated_once_only_on_real_completion():
    c = _team_company(kr_text="ship 5 signups", metric="signups")   # kr1 target=5
    loop = AutonomyLoop(c, meeting_every_s=1e18, review_every_s=1e18,
                        metrics_every_s=1e18, initiative_every_s=1e18)
    loop._last_radar = loop._last_hr = 1e18
    # not yet complete → no celebration
    c.okrs.key_results[0].current = 3
    loop.tick(0)
    assert "milestone" not in [a["kind"] for a in c.activity_view(50)]
    # now it genuinely reaches 100% → celebrated exactly once
    c.okrs.key_results[0].current = 5
    loop.tick(1); loop.tick(2)
    miles = [a for a in c.activity_view(50) if a["kind"] == "milestone"]
    assert len(miles) == 1 and "signups" in miles[0]["text"]


def test_blocked_workflow_is_abandoned_after_retry_budget():
    from pixel_office.company.workflows import MAX_RETRIES
    c = build_company({"what": "x", "stack": "api-service", "roles": [
        {"title": "Backend Engineer", "count": 1}, {"title": "QA Engineer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "ship the payments feature", target=10))
    c.start_workflow("kr1", "ship-feature")
    c.workflows["kr1"].blocked = True
    # the review keeps unblocking, but only up to the budget — then it's abandoned
    for _ in range(MAX_RETRIES):
        assert c.clear_workflow("kr1") is True
        c.workflows["kr1"].blocked = True    # step fails again
    assert c.clear_workflow("kr1") is False  # budget spent → no more auto-retry
    assert c.workflows["kr1"].abandoned is True
    assert "kr1" not in [k.id for k in _active_stalled_ids(c)]   # excluded from the work set


def _active_stalled_ids(c):
    from pixel_office.company.autonomy import _active_stalled
    return _active_stalled(c)


def test_abandoned_workflow_is_not_live_blocker_evidence_for_meetings():
    # an abandoned run keeps blocked=True; it must NOT admit meetings forever about
    # some other single active KR (that KR is async-resolvable → no meeting).
    c = _team_company()
    c.okrs.add_kr(KeyResult("kr2", "cut latency", target=5))   # a 2nd, active stalled KR
    c.start_workflow("kr1", "ship-feature")
    c.workflows["kr1"].blocked = True
    c.workflows["kr1"].abandoned = True                        # halted for good (stale blocked flag)
    AutonomyLoop(c, meeting_every_s=0).tick(0)
    # kr1 is excluded (abandoned) and kr2 alone is async → the abandoned flag doesn't
    # fabricate a "blocked workflow" blocker, so no meeting is admitted.
    assert c.meeting_view() is None


def test_missing_dri_task_leaves_an_honest_blocked_trace_not_silence():
    # a task whose DRI doesn't exist must NOT vanish — it leaves a blocked activity.
    c = _team_company()
    c.add_task("do something", dri="ghost", task_class="general")   # no such employee
    loop = AutonomyLoop(c, max_dispatch=1)
    loop._last_review = loop._last_meeting = loop._last_metrics = loop._last_initiative = 1e18
    loop._last_radar = loop._last_hr = 1e18
    loop.tick(0)
    kinds = [a["kind"] for a in c.activity_view(50)]
    assert "blocked" in kinds and not c.backlog          # recorded + drained, not lost


def test_workflow_planner_falls_back_to_default_when_no_workflow_matches():
    c = build_company({"what": "x", "roles": [{"title": "Backend Engineer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "xyzzy qwerty", target=10))   # matches no workflow family
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, True, "x")
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop._last_review = loop._last_meeting = loop._last_metrics = loop._last_initiative = 1e18
    loop.tick(0)
    seen = {ev.task_class for mem in c.runtime.memories.values() for ev in mem.evidence}
    assert "kr1" in seen and "kr1" not in c.workflows    # bare kr id, no workflow run created
