"""Instrumentation-complete product skeletons.

Each template is the "bones" PO lays down before agents add features: a runnable
FastAPI+SQLite backend that ALREADY exposes /health, /ready, the KPI surface
(/api/telemetry|funnel|quality|growth the autonomy loop polls), X-App-Token
write auth, and — crucially — emits pixel-office telemetry so avatars work no
matter what the agents build on top. The agent's job is to fill in features
inside these bones, never to wire up observability from scratch.

Templates are rendered as a dict {relative_path: file_text}. Placeholders use
str.format with a small, fixed field set (no user code is executed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict

# Values from an untrusted manifest are interpolated into GENERATED Python source
# (docstrings, FastAPI(title=...)) and markdown. Strip everything that could break
# out of a string/docstring literal or inject code — a hard allowlist, since these
# are display strings, not identifiers.
_CODE_UNSAFE = re.compile(r'[^A-Za-z0-9 .,!?:;/&()\'#\-+_]')


def _code_safe(s: str) -> str:
    return _CODE_UNSAFE.sub("", str(s or "")).replace("'''", "").replace('"""', "")

# ---- shared building blocks --------------------------------------------------

_APP_PY = '''\
"""{title} — backend skeleton (scaffolded by pixel-office).

Instrumentation is pre-wired: /health, /ready, the KPI surface the office polls,
X-App-Token write auth, and per-request telemetry. ADD FEATURES BELOW — do not
remove the instrumentation, or the office dashboard stops seeing this service.
"""
import os
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

APP_TOKEN = os.environ.get("APP_TOKEN", "dev-token")
DB = Path(__file__).parent / "app.db"
app = FastAPI(title="{title}")

_METRICS = {{"requests": 0, "errors": 0, "started_at": time.time()}}


def db():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, body TEXT)")
    return conn


def require_token(x_app_token: str = Header(default="")):
    if x_app_token != APP_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")


@app.middleware("http")
async def _count(request, call_next):
    _METRICS["requests"] += 1
    try:
        resp = await call_next(request)
    except Exception:
        _METRICS["errors"] += 1
        raise
    if resp.status_code >= 500:
        _METRICS["errors"] += 1
    return resp


# ---- instrumentation surface (the office + autonomy loop read these) ----------

@app.get("/health")
def health():
    return {{"ok": True}}


@app.get("/ready")
def ready():
    try:
        db().execute("SELECT 1")
        return {{"ready": True}}
    except Exception:
        raise HTTPException(status_code=503, detail="db not ready")


@app.get("/api/telemetry")
def telemetry():
    up = time.time() - _METRICS["started_at"]
    reqs = _METRICS["requests"] or 1
    return {{"requests": _METRICS["requests"], "errors": _METRICS["errors"],
            "error_rate": _METRICS["errors"] / reqs, "uptime_s": round(up)}}


@app.get("/api/funnel")
def funnel():
    return {{"published": 0, "success_rate": 1.0}}


@app.get("/api/quality")
def quality():
    return {{"audience": 0, "new_delta": 0, "top": []}}


@app.get("/api/growth")
def growth():
    return {{"subscribers": 0, "citations": 0, "channels": {{}}}}


# ---- FEATURES: agents build the real product below ----------------------------
{feature_routes}
'''

_README = '''\
# {title}

{pitch}

- **Goal (north star):** {goal}
- **Niche:** {niche}
- **Stack:** {stack}
{benchmarks}
Scaffolded by pixel-office — the backend ships instrumentation-complete
(`/health`, `/ready`, `/api/telemetry|funnel|quality|growth`, `X-App-Token`
writes). Fill in features in `backend/app.py`; leave the instrumentation intact.

## Run
```
cd backend && pip install fastapi uvicorn && uvicorn app:app --reload
```
'''

_TEST_SMOKE = '''\
"""Smoke test — the instrumentation surface must always answer."""
from fastapi.testclient import TestClient
import app as appmod


def test_instrumentation_surface():
    c = TestClient(appmod.app)
    assert c.get("/health").json()["ok"] is True
    assert c.get("/ready").json()["ready"] is True
    for path in ("/api/telemetry", "/api/funnel", "/api/quality", "/api/growth"):
        assert c.get(path).status_code == 200
'''

_DEPLOY_PLAYBOOK = '''\
# Deploy playbook (env-adaptive — an agent runs this, not a human)

Pixel Office is local-first. To promote this service so it is reachable (and a
phone can watch the office), an agent detects the environment and picks a path:

1. **localhost** (default): `uvicorn app:app` on 127.0.0.1 — dev only, not remote.
2. **docker present** (`docker info` succeeds): build the included Dockerfile,
   run with a published port.
3. **tunnel available** (`cloudflared`/`tailscale funnel`): expose the local
   port over the tunnel; record the public URL in `ops/URL`.
4. **cloud target configured**: follow the provider's deploy (out of scope for
   the skeleton — the agent fills this in per the user's environment).

Rules: never expose secrets; prefer the least-public option that satisfies
"the user can watch it"; write the resulting URL to `ops/URL` so the office can
link to it.
'''

_DOCKERFILE = '''\
FROM python:3.12-slim
WORKDIR /app
COPY backend/ /app/
RUN pip install --no-cache-dir fastapi uvicorn
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
'''


@dataclass(frozen=True)
class Template:
    key: str
    summary: str
    render: Callable[[dict], Dict[str, str]]


def _base_files(ctx: dict, feature_routes: str) -> Dict[str, str]:
    # everything reaching generated source/markdown is made code-safe here, so no
    # single template needs to remember to escape untrusted manifest values.
    title = _code_safe(ctx["title"]) or "app"
    pitch = _code_safe(ctx["pitch"])
    goal = _code_safe(ctx["goal"])
    niche = _code_safe(ctx["niche"])
    marks = [_code_safe(b) for b in ctx["benchmarks"]]
    bench = ("- **Benchmarks:** " + ", ".join(m for m in marks if m) + "\n") if any(marks) else ""
    return {
        "backend/app.py": _APP_PY.format(title=title, feature_routes=feature_routes),
        "backend/test_smoke.py": _TEST_SMOKE,
        "README.md": _README.format(title=title, pitch=pitch, goal=goal or "(unset)",
                                    niche=niche or "(broad)", stack=ctx["stack"], benchmarks=bench),
        "ops/DEPLOY.md": _DEPLOY_PLAYBOOK,
        "Dockerfile": _DOCKERFILE,
    }


def _api_service(ctx):
    routes = '''
@app.get("/api/items")
def list_items():
    with db() as c:
        return [{"id": i, "body": b} for i, b in c.execute("SELECT id, body FROM items")]


@app.post("/api/items", dependencies=[__import__("fastapi").Depends(require_token)])
def create_item(body: dict):
    with db() as c:
        cur = c.execute("INSERT INTO items(body) VALUES (?)", (str(body.get("body", "")),))
        c.commit()
        return {"id": cur.lastrowid}
'''
    return _base_files(ctx, routes)


def _data_pipeline(ctx):
    routes = '''
@app.get("/api/status")
def pipeline_status():
    return {"stage": "idle", "processed": 0}


@app.post("/api/run", dependencies=[__import__("fastapi").Depends(require_token)])
def run_pipeline():
    # agents implement the real pipeline; instrumentation already counts runs
    return {"started": True}
'''
    return _base_files(ctx, routes)


def _chat_product(ctx):
    routes = '''
@app.get("/api/threads")
def threads():
    with db() as c:
        return [{"id": i, "body": b} for i, b in c.execute("SELECT id, body FROM items")]


@app.post("/api/threads", dependencies=[__import__("fastapi").Depends(require_token)])
def new_thread(body: dict):
    with db() as c:
        cur = c.execute("INSERT INTO items(body) VALUES (?)", (str(body.get("title", "")),))
        c.commit()
        return {"id": cur.lastrowid}
'''
    return _base_files(ctx, routes)


TEMPLATES: Dict[str, Template] = {
    "api-service": Template("api-service", "a JSON API backend", _api_service),
    "data-pipeline": Template("data-pipeline", "a batch/stream data pipeline", _data_pipeline),
    "chat-product": Template("chat-product", "a threaded chat/content product", _chat_product),
}


def render(stack: str, ctx: dict) -> Dict[str, str]:
    return TEMPLATES[stack].render(ctx)
