"""Codex rollout line -> (kind, ts, session_id, meta) | None.

Format verified against real rollouts (2026-07-10): every line is a wrapper
{"timestamp", "type", "payload"}; activity lives in payload.type. Per-line
records carry no session id (session_meta does, once) — the tailer's stable
fallback (file stem, unique per rollout) is the session identity.

Tailer fidelity: like Claude, rollouts record no approval-wait signal, so the
codex tailer derives only {working, done}.
"""
from __future__ import annotations

from typing import Optional, Tuple

# payload.type -> normalized-table kind (metadata only; arguments never leave)
_KINDS = {
    "task_started": "TaskStarted",
    "task_complete": "TaskComplete",
    "user_message": "UserMessage",
    "agent_message": "AgentMessage",
    "message": "AgentMessage",
    "reasoning": "Reasoning",
    "function_call": "FunctionCall",
    "function_call_output": "FunctionCallOutput",
    "image_generation_call": "FunctionCall",
}


def parse_line(record: dict) -> Optional[Tuple[str, str, Optional[str], dict]]:
    if not isinstance(record, dict):
        return None
    ts = record.get("timestamp")
    payload = record.get("payload")
    if not ts or not isinstance(payload, dict):
        return None
    kind = _KINDS.get(payload.get("type"))
    if kind is None:
        return None
    meta = {}
    if kind == "FunctionCall" and payload.get("name"):
        meta["tool"] = str(payload["name"])
    return (kind, ts, None, meta)  # session id: tailer fallback (rollout stem)
