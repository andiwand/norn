"""Axis cameras, through VAPIX (HTTP, digest auth) and RTSP.

    POST /axis-cgi/basicdeviceinfo.cgi  {"apiVersion": "1.0", "method": "getAllProperties"}
    GET  /axis-cgi/param.cgi?action=list&group=Properties.PTZ.PTZ        ...PTZ=yes
    GET  /axis-cgi/param.cgi?action=list&group=ImageSource.I0.DayNight   ...IrCutFilter=auto
    GET  /axis-cgi/param.cgi?action=update&ImageSource.I0.DayNight.IrCutFilter=yes
    GET  /axis-cgi/com/ptz.cgi?continuouspantiltmove=50,0   (stop: 0,0), continuouszoommove=, move=home,
                               query=presetposcam, gotoserverpresetname=
    POST /axis-cgi/firmwaremanagement.cgi   (multipart: JSON + firmware file)
    rtsp://<host>/axis-media/media.amp?videocodec=h264[&resolution=640x360]

Tested against the documented API, not yet against a real camera.
"""

from __future__ import annotations

import json
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
from .dahua import parse_table

IR_CUT = {"auto": "Auto", "no": "Day (filter on)", "yes": "Night (filter off)"}


class AxisOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name")
    username: str = Field("root", title="Username")
    password: str = Field(title="Password")
    http_port: int = Field(80, title="HTTP port", ge=1, le=65535)
    rtsp_port: int = Field(554, title="RTSP port", ge=1, le=65535)


@register
class AxisDriver(Driver):
    name = "axis"
    label = "Axis"
    description = "Axis network cameras: video, PTZ and presets, day/night, firmware upload (VAPIX)."
    Options = AxisOptions
    options: AxisOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self.client = httpx.AsyncClient(
            base_url=f"http://{o.host}:{o.http_port}/axis-cgi/",
            auth=httpx.DigestAuth(o.username, o.password),
            timeout=8,
        )
        self.has_ptz = False

    async def start(self) -> None:
        try:
            params = await self._params("Properties.PTZ")
            self.has_ptz = params.get("root.Properties.PTZ.PTZ") == "yes"
        except DriverError:
            self.has_ptz = False

    async def stop(self) -> None:
        await self.client.aclose()

    def streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        base = f"rtsp://{auth}{o.host}:{o.rtsp_port}/axis-media/media.amp?videocodec=h264"
        return [
            Stream(id="main", label="Main", source=base, codec="h264"),
            Stream(id="sub", label="Sub", source=f"{base}&resolution=640x360", codec="h264"),
        ]

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS, Capability.FIRMWARE_UPLOAD}
        if self.has_ptz:
            caps |= {Capability.PTZ, Capability.PRESETS}
        return caps

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise DriverError(f"{self.options.host}: {e}") from e
        if response.status_code == 401:
            raise DriverError("wrong username or password")
        if response.status_code >= 400 or response.text.lstrip().startswith("# Error"):
            raise DriverError(f"{path}: {response.text.strip()[:80] or response.status_code}")
        return response

    async def _params(self, group: str) -> dict[str, str]:
        response = await self._request("GET", "param.cgi", params={"action": "list", "group": group})
        return parse_table(response.text)

    async def info(self) -> DeviceInfo:
        try:
            response = await self._request(
                "POST", "basicdeviceinfo.cgi", json={"apiVersion": "1.0", "method": "getAllProperties"}
            )
            props = response.json().get("data", {}).get("propertyList", {})
        except (DriverError, ValueError) as e:
            return DeviceInfo(online=False, error=str(e))
        return DeviceInfo(
            manufacturer=props.get("Brand") or "Axis",
            model=props.get("ProdNbr") or props.get("ProdShortName"),
            firmware=props.get("Version"),
            hardware=props.get("HardwareID"),
            serial=props.get("SerialNumber"),
            details={"Product": props["ProdFullName"]} if props.get("ProdFullName") else {},
        )

    async def controls(self) -> list[Control]:
        try:
            params = await self._params("ImageSource.I0.DayNight")
        except DriverError:
            return []
        mode = params.get("root.ImageSource.I0.DayNight.IrCutFilter")
        if mode is None:
            return []
        return [
            Control(
                id="ircut",
                label="Day/night",
                kind="select",
                group="Image",
                icon="moon",
                value=mode,
                options=[Option(value=k, label=v) for k, v in IR_CUT.items()],
            )
        ]

    async def set_control(self, control_id: str, value: Any) -> None:
        if control_id != "ircut":
            raise NotSupportedError(f"no control {control_id!r}")
        if value not in IR_CUT:
            raise ValueError(f"{value!r} is not one of {', '.join(IR_CUT)}")
        response = await self._request(
            "GET", "param.cgi", params={"action": "update", "ImageSource.I0.DayNight.IrCutFilter": value}
        )
        if "OK" not in response.text:
            raise DriverError(f"the camera didn't take the setting: {response.text.strip()[:80]}")
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        if not self.has_ptz:
            return []
        try:
            response = await self._request(
                "GET", "com/ptz.cgi", params={"query": "presetposcam", "camera": 1}
            )
        except DriverError:
            return []
        # presetposno1=Gate
        return [
            Preset(id=name, name=name)
            for key, name in parse_table(response.text).items()
            if "presetposno" in key
        ]

    async def ptz(self, command: PtzCommand) -> None:
        if not self.has_ptz:
            raise NotSupportedError("this camera can't pan or tilt")
        params: dict[str, Any] = {"camera": 1}
        if command.action == "move":
            params["continuouspantiltmove"] = f"{round(command.pan * 100)},{round(command.tilt * 100)}"
            params["continuouszoommove"] = round(command.zoom * 100)
        elif command.action == "stop":
            params |= {"continuouspantiltmove": "0,0", "continuouszoommove": 0}
        elif command.action == "home":
            params["move"] = "home"
        elif command.action == "goto":
            if not command.preset:
                raise ValueError("which preset?")
            params["gotoserverpresetname"] = command.preset
        await self._request("GET", "com/ptz.cgi", params=params)

    async def firmware_upload(self, image: bytes) -> None:
        """Upload firmware (a .bin from axis.com); the camera checks it, installs it and restarts."""
        if len(image) < 1_000_000:
            raise ValueError("this is too small to be an Axis firmware file")
        meta = json.dumps({"apiVersion": "1.0", "method": "upgrade"})
        response = await self._request(
            "POST",
            "firmwaremanagement.cgi",
            files={
                "data": (None, meta, "application/json"),
                "file": ("firmware.bin", image, "application/octet-stream"),
            },
            timeout=600,
        )
        try:
            error = response.json().get("error")
        except ValueError:
            error = None
        if error:
            raise DriverError(f"the camera refused the firmware: {error.get('message', error)}")
