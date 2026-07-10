import json

import pytest

from pixel_office import hooks
from pixel_office.telemetry.hook_events import HookEventFactory


@pytest.fixture()
def hook_env(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "PO_DIR", tmp_path / "po")
    monkeypatch.setattr(hooks, "ENDPOINT_FILE", tmp_path / "po" / "hook-endpoint.json")
    monkeypatch.setattr(hooks, "SCRIPT_PATH", tmp_path / "po" / "hooks" / "claude-hook.sh")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    return tmp_path


def test_install_is_idempotent_and_additive(hook_env):
    settings_path = hooks.claude_settings_path()
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "Bash",
                                   "hooks": [{"type": "command", "command": "/user/own.sh"}]}]},
         "theme": "dark"}))
    hooks.install()
    hooks.install()  # idempotent
    s = json.loads(settings_path.read_text())
    assert s["theme"] == "dark"  # unrelated settings preserved
    pre = s["hooks"]["PreToolUse"]
    assert any(h["command"] == "/user/own.sh" for e in pre for h in e["hooks"])  # user kept
    ours = [h for e in pre for h in e["hooks"] if str(hooks.SCRIPT_PATH) in h["command"]]
    assert len(ours) == 1  # no duplicates
    assert set(s["hooks"].keys()) >= set(hooks.CLAUDE_EVENTS)
    assert hooks.SCRIPT_PATH.exists() and hooks.MARKER in hooks.SCRIPT_PATH.read_text()


def test_uninstall_is_surgical(hook_env):
    settings_path = hooks.claude_settings_path()
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(
        {"hooks": {"Stop": [{"matcher": "*",
                             "hooks": [{"type": "command", "command": "/user/own.sh"}]}]}}))
    hooks.install()
    assert hooks.status()["installed"] is True
    hooks.uninstall()
    s = json.loads(settings_path.read_text())
    stop = s.get("hooks", {}).get("Stop", [])
    assert any(h["command"] == "/user/own.sh" for e in stop for h in e["hooks"])
    assert hooks.status()["installed"] is False


def test_uninstall_exact_match_never_removes_lookalike_user_commands(hook_env):
    settings_path = hooks.claude_settings_path()
    settings_path.parent.mkdir(parents=True)
    lookalike = f"/usr/bin/logger --wrap {hooks.SCRIPT_PATH}"  # contains our path
    settings_path.write_text(json.dumps(
        {"hooks": {"Stop": [{"matcher": "*",
                             "hooks": [{"type": "command", "command": lookalike}]}]}}))
    hooks.install()
    hooks.uninstall()
    s = json.loads(settings_path.read_text())
    kept = [h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]]
    assert lookalike in kept  # substring match would have deleted it


def test_save_detects_concurrent_modification(hook_env):
    settings_path = hooks.claude_settings_path()
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{}")
    settings, token = hooks._load_settings(settings_path)
    settings_path.write_text(json.dumps({"hooks": {}, "user": "raced"}))  # concurrent edit
    with pytest.raises(RuntimeError):
        hooks._save_settings(settings_path, settings, token)
    assert json.loads(settings_path.read_text())["user"] == "raced"  # not clobbered


def test_script_quotes_endpoint_path(hook_env, monkeypatch):
    weird = hook_env / 'we"ird$(dir)' / "hook-endpoint.json"
    monkeypatch.setattr(hooks, "ENDPOINT_FILE", weird)
    content = hooks._script_content()
    assert "$(dir)" not in content.replace("'", "")  or "'" in content  # quoted literal
    assert 'EP=\'' in content or "EP='" in content


def test_install_refuses_corrupt_settings(hook_env):
    settings_path = hooks.claude_settings_path()
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{not json")
    with pytest.raises(RuntimeError):
        hooks.install()
    assert settings_path.read_text() == "{not json"  # untouched


def test_backup_written_on_change(hook_env):
    settings_path = hooks.claude_settings_path()
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{}")
    hooks.install()
    assert settings_path.with_suffix(".json.po-backup").exists()


def test_endpoint_file_written_0600(hook_env):
    hooks.write_endpoint_file(7717, "tok123")
    data = json.loads(hooks.ENDPOINT_FILE.read_text())
    assert data["port"] == 7717 and data["token"] == "tok123"
    assert (hooks.ENDPOINT_FILE.stat().st_mode & 0o777) == 0o600


# ---- payload -> RawEvent factory ------------------------------------------------

def _payload(**kw):
    d = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Bash",
         "tool_input": {"command": "SECRET"}}
    d.update(kw)
    return d


def test_factory_seq_is_per_session_stream():
    f = HookEventFactory("h1")
    a1 = f.from_payload("claude", _payload())
    a2 = f.from_payload("claude", _payload())
    b1 = f.from_payload("claude", _payload(session_id="s2"))
    assert (a1.seq, a2.seq, b1.seq) == (1, 2, 1)
    assert a1.source == "hook" and a1.source_confidence == "high"


def test_factory_composite_ask_user_question():
    f = HookEventFactory("h1")
    ev = f.from_payload("claude", _payload(tool_name="AskUserQuestion"))
    assert ev.kind == "AskUserQuestion"


def test_factory_subagent_identity():
    f = HookEventFactory("h1")
    ev = f.from_payload("claude", _payload(hook_event_name="SubagentStart",
                                           agent_id="sub-9", agent_type="Explore"))
    assert ev.agent_id == "sub-9" and ev.parent_agent_id == "main"
    assert ev.meta.get("agent_type") == "Explore"


def test_factory_never_leaks_tool_input():
    ev = HookEventFactory("h1").from_payload("claude", _payload())
    assert "SECRET" not in json.dumps(ev.meta)


def test_factory_rejects_unknown_or_incomplete():
    f = HookEventFactory("h1")
    assert f.from_payload("claude", _payload(hook_event_name="Bogus")) is None
    assert f.from_payload("claude", {"hook_event_name": "Stop"}) is None
    assert f.from_payload("claude", "junk") is None


def test_factory_mints_notification_subtype_composite():
    from pixel_office.telemetry.normalize import normalize
    f = HookEventFactory("h1")
    # an idle/completed notification must become 'done', not a false 'waiting'
    ev = f.from_payload("claude", {"hook_event_name": "Notification", "session_id": "s1",
                                   "notification_type": "idle_prompt"})
    assert ev.kind == "Notification:idle_prompt"
    assert normalize("claude", ev.kind) == "done"
    # an unknown subtype stays bare Notification (-> waiting)
    ev2 = f.from_payload("claude", {"hook_event_name": "Notification", "session_id": "s1",
                                    "notification_type": "mystery"})
    assert ev2.kind == "Notification"


def test_windows_install_refuses_with_clear_message(monkeypatch, hook_env):
    monkeypatch.setattr(hooks, "WINDOWS", True)
    with pytest.raises(RuntimeError, match="macOS/Linux/WSL"):
        hooks.install()


def test_remove_endpoint_file(hook_env):
    hooks.write_endpoint_file(7717, "tok")
    assert hooks.ENDPOINT_FILE.exists()
    hooks.remove_endpoint_file()
    assert not hooks.ENDPOINT_FILE.exists()
    hooks.remove_endpoint_file()  # idempotent, no raise


def test_settings_dir_gives_distinct_error(hook_env):
    path = hooks.claude_settings_path()
    path.parent.mkdir(parents=True)
    path.mkdir()  # settings.json is a directory
    with pytest.raises(RuntimeError, match="is a directory"):
        hooks.install()
