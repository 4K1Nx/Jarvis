import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import create_app
from viv.bus import BUS

CFG = {"server": {"host": "127.0.0.1", "port": 8765}, "live": {"model": "gemini-x"},
       "tools": {"vision": {"screenshot_path": "data/__nao_existe__.png"}}}
ORIGIN = {"Origin": "http://127.0.0.1:8765"}


class FakeViv:
    def __init__(self):
        self.state = type("S", (), {"value": "sleeping"})()
        self.calls = []

    def wake(self, reason=""):
        self.calls.append(("wake", reason))

    def sleep(self):
        self.calls.append(("sleep",))


class FakeGate:
    def __init__(self):
        self.pending, self.clicks = None, []

    def on_click(self, accepted):
        self.clicks.append(accepted)


class FakeAudio:
    input_name = "Microfone falso"


class FakeSpeaker:
    enrolled = False


@pytest.fixture
def env():
    viv, gate = FakeViv(), FakeGate()
    app = create_app(viv, gate, FakeAudio(), CFG, FakeSpeaker())
    with TestClient(app) as client:
        yield client, viv, gate


def test_status_reports_state_mic_model_pending_and_enrollment(env):
    client, viv, gate = env
    gate.pending = {"name": "fs_delete", "args": {"path": "x"}, "expires": 0}
    data = client.get("/api/status").json()
    assert data["state"] == "sleeping" and data["mic"] == "Microfone falso" and data["model"] == "gemini-x"
    assert data["enrolled"] is False and data["pending"]["name"] == "fs_delete"


def test_wake_and_sleep_endpoints(env):
    client, viv, _ = env
    assert client.post("/api/wake", headers=ORIGIN).status_code == 200
    assert client.post("/api/sleep", headers=ORIGIN).status_code == 200
    assert viv.calls == [("wake", "button"), ("sleep",)]


def test_confirm_endpoints(env):
    client, _, gate = env
    client.post("/api/confirm/sim", headers=ORIGIN)
    client.post("/api/confirm/nao", headers=ORIGIN)
    assert gate.clicks == [True, False]
    assert client.post("/api/confirm/talvez", headers=ORIGIN).status_code == 400
    assert gate.clicks == [True, False]


@pytest.mark.parametrize("origin", ["https://site-malicioso.example", "http://127.0.0.1:9999", "null"])
def test_posts_from_other_origins_are_rejected(env, origin):
    client, viv, gate = env
    assert client.post("/api/confirm/sim", headers={"Origin": origin}).status_code == 403
    assert client.post("/api/wake", headers={"Origin": origin}).status_code == 403
    assert gate.clicks == [] and viv.calls == []


def test_post_without_origin_header_is_rejected(env):
    client, _, gate = env
    assert client.post("/api/confirm/sim").status_code == 403 and gate.clicks == []


def test_localhost_origin_is_accepted(env):
    client, _, gate = env
    assert client.post("/api/confirm/sim", headers={"Origin": "http://localhost:8765"}).status_code == 200


def test_websocket_forwards_bus_events_and_unsubscribes(env):
    client, _, _ = env
    before = len(BUS._subs)
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        for _ in range(100):
            if len(BUS._subs) > before:
                break
            time.sleep(0.01)
        BUS.emit("state", state="listening")
        event = ws.receive_json()
        assert event["channel"] == "state" and event["state"] == "listening"
    for _ in range(200):
        if len(BUS._subs) == before:
            break
        time.sleep(0.01)
    assert len(BUS._subs) == before


def test_websocket_from_other_origin_is_refused(env):
    client, _, _ = env
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={"Origin": "https://site-malicioso.example"}) as ws:
            ws.receive_json()


def test_index_and_static_are_served(env):
    client, _, _ = env
    assert Path("web/index.html").exists()
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_screen_returns_404_without_capture(env):
    client, _, _ = env
    assert client.get("/api/screen").status_code == 404
