"""SQLite session source — for CLIs that store sessions in a DB, not JSONL.

Some agents (agy/Antigravity's `conversations*.db`, opencode) keep their session
history in SQLite rather than an append-only log. This source polls new rows past
a rowid watermark and mints RawEvents through a per-CLI ROW MAPPER.

Design mirrors TranscriptTailer's guarantees:
- Read-only: opens the DB in immutable mode so it never locks the live writer.
- Forward-only minted seq (rowid is the resume cursor, never the seq itself).
- Fail-open: a locked/missing DB or a bad row yields an empty/partial batch,
  never an exception.
- Durable state round-trips (watermark) for restart-without-re-emit.

A mapper is `fn(row: sqlite3.Row) -> (kind, ts, session_id|None, meta) | None`.
Because a CLI's real schema must be verified against a live install before its
mapper is trusted, `known_mappers()` lists only VERIFIED ones; unverified CLIs
appear in the catalog but stay normalize-unsupported until a mapper lands.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.request import pathname2url

from .contract import RawEvent

from ..adapters import registry

RowMapper = Callable[[sqlite3.Row], Optional[Tuple[str, str, Optional[str], dict]]]

# Dynamically-registered mappers (tests, plugins). Verified per-CLI mappers live
# on the adapter (adapters/<cli>.py sets sqlite_mapper once a schema is confirmed).
_MAPPERS: dict = {}


def register_mapper(cli: str, mapper: RowMapper) -> None:
    _MAPPERS[cli] = mapper


def _mapper_for(cli: str) -> Optional[RowMapper]:
    # a dynamically-registered mapper overrides the adapter default (tests/plugins)
    return _MAPPERS.get(cli) or registry.sqlite_mapper_for(cli)


def known_mappers() -> tuple:
    reg = {a.name for a in registry.all_adapters() if a.sqlite_mapper is not None}
    return tuple(sorted(reg | set(_MAPPERS)))


class SqliteSessionSource:
    """Poll a SQLite table for new rows and mint RawEvents.

    query must select rows with a monotonic `rowid` (or aliased id) ordered
    ascending, filtered to `rowid > :watermark`. The mapper turns a row into an
    event. Only rows the mapper accepts advance activity; the watermark always
    advances past every seen rowid so we never re-scan them.
    """

    def __init__(self, db_path: Path, *, host_id: str, cli: str,
                 query: str, mapper: Optional[RowMapper] = None,
                 fallback_session_id: Optional[str] = None,
                 max_rows: int = 2000):
        self.db_path = Path(db_path)
        self.host_id = host_id
        self.cli = cli
        self.query = query
        self.mapper = mapper or _mapper_for(cli)
        if self.mapper is None:
            raise ValueError(f"no verified sqlite mapper for cli {cli!r}")
        self.fallback_session_id = fallback_session_id or self.db_path.parent.name
        self.max_rows = max_rows
        self._rowid = 0        # resume cursor (last seen rowid)
        self._watermark = 0    # last minted seq (forward-only)
        self._broken = False   # disabled after a query that can't advance the cursor

    def _connect(self) -> Optional[sqlite3.Connection]:
        if not self.db_path.exists():
            return None
        try:
            # mode=ro: read-only (never locks the live writer). NOT immutable=1 —
            # the DB IS changing, and immutable would let SQLite miss WAL updates
            # or return inconsistent reads.
            # pathname2url percent-encodes backslashes/drive-letters/unicode so
            # the file: URI is valid on Windows and POSIX alike
            uri = "file:" + pathname2url(str(self.db_path)) + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=0.5)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    def poll(self) -> List[RawEvent]:
        if self._broken:
            return []  # a prior poll proved the query can't advance — stay off
        conn = self._connect()
        if conn is None:
            return []
        events: List[RawEvent] = []
        try:
            cur = conn.execute(self.query, {"watermark": self._rowid})
            rows = cur.fetchmany(self.max_rows)
        except sqlite3.Error:
            conn.close()
            return []
        prev_rowid = self._rowid
        for row in rows:
            try:
                rowid = row["rowid"] if "rowid" in row.keys() else row[0]
                self._rowid = max(self._rowid, int(rowid))
            except Exception:
                pass  # can't read this row's cursor; other rows still advance it
            try:
                parsed = self.mapper(row)
                if parsed is None:
                    continue
                kind, ts, session_id, meta = parsed  # bad shapes fail open here
                self._watermark += 1
                events.append(RawEvent.from_dict({
                    "host_id": self.host_id, "cli": self.cli,
                    "session_id": session_id or self.fallback_session_id,
                    "agent_id": "main", "seq": self._watermark, "ts": ts,
                    "source": "tailer", "kind": kind, "meta": meta,
                }))
            except Exception:
                continue  # mapper error / bad tuple / bad event — never escapes poll()
        conn.close()
        # rows returned but the cursor didn't advance ⇒ the query exposes no
        # readable ascending rowid (a misconfigured mapper). Disable rather than
        # re-scanning the same rows forever (fail-open: no events, no crash).
        if rows and self._rowid == prev_rowid:
            self._broken = True
        return events

    def state_dict(self) -> dict:
        return {"rowid": self._rowid, "watermark": self._watermark}

    def load_state(self, state: dict) -> None:
        try:
            self._rowid = max(0, int(state.get("rowid", 0)))
            self._watermark = max(0, int(state.get("watermark", 0)))
        except (TypeError, ValueError):
            self._rowid = 0
