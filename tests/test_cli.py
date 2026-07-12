"""CLI entrypoint wiring — the exit-code/stdout contract (was untested)."""
import json
import types

import pytest

from pixel_office import cli, doctor


def _args(**kw):
    return types.SimpleNamespace(**kw)


# ---- onboarding: capability note surfaces at `po new` --------------------------

def test_capability_note_names_available_clis(monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda: {"clis": {
        "claude": {"available": True}, "codex": {"available": False}}})
    note = cli._capability_note()
    assert "claude" in note and "codex" not in note and "po doctor" in note


def test_capability_note_when_no_cli_still_points_to_demo(monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda: {"clis": {"claude": {"available": False}}})
    note = cli._capability_note()
    assert "no AI CLIs detected" in note and "po run --demo" in note   # honest: demo still works


def test_po_new_product_url_wires_growth_loop_and_notes_validation(tmp_path, capsys, monkeypatch):
    import json as _json
    monkeypatch.setattr(doctor, "run", lambda: {"clis": {}})
    monkeypatch.setattr("pixel_office.company.metrics.fetch_metrics", lambda url, timeout=1.5: {"signups": 3})
    rc = cli._cmd_new(_args(dir=str(tmp_path), what="blog", name="rb", goal="", niche="",
                            stack="api-service", benchmarks="", roles="", kr="", mode="Copilot",
                            product_url="http://127.0.0.1:9999", yes=True))
    out = capsys.readouterr().out
    assert rc == 0 and "growth loop" in out and "validated against real metrics" in out
    saved = _json.loads((tmp_path / "rb" / "pixel-office.json").read_text())
    assert saved["product_url"] == "http://127.0.0.1:9999"        # persisted for `po run`


def test_po_new_without_product_url_warns_outcomes_unvalidated(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda: {"clis": {}})
    cli._cmd_new(_args(dir=str(tmp_path), what="blog", name="b2", goal="", niche="",
                       stack="api-service", benchmarks="", roles="", kr="", mode="Copilot",
                       product_url=None, yes=True))
    assert "UNVALIDATED" in capsys.readouterr().out               # honest: no metrics → no validation


def test_po_new_surfaces_env_and_company_next_steps(tmp_path, capsys, monkeypatch):
    # a new user should learn what they can run (env) AND the right next command
    monkeypatch.setattr(doctor, "run", lambda: {"clis": {"claude": {"available": True}}})
    rc = cli._cmd_new(_args(dir=str(tmp_path), what="recipe blog", name="rb", goal="", niche="",
                            stack="api-service", benchmarks="", roles="", kr="", mode="Copilot", yes=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "po run --demo" in out and "po run --live" in out    # company mode, not stale `po up`
    assert "detected AI CLIs: claude" in out                    # env check auto-surfaced at `new`


# ---- po up multi-CLI wiring ----------------------------------------------------

@pytest.fixture()
def capture_up(monkeypatch):
    pytest.importorskip("fastapi")  # `po up` needs the web extra
    captured = {}

    def fake_create_app(transcripts=None, *, host_id="local", sources=None, hook_token=None):
        captured["transcripts"] = transcripts
        captured["sources"] = sources or []
        captured["host_id"] = host_id
        return object()

    monkeypatch.setattr("pixel_office.server.create_app", fake_create_app)
    monkeypatch.setattr("pixel_office.hooks.write_endpoint_file", lambda *a, **k: None)
    monkeypatch.setattr("pixel_office.hooks.remove_endpoint_file", lambda: None)
    monkeypatch.setattr("pixel_office.hooks.status", lambda: {"installed": False})
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    return captured


def test_cmd_up_wires_installed_clis_only(capture_up, monkeypatch):
    installed = {"claude", "grok"}  # codex NOT installed
    monkeypatch.setattr(doctor, "which", lambda a: "/bin/" + a.name if a.name in installed else None)
    rc = cli._cmd_up(_args(file=None, port=7717, host_id="h1"))
    assert rc == 0
    assert sorted(s.cli for s in capture_up["sources"]) == ["claude", "grok"]  # codex skipped
    assert all(s.host_id == "h1" for s in capture_up["sources"])


def test_cmd_up_no_clis_returns_1(capture_up, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "which", lambda a: None)  # nothing installed
    rc = cli._cmd_up(_args(file=None, port=7717, host_id="local"))
    assert rc == 1
    assert "no supported CLIs" in capsys.readouterr().err


def test_cmd_up_file_builds_single_tailer(capture_up, tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text('{"type":"user","timestamp":"2026-07-10T00:00:00Z","sessionId":"s",'
                 '"message":{"role":"user","content":"hi"}}\n')
    rc = cli._cmd_up(_args(file=str(f), port=7717, host_id="local"))
    assert rc == 0
    assert capture_up["transcripts"] == [f]


# ---- po deploy -----------------------------------------------------------------

def test_cmd_deploy_json(capsys):
    rc = cli._cmd_deploy(_args(json=True))
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["localhost"] is True and "recommendation" in plan


# ---- po hooks ------------------------------------------------------------------

def test_cmd_hooks_status(monkeypatch, capsys):
    monkeypatch.setattr("pixel_office.hooks.status", lambda: {"installed": False})
    assert cli._cmd_hooks(_args(action="status")) == 0
    assert "installed" in capsys.readouterr().out


def test_cmd_hooks_runtime_error_returns_1(monkeypatch, capsys):
    def boom():
        raise RuntimeError("no can do")
    monkeypatch.setattr("pixel_office.hooks.install", boom)
    assert cli._cmd_hooks(_args(action="install")) == 1
    assert "no can do" in capsys.readouterr().err


# ---- po new --------------------------------------------------------------------

def _new_args(tmp_path, **kw):
    base = dict(dir=str(tmp_path), what="a demo api", name="demo", goal="", niche="",
                stack="api-service", benchmarks="", roles="", yes=True)
    base.update(kw)
    return _args(**base)


def test_cmd_new_without_yes_creates_nothing(tmp_path, capsys):
    rc = cli._cmd_new(_new_args(tmp_path, yes=False))
    assert rc == 0
    assert "charter" in capsys.readouterr().out.lower() or not (tmp_path / "demo").exists()
    assert not (tmp_path / "demo").exists()


def test_cmd_new_with_yes_builds(tmp_path):
    rc = cli._cmd_new(_new_args(tmp_path))
    assert rc == 0
    assert (tmp_path / "demo" / "backend" / "app.py").exists()


def test_cmd_new_into_readonly_dir_degrades(tmp_path, capsys):
    import os
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    try:
        rc = cli._cmd_new(_new_args(ro))
        assert rc == 1                       # clean error, not a traceback
        assert "po new:" in capsys.readouterr().err
    finally:
        os.chmod(ro, 0o700)


# ---- po run ---------------------------------------------------------------------

def test_run_demo_and_live_are_mutually_exclusive():
    # combining them would fake goal progress while real work spends tokens
    parser = cli.build_parser()
    parser.parse_args(["run", "--demo"])       # each alone is fine
    parser.parse_args(["run", "--live"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--demo", "--live"])
