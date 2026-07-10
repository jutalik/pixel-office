"""Hook payload -> RawEvent: the receiver-side half of the hooks tier (Phase 2).

- seq is a receiver-assigned arrival ordinal per (host, cli, session_id) hook
  stream (contract §1: sources mint their own stream numbering).
- Composite kinds are minted HERE (contract §3): PreToolUse on the
  AskUserQuestion tool becomes kind "AskUserQuestion" (waiting, not working).
- agent identity: Claude subagent hooks carry agent_id/agent_type; the main
  thread has none -> "main". parent defaults to "main" for subagents (single
  nesting is the common case; deeper trees refine in Phase 3).
- ts is stamped at arrival (hook payloads carry no timestamp); meta is
  metadata-only and still passes the contract sanitizer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from .contract import RawEvent

KNOWN_EVENTS = frozenset({
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "SubagentStart", "SubagentStop", "PermissionRequest",
    "PermissionDenied", "Notification", "PreCompact", "Stop", "StopFailure",
    "SessionEnd",
})

# Notification subtypes the normalize table understands (see adapters/claude.py).
KNOWN_COMPOSITES = frozenset({
    "Notification:permission_prompt", "Notification:agent_needs_input",
    "Notification:elicitation_dialog", "Notification:idle_prompt",
    "Notification:agent_completed",
})


class HookEventFactory:
    def __init__(self, host_id: str):
        self.host_id = host_id
        self._counters: Dict[Tuple[str, str, str], int] = {}

    def _next_seq(self, cli: str, session_id: str) -> int:
        key = (self.host_id, cli, session_id)
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    def from_payload(self, cli: str, payload: dict) -> Optional[RawEvent]:
        if not isinstance(payload, dict):
            return None
        name = payload.get("hook_event_name")
        session_id = payload.get("session_id")
        if not name or name not in KNOWN_EVENTS or not session_id:
            return None
        tool = payload.get("tool_name")
        kind = str(name)
        if kind == "PreToolUse" and tool == "AskUserQuestion":
            kind = "AskUserQuestion"  # composite kind (contract §3)
        elif kind == "Notification":
            # mint Notification:<subtype> so idle/completed map to 'done', not
            # a false 'waiting' (contract §3). Unknown subtypes stay bare.
            subtype = payload.get("notification_type") or payload.get("subtype")
            if subtype and f"Notification:{subtype}" in KNOWN_COMPOSITES:
                kind = f"Notification:{subtype}"
        agent_id = str(payload.get("agent_id") or "main")
        parent = "main" if agent_id != "main" else None
        meta = {}
        if tool:
            meta["tool"] = str(tool)
        if payload.get("agent_type"):
            meta["agent_type"] = str(payload["agent_type"])
        try:
            return RawEvent.from_dict({
                "host_id": self.host_id,
                "cli": cli,
                "session_id": str(session_id),
                "agent_id": agent_id,
                "parent_agent_id": parent,
                "seq": self._next_seq(cli, str(session_id)),
                "ts": datetime.now(timezone.utc).isoformat(),
                "source": "hook",
                "kind": kind,
                "meta": meta,
            })
        except ValueError:
            return None  # fail open — a malformed payload never breaks ingest
