"""Frozen telemetry contract — see docs/TELEMETRY-CONTRACT.md.

Everything downstream (tailer, hooks, store, WebSocket, avatars) depends on these
types. Changes are versioned via SCHEMA_VERSION.

Revision 2026-07-10 (pre-release, after the Phase-0 multi-agent review):
- `seq` is SOURCE-SCOPED: minted by the adapter, monotonic within one
  (host_id, cli, session_id, source) stream. Hook and tailer are independent
  observers and never share a numbering; cross-source reconciliation happens in
  the reducer via per-(agent, source) frontiers (see reducer.py).
- sanitize_meta is recursive and bounded (nested prompts/secrets are stripped,
  strings truncated, depth/size capped).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Tuple

SCHEMA_VERSION = 1

# Normalized activity states an avatar can show.
ACTIVITY_STATES: Tuple[str, ...] = ("working", "waiting", "blocked", "done")
# Liveness is derived from time/connection, never carried by a raw event.
LIVENESS_STATES: Tuple[str, ...] = ("live", "stale", "disconnected", "unknown")

SOURCES: Tuple[str, ...] = ("hook", "tailer")
# Higher precedence wins when frontiers are equally fresh (see reducer.winning).
SOURCE_PRECEDENCE = {"tailer": 1, "hook": 2}
SOURCE_CONFIDENCE: Tuple[str, ...] = ("high", "low")

# ---- meta sanitization -------------------------------------------------------
# meta must carry metadata only — never prompts, tool args, secrets, or file
# contents. Sanitization is recursive and bounded; it runs exactly once, at the
# ingest boundary (RawEvent.from_dict), so only sanitized metadata ever reaches
# reducer state or any snapshot — content never leaves ingest.
MAX_META_STRING = 256          # max characters per string value INCLUDING the mark
MAX_META_DEPTH = 3             # max container nesting depth
MAX_META_KEYS = 16             # max keys kept per dict
MAX_META_KEY_LENGTH = 128      # keys longer than this are dropped entirely
MAX_META_LIST_ITEMS = 8        # max items kept per list
MAX_META_INT = 2 ** 63         # numeric magnitude bound (bigints are content-sized)
TRUNCATION_MARK = "…[truncated]"

FORBIDDEN_META_KEYS = frozenset({
    "prompt", "prompts", "content", "text", "message", "messages",
    "args", "arguments", "argv", "input", "tool_input", "toolinput", "params",
    "secret", "secrets", "token", "api_key", "apikey", "password", "passwd", "pwd",
    "file_content", "file_contents", "filecontent", "filecontents",
    "diff", "patch", "code", "output", "stdout", "stderr",
    "userprompt", "systemprompt", "system_prompt", "transcript",
    "command", "cmd", "query", "instructions", "result", "results", "response",
    # credential/secret-shaped keys (both underscore and camelCase-casefolded forms).
    # exact-key by design (substring matching would drop legit fields like
    # "token_count"); this is best-effort defense-in-depth, not a total guarantee.
    "authorization", "auth", "auth_token", "authtoken", "bearer",
    "cookie", "cookies", "set-cookie", "setcookie",
    "credential", "credentials", "access_token", "accesstoken", "access_key", "accesskey",
    "aws_secret_access_key", "refresh_token", "refreshtoken", "id_token", "idtoken",
    "private_key", "privatekey", "secret_key", "secretkey", "client_secret", "clientsecret",
    "api_secret", "apisecret", "github_token", "gh_token", "session_token", "sessiontoken",
    "env", "environ", "environment",
})

_DROP = object()  # sentinel: value rejected by the sanitizer


def _clean_key(key) -> str:
    """Normalize a key for denylist matching: NFKC, strip, casefold.

    Catches aliases like 'prompt ', fullwidth homoglyphs, and camelCase
    ('toolInput' -> 'toolinput' is in the denylist explicitly).
    """
    return unicodedata.normalize("NFKC", str(key)).strip().casefold()


def _sanitize_value(value, depth: int):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if abs(value) <= MAX_META_INT else _DROP
    if isinstance(value, float):
        # non-finite floats are not JSON-encodable; oversized ones are content-shaped
        if value != value or value in (float("inf"), float("-inf")):
            return _DROP
        return value if abs(value) <= MAX_META_INT else _DROP
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) > MAX_META_STRING:
            return value[:MAX_META_STRING - len(TRUNCATION_MARK)] + TRUNCATION_MARK
        return value
    if isinstance(value, dict):
        if depth >= MAX_META_DEPTH:
            return _DROP
        out = {}
        for k, v in value.items():
            if len(out) >= MAX_META_KEYS:
                break
            key = str(k)
            if len(key) > MAX_META_KEY_LENGTH:
                continue
            if _clean_key(key) in FORBIDDEN_META_KEYS:
                continue
            sv = _sanitize_value(v, depth + 1)
            if sv is not _DROP:
                out[key] = sv
        return out
    if isinstance(value, (list, tuple)):
        if depth >= MAX_META_DEPTH:
            return _DROP
        out = []
        for item in value[:MAX_META_LIST_ITEMS]:
            sv = _sanitize_value(item, depth + 1)
            if sv is not _DROP:
                out.append(sv)
        return out
    return _DROP  # unexpected types (bytes, objects, ...) are dropped


def sanitize_meta(meta: Optional[dict]) -> dict:
    """Recursively drop content-carrying keys at any depth and bound all values.

    Idempotent; runs exactly once at the ingest boundary.
    """
    if not isinstance(meta, dict):
        return {}
    cleaned = _sanitize_value(meta, 0)
    return cleaned if cleaned is not _DROP else {}


# ---- raw event ---------------------------------------------------------------

@dataclass(frozen=True)
class RawEvent:
    host_id: str
    cli: str
    session_id: str
    agent_id: str
    seq: int           # minted by the ADAPTER: monotonic within the
                       # (host_id, cli, session_id, source) stream; 0-based OK;
                       # gaps OK; strictly increasing per stream required.
    ts: str            # RFC3339 / ISO-8601 (source timestamp)
    source: str        # "hook" | "tailer"
    kind: str          # raw lifecycle name from the source (may be a composite
                       # kind minted by the adapter, e.g. "Notification:idle_prompt")
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
        raw_seq = d["seq"]
        if isinstance(raw_seq, bool):
            raise ValueError(f"seq must be an integer, got {raw_seq!r}")
        if isinstance(raw_seq, int):
            seq = raw_seq
        elif isinstance(raw_seq, float) and raw_seq.is_integer():
            seq = int(raw_seq)  # JSON transports may float-encode integers
        elif isinstance(raw_seq, str) and raw_seq.strip().isdigit():
            seq = int(raw_seq)
        else:
            raise ValueError(f"seq must be an integer, got {raw_seq!r}")
        if seq < 0:
            raise ValueError("seq must be non-negative")
        confidence = d.get("source_confidence") or ("high" if source == "hook" else "low")
        if confidence not in SOURCE_CONFIDENCE:
            raise ValueError(
                f"invalid source_confidence {confidence!r}, expected one of {SOURCE_CONFIDENCE}")
        raw_sv = d.get("schema_version", SCHEMA_VERSION)
        if isinstance(raw_sv, bool):                       # bool is an int subclass
            raise ValueError(f"schema_version must be an integer, got {raw_sv!r}")
        if isinstance(raw_sv, int):
            schema_version = raw_sv
        elif isinstance(raw_sv, float) and raw_sv.is_integer():
            schema_version = int(raw_sv)                   # 1.0 OK, 1.5 rejected below
        elif isinstance(raw_sv, str) and raw_sv.strip().isdigit():
            schema_version = int(raw_sv)
        else:
            raise ValueError(f"schema_version must be an integer, got {raw_sv!r}")
        if schema_version != SCHEMA_VERSION:
            # a FROZEN contract rejects versions it doesn't speak — callers fail open
            # (the tailer/hook drop the record rather than mis-reduce a newer shape).
            raise ValueError(
                f"unsupported schema_version {schema_version} (this build speaks {SCHEMA_VERSION})")
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
            source_confidence=confidence,
            schema_version=schema_version,
            meta=sanitize_meta(d.get("meta")),
        )


AgentKey = Tuple[str, str, str, str]     # (host_id, cli, session_id, agent_id)


def agent_key(ev: RawEvent) -> AgentKey:
    return (ev.host_id, ev.cli, ev.session_id, ev.agent_id)
