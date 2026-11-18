"""Notifications (web push) without a network: the rules, the devices, sending, the API."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from norn.config import NotificationSettings, Window
from norn.drivers.base import Event
from norn.hub import Hub
from norn.notify import Device, DeviceStore, Notifier, blocked, device_name
from norn.settings import Settings

WEDNESDAY_NOON = datetime(2026, 11, 18, 12, 0)
KEYS = {"p256dh": "BPk", "auth": "a1"}


def test_the_rules() -> None:
    rules = NotificationSettings()
    assert blocked(rules, "door", "person", False, WEDNESDAY_NOON) is None
    assert blocked(rules, "door", "motion", False, WEDNESDAY_NOON)  # motion is off by default
    assert blocked(NotificationSettings(enabled=False), "door", "person", False, WEDNESDAY_NOON)
    only_yard = NotificationSettings(cameras=["yard"])
    assert blocked(only_yard, "door", "person", False, WEDNESDAY_NOON)
    assert blocked(only_yard, "yard", "person", False, WEDNESDAY_NOON) is None
    away = NotificationSettings(away_only=True)
    assert blocked(away, "door", "person", False, WEDNESDAY_NOON) == "only while away"
    assert blocked(away, "door", "person", True, WEDNESDAY_NOON) is None
    lunch = NotificationSettings(quiet=[Window.model_validate({"from": "11:00", "to": "13:00"})])
    assert blocked(lunch, "door", "person", False, WEDNESDAY_NOON) == "quiet hours"
    assert blocked(lunch, "door", "person", False, WEDNESDAY_NOON.replace(hour=14)) is None


def test_device_names() -> None:
    android = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"
    iphone = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
        "Version/18.1 Mobile/15E148 Safari/604.1"
    )
    mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
    assert device_name(android) == "Chrome on Android"
    assert device_name(iphone) == "iPhone"
    assert device_name(mac) == "Chrome on Mac"
    assert device_name("") == "Browser"


def test_devices_are_kept_and_a_browser_keeps_its_device(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path / "push.json")
    phone = store.add("https://fcm.googleapis.com/fcm/send/x", KEYS, "Chrome on Android", None)
    phone.name = "Kitchen tablet"
    store.save()
    again = store.add("https://fcm.googleapis.com/fcm/send/x", {"p256dh": "new", "auth": "b"}, "x", "anna")
    assert again.id == phone.id and again.name == "Kitchen tablet" and again.keys["p256dh"] == "new"
    loaded = DeviceStore(tmp_path / "push.json")
    assert [d.name for d in loaded.devices.values()] == ["Kitchen tablet"]
    assert loaded.devices[phone.id].user == "anna"
    assert (tmp_path / "push.json").stat().st_mode & 0o077 == 0  # the keys are for Norn only


class Sent:
    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.messages: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, device: Device, data: str) -> int:
        self.messages.append((device.name, json.loads(data)))
        return self.status


def notifier(tmp_path: Path, rules: NotificationSettings, sent: Sent) -> Notifier:
    async def still(camera: str) -> bytes:
        return b"\xff\xd8jpeg"

    n = Notifier(tmp_path, lambda: rules, still, sender=sent)
    n.store.add("https://fcm.googleapis.com/fcm/send/a", KEYS, "Phone", None)
    return n


async def test_a_detection_notifies_once_in_a_while(tmp_path: Path) -> None:
    sent = Sent()
    n = notifier(tmp_path, NotificationSettings(every_minutes=5), sent)
    assert await n.detected("door", "Front door", "person", {"camera", "norn"}, False) == 1
    title, message = sent.messages[0][1]["title"], sent.messages[0][1]
    assert title == "Person · Front door" and message["body"].startswith("Seen by camera + Norn")
    assert message["url"] == "/cameras/door" and message["tag"] == "norn-door"
    token = message["image"].removeprefix("/api/notifications/pictures/").removesuffix(".jpg")
    assert n.picture(token) == b"\xff\xd8jpeg"
    # The same camera again soon: quiet. Another camera: notifies.
    assert await n.detected("door", "Front door", "vehicle", {"norn"}, False) == 0
    assert await n.detected("yard", "Yard", "person", {"camera"}, False) == 1


async def test_a_device_can_take_only_some_cameras(tmp_path: Path) -> None:
    sent = Sent()
    n = notifier(tmp_path, NotificationSettings(), sent)
    next(iter(n.store.devices.values())).cameras = ["yard"]
    assert await n.detected("door", "Front door", "person", {"camera"}, False) == 0
    assert await n.detected("yard", "Yard", "person", {"camera"}, False) == 1


async def test_devices_the_push_service_forgot_are_dropped(tmp_path: Path) -> None:
    n = notifier(tmp_path, NotificationSettings(), Sent(410))
    assert await n.detected("door", "Front door", "person", {"camera"}, False) == 0
    assert n.store.devices == {}
    assert DeviceStore(tmp_path / "push.json").devices == {}


async def test_without_a_picture_it_still_notifies(tmp_path: Path) -> None:
    sent = Sent()
    n = notifier(tmp_path, NotificationSettings(picture=False), sent)
    assert await n.detected("door", "Front door", "person", {"camera"}, False) == 1
    assert sent.messages[0][1]["image"] is None


def test_the_key_is_made_once(tmp_path: Path) -> None:
    n = Notifier(tmp_path, NotificationSettings, lambda c: asyncio.sleep(0, None))
    key = n.public_key
    assert len(key) == 87  # an uncompressed P-256 point, base64url
    assert Notifier(tmp_path, NotificationSettings, lambda c: asyncio.sleep(0, None)).public_key == key


async def test_what_counts_notifies(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hub tells the notifier when a detection starts to count, with who sees it; under
    `check_camera: require` not for the camera's alarm alone."""
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text("cameras:\n  hall: {name: Hall, driver: demo}\n")
    hub = Hub(settings)
    await hub.start()
    calls: list[tuple[Any, ...]] = []

    async def detected(*args: Any) -> int:
        calls.append(args)
        return 1

    monkeypatch.setattr(hub.notifier, "detected", detected)
    try:
        hub.on_event("hall", Event(kind="person", active=True))
        await asyncio.sleep(0.05)
        assert calls == [("hall", "Hall", "person", {"camera"}, False)]
        hub.on_event("hall", Event(kind="person", active=True), "norn")  # still the same person
        hub.on_event("hall", Event(kind="person", active=False))
        hub.on_event("hall", Event(kind="person", active=False), "norn")
        monkeypatch.setattr(hub.detectors, "_missing", None)
        hub.config.detection.check_camera = "require"
        hub.on_event("hall", Event(kind="person", active=True))
        await asyncio.sleep(0.05)
        assert len(calls) == 1  # the camera alone: not yet
        hub.cameras["hall"].norn_looked = time.monotonic()
        hub.on_event("hall", Event(kind="person", active=True), "norn")
        await asyncio.sleep(0.05)
        assert calls[-1] == ("hall", "Hall", "person", {"camera", "norn"}, False)
    finally:
        await hub.stop()


def test_the_api(client: TestClient) -> None:
    hub: Hub = client.app.state.hub  # type: ignore[attr-defined]
    sent = Sent()
    hub.notifier._sender = sent
    info = client.get("/api/notifications").json()
    assert len(info["public_key"]) == 87 and info["devices"] == []
    for bad in ("http://fcm.googleapis.com/x", "https://192.168.1.2/x", "https://localhost/x"):
        r = client.post("/api/notifications/devices", json={"endpoint": bad, "keys": KEYS})
        assert r.status_code == 422, bad
    # Keys that aren't a browser's: refused at once, not at the first notification.
    r = client.post(
        "/api/notifications/devices", json={"endpoint": "https://fcm.googleapis.com/x", "keys": KEYS}
    )
    assert r.status_code == 422
    point = base64.urlsafe_b64encode(b"\x04" + bytes(64)).rstrip(b"=").decode()
    secret = base64.urlsafe_b64encode(bytes(16)).rstrip(b"=").decode()
    keys = {"p256dh": point, "auth": secret}
    ua = {"user-agent": "Mozilla/5.0 (Linux; Android 14) Chrome/131.0 Mobile Safari/537.36"}
    r = client.post(
        "/api/notifications/devices",
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/z", "keys": keys, "expirationTime": None},
        headers=ua,
    )
    assert r.status_code == 201
    device = r.json()
    assert device["name"] == "Chrome on Android" and "keys" not in device
    r = client.patch(
        f"/api/notifications/devices/{device['id']}", json={"name": "Pixel", "cameras": ["door"]}
    )
    assert r.json()["name"] == "Pixel" and r.json()["cameras"] == ["door"]
    assert client.post(f"/api/notifications/devices/{device['id']}/test").json() == {"sent": 1}
    assert sent.messages[0][0] == "Pixel" and sent.messages[0][1]["tag"] == "norn-test"
    assert client.get("/api/notifications/pictures/nope.jpg").status_code == 404
    assert client.delete(f"/api/notifications/devices/{device['id']}").status_code == 204
    assert client.get("/api/notifications").json()["devices"] == []
    # The rules are a settings section; defaults stay out of config.yaml.
    r = client.put("/api/settings", json={"notifications": {"away_only": True, "every_minutes": 5}})
    assert r.json()["values"]["notifications"]["away_only"] is True
    text = hub.store.path.read_text()
    assert "away_only: true" in text and "every_minutes" not in text
