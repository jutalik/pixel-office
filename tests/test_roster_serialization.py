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


def test_api_company_includes_workflows_key_and_all_originals():
    c = build_company({"what": "x", "roles": [{"title": "backend engineer", "count": 1}]})
    with TestClient(create_app(sources=[], company=c)) as client:
        d = client.get("/api/company").json()
    for k in ("summary", "okrs", "ceo_cards", "hr", "trends", "meeting", "activity",
              "roster", "workflows"):
        assert k in d, k
    assert isinstance(d["workflows"], list)
