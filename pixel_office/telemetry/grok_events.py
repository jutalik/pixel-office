"""Grok events.jsonl line -> (kind, ts, session_id, meta) | None.

Grok writes a structured event stream (NOT chat_history.jsonl, which has no
timestamps). Verified against real sessions (2026-07-10): each line is
{"type", "ts", ...}. Unlike Claude/Codex transcripts, grok's stream records
permission prompts explicitly — so the grok TAILER can derive `waiting`, the
one CLI where tailer-mode reaches full fidelity.

Session identity: `turn_started` carries session_id, but most lines don't;
the tailer's per-session fallback (the parent-dir uuid) supplies it — see
tailer._session_fallback for grok.
"""
from __future__ import annotations

from typing import Optional, Tuple

_KINDS = {
    "turn_started": "TurnStarted",
    "loop_started": "LoopStarted",
    "first_token": "FirstToken",
    "tool_started": "ToolStarted",
    "tool_completed": "ToolCompleted",
    "permission_requested": "PermissionRequested",
    "permission_resolved": "PermissionResolved",
    "turn_ended": "TurnEnded",
    # phase_changed is high-frequency noise (83k+ in the corpus) — ignored.
}


def parse_line(record: dict) -> Optional[Tuple[str, str, Optional[str], dict]]:
    if not isinstance(record, dict):
        return None
    ts = record.get("ts")
    kind = _KINDS.get(record.get("type"))
    if not ts or kind is None:
        return None
    meta = {}
    if record.get("tool_name"):
        meta["tool"] = str(record["tool_name"])
    return (kind, str(ts), record.get("session_id"), meta)
