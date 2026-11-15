"""UniFi Protect cameras, through the console's public Integration API.

Create an API key in UniFi (Settings > Control Plane > Integrations) and give Norn the console's
address, the key, and the camera's name (or its id).

    GET  /proxy/protect/integration/v1/cameras                     list (id, name, state, ...)
    GET  /proxy/protect/integration/v1/cameras/{id}                one camera
    PATCH /proxy/protect/integration/v1/cameras/{id}               settings, like ledSettings
    GET|POST /proxy/protect/integration/v1/cameras/{id}/rtsps-stream   {"qualities": ["high", "low"]}
    POST /proxy/protect/integration/v1/cameras/{id}/ptz/goto/{slot}    slot -1: home

Video: the RTSPS URLs Protect hands out, read by go2rtc as rtspx:// (TLS without certificate
checks; consoles use self-signed certificates). Protect itself manages the cameras' firmware.

Written against the documented Integration API, not yet tested against a real console.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field

from . import register
from .base import (
    Capability,
    Control,
    DeviceInfo,
    Driver,
    DriverError,
    DriverOptions,
    NotSupportedError,
    Preset,
    PtzCommand,
    Stream,
)

API = "/proxy/protect/integration/v1"


def go2rtc_url(url: str) -> str:
    """rtsps://host:7441/token?enableSrtp -> rtspx://host:7441/token (go2rtc's TLS without checks)."""
    base = url.split("?", 1)[0]
    return "rtspx://" + base.removeprefix("rtsps://") if base.startswith("rtsps://") else base


class UnifiOptions(DriverOptions):
    host: str = Field(title="Console address", description="The UniFi console, like 192.168.1.1")
    api_key: str = Field(title="API key", description="UniFi > Settings > Control Plane > Integrations")
    camera: str = Field(title="Camera", description="The camera's name in Protect, or its id")


@register
class UnifiDriver(Driver):
    name = "unifi"
    label = "UniFi Protect"
    description = "Cameras of a UniFi Protect console: video (RTSPS), status light, PTZ presets."
    Options = UnifiOptions
    options: UnifiOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self.client = httpx.AsyncClient(
            base_url=f"https://{o.host}{API}",
            headers={"X-API-KEY": o.api_key, "Accept": "application/json"},
            verify=False,  # consoles use self-signed certificates
            timeout=10,
        )
        self.camera_id: str | None = None
        self.urls: dict[str, str] = {}
        self.data: dict[str, Any] = {}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise DriverError(f"{self.options.host}: {e}") from e
        if response.status_code in (401, 403):
            raise DriverError("the API key was refused")
        if response.status_code >= 400:
            raise DriverError(f"{path}: HTTP {response.status_code} {response.text[:80]}")
        return response.json() if response.content else None

    async def _find(self) -> str:
        if self.camera_id:
            return self.camera_id
        cameras = await self._request("GET", "/cameras")
        wanted = self.options.camera.strip().lower()
        for camera in cameras or []:
            if wanted in (str(camera.get("id", "")).lower(), str(camera.get("name", "")).lower()):
                self.camera_id = camera["id"]
                return self.camera_id
        names = ", ".join(str(c.get("name")) for c in cameras or [])
        raise DriverError(f"no camera {self.options.camera!r} in Protect (there are: {names})")

    async def start(self) -> None:
        try:
            cid = await self._find()
            urls = await self._request("GET", f"/cameras/{cid}/rtsps-stream") or {}
            if not any(urls.get(q) for q in ("high", "low")):
                urls = await self._request(
                    "POST", f"/cameras/{cid}/rtsps-stream", json={"qualities": ["high", "low"]}
                )
            self.urls = {q: go2rtc_url(u) for q, u in (urls or {}).items() if isinstance(u, str) and u}
        except DriverError as e:
            self.urls = {}
            self.data = {"error": str(e)}

    async def stop(self) -> None:
        await self.client.aclose()

    def streams(self) -> list[Stream]:
        streams = []
        if url := self.urls.get("high"):
            streams.append(Stream(id="main", label="Main", source=url, codec="h264"))
        if url := self.urls.get("low"):
            streams.append(Stream(id="sub", label="Sub", source=url, codec="h264"))
        return streams

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS}
        if self.data.get("featureFlags", {}).get("isPtz"):
            caps |= {Capability.PTZ, Capability.PRESETS}
        return caps

    async def _load(self) -> dict[str, Any]:
        cid = await self._find()
        self.data = await self._request("GET", f"/cameras/{cid}") or {}
        return self.data

    async def info(self) -> DeviceInfo:
        try:
            data = await self._load()
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        state = data.get("state")
        if state and state != "CONNECTED":
            return DeviceInfo(online=False, error=f"Protect reports the camera as {state.lower()}")
        return DeviceInfo(
            manufacturer="Ubiquiti",
            model=data.get("marketName") or data.get("modelKey") or data.get("type"),
            firmware=data.get("firmwareVersion"),
            mac=data.get("mac"),
            name=data.get("name"),
            notes=["UniFi Protect keeps the camera's firmware up to date."],
        )

    async def controls(self) -> list[Control]:
        try:
            data = await self._load()
        except DriverError:
            return []
        controls = []
        if isinstance(data.get("ledSettings"), dict):
            controls.append(
                Control(
                    id="led",
                    label="Status light",
                    kind="toggle",
                    group="Light",
                    value=bool(data["ledSettings"].get("isEnabled")),
                )
            )
        if isinstance(data.get("micVolume"), int):
            controls.append(
                Control(
                    id="mic",
                    label="Microphone volume",
                    kind="range",
                    group="Audio",
                    icon="volume",
                    value=data["micVolume"],
                    min=0,
                    max=100,
                    step=1,
                )
            )
        return controls

    async def set_control(self, control_id: str, value: Any) -> None:
        cid = await self._find()
        if control_id == "led":
            body: dict[str, Any] = {"ledSettings": {"isEnabled": bool(value)}}
        elif control_id == "mic":
            body = {"micVolume": max(0, min(100, int(value)))}
        else:
            raise NotSupportedError(f"no control {control_id!r}")
        await self._request("PATCH", f"/cameras/{cid}", json=body)
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        if Capability.PRESETS not in self.capabilities():
            return []
        # The Integration API has no preset names; Protect's slots are numbered from 0.
        return [Preset(id=str(slot), name=f"Preset {slot + 1}") for slot in range(4)]

    async def ptz(self, command: PtzCommand) -> None:
        if Capability.PTZ not in self.capabilities():
            raise NotSupportedError("this camera can't pan or tilt")
        cid = await self._find()
        if command.action == "home":
            await self._request("POST", f"/cameras/{cid}/ptz/goto/-1")
        elif command.action == "goto":
            await self._request("POST", f"/cameras/{cid}/ptz/goto/{int(command.preset or 0)}")
        elif command.action == "stop":
            return
        else:
            raise NotSupportedError("Protect's API moves PTZ cameras to presets only")
