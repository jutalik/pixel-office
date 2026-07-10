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
        assert "room" in r.text  # game overlay


def test_pwa_assets_served(transcript):
    import json as _json
    with TestClient(create_app([transcript])) as client:
        m = client.get("/manifest.webmanifest")
        assert m.status_code == 200 and "manifest" in m.headers["content-type"]
        data = _json.loads(m.text)
        assert data["name"] == "Pixel Office" and data["display"] == "standalone"
        assert data["icons"] and data["icons"][0]["src"] == "/icon.svg"
        sw = client.get("/sw.js")
        assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
        assert "caches" in sw.text  # a real service worker
        assert client.get("/icon.svg").headers["content-type"] == "image/svg+xml"
        # office page wires the PWA + offline snapshot + responsive mobile mode
        page = client.get("/").text
        assert "/manifest.webmanifest" in page and "serviceWorker" in page
        assert "po:last" in page and "max-width:600px" in page


def test_overlay_off_serves_plain_page(transcript, monkeypatch):
    monkeypatch.setenv("PO_OVERLAY", "off")
    with TestClient(create_app([transcript])) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "plain" in r.text and "PO_OVERLAY=off" in r.text
        # same live data contract regardless of overlay
        assert client.get("/api/office").json()["rows"][0]["activity"] == "working"


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


def test_api_meta_reports_run_mode(transcript):
    # the browser reads this to show DEMO vs LIVE persistently + honestly
    with TestClient(create_app([transcript], run_mode="demo")) as client:
        m = client.get("/api/meta").json()
        assert m["run_mode"] == "demo" and m["has_company"] is False
    with TestClient(create_app([transcript])) as client:       # default = watch
        assert client.get("/api/meta").json()["run_mode"] == "watch"


def test_ws_heartbeat_pong(transcript):
    # a live-but-quiet office answers the client ping so its watchdog sees frames
    with TestClient(create_app([transcript])) as client:
        with client.websocket_connect("/ws/office") as ws:
            assert ws.receive_json()["type"] == "snapshot"
            ws.send_text("ping")
            assert ws.receive_json() == {"type": "pong"}


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


def test_ws_client_receives_delta_frame_end_to_end(transcript):
    app = create_app([transcript], hook_token="tok")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/office") as ws:
            assert ws.receive_json()["type"] == "snapshot"
            client.post("/hook/claude", json={"hook_event_name": "PermissionRequest",
                                              "session_id": "sess-1"},
                        headers={"x-po-hook-token": "tok"})
            delta = ws.receive_json()          # the PUSH path, not tick_sync()
            assert delta["type"] == "delta"
            assert delta["rows"][0]["activity"] == "waiting"
            assert delta["rows"][0]["last_source"] == "hook"


def test_ws_rejects_foreign_origin(transcript):
    app = create_app([transcript])
    with TestClient(app) as client:
        with pytest.raises(Exception):  # 1008 close -> WebSocketDisconnect
            with client.websocket_connect("/ws/office",
                                          headers={"origin": "https://evil.example"}) as ws:
                ws.receive_json()
        # a local origin is fine
        with client.websocket_connect("/ws/office",
                                      headers={"origin": "http://127.0.0.1:7717"}) as ws:
            assert ws.receive_json()["type"] == "snapshot"


def test_broadcast_survives_client_set_mutation_midway():
    import asyncio
    from pixel_office.server import OfficeHub

    hub = OfficeHub([])

    class FakeWS:
        def __init__(self, on_send=None):
            self.on_send, self.got = on_send, []

        async def send_text(self, m):
            self.got.append(m)
            if self.on_send:
                self.on_send()

    late = FakeWS()
    a = FakeWS(on_send=lambda: hub.clients.add(late))  # mutate set mid-iteration
    b = FakeWS()
    hub.clients.update({a, b})
    asyncio.run(hub._broadcast({"type": "delta", "rows": []}))  # must not raise
    assert a.got and b.got  # original clients still delivered


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
