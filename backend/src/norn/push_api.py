"""The API for notifications (web push): Norn's public key, the devices, a test, the pictures.

The rules are a settings section (`notifications`, PUT /api/settings). Who may do what, with
sign-in: everyone signed in subscribes their own devices, renames, removes and tests them;
other people's devices (and the rules) are for admins.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import device_name
from .auth_api import who_of
from .hub import Hub
from .notify import Device

# --- Who asks (auth_api's middleware put it on the request). Without sign-in everyone is an
# admin without a name.


def current_user(request: Request) -> str | None:
    """The signed-in user's name; None without sign-in."""
    who = who_of(request)
    return who.name if who else None


def is_admin(request: Request) -> bool:
    """Whether the user may change the rules and other people's devices."""
    who = who_of(request)
    return who is None or who.role == "admin"


# ---


class Subscription(BaseModel):
    """What a browser's PushManager.subscribe() gives (its toJSON()), and a name for it."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(max_length=2000)
    keys: dict[str, str]
    name: str | None = Field(None, max_length=60)


class DeviceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=60)
    enabled: bool | None = None
    # Only these cameras on this device; null: as the rules say.
    cameras: list[str] | None = None


# The browsers' push services: a subscription must name one of these, so Norn never posts to
# an address in the house (or anywhere else a subscription might name).
PUSH_SERVICES = (
    "fcm.googleapis.com",  # Chrome, Edge, Samsung Internet, Opera (Android and desktop)
    ".push.services.mozilla.com",  # Firefox
    ".push.apple.com",  # Safari: macOS, and iOS from the installed app
    ".notify.windows.com",  # Edge on Windows (WNS)
)


def push_endpoint(url: str) -> str:
    """A push service's address: https, at one of the browsers' push services."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    known = any(host == s or (s.startswith(".") and host.endswith(s)) for s in PUSH_SERVICES)
    if parts.scheme != "https" or not known or parts.port not in (None, 443):
        raise HTTPException(422, "not a push service's address")
    return url


def push_keys(keys: dict[str, str]) -> dict[str, str]:
    """The browser's keys, checked: a P-256 public key (65 bytes, uncompressed) and a 16-byte
    secret, in base64url. Bad ones would only fail later, at the first notification."""
    try:
        p256dh = base64.urlsafe_b64decode(keys["p256dh"] + "==")
        auth = base64.urlsafe_b64decode(keys["auth"] + "==")
    except (KeyError, ValueError) as e:
        raise HTTPException(422, "the subscription's keys are missing or not base64url") from e
    if len(p256dh) != 65 or p256dh[0] != 4 or len(auth) < 16:
        raise HTTPException(422, "the subscription's keys are not a browser's push keys")
    return {"p256dh": keys["p256dh"], "auth": keys["auth"]}


def push_routes(api: APIRouter, hub: Hub) -> None:
    notifier = hub.notifier

    def visible(user: str | None, admin: bool) -> list[Device]:
        devices = list(notifier.store.devices.values())
        return devices if admin else [d for d in devices if d.user == user]

    def device_for(device_id: str, user: str | None, admin: bool) -> Device:
        device = notifier.store.devices.get(device_id)
        if device is None or device not in visible(user, admin):
            raise HTTPException(404, "no such device")
        return device

    @api.get("/notifications")
    async def notifications(
        user: str | None = Depends(current_user), admin: bool = Depends(is_admin)
    ) -> dict[str, Any]:
        """The key browsers subscribe with, and the devices (one's own; an admin's: all)."""
        return {
            "public_key": notifier.public_key,
            "devices": [d.public() for d in visible(user, admin)],
        }

    @api.post("/notifications/devices", status_code=201)
    async def subscribe(
        body: Subscription, request: Request, user: str | None = Depends(current_user)
    ) -> dict[str, Any]:
        keys = push_keys(body.keys)
        name = (body.name or "").strip() or device_name(request.headers.get("user-agent", ""))
        return notifier.store.add(push_endpoint(body.endpoint), keys, name, user).public()

    @api.patch("/notifications/devices/{device_id}")
    async def change_device(
        device_id: str,
        body: DeviceChange,
        user: str | None = Depends(current_user),
        admin: bool = Depends(is_admin),
    ) -> dict[str, Any]:
        device = device_for(device_id, user, admin)
        changes = body.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] is not None:
            device.name = changes["name"].strip()
        if changes.get("enabled") is not None:
            device.enabled = changes["enabled"]
        if "cameras" in changes:
            device.cameras = changes["cameras"]
        notifier.store.save()
        return device.public()

    @api.delete("/notifications/devices/{device_id}", status_code=204)
    async def remove_device(
        device_id: str, user: str | None = Depends(current_user), admin: bool = Depends(is_admin)
    ) -> Response:
        notifier.store.remove(device_for(device_id, user, admin).id)
        return Response(status_code=204)

    @api.post("/notifications/devices/{device_id}/test")
    async def test_device(
        device_id: str, user: str | None = Depends(current_user), admin: bool = Depends(is_admin)
    ) -> dict[str, Any]:
        device = device_for(device_id, user, admin)
        sent = await notifier.test([device])
        if not sent:
            gone = device_id not in notifier.store.devices
            raise HTTPException(
                410 if gone else 502,
                "the browser's push service no longer knows this device: turn notifications on again"
                if gone
                else "it couldn't be sent (Norn's log says why)",
            )
        return {"sent": sent}

    @api.get("/notifications/pictures/{token}.jpg", include_in_schema=False)
    async def picture(token: str) -> Response:
        """A notification's picture. The token is the access: a phone fetches it without a
        session. Gone after an hour."""
        jpeg = notifier.picture(token)
        if jpeg is None:
            raise HTTPException(404, "gone")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
