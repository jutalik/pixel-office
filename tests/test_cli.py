"""CLI entrypoint wiring — the exit-code/stdout contract (was untested)."""
import json
import types

import pytest

from pixel_office import cli, doctor


def _args(**kw):
    return types.SimpleNamespace(**kw)


# ---- po up multi-CLI wiring ----------------------------------------------------

@pytest.fixture()
def capture_up(monkeypatch):
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
