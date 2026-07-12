import pytest

from pixel_office.company.factory import build_company

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from pixel_office.server import create_app  # noqa: E402


def test_roster_carries_role_skills_workflows_additively():
    c = build_company({"what": "x", "roles": [{"title": "backend engineer", "count": 1}]})
    r = c.roster()[0]
    assert {"id", "title", "dept"} <= set(r)          # original contract preserved
    assert r["role"] == "backend" and "backend-impl" in r["skills"]
    assert "ship-feature" in r["workflows"] and r["tier"] == "standard"


def test_plain_employee_roster_row_is_empty_but_present():
    c = build_company({"what": "x", "roles": [{"title": "Founder", "count": 1}]})
    r = c.roster()[0]
    assert r["role"] == "" and r["skills"] == [] and r["workflows"] == []


def test_roster_exposes_creative_flag_and_evidence_based_style():
    c = build_company({"what": "x", "roles": [
        {"title": "Growth Marketer", "count": 1}, {"title": "Backend Engineer", "count": 1}]})
    by_title = {r["title"]: r for r in c.roster()}
    assert by_title["Growth Marketer"]["creative"] is True
    assert by_title["Backend Engineer"]["creative"] is False
    # style stays None until a focus emerges from >=2 observations (never declared)
    be = c.team.all()[1]
    assert c.roster()[1]["style"] is None
    mem = c.runtime.memory_of(be.id)
    mem.observe("focus", "backend-impl")
    mem.observe("focus", "backend-impl")
    assert c.roster()[1]["style"] == "backend-impl"


def test_roster_proficiency_is_evidence_based():
    from pixel_office.company import skills
    c = build_company({"what": "x", "roles": [{"title": "backend engineer", "count": 1}]})
    r = c.roster()[0]
    assert "proficiency" in r
    assert all(v is None for v in r["proficiency"].values())      # no evidence yet → "learning"
    mem = c.runtime.memory_of(r["id"])
    for _ in range(3):
        mem.record("task_done", skills.task_class_for("backend-impl", "kr1"), True)
    assert c.roster()[0]["proficiency"]["backend-impl"] is not None   # emerges from evidence


def test_api_company_includes_workflows_key_and_all_originals():
    c = build_company({"what": "x", "roles": [{"title": "backend engineer", "count": 1}]})
    with TestClient(create_app(sources=[], company=c)) as client:
        d = client.get("/api/company").json()
    for k in ("summary", "okrs", "ceo_cards", "hr", "trends", "meeting", "activity",
              "roster", "workflows"):
        assert k in d, k
    assert isinstance(d["workflows"], list)
