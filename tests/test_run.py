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
    rc = cli._cmd_run(types.SimpleNamespace(dir=str(tmp_path), port=7717, host_id="local",
                                            demo=False, live=False))
    assert rc == 1 and "po new" in capsys.readouterr().err


def test_cmd_run_bad_json(tmp_path, capsys):
    pytest.importorskip("fastapi")
    from pixel_office import cli
    (tmp_path / "pixel-office.json").write_text("{not json")
    rc = cli._cmd_run(types.SimpleNamespace(dir=str(tmp_path), port=7717, host_id="local",
                                            demo=False, live=False))
    assert rc == 1 and "can't read" in capsys.readouterr().err   # clean error, no traceback


def test_cmd_run_live_wires_real_executor_without_running(tmp_path, monkeypatch):
    # --live swaps in the CLIExecutor but must NOT auto-run tasks (no token spend)
    pytest.importorskip("fastapi")
    import types as _t

    from pixel_office import cli
    from pixel_office.company.executor_cli import CLIExecutor

    (tmp_path / "pixel-office.json").write_text(
        '{"name":"c","goal":"g","mode":"Copilot","roles":[{"title":"eng","count":1}]}')

    captured = {}

    def fake_create_app(sources=None, company=None, host_id="local", run_mode="watch"):
        captured["company"] = company
        captured["run_mode"] = run_mode
        hub = _t.SimpleNamespace(ingest=lambda ev: None)
        return _t.SimpleNamespace(state=_t.SimpleNamespace(hub=hub))

    invoke_calls = []
    monkeypatch.setattr("pixel_office.server.create_app", fake_create_app)
    monkeypatch.setattr("pixel_office.company.cli_invoke.make_subprocess_invoke",
                        lambda **k: (lambda cli_, prompt: invoke_calls.append(1) or ""))
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)

    rc = cli._cmd_run(_t.SimpleNamespace(dir=str(tmp_path), port=7717, host_id="local",
                                         demo=False, live=True))
    assert rc == 0
    assert isinstance(captured["company"].runtime.executor, CLIExecutor)  # real executor wired
    assert invoke_calls == []                                              # NOT auto-run → 0 tokens
    assert captured["run_mode"] == "live"                                  # browser can show LIVE honestly


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


def test_api_company_payload_has_roster_and_activity(tmp_path):
    # the office UI depends on these keys (department rooms + CEO activity feed)
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from pixel_office.company.autonomy import AutonomyLoop
    from pixel_office.company.factory import build_company
    from pixel_office.server import create_app

    manifest = {"name": "RecipeCo", "goal": "weekly recipes", "mode": "Autopilot",
                "roles": [{"title": "backend engineer", "count": 1},
                          {"title": "content writer", "count": 1},
                          {"title": "growth marketer", "count": 1}],
                "key_results": [{"text": "publish 10 recipes", "target": 10, "cadence": "weekly"},
                                {"text": "reach 500 signups", "target": 500, "cadence": "monthly"}]}
    company = build_company(manifest)
    app = create_app(sources=[], company=company)
    company.runtime.sink = app.state.hub.ingest
    with TestClient(app) as client:
        AutonomyLoop(company, max_dispatch=2, review_every_s=1e9).tick(now=0)  # one real tick
        d = client.get("/api/company").json()
        for key in ("summary", "okrs", "ceo_cards", "hr", "trends", "meeting", "activity", "roster"):
            assert key in d, f"missing {key}"
        # roster carries departments (drives the office department rooms)
        depts = {m["dept"] for m in d["roster"]}
        assert {"Engineering", "Content", "Growth"} <= depts
        # KRs surfaced + activity recorded by the tick
        assert len(d["okrs"]) == 2
        assert any(a["kind"] in ("plan", "work") for a in d["activity"])
        # routing put the recipes work on the writer, not the engineer
        work = [a["text"] for a in d["activity"] if a["kind"] == "work"]
        assert any("content-writer" in t and "recipes" in t for t in work)
