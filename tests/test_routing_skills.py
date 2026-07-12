from pixel_office.company import routing, workflows
from pixel_office.company.company import Company
from pixel_office.company.employee import Employee
from pixel_office.company.factory import build_company
from pixel_office.company.okr import KeyResult


def test_skilled_engineer_owns_an_api_kr():
    c = build_company({"what": "x", "roles": [
        {"title": "backend engineer", "count": 1},
        {"title": "member", "count": 1}]})
    kr = KeyResult("kr1", "ship the payments API endpoint", target=1)
    assert routing.best_owner(c, kr).role == "backend"


def test_best_owner_for_step_routes_architecture_to_the_architect():
    c = build_company({"what": "x", "roles": [
        {"title": "architecture engineer", "count": 1},
        {"title": "backend engineer", "count": 1}]})
    kr = KeyResult("kr1", "ship a feature", target=1)
    arch_step = workflows.get("ship-feature").steps[1]      # "architecture" (skill=system-design)
    assert routing.best_owner_for_step(c, kr, arch_step).role == "architect"
    impl_step = workflows.get("ship-feature").steps[2]      # "implement" (skill=backend-impl)
    assert routing.best_owner_for_step(c, kr, impl_step).role == "backend"


def test_best_owner_for_step_routes_a_family_only_step():
    c = build_company({"what": "x", "roles": [
        {"title": "Content Writer", "count": 1}, {"title": "Backend Engineer", "count": 1}]})
    kr = KeyResult("kr1", "publish articles", target=1)
    step = workflows.get("content-pipeline").steps[0]   # "research": family=content, no skill
    assert routing.best_owner_for_step(c, kr, step).role == "writer"


def test_title_only_routing_is_unchanged():
    # no skills → skill keywords empty → routing behaves exactly as before
    c = Company("x", "grow")
    c.team.hire(Employee("w", "writer"))
    c.team.hire(Employee("e", "engineer"))
    kr = KeyResult("kr1", "ship an API feature", target=1)
    assert routing.best_owner(c, kr).id == "e"
