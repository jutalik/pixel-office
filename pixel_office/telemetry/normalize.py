"""Map a source's raw lifecycle `kind` to a normalized activity state.

One table per CLI. The SAME mapping is reused by the tailer, the hooks path, and
every multi-CLI adapter — a single source of truth for "what is this agent doing".
Returns None for kinds that carry no activity signal (ignored by the reducer).
"""
from __future__ import annotations

from typing import Optional

# Claude Code lifecycle events. Hook names and tailer-derived names align here.
_CLAUDE = {
    "SessionStart": "working",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PostToolUseFailure": "working",
    "SubagentStart": "working",
    "SubagentStop": "done",
    "PermissionRequest": "waiting",
    "AskUserQuestion": "waiting",
    "Notification": "waiting",
    "Stop": "done",
    "StopFailure": "done",
}

_TABLES = {
    "claude": _CLAUDE,
}


def normalize(cli: str, kind: str) -> Optional[str]:
    table = _TABLES.get(cli)
    if table is None:
        return None
    return table.get(kind)


def known_clis() -> tuple:
    return tuple(_TABLES.keys())
