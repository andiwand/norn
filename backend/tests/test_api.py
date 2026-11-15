from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from norn.api import create_app
from norn.events import EventBus
from norn.go2rtc import Go2rtc
from norn.settings import Settings


def test_health_and_info(client: TestClient) -> None:
    assert client.get("/api/health").json()["ok"] is True
    info = client.get("/api/info").json()
    assert info["go2rtc"] == {"running": False}
    assert info["config_error"] is None


def test_drivers_have_option_schemas(client: TestClient) -> None:
    drivers = {d["name"]: d for d in client.get("/api/drivers").json()}
    assert {"demo", "rtsp"} <= drivers.keys()
    assert "url" in drivers["rtsp"]["options"]["required"]


def test_default_demo_camera(client: TestClient) -> None:
    [camera] = client.get("/api/cameras").json()
    assert camera["id"] == "demo"
    assert {"live", "ptz", "presets", "controls"} <= set(camera["capabilities"])
    assert [s["name"] for s in camera["streams"]] == ["demo", "demo_sub"]


def test_camera_crud_writes_yaml(client: TestClient, settings: Settings) -> None:
    body = {"id": "porch", "name": "Porch", "driver": "rtsp", "url": "rtsp://cam/1"}
    response = client.post("/api/cameras", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["streams"] == [{"id": "main", "label": "Main", "name": "porch"}]
    assert "url: rtsp://cam/1" in settings.config_path.read_text()

    assert client.post("/api/cameras", json=body).status_code == 409
    bad = client.put("/api/cameras/porch", json={"name": "Porch", "driver": "rtsp", "url": "ftp://x"})
    assert bad.status_code == 422
    assert client.post("/api/cameras", json={**body, "id": "Bad Id"}).status_code == 422
    assert client.post("/api/cameras", json={**body, "id": "x", "driver": "nope"}).status_code == 422

    updated = client.put(
        "/api/cameras/porch",
        json={"name": "Porch", "driver": "rtsp", "url": "rtsp://cam/1", "substream": "rtsp://cam/2"},
    ).json()
    assert [s["id"] for s in updated["streams"]] == ["main", "sub"]

    assert client.delete("/api/cameras/porch").status_code == 204
    assert client.get("/api/cameras/porch").status_code == 404
    assert "porch" not in settings.config_path.read_text()


def test_demo_controls_and_ptz(client: TestClient) -> None:
    data = client.get("/api/cameras/demo/controls").json()
    controls = {c["id"]: c for c in data["controls"]}
    assert controls["ir"]["kind"] == "select"
    assert [p["id"] for p in data["presets"]] == ["door", "drive"]

    assert client.post("/api/cameras/demo/controls/spotlight", json={"value": True}).status_code == 200
    assert client.post("/api/cameras/demo/controls/ir", json={"value": "maybe"}).status_code == 422
    assert client.post("/api/cameras/demo/controls/nope", json={"value": 1}).status_code == 404
    controls = {c["id"]: c for c in client.get("/api/cameras/demo/controls").json()["controls"]}
    assert controls["spotlight"]["value"] is True

    assert client.post("/api/cameras/demo/ptz", json={"action": "goto", "preset": "drive"}).status_code == 200
    assert client.post("/api/cameras/demo/ptz", json={"action": "move", "pan": 2}).status_code == 422
    assert client.post("/api/cameras/demo/ptz", json={"action": "move", "pan": 0.5}).status_code == 200
    assert client.post("/api/cameras/demo/ptz", json={"action": "stop"}).status_code == 200


def test_ptz_on_camera_without_ptz(client: TestClient) -> None:
    client.post("/api/cameras", json={"id": "p", "name": "P", "driver": "rtsp", "url": "rtsp://c/1"})
    assert client.post("/api/cameras/p/ptz", json={"action": "home"}).status_code == 409
    assert client.get("/api/cameras/p/controls").json() == {"controls": [], "presets": []}


def test_events_websocket(client: TestClient) -> None:
    with client.websocket_connect("/api/events") as ws:
        client.post("/api/cameras/demo/controls/privacy", json={"value": True})
        event = ws.receive_json()
        assert event["type"] == "camera.control"
        assert event["data"] == {"camera": "demo", "control": "privacy", "value": True}


def test_recording_unavailable_without_go2rtc(client: TestClient) -> None:
    assert client.post("/api/cameras/demo/record", json={}).status_code == 503
    assert client.get("/api/recordings").json() == {"recordings": [], "days": []}


def test_recording_files(client: TestClient, settings: Settings) -> None:
    video = settings.recordings_path / "demo" / "2026-11-15" / "10-00-00_manual.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"0123456789")
    data = client.get("/api/recordings", params={"camera": "demo"}).json()
    assert data["days"] == ["2026-11-15"]
    assert data["recordings"][0]["id"] == "demo/2026-11-15/10-00-00_manual.mp4"

    url = "/api/recordings/demo/2026-11-15/10-00-00_manual.mp4"
    ranged = client.get(url, headers={"Range": "bytes=2-4"})
    assert ranged.status_code == 206 and ranged.content == b"234"
    assert client.get("/api/recordings/demo/2026-11-15/..%2F..%2Fx.mp4").status_code in (400, 404)
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_config_reload_from_disk(client: TestClient, settings: Settings) -> None:
    settings.config_path.write_text("cameras:\n  yard:\n    name: Yard\n    driver: demo\n")
    deadline = time.time() + 5
    while time.time() < deadline:
        ids = [c["id"] for c in client.get("/api/cameras").json()]
        if ids == ["yard"]:
            break
        time.sleep(0.2)
    assert ids == ["yard"]


def test_broken_config_still_starts(settings: Settings) -> None:
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text("cameras: [\n")
    with TestClient(create_app(settings)) as client:
        assert "config.yaml" in client.get("/api/info").json()["config_error"]
        assert client.get("/api/cameras").json() == []


def test_serves_web_ui_with_fallback(tmp_path: Path, settings: Settings) -> None:
    web = tmp_path / "web"
    (web / "_app" / "immutable").mkdir(parents=True)
    (web / "index.html").write_text("<html>norn</html>")
    (web / "_app" / "immutable" / "a.js").write_text("js")
    settings = Settings(**{**settings.__dict__, "static_path": web})
    with TestClient(create_app(settings)) as client:
        assert client.get("/").text == "<html>norn</html>"
        assert client.get("/cameras/demo").text == "<html>norn</html>"
        asset = client.get("/_app/immutable/a.js")
        assert "immutable" in asset.headers["cache-control"]
        assert client.get("/api/nope").status_code == 404


def test_go2rtc_config(settings: Settings) -> None:
    go2rtc = Go2rtc(settings, EventBus())
    config = go2rtc.config({"door": "rtsp://cam/1"})
    assert config["api"]["listen"] == "127.0.0.1:1984"
    assert config["rtsp"]["listen"] == "127.0.0.1:8554"
    assert config["webrtc"]["listen"] == ":8555"
    assert config["streams"] == {"door": "rtsp://cam/1"}
    assert go2rtc.ws_url("door") == "ws://127.0.0.1:1984/api/ws?src=door"
