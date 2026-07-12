"""`po hooks` — install/uninstall the managed Claude Code hook (Phase 2).

Principles (from the Phase-0 deliberation + Orca's field-tested pattern):
- OWNERSHIP MARKER: we only ever add/remove entries that invoke OUR script, so
  a user's own hooks are never touched. Uninstall is surgical and reversible.
- FAIL-OPEN AT THE CLI: the hook script exits 0 always, times out in 1s, and
  posts in the background — the agent is never blocked by a dead receiver.
- The receiver endpoint (port + bearer token) is discovered via an endpoint
  file written by `po up`, so hooks survive receiver restarts/port changes.
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import stat
import time
from pathlib import Path
from typing import Optional, Tuple

WINDOWS = os.name == "nt"

PO_DIR = Path(os.environ.get("PO_STATE_DIR", "")).parent if os.environ.get("PO_STATE_DIR") \
    else Path.home() / ".pixel-office"
ENDPOINT_FILE = PO_DIR / "hook-endpoint.json"
SCRIPT_PATH = PO_DIR / "hooks" / "claude-hook.sh"
MARKER = "pixel-office-managed-hook"

# Every lifecycle event the normalize table understands (SubagentStart/Stop give
# per-subagent avatars; PermissionRequest/Notification give `waiting`).
CLAUDE_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                 "PostToolUseFailure", "SubagentStart", "SubagentStop",
                 "PermissionRequest", "Notification", "Stop", "StopFailure",
                 "SessionEnd")

def _script_content() -> str:
    # shlex.quote the path: a hostile/odd HOME must not break quoting or inject
    ep = shlex.quote(str(ENDPOINT_FILE))
    return f"""#!/bin/sh
# {MARKER} — installed by `po hooks install`, removed by `po hooks uninstall`.
# Posts the hook payload (stdin) to the local pixel-office receiver. Fail-open:
# always exits 0, 1s timeout, never blocks the agent.
EP={ep}
[ -f "$EP" ] || exit 0
PORT=$(sed -n 's/.*"port": *\\([0-9]*\\).*/\\1/p' "$EP")
TOKEN=$(sed -n 's/.*"token": *"\\([^"]*\\)".*/\\1/p' "$EP")
[ -n "$PORT" ] || exit 0
curl -s -m 1 -X POST "http://127.0.0.1:$PORT/hook/claude" \\
  -H "x-po-hook-token: $TOKEN" -H "content-type: application/json" \\
  --data-binary @- >/dev/null 2>&1 || true
exit 0
"""


def claude_settings_path() -> Path:
    home = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(home) if home else Path.home() / ".claude"
    return base / "settings.json"


def write_endpoint_file(port: int, token: str) -> None:
    ENDPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(ENDPOINT_FILE.parent, 0o700)  # private dir (token lives inside)
    except OSError:
        pass
    tmp = ENDPOINT_FILE.with_suffix(".tmp")
    data = json.dumps({"port": port, "token": token, "written_at": time.time()}).encode()
    # create the temp file already 0600 so the token is never group/other-readable
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)  # force 0600 even if a stale permissive .tmp existed
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, ENDPOINT_FILE)
    os.chmod(ENDPOINT_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — token inside


def remove_endpoint_file() -> None:
    """Delete the endpoint file so a stale port never drives hook POSTs to a
    process that later rebinds it. Called on `po up` shutdown."""
    try:
        ENDPOINT_FILE.unlink()
    except OSError:
        pass


def _write_script() -> None:
    SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_PATH.write_text(_script_content())
    os.chmod(SCRIPT_PATH, 0o755)


def _is_ours(entry: dict) -> bool:
    # EXACT match only — a user command that merely mentions our path (wrapper,
    # logger, chained command) must never be classified as managed.
    return entry.get("type") == "command" and entry.get("command") == str(SCRIPT_PATH)


def _stat_token(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _load_settings(path: Path) -> Tuple[dict, object]:
    token = _stat_token(path)
    if path.is_dir():
        raise RuntimeError(f"{path} is a directory, not a settings file — remove it and re-run.")
    if not path.exists():
        return {}, token
    try:
        return json.loads(path.read_text()), token
    except (OSError, ValueError):
        raise RuntimeError(
            f"{path} is not valid JSON — refusing to modify it. Fix it first.")


def _save_settings(path: Path, settings: dict, expected_token) -> None:
    if _stat_token(path) != expected_token:  # optimistic concurrency guard
        raise RuntimeError(
            f"{path} changed while po was editing it — re-run the command.")
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    if path.exists():  # one reversible backup per change (private — settings can hold config)
        backup = path.with_suffix(".json.po-backup")
        backup.write_text(path.read_text())
        try:
            os.chmod(backup, prev_mode)
        except OSError:
            pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    try:
        os.chmod(tmp, prev_mode)   # preserve the original mode — never widen to world-readable
    except OSError:
        pass
    os.replace(tmp, path)


def install() -> str:
    if WINDOWS:
        # the managed hook is a POSIX /bin/sh script; native Windows Claude Code
        # can't run it, so live mode would silently never fire. Be honest.
        raise RuntimeError(
            "live-mode hooks require macOS/Linux/WSL (the hook is a /bin/sh script); "
            "tailer mode still works on native Windows — just run `po up`.")
    _write_script()
    path = claude_settings_path()
    settings, token = _load_settings(path)
    hooks = settings.setdefault("hooks", {})
    added = 0
    for event in CLAUDE_EVENTS:
        entries = hooks.setdefault(event, [])
        if any(_is_ours(h) for e in entries for h in e.get("hooks", [])):
            continue  # idempotent
        entries.append({"matcher": "*",
                        "hooks": [{"type": "command", "command": str(SCRIPT_PATH)}]})
        added += 1
    _save_settings(path, settings, token)
    return f"installed hook for {added} event(s) into {path} (script: {SCRIPT_PATH})"


def uninstall() -> str:
    path = claude_settings_path()
    settings, token = _load_settings(path)
    hooks = settings.get("hooks", {})
    removed = 0
    for event in list(hooks.keys()):
        kept = []
        for entry in hooks[event]:
            inner = [h for h in entry.get("hooks", []) if not _is_ours(h)]
            if len(inner) != len(entry.get("hooks", [])):
                removed += 1
            if inner:
                entry["hooks"] = inner
                kept.append(entry)
            elif not _is_ours_entry_only(entry):
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    _save_settings(path, settings, token)
    return f"removed {removed} managed entr(ies) from {path} — user hooks untouched"


def _is_ours_entry_only(entry: dict) -> bool:
    inner = entry.get("hooks", [])
    return bool(inner) and all(_is_ours(h) for h in inner)


def status() -> dict:
    path = claude_settings_path()
    try:
        settings, _ = _load_settings(path)
    except RuntimeError:
        return {"installed": False, "settings": str(path), "error": "unparseable settings"}
    events = [e for e, entries in settings.get("hooks", {}).items()
              if any(_is_ours(h) for en in entries for h in en.get("hooks", []))]
    return {"installed": bool(events), "events": sorted(events),
            "settings": str(path), "script": str(SCRIPT_PATH),
            "endpoint_file": str(ENDPOINT_FILE), "endpoint_exists": ENDPOINT_FILE.exists()}
