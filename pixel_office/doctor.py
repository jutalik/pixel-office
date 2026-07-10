"""`po doctor` — capability matrix for the current machine.

Read-only. Everything per-CLI comes from the adapter registry
(`adapters/<cli>.py`); this module only detects what's installed here and
whether tailable transcripts are actually reachable. "hooks" means hook-capable;
hooks activate only after `po hooks install` (Phase 2). A CLI is reported as a
`tailer` source only when it has a VERIFIED parser (jsonl) or SQLite mapper —
never on an unverified store (e.g. agy stays provisional).
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

from .adapters import registry
from .adapters.base import Adapter

_TRANSCRIPT_COUNT_CAP = 500
# The managed hook is a POSIX /bin/sh script, so hooks only run on macOS/Linux/WSL.
# (`hooks.install()` refuses native Windows.) Don't advertise `hooks` there.
_HOOKS_PLATFORM_OK = os.name != "nt"


def which(adapter: Adapter) -> Optional[str]:
    found = shutil.which(adapter.binary)
    if found:
        return found
    for d in adapter.extra_bin_dirs:
        # per-directory shutil.which inherits Windows PATHEXT (.exe/.cmd) handling
        found = shutil.which(adapter.binary, path=str(d))
        if found:
            return found
    return None


def resolve_home(adapter: Adapter) -> Path:
    if adapter.env_home:
        override = os.environ.get(adapter.env_home, "").strip()
        if override:
            return Path(override)
    return adapter.home or Path.home()


def session_pattern(adapter: Adapter) -> Optional[str]:
    """Absolute glob for the CLI's session files (jsonl or sqlite), or None."""
    home = resolve_home(adapter)
    rel = adapter.session_glob or adapter.session_sqlite
    return str(home / rel) if rel else None


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


def _count(pattern: Optional[str]) -> Optional[int]:
    if not pattern:
        return None
    matches = _glob.iglob(pattern)
    return sum(1 for _ in itertools.islice(matches, _TRANSCRIPT_COUNT_CAP + 1))


def detect_clis() -> dict:
    out = {}
    for a in registry.all_adapters():
        if not a.is_cli:
            continue  # pseudo-sources (the org runtime) aren't installable CLIs
        binpath = which(a)
        home = resolve_home(a)
        pattern = session_pattern(a)
        count = _count(pattern) if binpath else None
        caps = []
        if binpath:
            if a.has_verified_tailer:
                caps.append("tailer")
            if a.hooks_installable and _HOOKS_PLATFORM_OK:   # runnable hooks only
                caps.append("hooks")
        out[a.name] = {
            "available": binpath is not None,
            "path": binpath,
            "hooks_capable": a.hooks_capable,
            "hooks_installable": a.hooks_installable,
            "hook_kind": a.hook_kind,
            "normalize_supported": a.normalize_supported,
            "session_kind": a.session_kind if a.session_kind != "none" else None,
            "sqlite_mapper_verified": (a.sqlite_mapper is not None
                                       if a.session_kind == "sqlite" else None),
            "home": str(home),
            "session_glob": pattern,
            "transcripts": count,
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
