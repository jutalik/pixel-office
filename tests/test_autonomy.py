"""Autonomy loop — the company runs itself, verified deterministically (0 tokens)."""
from pixel_office.company.autonomy import AutonomyLoop, default_planner
from pixel_office.company.company import Company
from pixel_office.company.employee import Employee
from pixel_office.company.mode import preset
from pixel_office.company.okr import KeyResult


def _company(mode="Autopilot"):
    c = Company("co", "grow the thing", mode=preset(mode))
    c.team.hire(Employee("eng", "engineer"))
    c.okrs.add_kr(KeyResult("kr1", "ship features", target=10, cadence="weekly"))  # 0% → stalled
    return c


def test_tick_plans_and_dispatches_toward_stalled_kr():
    c = _company()
    events = []
    c.runtime.sink = events.append
    loop = AutonomyLoop(c, max_dispatch=3)
    r = loop.tick(now=0)
    assert r.planned == 1 and r.dispatched == 1                 # planned + did the work
    assert c.okrs  # objective intact
    # the employee actually worked (avatars + evidence)
    assert [e.kind for e in events] == ["Working", "Done"]
    assert c.runtime.memory_of("eng").samples("kr1") == 1


def test_dispatch_is_bounded_per_tick():
    c = _company()
    for i in range(10):
        c.add_task(f"t{i}", dri="eng")
    r = AutonomyLoop(c, max_dispatch=3).tick(now=0)
    assert r.dispatched == 3 and len(c.backlog) == 7           # bounded, rest stays queued


def test_review_raises_memo_and_escalates_by_mode():
    # Manual mode: a medium-risk reversible review memo reaches the CEO
    c = _company("Manual")
    loop = AutonomyLoop(c, review_every_s=100)
    r = loop.tick(now=0)
    assert r.reviewed is True
    assert c.memos.memos and r.ceo_pending >= 1                # escalated in Manual
    # Autopilot: the same reversible review just happens (never the CEO)
    c2 = _company("Autopilot")
    r2 = AutonomyLoop(c2, review_every_s=100).tick(now=0)
    assert r2.reviewed is True and r2.ceo_pending == 0


def test_cadence_gates_review_radar_hr():
    c = _company()
    c.radar.search_fn = lambda q: ["trend-x"]
    loop = AutonomyLoop(c, review_every_s=1000, radar_every_s=1000, hr_every_s=1000)
    first = loop.tick(now=0)
    assert first.reviewed and first.scanned                     # ran on the first tick
    second = loop.tick(now=500)                                 # within all intervals
    assert not second.reviewed and not second.scanned           # gated (budget)
    third = loop.tick(now=2000)
    assert third.reviewed and third.scanned                     # past the intervals


def test_bad_planner_never_wedges_the_loop():
    c = _company()
    def boom(company, kr):
        raise RuntimeError("x")
    r = AutonomyLoop(c, planner_fn=boom).tick(now=0)
    assert r.planned == 0 and r.dispatched == 0                 # no crash, just no work


def test_default_planner_targets_kr_owner_and_class():
    c = _company()
    t = default_planner(c, c.okrs.key_results[0])
    assert t.dri == "eng" and t.task_class == "kr1"


def test_tick_records_what_the_company_did():
    c = _company()
    loop = AutonomyLoop(c, review_every_s=100)
    loop.tick(now=0)
    kinds = [a["kind"] for a in c.activity_view()]
    assert "plan" in kinds and "work" in kinds and "decision" in kinds   # real actions logged
    # the work entry names the owner + the task (legible to a non-dev CEO)
    work = next(a for a in c.activity if a["kind"] == "work")
    assert "eng" in work["text"]


def test_failed_dispatch_is_logged_as_blocked_not_work():
    # honesty: a task the executor couldn't complete must not read as done work
    from pixel_office.company.runtime import TaskResult
    c = _company()
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, ok=False, summary="nope")
    AutonomyLoop(c, review_every_s=100).tick(now=0)
    kinds = [a["kind"] for a in c.activity]
    assert "blocked" in kinds and "work" not in kinds


def test_activity_feed_is_bounded():
    from pixel_office.company.company import MAX_ACTIVITY
    c = _company()
    for i in range(MAX_ACTIVITY + 25):
        c.record_activity("work", f"did thing {i}")
    assert len(c.activity) == MAX_ACTIVITY               # oldest fall off
    assert c.activity[-1]["text"] == f"did thing {MAX_ACTIVITY + 24}"   # newest kept
    assert len(c.activity_view(limit=5)) == 5            # view is a bounded tail


def test_one_cadence_failure_does_not_abort_the_others():
    # a mid-tick cadence step blows up; the HR review (later in the tick) must
    # still run — each step is independently fail-open
    c = _company()
    def boom(now):
        raise RuntimeError("net down")
    c.scan_trends = boom               # force the radar step to raise
    loop = AutonomyLoop(c, review_every_s=1000, radar_every_s=1000, hr_every_s=1000)
    r = loop.tick(now=0)
    assert r.reviewed is True          # review ran (before radar) — unaffected
    assert r.scanned is False          # radar raised, swallowed
    assert isinstance(r.hr_recs, list) # HR still ran (after radar) — not aborted


def test_tick_is_thread_safe_against_concurrent_reads():
    # the autonomy thread mutates company state while /api/company-style reads
    # run — the shared lock must keep both from crashing or seeing torn state
    import threading
    c = _company()
    for i in range(20):
        c.add_task(f"t{i}", dri="eng")
    loop = AutonomyLoop(c, max_dispatch=1)
    errors = []

    def tick_many():
        try:
            for i in range(50):
                loop.tick(now=i)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    def read_many():
        try:
            for _ in range(50):
                c.summary(); c.okr_view(); c.hr_view(); c.trends_view()
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=tick_many), threading.Thread(target=read_many)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
