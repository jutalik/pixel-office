"""Full-loop e2e: po new → po run → live company."""
import json
import types

import pytest

from pixel_office.company.factory import build_company


def test_build_company_from_manifest():
    m = {"name": "RecipeCo", "goal": "Be the #1 recipe blog", "mode": "Autopilot",
         "roles": [{"title": "backend engineer", "count": 1}, {"title": "writer", "count": 2}]}
    c = build_company(m)
    assert c.name == "RecipeCo" and c.okrs.objective.startswith("Be the")
    assert c.mode.drive == "Autopilot" and len(c.team) == 3
    ids = sorted(e.id for e in c.team.all())
    assert ids == ["backend-engineer", "writer-1", "writer-2"]   # slugged, unique


def test_build_company_tolerates_garbage():
    c = build_company({"roles": [{"title": ""}, "just a string", {"count": "bad"}]})
    assert len(c.team) >= 1 and c.okrs.objective  # never crashes
    # non-iterable / non-list roles must not crash or expand a string per-char
    assert build_company({"roles": 42}).okrs.objective
    assert len(build_company({"roles": "engineer"}).team) == 0


def test_cmd_run_missing_manifest(tmp_path, capsys):
    from pixel_office import cli
    rc = cli._cmd_run(types.SimpleNamespace(dir=str(tmp_path), port=7717, host_id="local", demo=False))
    assert rc == 1 and "po new" in capsys.readouterr().err


def test_cmd_run_bad_json(tmp_path, capsys):
    pytest.importorskip("fastapi")
    from pixel_office import cli
    (tmp_path / "pixel-office.json").write_text("{not json")
    rc = cli._cmd_run(types.SimpleNamespace(dir=str(tmp_path), port=7717, host_id="local", demo=False))
    assert rc == 1 and "can't read" in capsys.readouterr().err   # clean error, no traceback


def test_e2e_new_then_run_shows_live_company(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from pixel_office import cli
    from pixel_office.company.factory import build_company
    from pixel_office.company.runtime import Task
    from pixel_office.scaffold import builder
    from pixel_office.scaffold.manifest import Manifest

    # po new
    m = Manifest.from_dict({"what": "AI recipe blog", "name": "recipeco", "goal": "weekly cooks",
                            "mode": "Copilot", "roles": [{"title": "writer", "count": 2}]})
    project = builder.build(m, tmp_path)
    manifest = json.loads((project / "pixel-office.json").read_text())

    # po run (build the company from the recorded manifest + serve)
    company = build_company(manifest)
    from pixel_office.server import create_app
    app = create_app(sources=[], company=company)
    company.runtime.sink = app.state.hub.ingest
    with TestClient(app) as client:
        for emp in company.team.all():
            company.runtime.assign(Task("onboard", dri=emp.id))
        # company surface reflects the scaffolded project
        data = client.get("/api/company").json()
        assert data["summary"]["name"] == "recipeco"
        assert data["summary"]["headcount"] == 2
        # the two writers are live avatars in the office
        rows = client.get("/api/office").json()["rows"]
        writers = [r for r in rows if r["cli"] == "company"]
        assert len(writers) == 2 and all(r["activity"] == "done" for r in writers)
