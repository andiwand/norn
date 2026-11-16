"""Dahua cameras and their many relabels (Amcrest, Lorex, IMOU local, ...): HTTP CGI and RTSP.

The CGI answers `key=value` lines (digest auth):

    /cgi-bin/magicBox.cgi?action=getDeviceType       type=IPC-HDW2431T-AS
    /cgi-bin/magicBox.cgi?action=getSoftwareVersion  version=2.800.0000000.25.R,build:2021-07-02
    /cgi-bin/magicBox.cgi?action=getSerialNo         sn=...
    /cgi-bin/magicBox.cgi?action=getVendor           vendor=Dahua (or Amcrest, Lorex)
    /cgi-bin/configManager.cgi?action=getConfig&name=VideoInOptions   table.VideoInOptions[0].Flip=false
    /cgi-bin/configManager.cgi?action=setConfig&VideoInOptions[0].Flip=true
    /cgi-bin/ptz.cgi?action=start&channel=1&code=Left&arg1=0&arg2=4&arg3=0   (stop: action=stop)
    rtsp://<host>:554/cam/realmonitor?channel=1&subtype=0   (1: substream)

Tested against the documented API, not yet against a real camera.
"""

from __future__ import annotations

import contextlib
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
DAY_NIGHT = {"0": "Colour", "1": "Auto", "2": "Black and white"}


def parse_table(text: str) -> dict[str, str]:
    """`table.X[0].Y=1` and `key=value` lines into a dict (keys without the `table.` prefix)."""
    result = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep:
            result[key.removeprefix("table.")] = value.strip()
    return result


def _sign(x: float, dead: float = 0.2) -> int:
    return 0 if abs(x) < dead else (1 if x > 0 else -1)


class DahuaOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name")
    username: str = Field("admin", title="Username")
    password: str = Field(title="Password")
    http_port: int = Field(80, title="HTTP port", ge=1, le=65535)
    rtsp_port: int = Field(554, title="RTSP port", ge=1, le=65535)
    channel: int = Field(1, title="Channel", ge=1, description="1 for a camera; the input of an NVR")


@register
class DahuaDriver(Driver):
    name = "dahua"
    label = "Dahua / Amcrest / Lorex"
    description = "Dahua cameras and relabels (Amcrest, Lorex): video, PTZ, day/night, motion detection."
    Options = DahuaOptions
    options: DahuaOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self.client = httpx.AsyncClient(
            base_url=f"http://{o.host}:{o.http_port}/cgi-bin/",
            auth=httpx.DigestAuth(o.username, o.password),
            timeout=8,
        )
        self.has_ptz = False

    async def start(self) -> None:
        try:
            await self._get("ptz.cgi", action="getStatus", channel=self.options.channel)
            self.has_ptz = True
        except DriverError:
            self.has_ptz = False

    async def stop(self) -> None:
        await self.client.aclose()

    def web_url(self) -> str | None:
        return f"http://{self.options.host}:{self.options.http_port}/"

    def streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        base = f"rtsp://{auth}{o.host}:{o.rtsp_port}/cam/realmonitor?channel={o.channel}&subtype="
        return [
            Stream(id="main", label="Main", source=f"{base}0"),
            Stream(id="sub", label="Sub", source=f"{base}1"),
        ]

    def extra_streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        base = f"rtsp://{auth}{o.host}:{o.rtsp_port}/cam/realmonitor?channel={o.channel}&subtype="
        return [Stream(id="third", label="Third", source=f"{base}2")]

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS}
        if self.has_ptz:
            caps |= {Capability.PTZ, Capability.PRESETS, Capability.PRESET_SAVE}
        return caps

    def preset_slots(self) -> list[str]:
        return [str(n) for n in range(1, 256)]

    async def save_preset(self, slot: str, name: str) -> None:
        channel = self.options.channel
        await self._get(
            "ptz.cgi", action="start", channel=channel, code="SetPreset", arg1=0, arg2=slot, arg3=0
        )
        # The name is a nicety; cameras without the call keep the number.
        with contextlib.suppress(DriverError):
            await self._get("ptz.cgi", action="setPresetName", channel=channel, arg1=slot, arg2=name)

    async def _get(self, path: str, **params: Any) -> str:
        try:
            response = await self.client.get(path, params=params)
        except httpx.HTTPError as e:
            raise DriverError(f"{self.options.host}: {e}") from e
        if response.status_code == 401:
            raise DriverError("wrong username or password")
        if response.status_code >= 400 or response.text.strip().startswith("Error"):
            raise DriverError(f"{path}: {response.text.strip()[:80] or response.status_code}")
        return response.text

    async def _config(self, name: str) -> dict[str, str]:
        return parse_table(await self._get("configManager.cgi", action="getConfig", name=name))

    async def _set(self, key: str, value: str) -> None:
        text = await self._get("configManager.cgi", **{"action": "setConfig", key: value})
        if "OK" not in text:
            raise DriverError(f"the camera didn't take {key}: {text.strip()[:80]}")

    async def info(self) -> DeviceInfo:
        try:
            values: dict[str, str] = {}
            for action in (
                "getDeviceType",
                "getSoftwareVersion",
                "getSerialNo",
                "getVendor",
                "getMachineName",
            ):
                try:
                    values |= parse_table(await self._get("magicBox.cgi", action=action))
                except DriverError:
                    if action == "getDeviceType":
                        raise
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        version = values.get("version", "")
        firmware, _, build = version.partition(",build:")
        return DeviceInfo(
            manufacturer=values.get("vendor") or "Dahua",
            model=values.get("type"),
            firmware=f"{firmware} ({build})" if build else firmware or None,
            serial=values.get("sn"),
            name=values.get("name"),
        )

    async def controls(self) -> list[Control]:
        ch = self.options.channel - 1
        controls = []
        try:
            video = await self._config("VideoInOptions")
        except DriverError:
            video = {}
        if (mode := video.get(f"VideoInOptions[{ch}].DayNightColor")) is not None:
            controls.append(
                Control(
                    id="daynight",
                    label="Day/night",
                    kind="select",
                    group="Image",
                    icon="moon",
                    value=mode,
                    options=[Option(value=k, label=v) for k, v in DAY_NIGHT.items()],
                )
            )
        if (flip := video.get(f"VideoInOptions[{ch}].Flip")) is not None:
            controls.append(
                Control(id="flip", label="Flip image", kind="toggle", group="Image", value=flip == "true")
            )
        if (brightness := video.get(f"VideoInOptions[{ch}].Brightness")) is not None:
            controls.append(
                Control(
                    id="brightness",
                    label="Brightness",
                    kind="range",
                    group="Image",
                    icon="sun",
                    value=int(brightness),
                    min=0,
                    max=100,
                    step=1,
                )
            )
        try:
            motion = await self._config("MotionDetect")
        except DriverError:
            motion = {}
        if (enabled := motion.get(f"MotionDetect[{ch}].Enable")) is not None:
            controls.append(
                Control(
                    id="motion",
                    label="Motion detection",
                    kind="toggle",
                    group="Alarm",
                    icon="activity",
                    value=enabled == "true",
                )
            )
        return controls

    async def set_control(self, control_id: str, value: Any) -> None:
        ch = self.options.channel - 1
        if control_id == "daynight":
            if str(value) not in DAY_NIGHT:
                raise ValueError(f"{value!r} is not one of {', '.join(DAY_NIGHT)}")
            await self._set(f"VideoInOptions[{ch}].DayNightColor", str(value))
        elif control_id == "flip":
            await self._set(f"VideoInOptions[{ch}].Flip", "true" if value else "false")
        elif control_id == "brightness":
            await self._set(f"VideoInOptions[{ch}].Brightness", str(max(0, min(100, int(value)))))
        elif control_id == "motion":
            await self._set(f"MotionDetect[{ch}].Enable", "true" if value else "false")
        else:
            raise NotSupportedError(f"no control {control_id!r}")
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        if not self.has_ptz:
            return []
        try:
            table = parse_table(await self._get("ptz.cgi", action="getPresets", channel=self.options.channel))
        except DriverError:
            return []
        found = {}
        for key, value in table.items():
            # presets[0].Index=1, presets[0].Name=Gate
            prefix, _, field = key.partition(".")
            found.setdefault(prefix, {})[field] = value
        return [
            Preset(id=p["Index"], name=p.get("Name") or f"Preset {p['Index']}")
            for p in found.values()
            if "Index" in p
        ]

    async def ptz(self, command: PtzCommand) -> None:
        if not self.has_ptz:
            raise NotSupportedError("this camera can't pan or tilt")
        channel = self.options.channel
        if command.action == "goto":
            if not command.preset:
                raise ValueError("which preset?")
            await self._get(
                "ptz.cgi",
                action="start",
                channel=channel,
                code="GotoPreset",
                arg1=0,
                arg2=command.preset,
                arg3=0,
            )
            return
        if command.action == "home":
            await self._get(
                "ptz.cgi", action="start", channel=channel, code="GotoPreset", arg1=0, arg2=1, arg3=0
            )
            return
        if command.action == "stop":
            for code in ("Up", "ZoomTele"):  # stopping any one direction stops the motor
                await self._get("ptz.cgi", action="stop", channel=channel, code=code, arg1=0, arg2=0, arg3=0)
            return
        if command.zoom and not (command.pan or command.tilt):
            code = "ZoomTele" if command.zoom > 0 else "ZoomWide"
            speed = 0
        else:
            key = (_sign(command.pan), _sign(command.tilt))
            if key == (0, 0):
                raise ValueError("no direction")
            code = DIRECTIONS[key]
            speed = max(1, min(8, round(max(abs(command.pan), abs(command.tilt)) * 8)))
        await self._get("ptz.cgi", action="start", channel=channel, code=code, arg1=0, arg2=speed, arg3=0)
