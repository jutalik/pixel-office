"""Grok CLI adapter. See docs/CLI-MATRIX.md.

Grok's real signal is events.jsonl (structured, timestamped) — NOT
chat_history.jsonl (no timestamps). It logs permission prompts, so grok is the
one CLI whose TAILER reaches `waiting`. Its session file is always named
`events.jsonl`, so identity comes from the parent-dir uuid.
"""
from __future__ import annotations

from pathlib import Path

from ..telemetry.grok_events import parse_line
from .base import Adapter

KINDS = {
    "TurnStarted": "working",
    "LoopStarted": "working",
    "FirstToken": "working",
    "ToolStarted": "working",
    "ToolCompleted": "working",
    "PermissionRequested": "waiting",
    "PermissionResolved": "working",
    "TurnEnded": "done",
}

EMITTED_KINDS = frozenset(KINDS)

ADAPTER = Adapter(
    name="grok",
    kinds=KINDS,
    emitted_kinds=EMITTED_KINDS,
    home=Path.home() / ".grok",
    env_home="GROK_HOME",
    extra_bin_dirs=(Path.home() / ".grok" / "bin",),
    session_kind="jsonl",
    session_glob="sessions/*/*/events.jsonl",
    parse_line=parse_line,
    session_id_from_path=lambda p: p.parent.name,   # events.jsonl isn't unique
    hooks_capable=True,
    hook_kind="config",
)
