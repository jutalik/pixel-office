"""Codex CLI adapter. See docs/CLI-MATRIX.md."""
from __future__ import annotations

from pathlib import Path

from ..telemetry.codex_rollout import parse_line
from .base import Adapter

KINDS = {
    "TaskStarted": "working",
    "UserMessage": "working",
    "AgentMessage": "working",
    "Reasoning": "working",
    "FunctionCall": "working",
    "FunctionCallOutput": "working",
    "TaskComplete": "done",
}

EMITTED_KINDS = frozenset(KINDS)  # the rollout parser emits exactly these

ADAPTER = Adapter(
    name="codex",
    kinds=KINDS,
    emitted_kinds=EMITTED_KINDS,
    home=Path.home() / ".codex",
    env_home="CODEX_HOME",
    session_kind="jsonl",
    session_glob="sessions/*/*/*/rollout-*.jsonl",   # YYYY/MM/DD/rollout-*.jsonl
    parse_line=parse_line,
    hooks_capable=True,
    hook_kind="config",
)
