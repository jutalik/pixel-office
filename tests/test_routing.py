"""Skill-based task routing — sensible owner by role fit + evidence (0 tokens)."""
from pixel_office.company.company import Company
from pixel_office.company.employee import Employee
from pixel_office.company.okr import KeyResult
from pixel_office.company.routing import best_owner, department_of, role_fit


def _team():
    c = Company("co", "grow the studio")
    c.team.hire(Employee("eng", "backend engineer"))
    c.team.hire(Employee("writer", "content writer"))
    c.team.hire(Employee("mkt", "growth marketer"))
    return c


def test_routes_content_goal_to_the_writer():
    c = _team()
    owner = best_owner(c, KeyResult("k", "publish 10 recipes", target=10))
    assert owner.id == "writer"


def test_routes_growth_goal_to_the_marketer():
    c = _team()
    owner = best_owner(c, KeyResult("k", "reach 1000 signups", target=1000))
    assert owner.id == "mkt"


def test_routes_engineering_goal_to_the_engineer():
    c = _team()
    owner = best_owner(c, KeyResult("k", "ship 5 backend features", target=5))
    assert owner.id == "eng"


def test_proven_competency_breaks_ties_between_same_role():
    c = Company("co", "x")
    c.team.hire(Employee("w1", "content writer"))
    c.team.hire(Employee("w2", "content writer"))
    kr = KeyResult("kr1", "publish recipes", target=10)
    # w2 builds a real track record on this work-stream (≥ sample floor, all ok)
    for _ in range(3):
        c.runtime.memory_of("w2").record("task_done", "kr1", True)
    assert best_owner(c, kr).id == "w2"          # equal role fit → proven one wins


def test_no_role_match_falls_back_to_lightest_loaded_not_crash():
    c = Company("co", "x")
    c.team.hire(Employee("a", "operations"))     # no family matches the KR
    c.team.hire(Employee("b", "operations"))
    kr = KeyResult("kr1", "quux the frobnicator", target=1)
    c.runtime.memory_of("a").record("task_done", "other", True)   # a is busier
    assert best_owner(c, kr).id == "b"           # lighter load wins the fallback


def test_empty_team_returns_none():
    assert best_owner(Company("co", "x"), KeyResult("k", "anything", target=1)) is None


def test_role_fit_is_zero_for_unrelated_role():
    e = Employee("eng", "backend engineer")
    assert role_fit(KeyResult("k", "publish blog posts", target=3), e) == 0


def test_plain_engineer_title_activates_engineering_family():
    # a bare "software engineer" (no domain nouns) must still win engineering work,
    # even when a marketer was hired first (regression: both used to score 0 → first)
    c = Company("co", "x")
    c.team.hire(Employee("mkt", "growth marketer"))
    c.team.hire(Employee("eng", "software engineer"))
    assert best_owner(c, KeyResult("k", "ship 5 backend features", target=5)).id == "eng"


def test_unhashable_kr_id_does_not_crash_routing():
    c = _team()
    kr = KeyResult(["not", "a", "str"], "publish 10 recipes", target=10)  # bad id type
    assert best_owner(c, kr).id == "writer"      # routes by fit, no TypeError


def test_department_of_maps_role_to_a_room():
    assert department_of(Employee("e", "backend engineer")) == "Engineering"
    assert department_of(Employee("w", "content writer")) == "Content"
    assert department_of(Employee("m", "growth marketer")) == "Growth"
    assert department_of(Employee("o", "office manager")) == "Team"   # unmatched → shared room


def test_company_roster_carries_departments():
    c = _team()
    depts = {r["id"]: r["dept"] for r in c.roster()}
    assert depts == {"eng": "Engineering", "writer": "Content", "mkt": "Growth"}
