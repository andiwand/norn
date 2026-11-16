"""Camera events as recording triggers: who records, and for how long."""

from __future__ import annotations

import asyncio
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

    async def record_clip(camera: str, trigger: str = "manual", seconds: Any = None) -> None:
        calls.append((camera, trigger))

    monkeypatch.setattr(hub.recorder, "record_clip", record_clip)
    hub.calls = calls  # type: ignore[attr-defined]
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
