"""Dashboard domain: serve the office view + the WebSocket feed (Phase 1a).

- Loopback-only by design (the CLI binds 127.0.0.1; see cli.py).
- Transport per contract §6: on connect a full SNAPSHOT, then semantic DELTAS
  (changed rows only). Reconnecting clients always get a fresh snapshot.
- Telemetry fails open: tailer/parse problems never take the server down.
- The poll loop recomputes the view with a fresh `now` each tick, so liveness
  transitions (live -> stale -> disconnected) push without new events.
"""
import asyncio
import hmac
import json
import os
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# NOTE: no `from __future__ import annotations` here — FastAPI must resolve the
# WebSocket annotation at runtime, and these deps are the `web` extra (cli.py
# imports this module lazily and reports the missing extra cleanly).
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .telemetry.hook_events import HookEventFactory
from .telemetry.reducer import initial_state, reduce, view
from .telemetry.tailer import TranscriptTailer

POLL_INTERVAL_S = 0.5
STATIC_DIR = Path(__file__).parent / "static"


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _origin_is_local(origin: Optional[str]) -> bool:
    # No Origin => a native/non-browser client (curl, the PWA shell) — allowed.
    # A browser sends Origin; only same-machine origins may read the office, so a
    # foreign page the user visits cannot open the ws cross-origin (SOP exempts WS).
    if not origin:
        return True
    try:
        return urlsplit(origin).hostname in _LOCAL_HOSTS
    except ValueError:
        return False


def _overlay_enabled() -> bool:
    return os.environ.get("PO_OVERLAY", "on").strip().lower() not in ("off", "0", "false")


def _index_page() -> str:
    name = "office.html" if _overlay_enabled() else "office_plain.html"
    return (STATIC_DIR / name).read_text()


class OfficeHub:
    """Holds reducer state, polls event sources, fans out snapshot/deltas.

    A source is anything with .poll() -> List[RawEvent] (TranscriptTailer,
    SessionWatcher, and later the hook receiver) and optionally .close().
    """

    def __init__(self, sources: List):
        self.tailers = sources
        self.last_batch_size = 0
        # the autonomy loop may ingest from a background thread while the asyncio
        # poll loop also reduces — guard all state access with one lock
        self._state_lock = threading.Lock()
        self.state = initial_state()
        self.last_view: List[dict] = []
        self.clients: set = set()
        self._task: Optional[asyncio.Task] = None

    def _row_key(self, row: dict):
        return (row["host_id"], row["cli"], row["session_id"], row["agent_id"])

    def current_view(self) -> List[dict]:
        with self._state_lock:
            return view(self.state, datetime.now(timezone.utc))

    def ingest(self, ev) -> List[dict]:
        """Apply one event immediately (hook / autonomy path) and return changed rows."""
        with self._state_lock:
            self.state = reduce(self.state, ev)
            new_view = view(self.state, datetime.now(timezone.utc))
            old = {self._row_key(r): r for r in self.last_view}
            changed = [r for r in new_view if old.get(self._row_key(r)) != r]
            self.last_view = new_view
        return changed

    def tick_sync(self) -> List[dict]:
        """One poll cycle: ingest events, recompute view, return changed rows."""
        self.last_batch_size = 0
        with self._state_lock:   # one lock, no re-entrant current_view() call
            for tailer in self.tailers:
                for ev in tailer.poll():
                    self.state = reduce(self.state, ev)
                    self.last_batch_size += 1
            new_view = view(self.state, datetime.now(timezone.utc))
            old = {self._row_key(r): r for r in self.last_view}
            changed = [r for r in new_view if old.get(self._row_key(r)) != r]
            self.last_view = new_view
        return changed

    async def _loop(self):
        pending: dict = {}   # coalesced changed rows (by key, latest wins)
        while True:
            try:
                for r in self.tick_sync():
                    pending[self._row_key(r)] = r
                # while a capped-read source is still draining a big history,
                # accumulate silently and flush ONE delta when it settles — no
                # per-micro-tick message flood on cold start.
                draining = self.last_batch_size > 0
                if pending and not draining and self.clients:
                    await self._broadcast({"type": "delta", "rows": list(pending.values())})
                    pending = {}
            except Exception:
                pass  # fail open — telemetry must never kill the dashboard
            # sleep(0) still yields to the event loop so HTTP/ws stay responsive
            await asyncio.sleep(0 if self.last_batch_size else POLL_INTERVAL_S)

    async def _broadcast(self, payload: dict):
        message = json.dumps(payload)
        dead = []
        # snapshot the set: send_text awaits, so a client may connect/disconnect
        # mid-broadcast and mutate self.clients — iterating a copy is immune.
        for ws in list(self.clients):
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
               sources: Optional[List] = None,
               hook_token: Optional[str] = None,
               company=None) -> FastAPI:
    src = list(sources) if sources else []
    for p in (transcripts or []):
        src.append(TranscriptTailer(p, host_id=host_id))
    hub = OfficeHub(src)
    hook_factory = HookEventFactory(host_id)

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
        return _index_page()

    @app.get("/manifest.webmanifest")
    async def manifest():
        return Response((STATIC_DIR / "manifest.webmanifest").read_text(),
                        media_type="application/manifest+json")

    @app.get("/sw.js")
    async def service_worker():
        # served at root so its scope covers the whole app
        return Response((STATIC_DIR / "sw.js").read_text(),
                        media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/icon.svg")
    async def icon():
        return Response((STATIC_DIR / "icon.svg").read_text(), media_type="image/svg+xml")

    @app.get("/api/office")
    async def office_snapshot():
        return JSONResponse({"rows": hub.current_view()})

    @app.get("/api/company")
    async def company_snapshot():
        # honest: 204 (no body) when no Company Layer is running — the UI keeps
        # its "Requires Company Layer" gates. Real data lights them up otherwise.
        if company is None:
            return Response(status_code=204)
        # hold the company lock so the read is a consistent snapshot vs the
        # autonomy thread mutating memos/backlog/trends concurrently
        with company._lock:
            body = {"summary": company.summary(), "okrs": company.okr_view(),
                    "ceo_cards": company.ceo_cards(), "hr": company.hr_view(),
                    "trends": company.trends_view(), "meeting": company.meeting_view(),
                    "activity": company.activity_view()}
        return JSONResponse(body)

    @app.post("/hook/{cli}")
    async def hook_receiver(cli: str, request: Request):
        # bearer check first; everything past auth FAILS OPEN with 204 — a hook
        # must never learn (or care) that the receiver had a bad day. A missing
        # token CONFIGURATION means the receiver is off (403), never open.
        supplied = request.headers.get("x-po-hook-token", "")
        if not hook_token or not hmac.compare_digest(supplied, hook_token):
            return Response(status_code=403)
        try:
            payload = json.loads(await request.body())
            ev = hook_factory.from_payload(cli, payload)
            if ev is not None:
                changed = hub.ingest(ev)     # per-event push, no poll latency
                if changed and hub.clients:
                    await hub._broadcast({"type": "delta", "rows": changed})
        except Exception:
            pass
        return Response(status_code=204)

    @app.websocket("/ws/office")
    async def ws_office(ws: WebSocket):
        # block cross-origin browser reads (a foreign page targeting 127.0.0.1)
        if not _origin_is_local(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
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
