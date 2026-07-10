"""SessionWatcher: tail EVERY active session behind a glob, durably (Phase 1b).

- Rescans the glob on a slow cadence and tails the most recently modified files
  (bounded by max_files — backpressure at the file level; the byte-level bound
  lives in TranscriptTailer.MAX_READ_BYTES).
- Persists each tailer's cursor/watermark (atomic tmp+rename JSON) so a restart
  neither re-emits history nor breaks the forward-only seq guarantee.
- Fails open everywhere: a broken state file or unreadable transcript degrades
  to re-reading (with fresh forward seqs), never to a crash.
"""
from __future__ import annotations

import glob as _glob
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from .contract import RawEvent
from .tailer import TranscriptTailer

DEFAULT_STATE_DIR = Path(os.environ.get("PO_STATE_DIR", "")) if os.environ.get("PO_STATE_DIR") \
    else Path.home() / ".pixel-office" / "state"
RESCAN_INTERVAL_S = 10.0
PERSIST_INTERVAL_S = 2.0
DEFAULT_MAX_FILES = 32
DEFAULT_ACTIVE_WINDOW_S = 48 * 3600.0


def _path_key(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:24]


class SessionWatcher:
    def __init__(self, pattern: str, *, host_id: str, cli: str = "claude",
                 state_dir: Optional[Path] = DEFAULT_STATE_DIR,
                 max_files: int = DEFAULT_MAX_FILES,
                 active_window_s: float = DEFAULT_ACTIVE_WINDOW_S):
        self.pattern = pattern
        self.host_id = host_id
        self.cli = cli
        self.state_dir = Path(state_dir) if state_dir else None
        self.max_files = max_files
        self.active_window_s = active_window_s
        self.tailers: Dict[str, TranscriptTailer] = {}   # path -> tailer
        self._last_rescan = 0.0
        self._last_persist = 0.0
        self._dirty = False
        if self.state_dir:
            self.state_dir.mkdir(parents=True, exist_ok=True)

    # ---- durable state ------------------------------------------------------

    def _state_file(self) -> Optional[Path]:
        if not self.state_dir:
            return None
        return self.state_dir / f"watch-{self.cli}-{_path_key(Path(self.pattern))}.json"

    def _load_states(self) -> dict:
        sf = self._state_file()
        if not sf or not sf.exists():
            return {}
        try:
            return json.loads(sf.read_text())
        except (OSError, ValueError):
            return {}  # corrupt state file: fail open, re-read transcripts

    def _persist_states(self, force: bool = False) -> None:
        sf = self._state_file()
        if not sf or not self._dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_persist < PERSIST_INTERVAL_S:
            return
        payload = {path: t.state_dict() for path, t in self.tailers.items()}
        tmp = sf.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload))
            os.replace(tmp, sf)  # atomic
            self._last_persist = now
            self._dirty = False
        except OSError:
            pass  # fail open

    # ---- file discovery ------------------------------------------------------

    def _rescan(self) -> None:
        now = time.monotonic()
        if self.tailers and now - self._last_rescan < RESCAN_INTERVAL_S:
            return
        self._last_rescan = now
        try:
            matches = _glob.glob(self.pattern)
        except OSError:
            return
        cutoff = time.time() - self.active_window_s
        recent = []
        for m in matches:
            try:
                mtime = os.path.getmtime(m)
            except OSError:
                continue
            if mtime >= cutoff:
                recent.append((mtime, m))
        recent.sort(reverse=True)
        keep = {m for _, m in recent[:self.max_files]}

        states = None
        for path in keep - self.tailers.keys():
            tailer = TranscriptTailer(Path(path), host_id=self.host_id, cli=self.cli)
            if states is None:
                states = self._load_states()
            saved = states.get(path)
            if saved:
                tailer.load_state(saved)
            self.tailers[path] = tailer
        for path in list(self.tailers.keys() - keep):
            del self.tailers[path]  # aged out (state stays on disk if it returns)

    # ---- polling --------------------------------------------------------------

    def poll(self) -> List[RawEvent]:
        self._rescan()
        events: List[RawEvent] = []
        for tailer in self.tailers.values():
            batch = tailer.poll()
            if batch:
                events.extend(batch)
                self._dirty = True
        self._persist_states()
        return events

    def close(self) -> None:
        self._persist_states(force=True)
