from pixel_office.company.executor_cli import CLIExecutor
from pixel_office.company.factory import build_company
from pixel_office.company.runtime import Task


def test_prompt_carries_skills_focus_and_creative_lenses():
    c = build_company({"what": "x", "roles": [{"title": "Growth Marketer", "count": 1}]})
    emp = c.team.all()[0]
    mem = c.runtime.memory_of(emp.id)
    mem.observe("focus", "growth-experiment")
    mem.observe("focus", "growth-experiment")           # focus emerges (>=2)
    ex = CLIExecutor(memories=c.runtime.memories)
    p = ex.build_prompt(emp, Task("do X", emp.id, "kr1:growth-experiment"))
    assert "Skills:" in p and "growth-experiment" in p
    assert "focus on growth-experiment" in p            # evidence-based focus injected
    assert "lens" in p.lower()                          # creative role → divergent lenses


def test_prompt_for_non_creative_role_has_no_lenses():
    c = build_company({"what": "x", "roles": [{"title": "Backend Engineer", "count": 1}]})
    emp = c.team.all()[0]
    p = CLIExecutor(memories=c.runtime.memories).build_prompt(emp, Task("do X", emp.id, "kr1"))
    assert "Skills:" in p and "lens" not in p.lower()
