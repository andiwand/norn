from __future__ import annotations

import dataclasses
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
    # A sub-stream of its own: no transcoded one.
    assert [s["name"] for s in camera["streams"]] == ["demo", "demo_sub"]


def test_camera_crud_writes_yaml(client: TestClient, settings: Settings) -> None:
    body = {"id": "porch", "name": "Porch", "driver": "rtsp", "url": "rtsp://cam/1"}
    response = client.post("/api/cameras", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["streams"][0] == {"id": "main", "label": "Main", "name": "porch", "codec": None}
    hub = client.app.state.hub  # type: ignore[attr-defined]
    assert hub.streams()["porch_low"].startswith("ffmpeg:porch#video=h264")
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
    assert "porch_low" not in hub.streams()  # it has a small stream of its own

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
    assert client.get("/api/recordings").json() == {"recordings": [], "days": [], "truncated": False}


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


def test_settings_round_trip(client: TestClient, settings: Settings) -> None:
    data = client.get("/api/settings").json()
    assert data["values"]["recording"]["retention_days"] == 14
    assert data["defaults"]["recording"]["clip_seconds"] == 30
    recording = {**data["values"]["recording"], "retention_days": 30, "clip_seconds": 45}
    response = client.put("/api/settings", json={"recording": recording})
    assert response.status_code == 200, response.text
    assert response.json()["values"]["recording"]["retention_days"] == 30
    text = settings.config_path.read_text()
    assert "retention_days: 30" in text and "# delete recordings" in text  # the comment survives
    assert "clip_seconds: 45" in text
    assert client.get("/api/info").json()["recording"]["clip_seconds"] == 45
    bad = client.put("/api/settings", json={"recording": {**recording, "segment_minutes": 0}})
    assert bad.status_code == 422
    assert client.put("/api/settings", json={"nope": {}}).status_code == 422


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
    shared = Go2rtc(dataclasses.replace(settings, rtsp_share=True), EventBus())
    assert shared.config({})["rtsp"]["listen"] == ":8554"  # to the network
    assert shared.rtsp_url("door") == "rtsp://127.0.0.1:8554/door"  # Norn itself: as before


def test_go2rtc_config_is_block_yaml(settings: Settings) -> None:
    go2rtc = Go2rtc(settings, EventBus())
    go2rtc.write_config({"door": "rtsp://u:p%23w@cam/1"})
    text = go2rtc.config_path.read_text()
    assert "{" not in text  # go2rtc's own editor can't handle flow style
    assert "door: rtsp://u:p%23w@cam/1" in text


def test_storage_and_pictures(client: TestClient, settings: Settings) -> None:
    picture = settings.recordings_path / "demo" / "2026-11-15" / "10-00-00_interval.jpg"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"jpeg")
    (settings.temp_path / "demo").mkdir(parents=True)
    (settings.temp_path / "demo" / "x.bin").write_bytes(b"12")
    storage = client.get("/api/storage").json()
    assert storage["recordings"]["used"] == 4 and storage["temp"]["used"] == 2
    assert storage["buffer"]["used"] == 0
    data = client.get("/api/recordings", params={"kind": "picture"}).json()
    [item] = data["recordings"]
    assert item["kind"] == "picture" and item["expires"].startswith("2026-11-29T10:00:00")
    since = "2026-11-15T09:00:00+00:00"
    assert client.get("/api/recordings", params={"since": since}).json()["recordings"]
    assert client.delete(f"/api/recordings/{item['id']}").status_code == 204
    assert not picture.exists()


def test_firmware_settings_and_camera_overrides(client: TestClient, settings: Settings) -> None:
    response = client.put("/api/settings", json={"firmware": {"check_hours": 6}})
    assert response.json()["values"]["firmware"] == {"check_hours": 6}
    text = settings.config_path.read_text()
    assert text.index("firmware:") < text.index("cameras:")
    body = {"name": "Demo camera", "driver": "demo", "picture_seconds": 60}
    camera = client.put("/api/cameras/demo", json=body).json()
    assert camera["picture_seconds"] == 60 and camera["prebuffer_seconds"] is None
    assert "picture_seconds: 60" in settings.config_path.read_text()
    bad = client.put("/api/cameras/demo", json={**body, "picture_seconds": 3})
    assert bad.status_code == 422


def test_resources(client: TestClient) -> None:
    data = client.get("/api/resources").json()
    assert data["processes"][0]["kind"] == "Norn" or any(p["kind"] == "Norn" for p in data["processes"])
    assert data["system"]["cores"] >= 1 and data["memory"] > 0
    assert data["gpu"]["used"] is False


def test_circles(client: TestClient, settings: Settings) -> None:
    client.post("/api/cameras", json={"id": "yard", "name": "Yard", "driver": "demo"})
    body = {"id": "outside", "name": "Outside", "cameras": ["demo", "yard"], "picture_seconds": 300}
    response = client.post("/api/circles", json=body)
    assert response.status_code == 201, response.text
    text = settings.config_path.read_text()
    assert text.index("circles:") < text.index("cameras:")
    assert client.post("/api/circles", json={**body, "id": "x", "cameras": ["nope"]}).status_code == 422
    assert client.get("/api/circles").json()[0]["cameras"] == ["demo", "yard"]
    hub = client.app.state.hub  # type: ignore[attr-defined]
    assert hub.config.setting("yard", "picture_seconds") == (300, True)
    assert hub.config.setting("yard", "prebuffer_seconds") == (10, False)

    # The two demo cameras share their controls; one change sets both.
    controls = {c["id"]: c for c in client.get("/api/circles/outside/controls").json()["controls"]}
    assert controls["spotlight"]["mixed"] is False
    assert client.post("/api/circles/outside/controls/spotlight", json={"value": True}).json()["ok"]
    for camera in ("demo", "yard"):
        values = {
            c["id"]: c.get("value") for c in client.get(f"/api/cameras/{camera}/controls").json()["controls"]
        }
        assert values["spotlight"] is True
    client.post("/api/cameras/yard/controls/spotlight", json={"value": False})
    controls = {c["id"]: c for c in client.get("/api/circles/outside/controls").json()["controls"]}
    assert controls["spotlight"]["mixed"] is True and controls["spotlight"]["value"] is None

    assert client.post("/api/circles/outside/record", json={}).status_code == 503  # no go2rtc in tests
    assert client.delete("/api/circles/outside").status_code == 204
    assert "circles" not in settings.config_path.read_text()


def test_review_fixes(client: TestClient, settings: Settings) -> None:
    # Norn's own triggers can't come from outside.
    assert client.post("/api/cameras/demo/record", json={"trigger": "continuous"}).status_code == 422
    # A partial settings change keeps the other fields.
    client.put("/api/settings", json={"recording": {"clip_seconds": 60}})
    client.put("/api/settings", json={"recording": {"retention_days": 3}})
    recording = client.get("/api/settings").json()["values"]["recording"]
    assert (recording["clip_seconds"], recording["retention_days"]) == (60, 3)
    # Removing a camera takes it out of its circles.
    client.post("/api/cameras", json={"id": "yard", "name": "Yard", "driver": "demo"})
    body = {"id": "all", "name": "All", "cameras": ["demo", "yard", "yard"]}
    assert client.post("/api/circles", json=body).json()["cameras"] == ["demo", "yard"]
    assert client.delete("/api/cameras/yard").status_code == 204
    assert client.get("/api/circles").json()[0]["cameras"] == ["demo"]


def test_live_continuous_file_is_listed(client: TestClient, settings: Settings) -> None:
    live = settings.temp_path / "demo" / "2026-11-16" / "09-00-00_continuous.mp4"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"frag")
    [item] = client.get("/api/recordings").json()["recordings"]
    assert item["live"] is True and item["id"] == "demo/2026-11-16/09-00-00_continuous.mp4"
    assert client.get(f"/api/recordings/{item['id']}").content == b"frag"


def test_pin_keeps_a_recording(client: TestClient, settings: Settings) -> None:
    picture = settings.recordings_path / "demo" / "2020-01-01" / "10-00-00_interval.jpg"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"jpeg")
    url = "/api/recordings/demo/2020-01-01/10-00-00_interval.jpg/pin"
    pinned = client.put(url, json={"pinned": True}).json()
    assert pinned["pinned"] is True and pinned["expires"] is None
    hub = client.app.state.hub  # type: ignore[attr-defined]
    assert hub.library.prune(14) == [] and hub.library.evict(max_bytes=1)[0] == []
    assert client.put(url, json={"pinned": False}).json()["expires"] is not None
    assert hub.library.prune(14) == ["demo/2020-01-01/10-00-00_interval.jpg"]


def test_streams_from_probing(client: TestClient) -> None:
    from norn.probe import StreamProbe

    client.post(
        "/api/cameras",
        json={"id": "door", "name": "Door", "driver": "rtsp", "url": "rtsp://c/1", "substream": "rtsp://c/2"},
    )
    hub = client.app.state.hub  # type: ignore[attr-defined]
    camera = hub.cameras["door"]
    camera.probe = {
        "main": StreamProbe(ok=True, width=2560, height=1440, codec="h264", fps=15),
        "sub": StreamProbe(ok=True, width=640, height=360, codec="h264", fps=7),
    }
    camera.concurrent = True
    data = client.get("/api/cameras/door").json()
    # A small stream of its own: no transcoding.
    assert [s["id"] for s in data["streams"]] == ["main", "sub"] and "door_low" not in hub.streams()
    assert data["streams"][1]["width"] == 640
    camera.concurrent = False  # one stream at a time: only the best
    assert [s["id"] for s in client.get("/api/cameras/door").json()["streams"]] == ["main", "low"]
    camera.concurrent = True
    body = {
        "name": "Door",
        "driver": "rtsp",
        "url": "rtsp://c/1",
        "substream": "rtsp://c/2",
        "streams": ["sub"],
    }
    client.put("/api/cameras/door", json=body)
    camera = hub.cameras["door"]
    camera.probe = {
        "main": StreamProbe(ok=True, width=2560, height=1440),
        "sub": StreamProbe(ok=True, width=640),
    }
    camera.concurrent = True
    # Only the sub-stream, as the camera's main one in go2rtc.
    assert hub.streams()["door"] == "rtsp://c/2"
    options = {o["id"]: o["active"] for o in client.get("/api/cameras/door").json()["stream_options"]}
    assert options == {"main": False, "sub": True}


def test_preset_recording_survives_other_saves(client: TestClient) -> None:
    assert client.put("/api/cameras/demo/presets/gate", json={"name": "Gate"}).status_code == 200
    body = {"triggers": ["person"], "clip_seconds": 90, "prebuffer_seconds": None}
    assert client.put("/api/cameras/demo/presets/gate/recording", json=body).status_code == 200
    assert client.put("/api/cameras/demo/presets/nope/recording", json=body).status_code == 404
    bad = client.put("/api/cameras/demo/presets/gate/recording", json={"triggers": ["ufo"]})
    assert bad.status_code == 422

    def gate() -> dict:
        return client.get("/api/cameras/demo").json()["presets_norn"]["gate"]

    client.put("/api/cameras/demo/presets/gate", json={"name": "Gate 2"})  # a new view
    assert (gate()["name"], gate()["triggers"], gate()["clip_seconds"]) == ("Gate 2", ["person"], 90)
    camera = client.get("/api/cameras/demo").json()
    body = {"name": camera["name"], "driver": "demo", "clip_seconds": 40}  # no presets: kept
    assert client.put("/api/cameras/demo", json=body).status_code == 200
    assert gate()["clip_seconds"] == 90
    assert client.get("/api/cameras/demo").json()["clip_seconds"] == 40
