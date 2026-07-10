"""Dashboard domain: serve the office view + the WebSocket feed (Phase 1a).

- Loopback-only by design (the CLI binds 127.0.0.1; see cli.py).
- Transport per contract §6: on connect a full SNAPSHOT, then semantic DELTAS
  (changed rows only). Reconnecting clients always get a fresh snapshot.
- Telemetry fails open: tailer/parse problems never take the server down.
- The poll loop recomputes the view with a fresh `now` each tick, so liveness
  transitions (live -> stale -> disconnected) push without new events.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# NOTE: no `from __future__ import annotations` here — FastAPI must resolve the
# WebSocket annotation at runtime, and these deps are the `web` extra (cli.py
# imports this module lazily and reports the missing extra cleanly).
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .telemetry.reducer import initial_state, reduce, view
from .telemetry.tailer import TranscriptTailer

POLL_INTERVAL_S = 0.5
STATIC_DIR = Path(__file__).parent / "static"


class OfficeHub:
    """Holds reducer state, polls event sources, fans out snapshot/deltas.

    A source is anything with .poll() -> List[RawEvent] (TranscriptTailer,
    SessionWatcher, and later the hook receiver) and optionally .close().
    """

    def __init__(self, sources: List):
        self.tailers = sources
        self.last_batch_size = 0
        self.state = initial_state()
        self.last_view: List[dict] = []
        self.clients: set = set()
        self._task: Optional[asyncio.Task] = None

    def _row_key(self, row: dict):
        return (row["host_id"], row["cli"], row["session_id"], row["agent_id"])

    def current_view(self) -> List[dict]:
        return view(self.state, datetime.now(timezone.utc))

    def tick_sync(self) -> List[dict]:
        """One poll cycle: ingest events, recompute view, return changed rows."""
        self.last_batch_size = 0
        for tailer in self.tailers:
            for ev in tailer.poll():
                self.state = reduce(self.state, ev)
                self.last_batch_size += 1
        new_view = self.current_view()
        old = {self._row_key(r): r for r in self.last_view}
        changed = [r for r in new_view if old.get(self._row_key(r)) != r]
        self.last_view = new_view
        return changed

    async def _loop(self):
        while True:
            try:
                changed = self.tick_sync()
                if changed and self.clients:
                    await self._broadcast({"type": "delta", "rows": changed})
            except Exception:
                pass  # fail open — telemetry must never kill the dashboard
            # while a capped-read source is still draining history (cold start on
            # a big transcript), keep ticking back-to-back — sleep(0) still yields
            # to the event loop so HTTP/ws stay responsive throughout.
            await asyncio.sleep(0 if self.last_batch_size else POLL_INTERVAL_S)

    async def _broadcast(self, payload: dict):
        message = json.dumps(payload)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        for src in self.tailers:
            close = getattr(src, "close", None)
            if close:
                try:
                    close()  # persist durable cursors on shutdown
                except Exception:
                    pass


def create_app(transcripts: Optional[List[Path]] = None, *, host_id: str = "local",
               sources: Optional[List] = None) -> FastAPI:
    src = list(sources) if sources else []
    for p in (transcripts or []):
        src.append(TranscriptTailer(p, host_id=host_id))
    hub = OfficeHub(src)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        hub.tick_sync()  # one synchronous tick so small files are ready instantly;
        hub.start()      # large histories drain in the loop without blocking startup
        yield
        await hub.stop()

    app = FastAPI(title="pixel-office", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.hub = hub

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (STATIC_DIR / "office.html").read_text()

    @app.get("/api/office")
    async def office_snapshot():
        return JSONResponse({"rows": hub.current_view()})

    @app.websocket("/ws/office")
    async def ws_office(ws: WebSocket):
        await ws.accept()
        hub.clients.add(ws)
        try:
            await ws.send_text(json.dumps({"type": "snapshot", "rows": hub.current_view()}))
            while True:
                await ws.receive_text()  # client pings; content ignored
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(ws)

    return app
