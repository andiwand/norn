"""Notifications on phones and browsers when something is detected: web push.

Each browser that turns notifications on subscribes with its maker's push service (Google,
Apple, Mozilla) and hands Norn an endpoint and two keys; Norn encrypts its messages for that
browser (RFC 8291) and signs them with its own VAPID key (RFC 8292), made once in
`<config dir>/.norn/vapid.pem`. The devices are kept in `.norn/push.json`: they are not
settings to edit, so they stay out of config.yaml. The rules (which detections, cameras, when,
how often) are config.yaml's `notifications`.

Pictures: a push message holds about 4 KB, too little for a picture. Norn keeps the still of
the moment for an hour behind an unguessable URL (`/api/notifications/pictures/<token>.jpg`)
and sends that; the phone fetches it when it shows the notification. The token is the access:
the phone's fetch of a notification image carries no session. Android shows the picture large;
iPhones and iPads show none in web notifications (only the app's icon), and get push only from
the installed app (Add to Home Screen), from iOS 16.4.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import NotificationSettings, in_schedule
from .labels import LABELS

log = logging.getLogger("norn.notify")

PICTURE_SECONDS = 3600  # how long a notification's picture stays reachable
PICTURES_KEPT = 50  # at most this many in memory (a few MB)
TTL = 3600  # seconds a push service keeps a message for a phone that is offline
# The VAPID "subscriber": push services want a way to reach the sender. The project, not the
# user's address: it would leave the house with every message.
CLAIMS_SUB = "https://andiwand.github.io"  # the project site; py_vapid takes no path


class Device(BaseModel):
    """A browser or installed app that gets notifications."""

    id: str
    endpoint: str
    keys: dict[str, str]  # p256dh and auth, from the browser's subscription
    name: str
    user: str | None = None  # who subscribed it (with sign-in)
    enabled: bool = True
    cameras: list[str] | None = None  # only these; None: as the rules say
    created: float = Field(default_factory=time.time)
    last_used: float | None = None

    def public(self) -> dict[str, Any]:
        """For the web app: without the keys (the endpoint lets a page find its own device)."""
        return self.model_dump(exclude={"keys"})


class DeviceStore:
    """The devices, in a JSON file written whole (to a temporary file, then moved)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.devices: dict[str, Device] = {}
        try:
            data = json.loads(path.read_text())
            for item in data.get("devices", []):
                device = Device.model_validate(item)
                self.devices[device.id] = device
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as e:
            log.warning("%s can't be read (%s): no devices get notifications", path, e)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        devices = [d.model_dump() for d in self.devices.values()]
        tmp.write_text(json.dumps({"devices": devices}, indent=2) + "\n")
        os.chmod(tmp, 0o600)  # the keys let anyone with the file write to these phones
        tmp.replace(self.path)

    def add(self, endpoint: str, keys: dict[str, str], name: str, user: str | None) -> Device:
        """A browser subscribed; the same browser again (a new key, a refreshed subscription)
        keeps its device, name and choices."""
        for device in self.devices.values():
            if device.endpoint == endpoint:
                device.keys, device.enabled = keys, True
                if user:
                    device.user = user
                self.save()
                return device
        device = Device(id=secrets.token_urlsafe(9), endpoint=endpoint, keys=keys, name=name, user=user)
        self.devices[device.id] = device
        self.save()
        return device

    def remove(self, device_id: str) -> bool:
        if self.devices.pop(device_id, None) is None:
            return False
        self.save()
        return True


def blocked(
    rules: NotificationSettings, camera_id: str, kind: str, away: bool, moment: datetime
) -> str | None:
    """Why the rules hold back a notification of `kind` on the camera now, or None."""
    if not rules.enabled:
        return "notifications are off"
    if kind not in rules.kinds:
        return f"{kind} doesn't notify"
    if rules.cameras and camera_id not in rules.cameras:
        return "the camera doesn't notify"
    if rules.away_only and not away:
        return "only while away"
    if rules.quiet and in_schedule(rules.quiet, moment):
        return "quiet hours"
    return None


Sender = Callable[[Device, str], Awaitable[int]]  # sends a payload; the push service's status


class Notifier:
    def __init__(
        self,
        runtime_dir: Path,
        rules: Callable[[], NotificationSettings],
        still: Callable[[str], Awaitable[bytes | None]],
        sender: Sender | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.rules = rules
        self.still = still
        self.store = DeviceStore(runtime_dir / "push.json")
        self._sender = sender or self._webpush
        self._vapid: Any = None
        self._last: dict[str, float] = {}  # camera -> when it last notified (monotonic)
        self._pictures: dict[str, tuple[bytes, float]] = {}  # token -> (JPEG, until)

    # --- The key

    @property
    def vapid(self) -> Any:
        """Norn's VAPID key: read, or made once."""
        if self._vapid is None:
            from py_vapid import Vapid

            path = self.runtime_dir / "vapid.pem"
            if path.is_file():
                self._vapid = Vapid.from_file(str(path))
            else:
                key = Vapid()
                key.generate_keys()
                path.parent.mkdir(parents=True, exist_ok=True)
                key.save_key(str(path))
                os.chmod(path, 0o600)
                self._vapid = key
        return self._vapid

    @property
    def public_key(self) -> str:
        """The application server key browsers subscribe with (base64url, uncompressed P-256)."""
        from cryptography.hazmat.primitives import serialization
        from py_vapid import b64urlencode

        raw = self.vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return b64urlencode(raw)

    # --- Pictures

    def keep_picture(self, jpeg: bytes) -> str:
        now = time.time()
        for token, (_, until) in list(self._pictures.items()):
            if until < now:
                del self._pictures[token]
        while len(self._pictures) >= PICTURES_KEPT:
            del self._pictures[next(iter(self._pictures))]
        token = secrets.token_urlsafe(24)
        self._pictures[token] = (jpeg, now + PICTURE_SECONDS)
        return token

    def picture(self, token: str) -> bytes | None:
        kept = self._pictures.get(token)
        return kept[0] if kept and kept[1] >= time.time() else None

    # --- Sending

    async def detected(
        self, camera_id: str, camera_name: str, kind: str, sources: set[str], away: bool
    ) -> int:
        """Something counts as detected on a camera: notify the devices, if the rules let it.
        How many got it."""
        rules = self.rules()
        why = blocked(rules, camera_id, kind, away, datetime.now())
        devices = [
            d
            for d in self.store.devices.values()
            if d.enabled and (d.cameras is None or camera_id in d.cameras)
        ]
        if why or not devices:
            if why:
                log.debug("%s: no notification of %s: %s", camera_id, kind, why)
            return 0
        now = time.monotonic()
        last = self._last.get(camera_id)
        if last is not None and now - last < rules.every_minutes * 60:
            return 0
        self._last[camera_id] = now
        image = None
        if rules.picture:
            try:
                jpeg = await self.still(camera_id)
            except Exception as e:  # no picture is no reason to stay silent
                log.info("%s: no picture for the notification: %s", camera_id, e)
                jpeg = None
            if jpeg:
                image = f"/api/notifications/pictures/{self.keep_picture(jpeg)}.jpg"
        label = LABELS[kind].name if kind in LABELS else kind.capitalize()
        names = {"camera": "camera", "norn": "Norn"}
        who = " + ".join(names.get(s, s) for s in sorted(sources))
        payload = {
            "title": f"{label} · {camera_name}",
            "body": f"Seen by {who} at {datetime.now():%H:%M}" if who else f"At {datetime.now():%H:%M}",
            "tag": f"norn-{camera_id}",  # a new one on the same camera replaces the last
            "url": f"/cameras/{camera_id}",
            "image": image,
            "time": int(time.time() * 1000),
        }
        return await self.send(devices, payload)

    async def test(self, devices: list[Device]) -> int:
        payload = {
            "title": "Norn",
            "body": "Notifications work on this device.",
            "tag": "norn-test",
            "url": "/settings?tab=notifications",
            "image": None,
            "time": int(time.time() * 1000),
        }
        return await self.send(devices, payload)

    async def send(self, devices: list[Device], payload: dict[str, Any]) -> int:
        """Send to each device at once. Devices the push service no longer knows (unsubscribed,
        the app removed) are forgotten. How many got it."""
        data = json.dumps(payload)

        async def one(device: Device) -> bool:
            try:
                status = await self._sender(device, data)
            except Exception as e:
                log.warning("notification to %s failed: %s", device.name, e)
                return False
            if status in (404, 410):
                log.info("%s no longer gets notifications: forgotten", device.name)
                self.store.devices.pop(device.id, None)
                return False
            if status >= 400:
                log.warning("notification to %s: the push service answered %s", device.name, status)
                return False
            device.last_used = time.time()
            return True

        sent = sum(await asyncio.gather(*(one(d) for d in devices)))
        self.store.save()  # last_used, and the devices forgotten
        return sent

    async def _webpush(self, device: Device, data: str) -> int:
        from pywebpush import WebPushException, webpush

        def post() -> int:
            try:
                response = webpush(
                    subscription_info={"endpoint": device.endpoint, "keys": device.keys},
                    data=data,
                    vapid_private_key=self.vapid,
                    vapid_claims={"sub": CLAIMS_SUB},
                    ttl=TTL,
                    timeout=10,
                    headers={"Urgency": "high"},
                )
            except WebPushException as e:
                if e.response is not None:
                    return e.response.status_code
                raise
            return response.status_code  # type: ignore[union-attr]

        return await asyncio.to_thread(post)
