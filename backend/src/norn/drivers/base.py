"""The camera abstraction.

A driver knows one kind of camera. It says where the video comes from (sources for go2rtc), what
the camera can do (capabilities), and which settings it exposes (controls). The web UI builds
its controls from that description, so a new camera type needs a new driver and no UI change.

Video never passes through a driver: go2rtc reads the camera and repackages the stream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from enum import StrEnum
from typing import Any, ClassVar, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field


class Capability(StrEnum):
    LIVE = "live"  # has at least one stream
    SNAPSHOT = "snapshot"  # a still image (go2rtc decodes one frame)
    PTZ = "ptz"  # pan, tilt and/or zoom
    PRESETS = "presets"  # named PTZ positions
    CONTROLS = "controls"  # settings like IR, spotlight, siren
    AUDIO = "audio"  # the stream has sound
    TALKBACK = "talkback"  # two-way audio
    FIRMWARE_UPLOAD = "firmware-upload"  # installs a firmware file the user provides
    FIRMWARE_ONLINE = "firmware-online"  # finds and installs new firmware by itself
    EVENTS = "events"  # reports what the camera detects (motion, people, ...), see Driver.events
    PRESET_SAVE = "preset-save"  # can store the current view in one of its preset slots


class Event(BaseModel):
    """A detection starting (active) or ending."""

    kind: str
    active: bool


class Stream(BaseModel):
    """One video stream of a camera. `main` is the full quality, `sub` a smaller one."""

    id: str
    label: str
    source: str  # a go2rtc source: rtsp://..., ffmpeg:..., onvif://..., tapo://...
    # The video codec, if the driver knows it. MJPEG can't go over WebRTC or into a browser's MP4,
    # so the player asks go2rtc for MJPEG frames and the recorder encodes it to H.264.
    codec: Literal["h264", "h265", "mjpeg"] | None = None


class Option(BaseModel):
    value: str
    label: str


class Control(BaseModel):
    """A setting the UI shows as a widget. `value` is the current state."""

    id: str
    label: str
    kind: Literal["toggle", "select", "range", "button"]
    group: str = "General"
    value: Any = None
    options: list[Option] | None = None  # select
    min: float | None = None  # range
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    icon: str | None = None  # a hint for the UI, like "sun", "siren", "moon"


class DeviceInfo(BaseModel):
    """What a camera says about itself. The hub polls it, so it must be cheap."""

    online: bool = True
    error: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    hardware: str | None = None
    serial: str | None = None
    mac: str | None = None
    name: str | None = None  # the name set on the camera itself
    # More facts for the UI, in display order: {"Uptime": "3 days", "Wi-Fi": "connected"}
    details: dict[str, str] = Field(default_factory=dict)
    # Things the user should know: an endpoint that leaks secrets, a protocol that is off, ...
    notes: list[str] = Field(default_factory=list)


class Preset(BaseModel):
    id: str
    name: str


class PtzCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["move", "stop", "goto", "home"]
    # Speeds for move, from -1 to 1. Positive pan is right, positive tilt is up, positive zoom is in.
    pan: float = Field(0, ge=-1, le=1)
    tilt: float = Field(0, ge=-1, le=1)
    zoom: float = Field(0, ge=-1, le=1)
    preset: str | None = None  # goto


class NotSupportedError(Exception):
    pass


class DriverError(Exception):
    pass


class DriverOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


Emit = Callable[[str, dict[str, Any]], None]

# Pan/tilt directions by (pan sign, tilt sign), as Reolink and Dahua name them.
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


def sign(x: float, dead: float = 0.2) -> int:
    """-1, 0 or 1 for a PTZ speed; small speeds count as 0."""
    return 0 if abs(x) < dead else (1 if x > 0 else -1)


def userinfo(username: str, password: str) -> str:
    """`user:password@` for a stream URL, percent-encoded (go2rtc reads it from the URL)."""
    return f"{quote(username, safe='')}:{quote(password, safe='')}@"


def parse_table(text: str) -> dict[str, str]:
    """`table.X[0].Y=1` and `key=value` lines into a dict (keys without the `table.` prefix)."""
    result = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep:
            result[key.removeprefix("table.")] = value.strip()
    return result


class Driver(ABC):
    """Base class of all drivers. Subclasses set the class variables and register themselves."""

    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    Options: ClassVar[type[DriverOptions]] = DriverOptions

    def __init__(self, camera_id: str, options: DriverOptions, emit: Emit | None = None) -> None:
        self.camera_id = camera_id
        self.options = options
        self._emit = emit or (lambda _type, _data: None)

    def emit(self, type_: str, data: dict[str, Any]) -> None:
        self._emit(type_, {"camera": self.camera_id, **data})

    @abstractmethod
    def streams(self) -> list[Stream]: ...

    def preset_slots(self) -> list[str]:
        """The preset ids `save_preset` takes, for Norn to pick a free one. Empty: any id."""
        return []

    async def save_preset(self, slot: str, name: str) -> str | None:
        """Store the current view in preset `slot`, for Capability.PRESET_SAVE. Returns the slot the
        camera used, if it picks its own (ONVIF), else None."""
        raise NotSupportedError("this camera can't save presets")

    def web_url(self) -> str | None:
        """The camera's own web page, if it has one (Norn checks that it answers)."""
        return None

    def extra_streams(self) -> list[Stream]:
        """More streams the camera may have (a third, smaller one, ...). Norn probes them and
        offers the ones that work; `streams()` are the ones every camera of the kind has."""
        return []

    def capabilities(self) -> set[Capability]:
        caps = {Capability.SNAPSHOT}
        if self.streams():
            caps.add(Capability.LIVE)
        return caps

    async def start(self) -> None:
        """Connect to the camera, if the driver needs a session. Must not raise for an offline camera."""

    async def stop(self) -> None:
        pass

    async def info(self) -> DeviceInfo:
        """Model, firmware, state. The default knows nothing; drivers ask the camera."""
        return DeviceInfo(manufacturer=None, model=self.label)

    async def controls(self) -> list[Control]:
        return []

    async def set_control(self, control_id: str, value: Any) -> None:
        raise NotSupportedError(f"{self.label} has no control {control_id!r}")

    async def presets(self) -> list[Preset]:
        return []

    async def firmware_upload(self, image: bytes) -> None:
        """Install a firmware file. Drivers with Capability.FIRMWARE_UPLOAD implement it."""
        raise NotSupportedError(f"{self.label} can't install firmware through Norn")

    async def firmware_online_check(self) -> str | None:
        """The version of newer firmware the vendor offers, or None. For FIRMWARE_ONLINE."""
        return None

    async def firmware_online_update(self) -> None:
        raise NotSupportedError(f"{self.label} can't update itself online")

    def event_kinds(self) -> list[str]:
        """The kinds of events this camera reports: ids of labels.LABELS."""
        return []

    def events(self) -> AsyncIterator[Event]:
        """The camera's detections as they happen, for Capability.EVENTS. Runs until cancelled;
        raise DriverError when the connection breaks, and the hub starts it again."""
        raise NotSupportedError("this camera reports no events")

    async def ptz(self, command: PtzCommand) -> None:
        raise NotSupportedError(f"{self.label} cannot pan, tilt or zoom")
