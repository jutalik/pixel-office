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


def test_scaffolded_backend_smoke_passes(tmp_path):
    # the instrumentation surface of a freshly scaffolded product must answer
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    m = Manifest.from_dict({"what": "demo api", "stack": "api-service"})
    project = builder.build(m, tmp_path)
    ns = {"__file__": str(project / "backend" / "app.py")}
    code = (project / "backend" / "app.py").read_text()
    exec(compile(code, "app.py", "exec"), ns)
    client = TestClient(ns["app"])
    assert client.get("/health").json()["ok"] is True
    assert client.get("/api/telemetry").status_code == 200
    # write auth enforced
    assert client.post("/api/items", json={"body": "x"}).status_code == 401
    assert client.post("/api/items", json={"body": "x"},
                       headers={"x-app-token": "dev-token"}).status_code == 200


def test_interactive_flow_with_injected_io():
    scripted = iter(["a cooking blog", "CookBot", "weekly recipes", "home cooks", "allrecipes",
                     "chat-product", "1 writer"])
    said = []
    m = run_interactive(lambda _p: next(scripted), lambda _p: True, said.append)
    assert m is not None and m.name == "CookBot" and m.stack == "chat-product"
    assert any("charter" in s for s in said)


def test_interactive_cancel_writes_nothing():
    scripted = iter(["a blog", "", "", "", "", "", ""])
    m = run_interactive(lambda _p: next(scripted), lambda _p: False, lambda _s: None)
    assert m is None
