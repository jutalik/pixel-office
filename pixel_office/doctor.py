"""`po doctor` — capability matrix for the current machine.

Read-only. Detects OS/WSL, which supported CLIs are available and where, whether
each supports hooks, its session directory, and whether the loopback receiver can
bind. This is what lets Pixel Office degrade gracefully instead of failing to boot.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Optional

HOME = Path.home()

# name -> extra known binary locations, session dir, hook support
_CLIS = {
    "claude": {"paths": [], "session": HOME / ".claude" / "projects", "hooks": True},
    "codex":  {"paths": [], "session": HOME / ".codex" / "sessions", "hooks": True},
    "grok":   {"paths": [HOME / ".grok" / "bin" / "grok"], "session": HOME / ".grok" / "sessions", "hooks": True},
    "gemini": {"paths": [], "session": HOME / ".gemini" / "tmp", "hooks": True},
    "hermes": {"paths": [], "session": HOME / ".hermes" / "sessions", "hooks": False},
}


def _which(name: str, extra_paths) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for cand in extra_paths:
        if Path(cand).exists() and os.access(cand, os.X_OK):
            return str(cand)
    return None


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
    out = {}
    for name, spec in _CLIS.items():
        binpath = _which(name, spec["paths"])
        session = spec["session"]
        out[name] = {
            "available": binpath is not None,
            "path": binpath,
            "hooks": spec["hooks"],
            "session_dir": str(session),
            "session_dir_exists": session.exists(),
            "telemetry": ("hooks+tailer" if (binpath and spec["hooks"])
                          else "tailer" if binpath else "unavailable"),
        }
    return out


def run() -> dict:
    return {
        "os": detect_os(),
        "loopback_port": free_port_available(),
        "clis": detect_clis(),
    }


def format_report(report: dict) -> str:
    o = report["os"]
    lines = [
        f"OS       : {o['system']} {o['release']}"
        + (" (WSL)" if o["wsl"] else "") + f" · python {o['python']}",
        f"Loopback : {'ok (127.0.0.1 bindable)' if report['loopback_port'] else 'BLOCKED'}",
        "",
        f"{'CLI':<9} {'status':<12} {'telemetry':<14} session",
        "-" * 64,
    ]
    for name, c in report["clis"].items():
        status = "available" if c["available"] else "not found"
        sess = c["session_dir"] + ("" if c["session_dir_exists"] else "  (no sessions yet)")
        lines.append(f"{name:<9} {status:<12} {c['telemetry']:<14} {sess}")
    return "\n".join(lines)
