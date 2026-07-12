from pixel_office.company.autonomy import AutonomyLoop
from pixel_office.company.factory import build_company
from pixel_office.company.okr import KeyResult
from pixel_office.company.runtime import TaskResult


def test_creative_employee_proposes_a_bounded_initiative():
    c = build_company({"what": "x", "goal": "1000 signups",
                       "roles": [{"title": "Growth Marketer", "count": 1}]})
    c.okrs.add_kr(KeyResult("kr1", "reach 1000 signups", target=1000))   # a measurable target
    c.runtime.executor = lambda emp, task: TaskResult(task.id, emp.id, True, "x")
    loop = AutonomyLoop(c, max_dispatch=2, initiative_every_s=0)   # fire on the first tick
    r = loop.tick(0)
    assert r.initiatives == 1
    assert "idea" in [a["kind"] for a in c.activity_view(50)]         # visible proposal
    # a reversible/local idea auto-becomes ONE bounded exploration task, targeting the KR
    assert any(t.task_class == "initiative" for t in c.backlog)
    assert c.ideas and c.ideas[0].target_kr_id == "kr1"              # honest: named target


def test_non_creative_team_proposes_nothing():
    c = build_company({"what": "x", "roles": [{"title": "Backend Engineer", "count": 1}]})
    loop = AutonomyLoop(c, initiative_every_s=0)
    assert loop.tick(0).initiatives == 0
