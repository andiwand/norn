"""Cameras with the Foscam-style CGI interface.

Many cheap pan/tilt cameras from about 2010 to 2016 share it (ReeCam firmware): Foscam
FI8918W and its clones, supra IPC-1A and IPC-100HD, early INSTAR and Wansview models. They have
no RTSP; video is MJPEG over HTTP (`videostream.cgi`). go2rtc reads it as it is; the player
shows MJPEG frames and the recorder encodes to H.264 (cheap at 640x480).

    get_status.cgi         id, firmware (sys_ver), web UI (app_ver), alias. Readable WITHOUT login
                           on most of these cameras.
    get_camera_params.cgi  resolution, brightness, contrast, mode (mains frequency), flip
    camera_control.cgi     ?param=<n>&value=<v>: 0 resolution, 1 brightness, 2 contrast,
                           3 mode, 5 flip
    decoder_control.cgi    ?command=<n>: 0 up, 2 down, 4 left, 6 right, 90-93 diagonals, 1 stop,
                           25 center, 30+2n set preset n, 31+2n go to preset n

Never call get_params.cgi: on old firmware it returns every password and the Wi-Fi key.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

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
    Event,
    NotSupportedError,
    Option,
    Preset,
    PtzCommand,
    Stream,
)

VARS = re.compile(r"""var\s+(\w+)\s*=\s*(?:'([^']*)'|"([^"]*)"|([^;]*));""")

RESOLUTIONS = {8: "320×240", 32: "640×480", 96: "1280×720"}
FLIP = {0: "Normal", 1: "Flipped", 2: "Mirrored", 3: "Flipped and mirrored"}
MODES = {0: "50 Hz", 1: "60 Hz", 2: "Outdoor"}
PRESETS = 4

# Pan/tilt directions -> decoder commands. Keys: (pan sign, tilt sign).
DIRECTIONS = {
    (0, 1): 0,
    (0, -1): 2,
    (-1, 0): 4,
    (1, 0): 6,
    (-1, 1): 90,
    (1, 1): 91,
    (-1, -1): 92,
    (1, -1): 93,
}


def parse_vars(text: str) -> dict[str, str]:
    """The `var name=value;` lines these CGIs answer with."""
    return {m[1]: next(g for g in m.groups()[1:] if g is not None).strip() for m in VARS.finditer(text)}


class FoscamOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name, like 192.168.1.20")
    port: int = Field(80, title="HTTP port", ge=1, le=65535)
    username: str = Field("admin", title="Username")
    password: str = Field("", title="Password")


@register
class FoscamDriver(Driver):
    name = "foscam"
    label = "Foscam-compatible camera"
    description = "Older pan/tilt cameras with the Foscam CGI interface: supra, early INSTAR, Wansview."
    Options = FoscamOptions
    options: FoscamOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self.base = f"http://{o.host}:{o.port}"
        self._client = httpx.AsyncClient(
            base_url=self.base, auth=httpx.BasicAuth(o.username, o.password), timeout=5
        )
        self._product: str | None = None
        self._app_ver: str | None = None

    async def stop(self) -> None:
        await self._client.aclose()

    def streams(self) -> list[Stream]:
        o = self.options
        # go2rtc reads the credentials from the URL; they must be percent-encoded (# in a password).
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        url = f"http://{auth}{o.host}:{o.port}/videostream.cgi"
        return [Stream(id="main", label="Main", source=url, codec="mjpeg")]

    def capabilities(self) -> set[Capability]:
        caps = {Capability.PTZ, Capability.PRESETS, Capability.CONTROLS, Capability.EVENTS}
        return super().capabilities() | caps

    def event_kinds(self) -> list[str]:
        return ["motion"]

    async def events(self) -> AsyncIterator[Event]:
        """The camera's motion alarm, polled from get_status.cgi every 2 s (it pushes nothing).
        It only fires while the camera's own motion alarm is armed."""
        active = False
        while True:
            status = parse_vars(await self._get("/get_status.cgi"))
            alarm = status.get("alarm_status") or status.get("status_alarm") or "0"
            now = alarm == "1"  # 1: motion; 2 would be the alarm input
            if now != active:
                active = now
                yield Event(kind="motion", active=active)
            await asyncio.sleep(2)

    async def _get(self, path: str, **params: Any) -> str:
        try:
            response = await self._client.get(path, params=params or None)
        except httpx.HTTPError as e:
            raise DriverError(f"{self.options.host}: {e}") from e
        if response.status_code == 401:
            raise DriverError("wrong username or password")
        if response.status_code >= 400:
            raise DriverError(f"{path}: HTTP {response.status_code}")
        return response.text

    async def info(self) -> DeviceInfo:
        try:
            status = parse_vars(await self._get("/get_status.cgi"))
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        if self._product is None:
            self._product = await self._branding()
        brand, _, product = (self._product or "").partition(" ")
        self._app_ver = status.get("app_ver")
        details = {"Web interface": status.get("app_ver", "?")}
        wifi = status.get("wifi_status") or status.get("status_network")
        if wifi is not None:
            details["Network"] = "connected" if wifi not in ("0", "") else "disconnected"
        if (alarm := status.get("alarm_status") or status.get("status_alarm")) is not None:
            details["Alarm"] = "triggered" if alarm == "1" else "idle"
        return DeviceInfo(
            manufacturer=brand or None,
            model=product or None,
            firmware=status.get("sys_ver"),
            mac=_mac(status.get("id")),
            name=status.get("alias"),
            details=details,
            notes=[
                "No RTSP: video is MJPEG over HTTP, so recordings are encoded to H.264.",
                "The camera's status page (get_status.cgi) can be read without a login.",
            ],
        )

    async def _branding(self) -> str | None:
        """'supra IPC-1A' from the web UI's branding file, which these firmwares ship."""
        for path in ("/branding/branding.js", "/branding.js"):
            try:
                text = await self._get(path)
            except DriverError:
                continue
            brand = re.search(r'brand\s*:\s*"([^"]+)"', text)
            product = re.search(r'product\s*:\s*"([^"]+)"', text)
            if brand or product:
                return f"{brand[1] if brand else ''} {product[1] if product else ''}".strip()
        return None

    @property
    def _new_ui(self) -> bool:
        # Web UI 3.x (HD models) uses 0-255 for contrast; 2.x uses 0-6.
        return bool(
            self._app_ver and self._app_ver.split(".")[0].isdigit() and int(self._app_ver.split(".")[0]) >= 3
        )

    async def controls(self) -> list[Control]:
        try:
            p = parse_vars(await self._get("/get_camera_params.cgi"))
        except DriverError:
            return []
        if self._app_ver is None:
            await self.info()
        resolutions = dict(RESOLUTIONS)
        if not self._new_ui:
            resolutions.pop(96)
        contrast_max = 255 if self._new_ui else 6
        return [
            Control(
                id="resolution",
                label="Resolution",
                kind="select",
                group="Image",
                value=p.get("resolution"),
                options=[Option(value=str(k), label=v) for k, v in resolutions.items()],
            ),
            Control(
                id="brightness",
                label="Brightness",
                kind="range",
                group="Image",
                icon="sun",
                value=int(p.get("brightness", 0)),
                min=0,
                max=255,
                step=1,
            ),
            Control(
                id="contrast",
                label="Contrast",
                kind="range",
                group="Image",
                value=int(p.get("contrast", 0)),
                min=0,
                max=contrast_max,
                step=1,
            ),
            Control(
                id="flip",
                label="Orientation",
                kind="select",
                group="Image",
                value=p.get("flip"),
                options=[Option(value=str(k), label=v) for k, v in FLIP.items()],
            ),
            Control(
                id="mode",
                label="Mains frequency",
                kind="select",
                group="Image",
                value=p.get("mode"),
                options=[Option(value=str(k), label=v) for k, v in MODES.items()],
            ),
        ]

    async def set_control(self, control_id: str, value: Any) -> None:
        params = {"resolution": 0, "brightness": 1, "contrast": 2, "mode": 3, "flip": 5}
        if control_id not in params:
            raise NotSupportedError(f"no control {control_id!r}")
        await self._get("/camera_control.cgi", param=params[control_id], value=int(value))
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        return [Preset(id=str(n), name=f"Preset {n}") for n in range(1, PRESETS + 1)]

    async def ptz(self, command: PtzCommand) -> None:
        if command.action == "stop":
            code = 1
        elif command.action == "home":
            code = 25
        elif command.action == "goto":
            if command.preset not in {str(n) for n in range(1, PRESETS + 1)}:
                raise ValueError(f"unknown preset {command.preset!r}")
            code = 29 + 2 * int(command.preset)
        else:
            key = (_sign(command.pan), _sign(command.tilt))
            if key == (0, 0):
                raise NotSupportedError("this camera can't zoom")
            code = DIRECTIONS[key]
        await self._get("/decoder_control.cgi", command=code)


def _sign(x: float, dead: float = 0.2) -> int:
    return 0 if abs(x) < dead else (1 if x > 0 else -1)


def _mac(device_id: str | None) -> str | None:
    if not device_id or not re.fullmatch(r"[0-9A-Fa-f]{12}", device_id):
        return None
    return ":".join(device_id[i : i + 2] for i in range(0, 12, 2)).lower()
