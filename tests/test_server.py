import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from pixel_office.server import create_app  # noqa: E402

TS = "2026-07-10T00:00:01.000Z"


def _line(rtype="user", content="hello", stop_reason=None):
    msg = {"role": rtype, "content": content}
    if stop_reason:
        msg["stop_reason"] = stop_reason
    return json.dumps({"type": rtype, "timestamp": TS, "sessionId": "sess-1",
                       "message": msg}) + "\n"


@pytest.fixture()
def transcript(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(_line())
    return f


def test_index_serves_office_page(transcript):
    with TestClient(create_app([transcript])) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "PIXEL OFFICE" in r.text
        assert "Content-Security-Policy" in r.text


def test_snapshot_endpoint_reflects_transcript(transcript):
    with TestClient(create_app([transcript])) as client:
        rows = client.get("/api/office").json()["rows"]
        assert len(rows) == 1
        assert rows[0]["activity"] == "working"
        assert rows[0]["cli"] == "claude" and rows[0]["agent_id"] == "main"


def test_ws_snapshot_then_delta(transcript):
    app = create_app([transcript])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/office") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert first["rows"][0]["activity"] == "working"
            # a new terminal record lands; the hub tick should push a delta
            with open(transcript, "a") as fh:
                fh.write(_line("assistant", [{"type": "text", "text": "bye"}],
                               stop_reason="end_turn"))
            changed = app.state.hub.tick_sync()
            assert changed and changed[0]["activity"] == "done"


def test_hook_receiver_auth_and_ingest(transcript):
    app = create_app([transcript], hook_token="tok")
    with TestClient(app) as client:
        payload = {"hook_event_name": "PermissionRequest", "session_id": "sess-1"}
        r = client.post("/hook/claude", json=payload)          # no token
        assert r.status_code == 403
        r = client.post("/hook/claude", json=payload, headers={"x-po-hook-token": "tok"})
        assert r.status_code == 204
        rows = client.get("/api/office").json()["rows"]
        # hook waiting outranks the tailer's ancient 'working' frontier
        assert rows[0]["activity"] == "waiting" and rows[0]["last_source"] == "hook"


def test_hook_receiver_fails_open_on_garbage(transcript):
    app = create_app([transcript], hook_token="tok")
    with TestClient(app) as client:
        r = client.post("/hook/claude", content=b"\x00not-json",
                        headers={"x-po-hook-token": "tok"})
        assert r.status_code == 204  # never blocks a hook


def test_hub_delta_only_on_change(transcript):
    app = create_app([transcript])
    with TestClient(app):
        hub = app.state.hub
        assert hub.tick_sync() == []  # startup already consumed the backfill
        assert hub.tick_sync() == []  # steady state: no spurious deltas
