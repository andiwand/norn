"""Foscam HD cameras (most Foscam models since about 2014), through CGIProxy.fcgi and RTSP.

Every call is GET /cgi-bin/CGIProxy.fcgi?cmd=<command>&usr=<user>&pwd=<password>; the answer is
XML: <CGI_Result><result>0</result><productName>...</productName>...</CGI_Result>. Result codes:
0 ok, -1 bad request, -2 wrong user or password, -3 no access.

    getDevInfo                       productName, firmwareVer, hardwareVer, serialNo, mac, devName
    getInfraLedConfig / setInfraLedConfig&mode=0|1   (0 auto, 1 manual)
    openInfraLed / closeInfraLed     manual IR on and off
    getMirrorAndFlipSetting, mirrorVideo&isMirror=1, flipVideo&isFlip=1
    ptzMoveUp|Down|Left|Right|TopLeft|TopRight|BottomLeft|BottomRight, ptzStopRun, ptzReset
    zoomIn, zoomOut, zoomStop
    getPTZPresetPointList            cnt=2, point0=Gate, point1=...;  ptzGotoPresetPoint&name=
    rtsp://<host>:88/videoMain and /videoSub (the RTSP port is the HTTP port, 88 by default)

Tested against the documented API, not yet against a real camera.
"""

from __future__ import annotations

import contextlib
import re
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
    NotSupportedError,
    Option,
    Preset,
    PtzCommand,
    Stream,
)

MOVES = {
    (0, 1): "ptzMoveUp",
    (0, -1): "ptzMoveDown",
    (-1, 0): "ptzMoveLeft",
    (1, 0): "ptzMoveRight",
    (-1, 1): "ptzMoveTopLeft",
    (1, 1): "ptzMoveTopRight",
    (-1, -1): "ptzMoveBottomLeft",
    (1, -1): "ptzMoveBottomRight",
}
ERRORS = {"-1": "bad request", "-2": "wrong username or password", "-3": "no access", "-4": "failed"}


def parse_result(xml: str) -> dict[str, str]:
    return dict(re.findall(r"<(\w+)>([^<]*)</\1>", xml))


def _sign(x: float, dead: float = 0.2) -> int:
    return 0 if abs(x) < dead else (1 if x > 0 else -1)


class FoscamHdOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name")
    port: int = Field(88, title="Port", ge=1, le=65535, description="HTTP and RTSP; 88 by default")
    username: str = Field("admin", title="Username")
    password: str = Field(title="Password")


@register
class FoscamHdDriver(Driver):
    name = "foscam-hd"
    label = "Foscam HD"
    description = "Foscam cameras since about 2014 (CGIProxy): video, pan/tilt/zoom, presets, IR, flip."
    Options = FoscamHdOptions
    options: FoscamHdOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self.client = httpx.AsyncClient(base_url=f"http://{o.host}:{o.port}/cgi-bin/", timeout=8)
        self.has_ptz = True  # most Foscam HD cameras pan and tilt; a fixed one answers ptz calls with -1

    async def stop(self) -> None:
        await self.client.aclose()

    def web_url(self) -> str | None:
        return f"http://{self.options.host}:{self.options.port}/"

    def streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        return [
            Stream(id="main", label="Main", source=f"rtsp://{auth}{o.host}:{o.port}/videoMain", codec="h264"),
            Stream(id="sub", label="Sub", source=f"rtsp://{auth}{o.host}:{o.port}/videoSub", codec="h264"),
        ]

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS}
        if self.has_ptz:
            caps |= {Capability.PTZ, Capability.PRESETS, Capability.PRESET_SAVE}
        return caps

    async def save_preset(self, slot: str, name: str) -> None:
        """Foscam presets are named: the slot is the name."""
        await self._cmd("ptzAddPresetPoint", name=slot or name)

    async def _cmd(self, cmd: str, **params: Any) -> dict[str, str]:
        o = self.options
        try:
            response = await self.client.get(
                "CGIProxy.fcgi", params={"cmd": cmd, "usr": o.username, "pwd": o.password, **params}
            )
        except httpx.HTTPError as e:
            raise DriverError(f"{o.host}: {e}") from e
        result = parse_result(response.text)
        code = result.get("result")
        if response.status_code >= 400 or code is None:
            raise DriverError(f"{cmd}: HTTP {response.status_code}")
        if code != "0":
            raise DriverError(f"{cmd}: {ERRORS.get(code, 'error ' + code)}")
        return result

    async def info(self) -> DeviceInfo:
        try:
            dev = await self._cmd("getDevInfo")
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        mac = dev.get("mac", "")
        return DeviceInfo(
            manufacturer="Foscam",
            model=dev.get("productName"),
            firmware=dev.get("firmwareVer"),
            hardware=dev.get("hardwareVer"),
            serial=dev.get("serialNo"),
            mac=":".join(mac[i : i + 2] for i in range(0, 12, 2)).lower() if len(mac) == 12 else mac or None,
            name=dev.get("devName"),
        )

    async def controls(self) -> list[Control]:
        controls = []
        try:
            led = await self._cmd("getInfraLedConfig")
            controls.append(
                Control(
                    id="irmode",
                    label="Infrared",
                    kind="select",
                    group="Light",
                    icon="moon",
                    value=led.get("mode"),
                    options=[Option(value="0", label="Auto"), Option(value="1", label="Manual")],
                )
            )
            controls.append(
                Control(id="ir", label="Infrared on (manual)", kind="toggle", group="Light", value=None)
            )
        except DriverError:
            pass
        try:
            mf = await self._cmd("getMirrorAndFlipSetting")
            controls.append(
                Control(
                    id="mirror", label="Mirror", kind="toggle", group="Image", value=mf.get("isMirror") == "1"
                )
            )
            controls.append(
                Control(id="flip", label="Flip", kind="toggle", group="Image", value=mf.get("isFlip") == "1")
            )
        except DriverError:
            pass
        return controls

    async def set_control(self, control_id: str, value: Any) -> None:
        if control_id == "irmode":
            await self._cmd("setInfraLedConfig", mode=int(value))
        elif control_id == "ir":
            await self._cmd("openInfraLed" if value else "closeInfraLed")
        elif control_id == "mirror":
            await self._cmd("mirrorVideo", isMirror=1 if value else 0)
        elif control_id == "flip":
            await self._cmd("flipVideo", isFlip=1 if value else 0)
        else:
            raise NotSupportedError(f"no control {control_id!r}")
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        try:
            result = await self._cmd("getPTZPresetPointList")
        except DriverError:
            return []
        count = int(result.get("cnt", "0") or 0)
        names = [result.get(f"point{i}", "") for i in range(count)]
        return [Preset(id=n, name=n) for n in names if n]

    async def ptz(self, command: PtzCommand) -> None:
        if command.action == "stop":
            await self._cmd("ptzStopRun")
            with contextlib.suppress(DriverError):  # cameras without zoom
                await self._cmd("zoomStop")
        elif command.action == "home":
            await self._cmd("ptzReset")
        elif command.action == "goto":
            if not command.preset:
                raise ValueError("which preset?")
            await self._cmd("ptzGotoPresetPoint", name=command.preset)
        elif command.zoom and not (command.pan or command.tilt):
            await self._cmd("zoomIn" if command.zoom > 0 else "zoomOut")
        else:
            key = (_sign(command.pan), _sign(command.tilt))
            if key == (0, 0):
                raise ValueError("no direction")
            await self._cmd(MOVES[key])
