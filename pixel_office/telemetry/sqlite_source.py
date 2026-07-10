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

from .contract import RawEvent

RowMapper = Callable[[sqlite3.Row], Optional[Tuple[str, str, Optional[str], dict]]]

# Verified row mappers, keyed by cli. Empty until a live schema is confirmed —
# see docs: adding an agy/opencode mapper requires a real DB to verify columns.
_MAPPERS: dict = {}


def register_mapper(cli: str, mapper: RowMapper) -> None:
    _MAPPERS[cli] = mapper


def known_mappers() -> tuple:
    return tuple(_MAPPERS)


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
        self.mapper = mapper or _MAPPERS.get(cli)
        if self.mapper is None:
            raise ValueError(f"no verified sqlite mapper for cli {cli!r}")
        self.fallback_session_id = fallback_session_id or self.db_path.parent.name
        self.max_rows = max_rows
        self._rowid = 0        # resume cursor (last seen rowid)
        self._watermark = 0    # last minted seq (forward-only)

    def _connect(self) -> Optional[sqlite3.Connection]:
        if not self.db_path.exists():
            return None
        try:
            # mode=ro: read-only (never locks the live writer). NOT immutable=1 —
            # the DB IS changing, and immutable would let SQLite miss WAL updates
            # or return inconsistent reads.
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=0.5)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    def poll(self) -> List[RawEvent]:
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
        for row in rows:
            try:
                rowid = row["rowid"] if "rowid" in row.keys() else row[0]
                self._rowid = max(self._rowid, int(rowid))
            except Exception:
                continue  # can't read the cursor — skip this row
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
        return events

    def state_dict(self) -> dict:
        return {"rowid": self._rowid, "watermark": self._watermark}

    def load_state(self, state: dict) -> None:
        try:
            self._rowid = max(0, int(state.get("rowid", 0)))
            self._watermark = max(0, int(state.get("watermark", 0)))
        except (TypeError, ValueError):
            self._rowid = 0
