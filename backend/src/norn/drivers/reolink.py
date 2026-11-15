"""Reolink cameras, through Reolink's own Baichuan protocol (port 9000) and RTSP.

Baichuan is the binary protocol of Reolink's apps. It is always on, unlike the camera's HTTP API,
which newer firmware turns off by default. The driver uses reolink_aio (the library behind Home
Assistant's Reolink integration) in Baichuan-only mode: in that mode it never opens or closes
ports on the camera, unlike its default mode, which turns HTTPS on by itself.

Over Baichuan: device info, PTZ and presets, IR lights, status LED, day/night, auto-tracking,
motion sensitivity, siren, privacy mode, and firmware: the check asks Reolink's download center
for the camera's hardware version; the update downloads that file from Reolink and uploads it to
the camera, which checks the package itself before installing it.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import zipfile
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import Field
from reolink_aio.api import Host
from reolink_aio.baichuan.util import PortType
from reolink_aio.exceptions import ReolinkError

from . import register
from .base import (
    Capability,
    Control,
    DeviceInfo,
    Driver,
    DriverError,
    DriverOptions,
    NotSupportedError,
    Option,
    Preset,
    PtzCommand,
    Stream,
)

log = logging.getLogger("norn.reolink")

CHANNEL = 0  # a camera is channel 0; an NVR's cameras would be 0..n
DIRECTIONS = {
    (0, 1): "Up",
    (0, -1): "Down",
    (-1, 0): "Left",
    (1, 0): "Right",
    (-1, 1): "LeftUp",
    (1, 1): "RightUp",
    (-1, -1): "LeftDown",
    (1, -1): "RightDown",
}
DAY_NIGHT = {"Auto": "Auto", "Color": "Colour", "Black&White": "Black and white"}
# Reolink's HTTP API refuses passwords with other characters; Baichuan doesn't mind.
HTTP_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@$*~_-+=!?.,:;'()[]")


class _QuietPasswordWarning(logging.Filter):
    """reolink_aio warns about such passwords on every login; Norn says it once, in the notes."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "incompatible special character" not in record.getMessage()


logging.getLogger("reolink_aio.api").addFilter(_QuietPasswordWarning())


class ReolinkOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name")
    username: str = Field("admin", title="Username")
    password: str = Field(title="Password")
    rtsp_port: int = Field(554, title="RTSP port", ge=1, le=65535)
    baichuan_port: int = Field(
        9000, title="Baichuan port", ge=1, le=65535, description="Reolink's app protocol"
    )


def _sign(x: float, dead: float = 0.2) -> int:
    return 0 if abs(x) < dead else (1 if x > 0 else -1)


@register
class ReolinkDriver(Driver):
    name = "reolink"
    label = "Reolink"
    description = "Reolink cameras over Reolink's app protocol: video, pan/tilt, lights, siren, firmware."
    Options = ReolinkOptions
    options: ReolinkOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._api: Host | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._latest: Any = None  # the NewSoftwareVersion of the last firmware check

    @property
    def api(self) -> Host:
        # Created on first use: reolink_aio opens an aiohttp session, which needs a running loop.
        if self._api is None:
            o = self.options
            self._api = Host(
                o.host, o.username, o.password, bc_port=o.baichuan_port, bc_only=True, timeout=15
            )
        return self._api

    async def _connect(self) -> None:
        if self._connected:
            return
        try:
            await self.api.get_host_data()
        except ReolinkError as e:
            raise DriverError(str(e)) from e
        self._connected = True

    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a reolink_aio call, reconnecting once if the session dropped."""
        async with self._lock:
            for attempt in (1, 2):
                try:
                    await self._connect()
                    return await fn(*args, **kwargs)
                except DriverError:
                    raise
                except ReolinkError as e:
                    self._connected = False
                    if attempt == 2:
                        raise DriverError(str(e)) from e

    async def start(self) -> None:
        try:
            await self._call(self.api.get_states)
        except DriverError as e:
            log.warning("%s: %s", self.camera_id, e)

    async def stop(self) -> None:
        if self._api is not None:
            with contextlib.suppress(ReolinkError, OSError):
                await self._api.logout()

    def streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        base = f"rtsp://{auth}{o.host}:{o.rtsp_port}/h264Preview_01_"
        return [
            Stream(id="main", label="Main", source=f"{base}main", codec="h264"),
            Stream(id="sub", label="Sub", source=f"{base}sub", codec="h264"),
        ]

    def _supported(self, feature: str, channel: int | None = CHANNEL) -> bool:
        try:
            return bool(self._connected and self.api.supported(channel, feature))
        except (ReolinkError, KeyError):
            return False

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS, Capability.FIRMWARE_ONLINE}
        if not self._connected or self._supported("pan_tilt"):
            caps |= {Capability.PTZ, Capability.PRESETS}
        return caps

    async def info(self) -> DeviceInfo:
        try:
            await self._call(self.api.get_states)
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        a = self.api
        details: dict[str, str] = {}
        if (signal := a.wifi_signal(None)) is not None:
            details["Wi-Fi signal"] = f"{signal} dBm"
        if (state := a.daynight_state(CHANNEL)) is not None:
            details["Day/night"] = DAY_NIGHT.get(state, state)
        notes = []
        if not set(self.options.password) <= HTTP_SAFE:
            notes.append(
                "The password has characters Reolink's HTTP API refuses (like #). Norn uses Reolink's "
                "app protocol, which accepts it; other tools using the HTTP API may fail."
            )
        return DeviceInfo(
            manufacturer="Reolink",
            model=a.model,
            firmware=a.sw_version,
            hardware=a.hardware_version,
            serial=getattr(a, "uid", None) or None,
            mac=a.mac_address,
            name=a.camera_name(None),
            details=details,
            notes=notes,
        )

    async def controls(self) -> list[Control]:
        try:
            await self._call(self.api.get_states)
        except DriverError:
            return []
        a, ch = self.api, CHANNEL
        controls: list[Control] = []
        if (state := a.daynight_state(ch)) is not None:
            controls.append(
                Control(
                    id="daynight",
                    label="Day/night",
                    kind="select",
                    group="Image",
                    icon="moon",
                    value=state,
                    options=[Option(value=k, label=v) for k, v in DAY_NIGHT.items()],
                )
            )
        if self._supported("ir_lights"):
            controls.append(
                Control(
                    id="ir",
                    label="Infrared lights",
                    kind="toggle",
                    group="Light",
                    icon="moon",
                    value=a.ir_enabled(ch),
                )
            )
        if self._supported("floodLight"):
            controls.append(
                Control(
                    id="spotlight",
                    label="Spotlight",
                    kind="toggle",
                    group="Light",
                    icon="lamp",
                    value=a.whiteled_state(ch),
                )
            )
        if self._supported("status_led"):
            controls.append(
                Control(
                    id="led",
                    label="Status light",
                    kind="toggle",
                    group="Light",
                    value=a.status_led_enabled(ch),
                )
            )
        if self._supported("auto_track"):
            controls.append(
                Control(
                    id="autotrack",
                    label="Follow people",
                    kind="toggle",
                    group="Pan and tilt",
                    icon="activity",
                    value=a.auto_track_enabled(ch),
                )
            )
        if self._supported("md_sensitivity"):
            controls.append(
                Control(
                    id="sensitivity",
                    label="Motion sensitivity",
                    kind="range",
                    group="Alarm",
                    icon="activity",
                    value=a.md_sensitivity(ch),
                    min=1,
                    max=50,
                    step=1,
                )
            )
        if self._supported("siren_play"):
            controls.append(Control(id="siren", label="Siren", kind="button", group="Alarm", icon="siren"))
        try:
            ports = await self._call(self.api.baichuan.get_ports)
        except DriverError:
            ports = {}
        for key, label in (("http", "HTTP API"), ("https", "HTTPS API")):
            if key in ports:
                controls.append(
                    Control(
                        id=key,
                        label=label,
                        kind="toggle",
                        group="Network",
                        value=bool(ports[key].get("enable")),
                    )
                )
        if self._supported("privacy_mode", None):
            controls.append(
                Control(
                    id="privacy",
                    label="Privacy mode",
                    kind="toggle",
                    group="General",
                    icon="eye-off",
                    value=a.baichuan.privacy_mode(),
                )
            )
        return controls

    async def set_control(self, control_id: str, value: Any) -> None:
        a, ch = self.api, CHANNEL
        setters = {
            "daynight": lambda: a.set_daynight(ch, str(value)),
            "ir": lambda: a.set_ir_lights(ch, bool(value)),
            "spotlight": lambda: a.set_whiteled(ch, state=bool(value)),
            "led": lambda: a.set_status_led(ch, bool(value)),
            "autotrack": lambda: a.set_auto_tracking(ch, bool(value)),
            "sensitivity": lambda: a.set_md_sensitivity(ch, max(1, min(50, int(value)))),
            "siren": lambda: a.set_siren(ch, True, 2),
            "privacy": lambda: a.baichuan.set_privacy_mode(enable=bool(value)),
            # Older firmware stores these but runs no web server; newer firmware serves the API.
            "http": lambda: a.baichuan.set_port_enabled(PortType.http, bool(value)),
            "https": lambda: a.baichuan.set_port_enabled(PortType.https, bool(value)),
        }
        if control_id not in setters:
            raise NotSupportedError(f"no control {control_id!r}")
        if control_id == "daynight" and value not in DAY_NIGHT:
            raise ValueError(f"{value!r} is not one of {', '.join(DAY_NIGHT)}")

        async def run() -> None:
            await setters[control_id]()

        await self._call(run)
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        try:
            await self._call(self.api.get_states)
        except DriverError:
            return []
        found = self.api.ptz_presets(CHANNEL) if self._supported("ptz_presets") else {}
        return [Preset(id=str(number), name=name) for name, number in found.items()]

    async def ptz(self, command: PtzCommand) -> None:
        a, ch = self.api, CHANNEL
        if command.action == "stop":
            op: dict[str, Any] = {"command": "Stop"}
        elif command.action == "goto":
            if not command.preset or not command.preset.isdigit():
                raise ValueError(f"unknown preset {command.preset!r}")
            op = {"preset": int(command.preset)}
        elif command.action == "home":
            if not self._supported("ptz_guard"):
                raise NotSupportedError("this camera has no home position; save a preset instead")

            async def home() -> None:
                await a.set_ptz_guard(ch, command="toPos")

            await self._call(home)
            return
        elif command.zoom and not (command.pan or command.tilt):
            op = {"command": "ZoomInc" if command.zoom > 0 else "ZoomDec"}
        else:
            key = (_sign(command.pan), _sign(command.tilt))
            if key == (0, 0):
                raise ValueError("no direction")
            op = {"command": DIRECTIONS[key]}

        async def send() -> None:
            await a.set_ptz_command(ch, **op)

        await self._call(send)

    # Firmware
    async def firmware_online_check(self) -> str | None:
        result = await self._call(self.api.check_new_firmware)
        latest = result.get(None)
        if not latest or isinstance(latest, str) or not getattr(latest, "download_url", None):
            self._latest = None
            return None
        self._latest = latest
        return str(latest.version_string)

    async def firmware_online_update(self) -> None:
        """Download the firmware the check found from Reolink and install it over Baichuan."""
        if self._latest is None and not await self.firmware_online_check():
            raise DriverError("no newer firmware is available")
        url = self._latest.download_url
        if not url.startswith(
            ("https://home-cdn.reolink.us/", "https://reolink.com/", "https://cdn.reolink.com/")
        ):
            raise DriverError(f"refusing firmware from an unexpected address: {url}")
        log.warning("%s: downloading firmware %s", self.camera_id, self._latest.version_string)
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            response = await client.get(url)
        if response.status_code != 200:
            raise DriverError(f"download failed: HTTP {response.status_code}")
        package, file_name = None, None
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for entry in archive.infolist():
                if entry.filename.endswith((".pak", ".paks")):
                    package, file_name = archive.read(entry), entry.filename.rsplit("/", 1)[-1]
                    break
        if package is None or file_name is None:
            raise DriverError("the download has no firmware package (.pak)")
        log.warning(
            "%s: uploading %s (%d bytes); the camera restarts", self.camera_id, file_name, len(package)
        )

        async def upload() -> None:
            await self.api.baichuan.upload_firmware(package, file_name)

        await self._call(upload)
        self._connected = False  # the camera restarts
        self._latest = None
