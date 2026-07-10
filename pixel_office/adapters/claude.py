"""Claude Code adapter. See docs/CLI-MATRIX.md."""
from __future__ import annotations

from pathlib import Path

from ..telemetry.claude_transcript import parse_line
from .base import Adapter

# Full hook vocabulary (verified against the official hooks reference 2026-07-10).
# Composite kinds (AskUserQuestion, Notification:<subtype>) are minted by the
# hook adapter before normalization — see telemetry/hook_events.py.
KINDS = {
    "SessionStart": "working",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PostToolUseFailure": "working",
    "SubagentStart": "working",
    "SubagentStop": "done",
    "PermissionRequest": "waiting",
    "PermissionDenied": "working",
    "AskUserQuestion": "waiting",
    "Notification": "waiting",
    "Notification:permission_prompt": "waiting",
    "Notification:agent_needs_input": "waiting",
    "Notification:elicitation_dialog": "waiting",
    "Notification:idle_prompt": "done",
    "Notification:agent_completed": "done",
    "PreCompact": "working",
    "AssistantMessage": "working",   # tailer: model output in flight
    "Stop": "done",
    "SessionEnd": "done",
    "StopFailure": "blocked",
}

# The transcript is silent during permission waits, so the tailer only ever
# emits these (waiting/blocked are hook-only for Claude).
EMITTED_KINDS = frozenset({
    "UserPromptSubmit", "PreToolUse", "PostToolUse", "AssistantMessage", "Stop",
})

ADAPTER = Adapter(
    name="claude",
    kinds=KINDS,
    emitted_kinds=EMITTED_KINDS,
    home=Path.home() / ".claude",
    env_home="CLAUDE_CONFIG_DIR",
    session_kind="jsonl",
    session_glob="projects/*/*.jsonl",
    parse_line=parse_line,
    hooks_capable=True,
    hooks_installable=True,   # `po hooks install` + the claude hook-event table
    hook_kind="settings",
)
