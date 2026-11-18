"""Any ONVIF camera (Profile S): RTSP streams, pan/tilt/zoom, presets, and image settings.

At start the driver asks the camera for its media profiles and their RTSP addresses: the first
profile is the main stream, the second the substream. A vendor driver (reolink.py) can subclass
it to fix stream addresses or add what ONVIF doesn't cover.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from ..onvif import OnvifClient, OnvifError, Profile, value
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
    userinfo,
)

log = logging.getLogger("norn.onvif")

IMAGING_LEVELS = ("Brightness", "Contrast", "ColorSaturation", "Sharpness")
IR_CUT = {"AUTO": "Auto", "ON": "Day (filter on)", "OFF": "Night (filter off)"}


class OnvifOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name")
    port: int = Field(
        80, title="ONVIF port", ge=1, le=65535, description="80 on most cameras, 8000 on Reolink"
    )
    username: str = Field("admin", title="Username")
    password: str = Field(title="Password")


def with_credentials(uri: str, username: str, password: str) -> str:
    parts = urlsplit(uri)
    host = parts.hostname or ""
    netloc = f"{userinfo(username, password)}{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


@register
class OnvifDriver(Driver):
    name = "onvif"
    label = "ONVIF camera"
    description = "Any ONVIF camera: video, pan/tilt/zoom, presets and image settings."
    Options = OnvifOptions
    options: OnvifOptions
    manufacturer: str | None = None  # a subclass that knows better sets it

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        o = self.options
        self.client = OnvifClient(o.host, o.port, o.username, o.password)
        self.profiles: list[Profile] = []
        self.uris: list[str] = []
        self.error: str | None = None
        self._connected = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        try:
            await self._connect()
        except (OnvifError, DriverError) as e:
            self.error = str(e)
            log.warning("%s: %s", self.camera_id, e)

    async def stop(self) -> None:
        await self.client.close()

    async def _connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            await self.client.connect()
            self.profiles = await self.client.profiles()
            self.uris = []
            for profile in self.profiles[:2]:
                uri = await self.client.stream_uri(profile.token)
                if uri:
                    self.uris.append(uri)
            self._connected = True
            self.error = None

    def streams(self) -> list[Stream]:
        o = self.options
        streams = []
        for i, uri in enumerate(self.uris[:2]):
            codec = (self.profiles[i].encoding or "").lower() if i < len(self.profiles) else ""
            streams.append(
                Stream(
                    id="main" if i == 0 else "sub",
                    label="Main" if i == 0 else "Sub",
                    source=with_credentials(uri, o.username, o.password),
                    codec="h265" if codec in ("h265", "hevc") else "h264" if codec == "h264" else None,
                )
            )
        return streams

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS}
        if "ptz" in self.client.services and any(p.has_ptz for p in self.profiles):
            caps |= {Capability.PTZ, Capability.ZOOM, Capability.PRESETS, Capability.PRESET_SAVE}
        return caps

    @property
    def _profile(self) -> Profile:
        if not self.profiles:
            raise DriverError(self.error or "not connected to the camera")
        return self.profiles[0]

    async def info(self) -> DeviceInfo:
        streams = self.streams()
        try:
            await self._connect()
            device = await self.client.device_information()
        except (OnvifError, DriverError) as e:
            return DeviceInfo(online=False, error=str(e))
        if self.streams() != streams:  # offline at start, or reconnected with other streams
            self.emit("camera.streams", {})
        main = self._profile
        details = {}
        if main.width and main.height:
            details["Main stream"] = f"{main.width}×{main.height} {main.encoding or ''}".strip()
        if len(self.profiles) > 1 and self.profiles[1].width:
            sub = self.profiles[1]
            details["Substream"] = f"{sub.width}×{sub.height} {sub.encoding or ''}".strip()
        manufacturer = device["Manufacturer"]
        if self.manufacturer and (not manufacturer or manufacturer.lower() == "manufacturer"):
            manufacturer = self.manufacturer
        return DeviceInfo(
            manufacturer=manufacturer,
            model=device["Model"],
            firmware=device["FirmwareVersion"],
            hardware=device["HardwareId"],
            serial=device["SerialNumber"],
            details=details,
        )

    async def controls(self) -> list[Control]:
        source = self.profiles[0].source_token if self.profiles else None
        if not source or "imaging" not in self.client.services:
            return []
        try:
            xml = await self.client.imaging_settings(source)
        except OnvifError:
            return []
        controls = []
        for tag in IMAGING_LEVELS:
            level = value(xml, tag)
            if level is None:
                continue
            controls.append(
                Control(
                    id=tag.lower(),
                    label={"ColorSaturation": "Saturation"}.get(tag, tag),
                    kind="range",
                    group="Image",
                    icon="sun" if tag == "Brightness" else None,
                    value=round(float(level)),
                    min=0,
                    max=255 if float(level) > 100 else 100,
                    step=1,
                )
            )
        if (ir := value(xml, "IrCutFilter")) is not None:
            controls.insert(
                0,
                Control(
                    id="ircut",
                    label="Day/night",
                    kind="select",
                    group="Image",
                    icon="moon",
                    value=ir,
                    options=[Option(value=k, label=v) for k, v in IR_CUT.items()],
                ),
            )
        return controls

    async def set_control(self, control_id: str, value_: Any) -> None:
        source = self.profiles[0].source_token if self.profiles else None
        if not source:
            raise NotSupportedError("the camera has no image settings")
        if control_id == "ircut":
            if value_ not in IR_CUT:
                raise ValueError(f"{value_!r} is not one of {', '.join(IR_CUT)}")
            body = f"<IrCutFilter xmlns='{{schema}}'>{value_}</IrCutFilter>"
        else:
            tag = next((t for t in IMAGING_LEVELS if t.lower() == control_id), None)
            if tag is None:
                raise NotSupportedError(f"no control {control_id!r}")
            body = f"<{tag} xmlns='{{schema}}'>{float(value_):g}</{tag}>"
        try:
            await self.client.set_imaging(source, body)
        except OnvifError as e:
            raise DriverError(str(e)) from e
        self.emit("camera.control", {"control": control_id, "value": value_})

    async def save_preset(self, slot: str, name: str) -> str | None:
        """ONVIF SetPreset: overwrites preset `slot` if the camera has it; else the camera makes a
        new preset (a token it doesn't know is a fault) and its token is returned."""
        profile = self._profile.token
        try:
            tokens = {token for token, _ in await self.client.presets(profile)}
            return await self.client.set_preset(profile, slot if slot in tokens else None, name) or None
        except OnvifError as e:
            raise DriverError(f"the camera didn't save the preset: {e}") from e

    async def presets(self) -> list[Preset]:
        if Capability.PRESETS not in self.capabilities():
            return []
        try:
            found = await self.client.presets(self._profile.token)
        except (OnvifError, DriverError):
            return []
        return [Preset(id=token, name=name) for token, name in found if not re.fullmatch(r"\s*", name)]

    async def ptz(self, command: PtzCommand) -> None:
        if Capability.PTZ not in self.capabilities():
            raise NotSupportedError("this camera can't pan or tilt")
        token = self._profile.token
        try:
            if command.action == "move":
                await self.client.continuous_move(token, command.pan, command.tilt, command.zoom)
            elif command.action == "stop":
                await self.client.stop(token)
            elif command.action == "home":
                await self.client.goto_home(token)
            elif command.action == "goto":
                if not command.preset:
                    raise ValueError("which preset?")
                await self.client.goto_preset(token, command.preset)
        except OnvifError as e:
            raise DriverError(str(e)) from e
