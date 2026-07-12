from pixel_office.company import roles
from pixel_office.company.factory import build_company
from pixel_office.scaffold.init_chat import answers_to_manifest


def test_library_title_enriches_employee():
    c = build_company({"what": "x", "roles": [{"title": "backend engineer", "count": 1}]})
    e = c.team.all()[0]
    assert e.role == "backend"
    assert "backend-impl" in e.skills and e.tier == "standard"
    assert e.persona and "ship-feature" in e.workflows
    assert e.title == "backend engineer"      # the user's own title is kept (additive)


def test_unknown_title_stays_a_plain_employee():
    c = build_company({"what": "x", "roles": [{"title": "Founder", "count": 1}]})
    e = c.team.all()[0]
    assert e.role == "" and e.skills == () and e.workflows == ()
    assert e.title == "Founder"               # backward compatible


def test_architect_role_is_deep_tier_with_architecture_skills():
    c = build_company({"what": "x", "roles": [{"title": "architecture engineer", "count": 1}]})
    e = c.team.all()[0]
    assert e.role == "architect" and e.tier == "deep"
    assert "system-design" in e.skills


def test_scaffold_seeds_stack_default_team_when_no_roles():
    m = answers_to_manifest({"what": "a notes api", "stack": "api-service"})
    titles = [r.title for r in m.roles]
    assert len(titles) == len(roles.default_team_for("api-service"))
    assert any("Architecture" in t for t in titles)      # architect seeded


def test_scaffold_respects_explicit_roles():
    m = answers_to_manifest({"what": "blog", "roles": "2 writer"})
    assert len(m.roles) == 1 and m.roles[0].count == 2
