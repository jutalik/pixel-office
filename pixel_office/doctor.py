"""`po doctor` — capability matrix for the current machine.

Read-only. Detects OS/WSL, which supported CLIs are installed, whether each is
hook-capable (and via which mechanism), and whether TAILABLE TRANSCRIPTS are
actually reachable (a recursive glob against the CLI's real session layout —
not a bare parent-dir existence check, which is trivially true and misleading).

The matrix reports CAPABILITIES: "hooks" means hook-capable; hooks become
active only after `po hooks install` (Phase 2). Session layouts verified against
real installs 2026-07-10; each CLI's own home-override env var is honored where
one exists (gemini documents none, so its home is fixed at ~/.gemini).
"""
from __future__ import annotations

import glob as _glob
import itertools
import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Optional

from .telemetry.normalize import known_clis
from .telemetry.sqlite_source import known_mappers as known_sqlite_mappers

_TRANSCRIPT_COUNT_CAP = 500

# Per-CLI spec. session_glob is relative to the resolved home dir.
#   env_home  — the CLI's own home-override env var (same semantics the CLI uses)
#   hook_kind — how hooks are installed: settings (JSON settings file),
#               config (config file entry), plugin (plugin directory)
_CLIS = {
    "claude": {
        "extra_bin_dirs": [],
        "env_home": "CLAUDE_CONFIG_DIR",
        "home": Path.home() / ".claude",
        "session_glob": "projects/*/*.jsonl",
        "hooks": True, "hook_kind": "settings",
    },
    "codex": {
        "extra_bin_dirs": [],
        "env_home": "CODEX_HOME",
        "home": Path.home() / ".codex",
        # sessions are date-nested: sessions/YYYY/MM/DD/rollout-*.jsonl
        "session_glob": "sessions/*/*/*/rollout-*.jsonl",
        "hooks": True, "hook_kind": "config",
    },
    "grok": {
        "extra_bin_dirs": [Path.home() / ".grok" / "bin"],
        "env_home": "GROK_HOME",
        "home": Path.home() / ".grok",
        # per-session dirs: sessions/<encoded-cwd>/<uuid>/events.jsonl is the
        # structured telemetry stream (chat_history.jsonl has no timestamps).
        "session_glob": "sessions/*/*/events.jsonl",
        "hooks": True, "hook_kind": "config",
    },
    # agy = Antigravity CLI (Google), the successor to gemini-cli. Auth is a disk
    # token under ~/.gemini/antigravity-cli/; sessions are a SQLite conversations
    # DB (not JSONL). The SQLite session source exists (sqlite_source.py) but the
    # row mapper is PROVISIONAL until verified against a live agy install — so
    # normalize stays unsupported and telemetry reports hooks/DB availability only.
    "agy": {
        "extra_bin_dirs": [Path.home() / ".local" / "bin"],
        # agy has no dedicated home env var; it isolates by HOME (agy-ha runs each
        # session under HOME=~/.claude-ha/agy-sessions/<id>, whose DB is at
        # <that-home>/.gemini/antigravity-cli/*.db). The default single-user store
        # is ~/.gemini/antigravity-cli/*.db; globbing the isolated homes is a
        # watcher extension for later.
        "env_home": None,
        "home": Path.home() / ".gemini",
        "session_glob": None,                       # SQLite, not a glob of JSONL
        "session_sqlite": "antigravity-cli/*.db",   # conversations DB(s)
        "hooks": True, "hook_kind": "settings",
    },
    "hermes": {
        "extra_bin_dirs": [],
        "env_home": "HERMES_HOME",
        "home": Path.home() / ".hermes",
        # no session-file store located yet — hooks (plugin) are its telemetry path
        "session_glob": None,
        "hooks": True, "hook_kind": "plugin",
    },
}


def _which(name: str, extra_bin_dirs) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for d in extra_bin_dirs:
        # reuse shutil.which per-directory so Windows PATHEXT (.exe/.cmd)
        # handling is inherited instead of reimplemented
        found = shutil.which(name, path=str(d))
        if found:
            return found
    return None


def _resolve_home(spec) -> Path:
    env = spec["env_home"]
    if env:
        override = os.environ.get(env, "").strip()
        if override:
            return Path(override)
    return spec["home"]


def _count_transcripts(home: Path, pattern: Optional[str]) -> Optional[int]:
    """Count tailable transcripts via glob, capped at _TRANSCRIPT_COUNT_CAP."""
    if pattern is None:
        return None
    matches = _glob.iglob(str(home / pattern))
    return sum(1 for _ in itertools.islice(matches, _TRANSCRIPT_COUNT_CAP + 1))


def detect_os() -> dict:
    is_wsl = False
    try:
        rel = Path("/proc/version").read_text().lower()
        is_wsl = "microsoft" in rel or "wsl" in rel
    except OSError:
        pass
    return {"system": platform.system(), "release": platform.release(),
            "wsl": is_wsl, "python": platform.python_version()}


def free_port_available(preferred: int = 0) -> Optional[int]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", preferred))
            return s.getsockname()[1]
    except OSError:
        return None


def detect_clis() -> dict:
    supported = set(known_clis())
    sqlite_ok = set(known_sqlite_mappers())
    out = {}
    for name, spec in _CLIS.items():
        binpath = _which(name, spec["extra_bin_dirs"])
        home = _resolve_home(spec)
        sqlite_glob = spec.get("session_sqlite")
        # a CLI is tailable if it has a JSONL glob, OR a SQLite store with a
        # VERIFIED row mapper (unverified SQLite stores don't count as tailer)
        jsonl = spec["session_glob"]
        transcripts = _count_transcripts(home, jsonl) if (binpath and jsonl) else None
        sqlite_dbs = (_count_transcripts(home, sqlite_glob)
                      if (binpath and sqlite_glob) else None)
        caps = []
        if binpath:
            if jsonl is not None:
                caps.append("tailer")
            elif sqlite_glob is not None and name in sqlite_ok:
                caps.append("tailer")
            if spec["hooks"]:
                caps.append("hooks")
        out[name] = {
            "available": binpath is not None,
            "path": binpath,
            "hooks_capable": spec["hooks"],
            "hook_kind": spec["hook_kind"],
            "normalize_supported": name in supported,
            "session_kind": ("jsonl" if jsonl else "sqlite" if sqlite_glob else None),
            "sqlite_mapper_verified": name in sqlite_ok if sqlite_glob else None,
            "home": str(home),
            "session_glob": (str(home / jsonl) if jsonl
                             else str(home / sqlite_glob) if sqlite_glob else None),
            "transcripts": transcripts if jsonl else sqlite_dbs,
            "telemetry": "+".join(caps) if caps else "unavailable",
        }
    return out


def run() -> dict:
    return {
        "os": detect_os(),
        "loopback_port": free_port_available(),
        "clis": detect_clis(),
    }


def _fmt_transcripts(c) -> str:
    n = c["transcripts"]
    if n is None:
        return "-"
    if n > _TRANSCRIPT_COUNT_CAP:
        return f"{_TRANSCRIPT_COUNT_CAP}+"
    return str(n)


def format_report(report: dict) -> str:
    o = report["os"]
    lines = [
        f"OS       : {o['system']} {o['release']}"
        + (" (WSL)" if o["wsl"] else "") + f" · python {o['python']}",
        f"Loopback : {'ok (127.0.0.1 bindable)' if report['loopback_port'] else 'BLOCKED'}",
        "",
        f"{'CLI':<9} {'status':<11} {'capabilities':<14} {'transcripts':<12} home",
        "-" * 76,
    ]
    for name, c in report["clis"].items():
        status = "available" if c["available"] else "not found"
        lines.append(f"{name:<9} {status:<11} {c['telemetry']:<14} "
                     f"{_fmt_transcripts(c):<12} {c['home']}")
    lines.append("")
    lines.append("capabilities are potential telemetry sources; hooks activate via "
                 "`po hooks install` (Phase 2).")
    return "\n".join(lines)
