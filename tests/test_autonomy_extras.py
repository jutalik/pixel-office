import pixel_office.company.metrics as metrics
from pixel_office.company.autonomy import AutonomyLoop, default_planner, workflow_planner
from pixel_office.company.factory import build_company
from pixel_office.company.okr import KeyResult
from pixel_office.company.runtime import TaskResult


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
    AutonomyLoop(c, meeting_every_s=0).tick(0)
    mv = c.meeting_view()
    assert mv and len(mv["attendees"]) >= 2
    assert c.okrs.key_results[0].current == 0          # the meeting invented NO goal movement
    assert "meeting" in [a["kind"] for a in c.activity_view(50)]


def test_meeting_action_items_become_bounded_backlog():
    c = _team_company()
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


def test_workflow_planner_falls_back_to_default_when_no_workflow_matches():
    c = build_company({"what": "x", "roles": [{"title": "Backend Engineer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "xyzzy qwerty", target=10))   # matches no workflow family
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, True, "x")
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop._last_review = loop._last_meeting = loop._last_metrics = loop._last_initiative = 1e18
    loop.tick(0)
    seen = {ev.task_class for mem in c.runtime.memories.values() for ev in mem.evidence}
    assert "kr1" in seen and "kr1" not in c.workflows    # bare kr id, no workflow run created
