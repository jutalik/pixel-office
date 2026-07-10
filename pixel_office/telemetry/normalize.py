"""Map a source's raw lifecycle `kind` to a normalized activity state.

ONE TABLE PER CLI (vocabularies are disjoint across CLIs); all tables feed the
same reducer. Returns None for kinds that carry no activity signal.

COMPOSITE KINDS: normalize() is a flat lookup — events whose real signal lives
in sibling fields must be disambiguated by the ADAPTER before this call:
- PreToolUse with tool_name == "AskUserQuestion"  -> emit kind "AskUserQuestion"
- Notification with a known subtype               -> emit "Notification:<subtype>"
This keeps the table the single source of truth while staying context-aware.

FIDELITY (measured against real transcripts, 2026-07-10): Claude Code writes
NOTHING to the transcript while blocked on a permission/question prompt, so the
tailer can only ever derive {working, done} for Claude — `waiting` and `blocked`
are HOOK-ONLY states. The UI must treat this honestly (see TAILER_DERIVABLE).
"""
from __future__ import annotations

from typing import Optional

# Claude Code lifecycle events. All plain rows verified against the official
# hooks reference (2026-07-10); composite rows are adapter-minted (see header).
_CLAUDE = {
    "SessionStart": "working",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PostToolUseFailure": "working",     # agent keeps going after a failed tool
    "SubagentStart": "working",
    "SubagentStop": "done",
    "PermissionRequest": "waiting",
    "PermissionDenied": "working",       # denial resolves the wait; agent continues
    "AskUserQuestion": "waiting",        # composite: adapter-minted from PreToolUse
    "Notification": "waiting",           # fallback when the subtype is unknown
    "Notification:permission_prompt": "waiting",
    "Notification:agent_needs_input": "waiting",
    "Notification:elicitation_dialog": "waiting",
    "Notification:idle_prompt": "done",  # "done and waiting for your next prompt"
    "Notification:agent_completed": "done",
    "PreCompact": "working",             # compaction is real work, not idleness
    "AssistantMessage": "working",       # tailer: model output in flight
    "Stop": "done",
    "SessionEnd": "done",                # session closed; liveness will decay
    "StopFailure": "blocked",            # turn died on an API error — needs a human
}

# Codex rollout vocabulary (see codex_rollout.py; verified 2026-07-10).
_CODEX = {
    "TaskStarted": "working",
    "UserMessage": "working",
    "AgentMessage": "working",
    "Reasoning": "working",
    "FunctionCall": "working",
    "FunctionCallOutput": "working",
    "TaskComplete": "done",
}

_TABLES = {
    "claude": _CLAUDE,
    "codex": _CODEX,
}

# Which activity states each CLI's TAILER can actually produce (hooks produce
# the full table). Drives honest fidelity reporting in doctor/UI.
TAILER_DERIVABLE = {
    "claude": ("working", "done"),
    "codex": ("working", "done"),
}


def normalize(cli: str, kind: str) -> Optional[str]:
    table = _TABLES.get(cli)
    if table is None:
        return None
    return table.get(kind)


def known_clis() -> tuple:
    return tuple(_TABLES.keys())
