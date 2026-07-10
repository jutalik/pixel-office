"""Frozen telemetry contract — see docs/TELEMETRY-CONTRACT.md.

Everything downstream (tailer, hooks, store, WebSocket, avatars) depends on these
types. Changes are versioned via SCHEMA_VERSION.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

SCHEMA_VERSION = 1

# Normalized activity states an avatar can show.
ACTIVITY_STATES: Tuple[str, ...] = ("working", "waiting", "blocked", "done")
# Liveness is derived from time/connection, never carried by a raw event.
LIVENESS_STATES: Tuple[str, ...] = ("live", "stale", "disconnected", "unknown")

SOURCES: Tuple[str, ...] = ("hook", "tailer")
# Higher precedence wins when two sources describe the same (session, seq).
SOURCE_PRECEDENCE = {"tailer": 1, "hook": 2}

# meta must carry metadata only — never prompts, tool args, secrets, or file
# contents. Keys that commonly leak content are dropped on ingest.
FORBIDDEN_META_KEYS = frozenset({
    "prompt", "prompts", "content", "text", "message", "messages",
    "args", "arguments", "argv", "input", "tool_input", "params",
    "secret", "secrets", "token", "api_key", "apikey", "password",
    "file_content", "file_contents", "diff", "patch", "code", "output",
})


def sanitize_meta(meta: Optional[dict]) -> dict:
    """Drop any key that commonly carries content/secrets (case-insensitive)."""
    if not meta:
        return {}
    return {k: v for k, v in meta.items() if str(k).lower() not in FORBIDDEN_META_KEYS}


@dataclass(frozen=True)
class RawEvent:
    host_id: str
    cli: str
    session_id: str
    agent_id: str
    seq: int
    ts: str            # RFC3339 / ISO-8601
    source: str        # "hook" | "tailer"
    kind: str          # raw lifecycle name from the source
    parent_agent_id: Optional[str] = None
    source_confidence: str = "low"
    schema_version: int = SCHEMA_VERSION
    meta: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "RawEvent":
        required = ("host_id", "cli", "session_id", "agent_id", "seq", "ts", "source", "kind")
        missing = [k for k in required if k not in d or d[k] in (None, "")]
        if missing:
            raise ValueError(f"raw event missing required fields: {missing}")
        source = d["source"]
        if source not in SOURCES:
            raise ValueError(f"invalid source {source!r}, expected one of {SOURCES}")
        try:
            seq = int(d["seq"])
        except (TypeError, ValueError):
            raise ValueError(f"seq must be an integer, got {d['seq']!r}")
        if seq < 0:
            raise ValueError("seq must be non-negative")
        return RawEvent(
            host_id=str(d["host_id"]),
            cli=str(d["cli"]),
            session_id=str(d["session_id"]),
            agent_id=str(d["agent_id"]),
            seq=seq,
            ts=str(d["ts"]),
            source=source,
            kind=str(d["kind"]),
            parent_agent_id=(str(d["parent_agent_id"]) if d.get("parent_agent_id") else None),
            source_confidence=str(d.get("source_confidence", "low")),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            meta=sanitize_meta(d.get("meta")),
        )


AgentKey = Tuple[str, str, str, str]     # (host_id, cli, session_id, agent_id)
SeqKey = Tuple[str, str, str, int]        # (host_id, cli, session_id, seq)


def agent_key(ev: RawEvent) -> AgentKey:
    return (ev.host_id, ev.cli, ev.session_id, ev.agent_id)


def seq_key(ev: RawEvent) -> SeqKey:
    return (ev.host_id, ev.cli, ev.session_id, ev.seq)
