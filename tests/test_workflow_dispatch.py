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


def test_planner_for_picks_workflow_planner_when_team_has_workflows():
    c = _api_company()
    assert planner_for(c) is workflow_planner


def test_one_step_per_tick_gated_on_success():
    c = _api_company()
    c.runtime.executor = _executor(True)
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop.tick(0)
    run = c.workflows["kr1"]
    assert run.workflow_id == "ship-feature"
    assert run.step_index == 1 and not run.done and not run.blocked   # step 0 done → next is step 1
    loop.tick(1)
    assert c.workflows["kr1"].step_index == 2                          # only advances one step per tick


def test_a_failed_step_halts_the_workflow():
    c = _api_company()
    c.runtime.executor = _executor(False)
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop.tick(0)
    run = c.workflows["kr1"]
    assert run.blocked and run.step_index == 0     # failed step halts, never skips ahead
    loop.tick(1)
    assert c.workflows["kr1"].step_index == 0 and c.workflows["kr1"].blocked   # frozen while blocked


def test_step_records_evidence_under_compound_kr_skill_task_class():
    c = _api_company()
    c.runtime.executor = _executor(True)
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop.tick(0)   # step 0 = "spec" (skill api-design) → task_class "kr1:api-design"
    seen = {ev.task_class for mem in c.runtime.memories.values() for ev in mem.evidence}
    assert "kr1:api-design" in seen
    assert "kr1" not in seen   # workflow steps never collide with the default planner's bare kr id


def test_workflow_completes_after_all_steps():
    c = _api_company()
    c.runtime.executor = _executor(True)
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    from pixel_office.company import workflows
    n = len(workflows.get("ship-feature").steps)
    for t in range(n + 2):
        loop.tick(t)
    assert c.workflows["kr1"].done


def test_default_planner_path_unchanged_without_workflows():
    c = build_company({"what": "x", "roles": [{"title": "Founder", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "do the thing", target=10))
    assert planner_for(c) is default_planner
    c.runtime.executor = _executor(True)
    loop = AutonomyLoop(c, planner_fn=planner_for(c), max_dispatch=1)
    loop.tick(0)
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
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop.tick(0)
    assert c.workflows["kr1"].blocked and c._wf_task_kr == {}


def test_mismatched_result_is_not_credited():
    # an executor returning a result for a DIFFERENT task must not advance the step
    c = _api_company()
    c.runtime.executor = lambda emp, task: TaskResult(task.id + 999, emp.id, True, "wrong")
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop.tick(0)
    assert c.workflows["kr1"].blocked and c.workflows["kr1"].step_index == 0


def test_clear_workflow_unblocks_for_retry():
    c = _api_company()
    c.runtime.executor = _executor(False)
    loop = AutonomyLoop(c, planner_fn=workflow_planner, max_dispatch=1)
    loop.tick(0)
    assert c.workflows["kr1"].blocked
    assert c.clear_workflow("kr1") is True and not c.workflows["kr1"].blocked
    c.runtime.executor = _executor(True)
    loop.tick(1)
    assert c.workflows["kr1"].step_index == 1        # retried step now advances
