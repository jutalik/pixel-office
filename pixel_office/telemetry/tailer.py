"""Session-file tailer: incremental, truncation-safe, forward-only seq.

Contract (docs/TELEMETRY-CONTRACT.md §1/§4):
- seq is a tailer-minted strictly-increasing ordinal per stream; the byte-offset
  cursor is only the RESUME mechanism, never the seq itself.
- Only complete newline-terminated records are consumed; a partial trailing line
  stays unconsumed until its newline lands.
- Truncation (file shrinks below the cursor) resets the cursor and renumbers
  FORWARD from the watermark — re-read records get fresh seqs, so the reducer's
  stream frontier keeps advancing and nothing is silently rejected.
- Fails open: unparseable lines are skipped, IO errors yield an empty batch.

Phase 1a scope: single file, in-memory cursor/watermark, polling caller.
(Durable cursors, rotation/inode tracking, directory watching → Phase 1b.)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .claude_transcript import parse_line
from .contract import RawEvent

_PARSERS = {
    "claude": parse_line,
}


class TranscriptTailer:
    def __init__(self, path: Path, *, host_id: str, cli: str = "claude",
                 fallback_session_id: Optional[str] = None):
        if cli not in _PARSERS:
            raise ValueError(f"no transcript parser for cli {cli!r}")
        self.path = Path(path)
        self.host_id = host_id
        self.cli = cli
        self.fallback_session_id = fallback_session_id or self.path.stem
        self._cursor = 0        # byte offset past the last consumed newline
        self._watermark = 0     # last minted seq (forward-only, survives resets)
        self._sig = None        # (st_ino, st_dev) of the file we are cursored into
        self._head = b""        # first bytes of the consumed file (rewrite fingerprint)
        self._parse = _PARSERS[cli]

    _HEAD_LEN = 256

    def _file_changed_identity(self, stat_result, f) -> bool:
        """Detect rotation/replacement even when the new file is not smaller."""
        sig = (stat_result.st_ino, stat_result.st_dev)
        if self._sig is not None and sig != self._sig:
            return True
        if self._cursor > 0 and self._head:
            f.seek(0)
            head = f.read(min(len(self._head), self._cursor))
            if head != self._head[:len(head)]:
                return True
        return False

    def poll(self) -> List[RawEvent]:
        """Consume newly-completed records and mint RawEvents. Never raises."""
        try:
            st = self.path.stat()
            size = st.st_size
        except OSError:
            return []
        if size < self._cursor:
            self._cursor = 0  # truncation: reset cursor, KEEP the watermark
        try:
            with open(self.path, "rb") as f:
                if self._file_changed_identity(st, f):
                    self._cursor = 0  # replaced file: re-read, renumber forward
                if size == self._cursor:
                    self._sig = (st.st_ino, st.st_dev)
                    return []
                f.seek(self._cursor)
                chunk = f.read(size - self._cursor)
        except OSError:
            return []
        self._sig = (st.st_ino, st.st_dev)
        last_nl = chunk.rfind(b"\n")
        if last_nl < 0:
            return []  # no complete record yet
        consumed = chunk[:last_nl + 1]
        if self._cursor == 0:
            self._head = consumed[:self._HEAD_LEN]  # fingerprint for rewrite detection
        self._cursor += last_nl + 1

        events: List[RawEvent] = []
        for raw in consumed.split(b"\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw.decode("utf-8", errors="replace"))
                parsed = self._parse(record)
            except Exception:
                continue  # fail open PER RECORD — one poison line never drops the rest
            if parsed is None:
                continue
            kind, ts, session_id, meta = parsed
            self._watermark += 1
            try:
                events.append(RawEvent.from_dict({
                    "host_id": self.host_id,
                    "cli": self.cli,
                    "session_id": session_id or self.fallback_session_id,
                    "agent_id": "main",
                    "seq": self._watermark,
                    "ts": ts,
                    "source": "tailer",
                    "kind": kind,
                    "meta": meta,
                }))
            except ValueError:
                continue  # malformed synthesized event — skip, keep the batch
        return events
