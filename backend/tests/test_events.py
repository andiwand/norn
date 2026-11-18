"""Camera events as recording triggers: who records, and for how long."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from norn.drivers.base import Event
from norn.drivers.hikvision import parse_alerts
from norn.hub import Hub
from norn.settings import Settings

CONFIG = """\
recording:
  triggers: [motion]
circles:
  outside:
    name: Outside
    cameras: [door, yard]
    together: true
    triggers: [person]
cameras:
  door: {name: Door, driver: demo}
  yard: {name: Yard, driver: demo, triggers: []}
  hall: {name: Hall, driver: demo}
"""


@pytest.fixture
async def hub(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text(CONFIG)
    monkeypatch.setattr("norn.hub.HOLD_INTERVAL", 0.05)
    hub = Hub(settings)
    await hub.start()
    calls: list[tuple[str, str]] = []

    async def record_clip(camera: str, trigger: str = "manual", seconds: Any = None, by: Any = ()) -> None:
        calls.append((camera, trigger))
        hub.by.append((camera, trigger, sorted(by)))  # type: ignore[attr-defined]

    monkeypatch.setattr(hub.recorder, "record_clip", record_clip)
    hub.calls = calls  # type: ignore[attr-defined]
    hub.by = []  # type: ignore[attr-defined]
    yield hub
    await hub.stop()


async def test_triggers_follow_camera_circle_global(hub: Hub) -> None:
    assert hub.triggers_of("door") == {"person"}  # the circle's setting beats the global one
    assert hub.triggers_of("yard") == set()  # the camera's own: none
    assert hub.triggers_of("hall") == {"motion"}  # the global one


async def test_motion_records_while_it_lasts(hub: Hub) -> None:
    hub.on_event("hall", Event(kind="motion", active=True))
    await asyncio.sleep(0.2)
    hub.on_event("hall", Event(kind="motion", active=False))
    await asyncio.sleep(0.1)
    count = len(hub.calls)  # type: ignore[attr-defined]
    assert count >= 2 and set(hub.calls) == {("hall", "motion")}  # type: ignore[attr-defined]
    await asyncio.sleep(0.2)
    assert len(hub.calls) == count  # type: ignore[attr-defined]  # stopped extending
    assert hub.cameras["hall"].detecting == {}


async def test_circle_records_together(hub: Hub) -> None:
    hub.on_event("door", Event(kind="motion", active=True))  # not a trigger for door
    await asyncio.sleep(0.05)
    assert hub.calls == []  # type: ignore[attr-defined]
    assert hub.cameras["door"].detecting == {"motion": {"camera"}}
    hub.on_event("door", Event(kind="person", active=True))
    await asyncio.sleep(0.1)
    hub.on_event("door", Event(kind="person", active=False))
    assert {camera for camera, _ in hub.calls} == {"door", "yard"}  # type: ignore[attr-defined]


def test_parse_hikvision_alerts() -> None:
    stream = (
        "--boundary\r\nContent-Type: application/xml\r\n\r\n"
        "<EventNotificationAlert><eventType>VMD</eventType><eventState>active</eventState>"
        "</EventNotificationAlert>\r\n--boundary\r\n"
        "<EventNotificationAlert><eventType>videoloss</eventType><eventState>inactive</eventState>"
        "</EventNotificationAlert>"
        "<EventNotificationAlert><eventType>linedetection</eventType><targetType>human</targetType>"
        "<eventState>active</eventState></Event"
    )
    alerts, rest = parse_alerts(stream)
    assert alerts == [("motion", True)]
    alerts, _ = parse_alerts(rest + "NotificationAlert>")
    assert alerts == [("person", True)]


def test_schedule_windows() -> None:
    from datetime import datetime

    from norn.config import Window, in_schedule

    night = Window.model_validate({"days": ["fri"], "from": "20:00", "to": "07:00"})
    assert night.contains(datetime(2026, 11, 20, 21, 0))  # Friday evening
    assert night.contains(datetime(2026, 11, 21, 6, 59))  # Saturday morning: Friday's night
    assert not night.contains(datetime(2026, 11, 21, 21, 0))  # Saturday evening
    assert not night.contains(datetime(2026, 11, 20, 6, 0))  # Friday morning: Thursday's night
    day = Window.model_validate({"from": "09:00", "to": "17:00"})
    assert day.contains(datetime(2026, 11, 16, 9, 0)) and not day.contains(datetime(2026, 11, 16, 17, 0))
    assert in_schedule([], datetime(2026, 11, 16, 3, 0))  # no windows: always


def test_away_beats_schedules() -> None:
    from datetime import datetime

    from norn.config import Config

    config = Config.model_validate(
        {
            "recording": {"triggers": ["motion"], "schedule": [{"from": "22:00", "to": "06:00"}]},
            "away": {"start": "2026-12-20T15:00", "end": "2027-01-03T12:00", "triggers": ["person"]},
            "cameras": {"door": {"name": "Door", "driver": "demo"}},
        }
    )
    assert config.triggers("door", datetime(2026, 11, 16, 12, 0)) == set()  # outside the window
    assert config.triggers("door", datetime(2026, 11, 16, 23, 0)) == {"motion"}
    assert config.triggers("door", datetime(2026, 12, 24, 12, 0)) == {"person"}  # on holiday
    assert config.triggers("door", datetime(2027, 1, 3, 12, 0)) == set()  # back home, midday


def test_schedule_and_away_round_trip(client: Any, settings: Settings) -> None:
    body = {
        "recording": {
            "triggers": ["motion"],
            "schedule": [{"days": ["sat", "sun"], "from": "08:00", "to": "20:00"}],
        }
    }
    response = client.put("/api/settings", json=body)
    assert response.status_code == 200, response.text
    text = settings.config_path.read_text()
    assert "from: 08:00" in text or "from: '08:00'" in text
    assert response.json()["values"]["recording"]["schedule"][0]["from"] == "08:00"
    client.put("/api/settings", json={"away": {"active": True}})
    info = client.get("/api/info").json()
    assert info["away"]["now"] is True and info["away"]["triggers"] == ["motion", "person"]
    assert client.get("/api/settings").json()["values"]["recording"]["triggers"] == ["motion"]
    bad = {"recording": {"schedule": [{"from": "25:00", "to": "07:00"}]}}
    assert client.put("/api/settings", json=bad).status_code == 422


async def test_removing_a_camera_ends_its_clip(hub: Hub) -> None:
    hub.on_event("hall", Event(kind="motion", active=True))
    await asyncio.sleep(0.1)
    await hub.remove_camera("hall")
    count = len(hub.calls)  # type: ignore[attr-defined]
    await asyncio.sleep(0.2)
    assert len(hub.calls) == count  # type: ignore[attr-defined]  # no longer extended
    assert "hall" not in hub._held and "hall" not in hub._holds


async def test_editing_triggers_keeps_the_camera(hub: Hub) -> None:
    from norn.config import CameraConfig

    before = hub.cameras["hall"]
    cfg = CameraConfig.model_validate({"name": "Hall", "driver": "demo", "triggers": ["person"]})
    await hub.put_camera("hall", cfg)
    assert hub.cameras["hall"] is before  # same driver and watchers: only Norn's settings changed
    assert hub.triggers_of("hall") == {"person"}


def test_time_fixes() -> None:
    from datetime import datetime

    from norn.config import AwaySettings, Window

    away = AwaySettings.model_validate({"start": "2026-11-16T10:00:00Z"})
    assert away.start is not None and away.start.tzinfo is None  # local time, comparable
    assert away.now(datetime(2030, 1, 1)) in (True, False)
    day = Window.model_validate({"from": "00:00", "to": "00:00", "days": ["mon"]})
    assert day.contains(datetime(2026, 11, 16, 13, 0))  # a Monday: all of it


def test_presets_record_their_own_way() -> None:
    from norn.config import Config

    preset = {"slot": "1", "triggers": ["person"], "clip_seconds": 90, "prebuffer_seconds": 30}
    config = Config.model_validate(
        {
            "recording": {"triggers": ["motion"], "clip_seconds": 20, "prebuffer_seconds": 5},
            "cameras": {
                "yard": {
                    "name": "Yard",
                    "driver": "demo",
                    "clip_seconds": 40,
                    "presets": {"gate": {"name": "Gate", **preset}, "lawn": {"name": "Lawn", "slot": "2"}},
                }
            },
        }
    )
    assert config.triggers("yard") == {"motion"}
    assert config.triggers("yard", preset="gate") == {"person"}
    assert config.triggers("yard", preset="lawn") == {"motion"}  # nothing of its own: the camera's
    assert config.setting("yard", "clip_seconds") == (40, True)
    assert config.setting("yard", "clip_seconds", "gate") == (90, True)
    assert config.setting("yard", "prebuffer_seconds", "lawn") == (5, False)
    assert config.longest_prebuffer("yard") == (30, True)  # the buffer holds what any preset wants


async def test_a_trigger_during_a_clip_extends_it(settings: Settings) -> None:
    import time
    from datetime import datetime

    from norn.config import Config
    from norn.recorder import Clip

    recorder = Hub(settings).recorder
    recorder.available = True
    recorder._config = Config.model_validate(
        {"cameras": {"c": {"name": "C", "driver": "demo", "clip_seconds": 60}}}
    )
    now = datetime.now()
    clip = Clip("c", settings.temp_path / "c.mp4", "manual", now, now, 10, time.time() + 10, {"manual"})
    recorder.clips["c"] = clip
    assert await recorder.record_clip("c", "person") is clip  # the same video, not a second
    assert clip.events == {"manual", "person"}
    assert clip.end >= time.time() + 59  # the camera's clip length from now on


async def test_norn_confirms_the_cameras_alarm(hub: Hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """`check_camera: require`: the camera's person alone records nothing (it makes Norn's AI
    look); once Norn sees the person too, the clip records, noting who saw it."""
    monkeypatch.setattr(hub.detectors, "_missing", None)
    hub.config.recording.triggers = ["person"]
    hub.config.detection.check_camera = "require"
    async with hub.bus.subscribe() as queue:
        hub.on_event("hall", Event(kind="person", active=True))
        await asyncio.sleep(0.15)
        assert hub.calls == []  # type: ignore[attr-defined]
        assert hub._camera_alarm(hub.cameras["hall"])
        hub.on_event("hall", Event(kind="person", active=True), "norn")
        await asyncio.sleep(0.15)
        hub.on_event("hall", Event(kind="person", active=False), "norn")
        hub.on_event("hall", Event(kind="person", active=False))
        assert ("hall", "person", ["camera", "norn"]) in hub.by  # type: ignore[attr-defined]
        sources = []
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "camera.event":
                sources.append(event["data"]["sources"])
        # Each change of who sees it goes out: the camera, both, the camera again, nobody.
        assert sources == [["camera"], ["camera", "norn"], ["camera"], []]


async def test_the_cameras_word_counts_without_norn(hub: Hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Norn's AI (not installed), `require` falls back to the camera: nothing is lost."""
    monkeypatch.setattr(hub.detectors, "_missing", "onnxruntime is not installed")
    hub.config.recording.triggers = ["person"]
    hub.config.detection.check_camera = "require"
    hub.on_event("hall", Event(kind="person", active=True))
    await asyncio.sleep(0.15)
    hub.on_event("hall", Event(kind="person", active=False))
    assert ("hall", "person", ["camera"]) in hub.by  # type: ignore[attr-defined]


async def test_under_require_the_camera_alone_holds_nothing(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Norn confirmed and the clip ran; once Norn sees nobody, the camera's word alone doesn't
    keep extending it. Reactions too wait for Norn."""
    monkeypatch.setattr(hub.detectors, "_missing", None)
    reacted: list[str] = []
    monkeypatch.setattr(hub, "_react", lambda camera, kind: reacted.append(kind))
    hub.config.recording.triggers = ["person"]
    hub.config.detection.check_camera = "require"
    hub.on_event("hall", Event(kind="person", active=True))
    assert reacted == []  # the camera's alarm alone: no reaction
    hub.cameras["hall"].norn_looked = time.monotonic()  # Norn's AI looks
    hub.on_event("hall", Event(kind="person", active=True), "norn")
    assert reacted == ["person"]
    await asyncio.sleep(0.15)
    hub.on_event("hall", Event(kind="person", active=False), "norn")
    await asyncio.sleep(0.05)
    count = len(hub.calls)  # type: ignore[attr-defined]
    await asyncio.sleep(0.2)
    assert len(hub.calls) == count  # type: ignore[attr-defined]  # not held by the camera alone
    hub.on_event("hall", Event(kind="person", active=False))


async def test_the_cameras_word_counts_when_norn_cannot_look(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Norn's AI is installed but gets no stills (no go2rtc, a broken stream): after a grace
    time the camera's alarm records anyway."""
    monkeypatch.setattr(hub.detectors, "_missing", None)
    monkeypatch.setattr("norn.hub.NORN_LOOK_GRACE", 0.1)
    hub.config.recording.triggers = ["person"]
    hub.config.detection.check_camera = "require"
    hub.on_event("hall", Event(kind="person", active=True))
    await asyncio.sleep(0.05)
    assert hub.calls == []  # type: ignore[attr-defined]
    await asyncio.sleep(0.2)
    hub.on_event("hall", Event(kind="person", active=False))
    assert ("hall", "person", ["camera"]) in hub.by  # type: ignore[attr-defined]


async def test_a_circles_other_cameras_record_without_notes(hub: Hub) -> None:
    """Who saw it is noted on the clip of the camera that saw it, not on the others that
    record along."""
    hub.on_event("door", Event(kind="person", active=True))
    await asyncio.sleep(0.1)
    hub.on_event("door", Event(kind="person", active=False))
    by = {camera: sources for camera, _, sources in hub.by}  # type: ignore[attr-defined]
    assert by == {"door": ["camera"], "yard": []}
