from pixel_office.company.autonomy import AutonomyLoop, default_planner, planner_for, workflow_planner
from pixel_office.company.factory import build_company
from pixel_office.company.okr import KeyResult
from pixel_office.company.runtime import TaskResult


def _api_company():
    c = build_company({"what": "x", "stack": "api-service", "roles": [
        {"title": "project owner", "count": 1},
        {"title": "architecture engineer", "count": 1},
        {"title": "backend engineer", "count": 1},
        {"title": "qa engineer", "count": 1},
        {"title": "devops", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "ship the payments feature", target=10))   # stalled eng KR
    return c


def _executor(ok):
    return lambda emp, task: TaskResult(task.id, emp.id, ok, "x")


def _wf_loop(c, planner=None):
    """Isolate the workflow engine: only plan + dispatch run. The review/meeting/
    metrics/initiative cadences are pinned in the future so they don't perturb the
    per-step assertions (they're tested separately)."""
    loop = AutonomyLoop(c, planner_fn=planner or workflow_planner, max_dispatch=1)
    loop._last_review = loop._last_radar = loop._last_hr = 1e18
    loop._last_metrics = loop._last_meeting = loop._last_initiative = 1e18
    return loop


def test_planner_for_picks_workflow_planner_when_team_has_workflows():
    assert planner_for(_api_company()) is workflow_planner


def test_risky_step_is_never_auto_executed_and_needs_approval():
    # CONTROL FAILS CLOSED: a workflow driven to its deploy (risky) step must NOT
    # dispatch a task — it opens a CEO approval and waits.
    import pytest

    from pixel_office.company.autonomy import _NoWork, workflow_planner
    c = _api_company()
    c.start_workflow("kr1", "ship-feature")
    c.workflows["kr1"].step_index = 5          # the 'deploy' step (risky=True)
    with pytest.raises(_NoWork):
        workflow_planner(c, c.okrs.key_results[0])   # risky → no task, raises _NoWork
    assert c.memos.has_open("approve deploy: ship the payments feature")  # approval opened
    assert not c.backlog                                                  # nothing auto-dispatched


def test_live_budget_fails_closed_when_exhausted():
    from pixel_office.company.employee import Employee
    from pixel_office.company.executor_cli import CLIExecutor
    from pixel_office.company.runtime import Task
    from pixel_office.control.budget import BudgetGuard
    calls = []
    ex = CLIExecutor(invoke_fn=lambda cli, p: (calls.append(1), "DONE: shipped")[1],
                     budget=BudgetGuard(cap_usd=2.0))          # only 2 activations allowed
    for _ in range(4):
        ex(Employee("e", "eng"), Task("x", dri="e"))
    assert len(calls) == 2                                     # spent the budget, then stopped
    r = ex(Employee("e", "eng"), Task("x", dri="e"))
    assert r.ok is False and "budget" in r.summary            # fails closed, honestly


def test_one_step_per_tick_gated_on_success():
    c = _api_company()
    c.runtime.executor = _executor(True)
    loop = _wf_loop(c)
    loop.tick(0)
    run = c.workflows["kr1"]
    assert run.workflow_id == "ship-feature"
    assert run.step_index == 1 and not run.done and not run.blocked   # step 0 done → next is step 1
    loop.tick(1)
    assert c.workflows["kr1"].step_index == 2                          # only advances one step per tick


def test_a_failed_step_halts_the_workflow():
    c = _api_company()
    c.runtime.executor = _executor(False)
    loop = _wf_loop(c)
    loop.tick(0)
    assert c.workflows["kr1"].blocked and c.workflows["kr1"].step_index == 0   # halts, never skips
    loop.tick(1)
    assert c.workflows["kr1"].step_index == 0 and c.workflows["kr1"].blocked   # frozen while blocked


def test_step_records_evidence_under_compound_kr_skill_task_class():
    c = _api_company()
    c.runtime.executor = _executor(True)
    _wf_loop(c).tick(0)   # step 0 = "spec" (skill api-design) → task_class "kr1:api-design"
    seen = {ev.task_class for mem in c.runtime.memories.values() for ev in mem.evidence}
    assert "kr1:api-design" in seen
    assert "kr1" not in seen   # workflow steps never collide with the default planner's bare kr id


def test_workflow_completes_after_all_steps():
    from pixel_office.company import workflows
    c = _api_company()
    c.runtime.executor = _executor(True)
    c.start_workflow("kr1", "architecture-review")   # no risky steps → runs to completion
    loop = _wf_loop(c)
    for t in range(len(workflows.get("architecture-review").steps) + 2):
        loop.tick(t)
    assert c.workflows["kr1"].done


def test_ship_feature_stops_at_the_risky_deploy_step_for_approval():
    # a workflow WITH a risky step (ship-feature → deploy) advances up to it, then waits
    from pixel_office.company import workflows
    c = _api_company()
    c.runtime.executor = _executor(True)
    loop = _wf_loop(c)
    for t in range(len(workflows.get("ship-feature").steps) + 3):
        loop.tick(t)
    run = c.workflows["kr1"]
    assert not run.done and run.step_index == 5      # halted at 'deploy' (index 5), not completed
    assert c.memos.has_open("approve deploy: ship the payments feature")   # awaits approval


def test_default_planner_path_unchanged_without_workflows():
    c = build_company({"what": "x", "roles": [{"title": "Founder", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "do the thing", target=10))
    assert planner_for(c) is default_planner
    c.runtime.executor = _executor(True)
    _wf_loop(c, planner_for(c)).tick(0)
    seen = {ev.task_class for mem in c.runtime.memories.values() for ev in mem.evidence}
    assert "kr1" in seen and not c.workflows      # bare kr id, no workflow run created


def test_assign_raise_halts_and_releases_mapping():
    # if dispatch raises (e.g. a fired/unknown DRI) the workflow must halt and its
    # task→KR mapping must be released — no leak, no infinite retry.
    c = _api_company()
    c.runtime.executor = _executor(True)

    def boom(task):
        raise KeyError("no such DRI")

    c.runtime.assign = boom
    _wf_loop(c).tick(0)
    assert c.workflows["kr1"].blocked and c._wf_task_kr == {}


def test_mismatched_result_is_not_credited():
    # an executor returning a result for a DIFFERENT task must not advance the step
    c = _api_company()
    c.runtime.executor = lambda emp, task: TaskResult(task.id + 999, emp.id, True, "wrong")
    _wf_loop(c).tick(0)
    assert c.workflows["kr1"].blocked and c.workflows["kr1"].step_index == 0


def test_clear_workflow_unblocks_for_retry():
    c = _api_company()
    c.runtime.executor = _executor(False)
    loop = _wf_loop(c)
    loop.tick(0)
    assert c.workflows["kr1"].blocked
    assert c.clear_workflow("kr1") is True and not c.workflows["kr1"].blocked
    c.runtime.executor = _executor(True)
    loop.tick(1)
    assert c.workflows["kr1"].step_index == 1        # retried step now advances
