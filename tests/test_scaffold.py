import json

import pytest

from pixel_office.scaffold import builder
from pixel_office.scaffold.init_chat import answers_to_manifest, run_interactive
from pixel_office.scaffold.manifest import Manifest, slugify


def test_manifest_requires_what():
    with pytest.raises(ValueError):
        Manifest.from_dict({"name": "x"})


def test_manifest_rejects_unknown_stack():
    with pytest.raises(ValueError):
        Manifest.from_dict({"what": "a blog", "stack": "wordpress"})


def test_manifest_defaults_and_slug():
    m = Manifest.from_dict({"what": "A Simple Blog!"})
    assert m.stack == "api-service"
    assert m.roles == [__import__("pixel_office.scaffold.manifest", fromlist=["Role"]).Role("Founder", 1)]
    assert m.slug == "a-simple-blog"
    assert slugify("  Wild/Name  ") == "wild-name"


def test_charter_is_plain_language():
    m = Manifest.from_dict({"what": "AI recipes", "goal": "weekly cooks", "niche": "home cooks",
                            "benchmarks": ["allrecipes"], "roles": [{"title": "writer", "count": 2}]})
    text = m.charter()
    assert "AI recipes" in text and "weekly cooks" in text and "2× writer" in text
    assert "allrecipes" in text


def test_answers_to_manifest_parses_roles_and_benchmarks():
    m = answers_to_manifest({"what": "x", "roles": "2 writer, editor", "benchmarks": "a, b"})
    counts = {r.title: r.count for r in m.roles}
    assert counts == {"writer": 2, "editor": 1}
    assert m.benchmarks == ["a", "b"]


def test_answers_to_manifest_parses_key_results():
    m = answers_to_manifest({"what": "recipes",
                             "key_results": "publish 10 recipes weekly, reach 1000 signups monthly, launch beta"})
    assert len(m.key_results) == 3
    k0, k1, k2 = m.key_results
    assert k0.target == 10 and k0.cadence == "weekly" and "recipes" in k0.text and "weekly" not in k0.text
    assert k1.target == 1000 and k1.cadence == "monthly"
    assert k2.target == 1.0 and k2.cadence == "weekly"   # no number → binary milestone, default weekly
    assert "10" in m.charter() and "Key Results" in m.charter()


def test_parse_krs_keeps_thousands_separated_numbers_as_one_kr():
    m = answers_to_manifest({"what": "x", "key_results": "reach 1,000 signups monthly, ship 5 features"})
    assert len(m.key_results) == 2
    assert m.key_results[0].target == 1000 and m.key_results[0].cadence == "monthly"
    assert m.key_results[1].target == 5


def test_parse_krs_collapses_gap_and_derives_metric_for_growth_loop():
    # removing the cadence word must not leave a double space, and a KPI keyword
    # must be derived so apply_metrics() can auto-update the KR from real metrics.
    m = answers_to_manifest({"what": "x",
                             "key_results": "reach 1000 weekly saves, ship 5 features"})
    k0, k1 = m.key_results
    assert "  " not in k0.text and k0.text == "reach 1000 saves"   # gap collapsed
    assert k0.cadence == "weekly" and k0.metric == "saves"          # keyword derived
    assert k1.metric == "features"
    # and the derived keyword actually drives the growth loop:
    from pixel_office.company.okr import KeyResult, OKRTree
    okrs = OKRTree(objective="x")
    okrs.add_kr(KeyResult("k0", k0.text, target=k0.target, cadence=k0.cadence, metric=k0.metric))
    assert okrs.apply_metrics({"saves": 400}) == 1
    assert okrs.key_results[0].current == 400


def test_key_results_survive_json_roundtrip_and_seed_the_company(tmp_path):
    m = Manifest.from_dict({"what": "recipes", "name": "recipeco", "goal": "grow readership",
                            "key_results": [{"text": "ship 10 features", "target": 10, "cadence": "weekly"},
                                            {"text": "1000 users", "target": 1000, "cadence": "monthly"}]})
    project = builder.build(m, tmp_path)
    saved = json.loads((project / "pixel-office.json").read_text())
    assert [k["target"] for k in saved["key_results"]] == [10, 1000]
    # the factory seeds them into a live company → the autonomy loop has real work
    from pixel_office.company.factory import build_company
    company = build_company(saved)
    krs = company.okrs.key_results
    assert [k.text for k in krs] == ["ship 10 features", "1000 users"]
    assert [k.cadence for k in krs] == ["weekly", "monthly"]
    assert company.okrs.progress() == 0.0   # honest: 0% until real progress


def test_factory_skips_malformed_krs_without_crashing():
    from pixel_office.company.factory import build_company
    company = build_company({"goal": "x", "key_results": [
        {"text": "good", "target": 5},          # kept
        {"text": "", "target": 3},              # dropped (no text)
        "not-a-dict",                            # dropped
        {"text": "bad target", "target": float("inf")},   # target coerced to 1.0
    ]})
    krs = company.okrs.key_results
    assert [k.text for k in krs] == ["good", "bad target"]
    assert krs[1].target == 1.0


def test_builder_writes_instrumented_skeleton(tmp_path):
    m = Manifest.from_dict({"what": "AI notes", "name": "mednote", "stack": "chat-product"})
    project = builder.build(m, tmp_path)
    assert project == tmp_path / "mednote"
    app = (project / "backend" / "app.py").read_text()
    for surface in ("/health", "/ready", "/api/telemetry", "/api/funnel",
                    "/api/quality", "/api/growth", "X-App-Token", "require_token"):
        assert surface in app or surface.lower() in app.lower()
    assert (project / "ops" / "DEPLOY.md").exists()
    assert (project / "Dockerfile").exists()
    saved = json.loads((project / "pixel-office.json").read_text())
    assert saved["what"] == "AI notes" and saved["stack"] == "chat-product"
    assert saved["mode"]["drive"] == "Copilot"  # default operating mode recorded


def test_manifest_records_operating_mode():
    m = Manifest.from_dict({"what": "x", "mode": "Autopilot"})
    assert m.mode.drive == "Autopilot" and m.mode.ceo_updates == "Weekly digest"
    assert "Autopilot" in m.charter()


def test_malicious_name_cannot_inject_code(tmp_path):
    pytest.importorskip("fastapi")
    sentinel = tmp_path / "pwned"
    # a payload that WOULD create the sentinel if it escaped the string literal
    evil = f'"""\nimport os; open({str(sentinel)!r}, "w").close()\nx = """'
    m = Manifest.from_dict({"what": evil, "name": evil, "goal": evil,
                            "benchmarks": [f'"""+open({str(sentinel)!r},"w").close()+"""']})
    project = builder.build(m, tmp_path)
    app = (project / "backend" / "app.py").read_text()
    # definitive proof: the file compiles (no syntax breakout) AND executing it
    # does not run the injected payload (the sentinel is never created).
    exec(compile(app, "app.py", "exec"), {"__file__": str(project / "backend" / "app.py")})
    assert not sentinel.exists()
    # and FastAPI still got a usable title (sanitized, not empty)
    assert 'FastAPI(title="' in app


def test_manifest_tolerates_wrong_types(tmp_path):
    # untrusted input: roles/benchmarks as wrong types must not crash
    m = Manifest.from_dict({"what": "x", "roles": 5, "benchmarks": {"a": 1}})
    assert m.roles  # defaulted, not crashed
    m2 = Manifest.from_dict({"what": "x", "roles": "not-a-list", "benchmarks": None})
    assert m2.benchmarks == []


def test_builder_refuses_to_overwrite_nonempty(tmp_path):
    (tmp_path / "mednote").mkdir()
    (tmp_path / "mednote" / "keep.txt").write_text("user work")
    m = Manifest.from_dict({"what": "x", "name": "mednote"})
    with pytest.raises(FileExistsError):
        builder.build(m, tmp_path)
    assert (tmp_path / "mednote" / "keep.txt").read_text() == "user work"


def test_builder_cleans_up_partial_output_on_failure(tmp_path, monkeypatch):
    from pathlib import Path
    calls = {"n": 0}
    orig = Path.write_text

    def flaky(self, content, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:               # fail partway through the build
            raise OSError("disk full")
        return orig(self, content, *a, **k)

    monkeypatch.setattr(Path, "write_text", flaky)
    m = Manifest.from_dict({"what": "x", "name": "proj"})
    with pytest.raises(OSError):
        builder.build(m, tmp_path)
    assert not (tmp_path / "proj").exists()   # partial dir removed → retry not blocked


def test_scaffolded_backend_smoke_passes(tmp_path, monkeypatch):
    # the instrumentation surface of a freshly scaffolded product must answer
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    m = Manifest.from_dict({"what": "demo api", "stack": "api-service"})
    project = builder.build(m, tmp_path)
    code = (project / "backend" / "app.py").read_text()
    assert "dev-token" not in code   # no baked-in, guessable default token

    # (1) unset APP_TOKEN → writes are fail-closed (503), reads still answer
    monkeypatch.delenv("APP_TOKEN", raising=False)
    ns = {"__file__": str(project / "backend" / "app.py")}
    exec(compile(code, "app.py", "exec"), ns)
    client = TestClient(ns["app"])
    assert client.get("/health").json()["ok"] is True
    assert client.get("/api/telemetry").status_code == 200
    assert client.post("/api/items", json={"body": "x"}).status_code == 503  # off, not open

    # (2) APP_TOKEN set → normal write auth (bad token 401, good token 200)
    monkeypatch.setenv("APP_TOKEN", "s3cret")
    ns2 = {"__file__": str(project / "backend" / "app.py")}
    exec(compile(code, "app.py", "exec"), ns2)
    client2 = TestClient(ns2["app"])
    assert client2.post("/api/items", json={"body": "x"}).status_code == 401
    assert client2.post("/api/items", json={"body": "x"},
                        headers={"x-app-token": "s3cret"}).status_code == 200


def test_interactive_flow_with_injected_io():
    # answers must line up with QUESTIONS order:
    # what, name, goal, niche, benchmarks, stack, roles, key_results, mode
    scripted = iter(["a cooking blog", "CookBot", "weekly recipes", "home cooks", "allrecipes",
                     "chat-product", "1 writer", "publish 5 recipes weekly", "Autopilot"])
    said = []
    m = run_interactive(lambda _p: next(scripted), lambda _p: True, said.append)
    assert m is not None and m.name == "CookBot" and m.stack == "chat-product"
    assert m.key_results and m.key_results[0].target == 5   # KR captured from the flow
    assert m.mode.drive == "Autopilot"
    assert any("charter" in s for s in said)


def test_interactive_cancel_writes_nothing():
    scripted = iter(["a blog", "", "", "", "", "", "", "", ""])
    m = run_interactive(lambda _p: next(scripted), lambda _p: False, lambda _s: None)
    assert m is None
