"""Claude Code transcript line -> (kind, ts, session_id, meta) | None.

Mapping verified against real transcripts (2026-07-10 probe):
- assistant records carry message.stop_reason: "end_turn"/"stop_sequence" mark a
  REAL turn end (honest `Stop`); "tool_use" (or a tool_use content block) means
  the agent is about to run a tool (`PreToolUse`); anything else that reached
  the transcript is model output in flight (`AssistantMessage` -> working).
- user records whose content carries tool_result blocks are tool completions
  (`PostToolUse`); plain string/text content is a real prompt (`UserPromptSubmit`);
  isMeta user records are harness-injected, not user activity -> ignored.
- control records (mode, permission-mode, last-prompt, ai-title, attachment,
  file-history-snapshot, queue-operation, system) carry no activity signal.
- Sidechain (subagent) records are skipped in Phase 1a; per-subagent avatars
  arrive with hooks (Phase 2), which carry explicit SubagentStart/Stop.

Remember the fidelity contract: transcripts are SILENT during permission waits,
so this parser can only ever produce working/done — never waiting/blocked.
Meta stays metadata-only (tool NAME, block counts — never inputs/content).
"""
from __future__ import annotations

from typing import Optional, Tuple

TERMINAL_STOP_REASONS = ("end_turn", "stop_sequence")


def parse_line(record: dict) -> Optional[Tuple[str, str, str, dict]]:
    """Return (kind, ts, session_id, meta) for activity-bearing records."""
    if not isinstance(record, dict):
        return None
    rtype = record.get("type")
    if rtype not in ("user", "assistant"):
        return None
    if record.get("isSidechain"):
        return None  # subagent stream — deferred to hooks (Phase 2)
    ts = record.get("timestamp")
    session_id = record.get("sessionId")
    if not ts or not session_id:
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")

    if rtype == "assistant":
        stop_reason = message.get("stop_reason")
        tool_names = [b.get("name") for b in content
                      if isinstance(b, dict) and b.get("type") == "tool_use"] \
            if isinstance(content, list) else []
        if stop_reason in TERMINAL_STOP_REASONS:
            return ("Stop", ts, session_id, {})
        if tool_names:
            return ("PreToolUse", ts, session_id,
                    {"tool": tool_names[0], "tool_count": len(tool_names)})
        return ("AssistantMessage", ts, session_id, {})

    # rtype == "user"
    if record.get("isMeta"):
        return None
    if isinstance(content, list):
        results = sum(1 for b in content
                      if isinstance(b, dict) and b.get("type") == "tool_result")
        if results:
            return ("PostToolUse", ts, session_id, {"result_count": results})
        return ("UserPromptSubmit", ts, session_id, {})
    if isinstance(content, str):
        return ("UserPromptSubmit", ts, session_id, {})
    return None
