"""Adapter registry + the kinds each adapter can emit.

Every session-file adapter declares the set of `kind`s it produces. The
conformance test asserts each declared kind normalizes to a real activity
state — so adding a kind to an adapter without mapping it in normalize.py
(or vice-versa) fails CI instead of silently producing a dead avatar state.
"""
from __future__ import annotations

from . import claude_transcript, codex_rollout, grok_events

# cli -> frozenset of kinds its tailer adapter can emit
EMITTED_KINDS = {
    "claude": frozenset({
        "UserPromptSubmit", "PreToolUse", "PostToolUse", "AssistantMessage", "Stop",
    }),
    "codex": frozenset(codex_rollout._KINDS.values()),
    "grok": frozenset(grok_events._KINDS.values()),
}

PARSERS = {
    "claude": claude_transcript.parse_line,
    "codex": codex_rollout.parse_line,
    "grok": grok_events.parse_line,
}
