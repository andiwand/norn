"""Hikvision cameras, through ISAPI (HTTP with digest auth) and RTSP.

    /ISAPI/System/deviceInfo                          model, firmware, serial, MAC
    /ISAPI/System/status                              uptime, CPU, memory
    /ISAPI/Image/channels/<n>/IrcutFilter             day / night / auto
    /ISAPI/Image/channels/<n>/WDR                     wide dynamic range
    /ISAPI/Image/channels/<n>/ImageFlip               flip
    /ISAPI/Image/channels/<n>/Color                   brightness, contrast, saturation
    /ISAPI/System/Video/inputs/channels/<n>/motionDetection
    rtsp://<host>/Streaming/Channels/<n>01 (main), <n>02 (sub)

A setting is changed by reading its XML document, changing one element, and writing the whole
document back (PUT), so the fields Norn doesn't know keep their values.
"""

from __future__ import annotations

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
    Stream,
)


def xml_value(xml: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}(?:\s[^>]*)?>([^<]*)</{tag}>", xml)
    return match[1].strip() if match else None


def xml_replace(xml: str, tag: str, value: str) -> str:
    new, count = re.subn(rf"(<{tag}(?:\s[^>]*)?>)[^<]*(</{tag}>)", rf"\g<1>{value}\g<2>", xml, count=1)
    if not count:
        raise DriverError(f"the camera's settings have no <{tag}>")
    return new


def duration(seconds: int) -> str:
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days} d {hours} h"
    return f"{hours} h {rest // 60} min"


# control id -> (ISAPI path below the channel, XML element, kind)
SETTINGS: dict[str, tuple[str, str]] = {
    "daynight": ("Image/channels/{ch}/IrcutFilter", "IrcutFilterType"),
    "wdr": ("Image/channels/{ch}/WDR", "mode"),
    "flip": ("Image/channels/{ch}/ImageFlip", "enabled"),
    "brightness": ("Image/channels/{ch}/Color", "brightnessLevel"),
    "contrast": ("Image/channels/{ch}/Color", "contrastLevel"),
    "saturation": ("Image/channels/{ch}/Color", "saturationLevel"),
    "motion": ("System/Video/inputs/channels/{ch}/motionDetection", "enabled"),
}


class HikvisionOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name, like 192.168.1.64")
    username: str = Field("admin", title="Username")
    password: str = Field(title="Password")
    http_port: int = Field(80, title="HTTP port", ge=1, le=65535)
    rtsp_port: int = Field(554, title="RTSP port", ge=1, le=65535)
    channel: int = Field(1, title="Channel", ge=1, description="1 for a camera; the input of an NVR")


@register
class HikvisionDriver(Driver):
    name = "hikvision"
    label = "Hikvision"
    description = "Hikvision IP cameras: RTSP video, image settings and motion detection over ISAPI."
    Options = HikvisionOptions
    options: HikvisionOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self._client = httpx.AsyncClient(
            base_url=f"http://{o.host}:{o.http_port}/ISAPI/",
            auth=httpx.DigestAuth(o.username, o.password),
            timeout=8,
        )

    async def stop(self) -> None:
        await self._client.aclose()

    def streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        base = f"rtsp://{auth}{o.host}:{o.rtsp_port}/Streaming/Channels/{o.channel}"
        return [
            Stream(id="main", label="Main", source=f"{base}01", codec="h264"),
            Stream(id="sub", label="Sub", source=f"{base}02", codec="h264"),
        ]

    def capabilities(self) -> set[Capability]:
        return super().capabilities() | {Capability.CONTROLS, Capability.FIRMWARE_UPLOAD}

    async def firmware_upload(self, image: bytes) -> None:
        """Upload a firmware file (digicap.dav) and restart the camera to install it.

        The camera checks the file itself and refuses one for another model. Installing takes a
        few minutes; the camera is offline meanwhile. Don't cut its power.
        """
        if len(image) < 1_000_000:  # real firmware files are tens of MB; the camera checks the rest
            raise ValueError("this is too small to be a Hikvision firmware file (digicap.dav)")
        try:
            response = await self._client.put(
                "System/updateFirmware",
                content=image,
                headers={"Content-Type": "application/octet-stream"},
                timeout=600,
            )
        except httpx.HTTPError as e:
            raise DriverError(f"upload failed: {e}") from e
        if response.status_code >= 400 or xml_value(response.text, "statusCode") not in ("1", "7", None):
            reason = xml_value(response.text, "subStatusCode") or f"HTTP {response.status_code}"
            raise DriverError(f"the camera refused the firmware: {reason}")
        # statusCode 7 is "reboot required": the new firmware is installed on the next start.
        await self._request("PUT", "System/reboot")

    async def _request(self, method: str, path: str, content: str | None = None) -> str:
        path = path.format(ch=self.options.channel)
        try:
            response = await self._client.request(
                method,
                path,
                content=content,
                headers={"Content-Type": "application/xml"} if content else None,
            )
        except httpx.HTTPError as e:
            raise DriverError(f"{self.options.host}: {e}") from e
        if response.status_code == 401:
            raise DriverError("wrong username or password")
        if response.status_code >= 400 or (
            "<statusCode>" in response.text and xml_value(response.text, "statusCode") not in ("1", None)
        ):
            reason = xml_value(response.text, "subStatusCode") or f"HTTP {response.status_code}"
            raise DriverError(f"{path}: {reason}")
        return response.text

    async def info(self) -> DeviceInfo:
        try:
            device = await self._request("GET", "System/deviceInfo")
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        details: dict[str, str] = {}
        try:
            status = await self._request("GET", "System/status")
            if uptime := xml_value(status, "deviceUpTime"):
                details["Uptime"] = duration(int(uptime))
            if cpu := xml_value(status, "cpuUtilization"):
                details["CPU"] = f"{cpu} %"
            if memory := xml_value(status, "memoryUsage"):
                details["Memory"] = f"{memory} %"
        except DriverError:
            pass
        released = xml_value(device, "firmwareReleasedDate")
        firmware = xml_value(device, "firmwareVersion")
        return DeviceInfo(
            manufacturer="Hikvision",
            model=xml_value(device, "model"),
            firmware=f"{firmware} {released}" if firmware and released else firmware,
            serial=xml_value(device, "serialNumber"),
            mac=xml_value(device, "macAddress"),
            name=xml_value(device, "deviceName"),
            details=details,
        )

    async def controls(self) -> list[Control]:
        values: dict[str, str | None] = {}
        documents: dict[str, str] = {}
        for control_id, (path, tag) in SETTINGS.items():
            try:
                if path not in documents:
                    documents[path] = await self._request("GET", path)
                values[control_id] = xml_value(documents[path], tag)
            except DriverError:
                values[control_id] = None

        def level(control_id: str, label: str, icon: str | None = None) -> Control | None:
            if values[control_id] is None:
                return None
            return Control(
                id=control_id,
                label=label,
                kind="range",
                group="Image",
                icon=icon,
                value=int(values[control_id] or 0),
                min=0,
                max=100,
                step=1,
            )

        controls = [
            Control(
                id="daynight",
                label="Day/night",
                kind="select",
                group="Image",
                icon="moon",
                value=values["daynight"],
                options=[Option(value=v, label=v.capitalize()) for v in ("auto", "day", "night")],
            )
            if values["daynight"]
            else None,
            level("brightness", "Brightness", "sun"),
            level("contrast", "Contrast"),
            level("saturation", "Saturation"),
            Control(
                id="wdr",
                label="Wide dynamic range",
                kind="toggle",
                group="Image",
                value=values["wdr"] == "open",
            )
            if values["wdr"]
            else None,
            Control(
                id="flip", label="Flip image", kind="toggle", group="Image", value=values["flip"] == "true"
            )
            if values["flip"]
            else None,
            Control(
                id="motion",
                label="Motion detection",
                kind="toggle",
                group="Alarm",
                icon="activity",
                value=values["motion"] == "true",
            )
            if values["motion"]
            else None,
        ]
        return [c for c in controls if c]

    async def set_control(self, control_id: str, value: Any) -> None:
        if control_id not in SETTINGS:
            raise NotSupportedError(f"no control {control_id!r}")
        path, tag = SETTINGS[control_id]
        if control_id == "daynight":
            if value not in ("auto", "day", "night"):
                raise ValueError(f"{value!r} is not auto, day or night")
            text = str(value)
        elif control_id == "wdr":
            text = "open" if value else "close"
        elif control_id in ("flip", "motion"):
            text = "true" if value else "false"
        else:
            text = str(max(0, min(100, int(value))))
        document = await self._request("GET", path)
        await self._request("PUT", path, xml_replace(document, tag, text))
        self.emit("camera.control", {"control": control_id, "value": value})
