"""The camera abstraction.

A driver knows one kind of camera. It says where the video comes from (sources for go2rtc), what
the camera can do (capabilities), and which settings it exposes (controls). The web UI builds
its controls from that description, so a new camera type needs a new driver and no UI change.

Video never passes through a driver: go2rtc reads the camera and repackages the stream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class Capability(StrEnum):
    LIVE = "live"  # has at least one stream
    SNAPSHOT = "snapshot"  # a still image (go2rtc decodes one frame)
    PTZ = "ptz"  # pan, tilt and/or zoom
    PRESETS = "presets"  # named PTZ positions
    CONTROLS = "controls"  # settings like IR, spotlight, siren
    AUDIO = "audio"  # the stream has sound
    TALKBACK = "talkback"  # two-way audio


class Stream(BaseModel):
    """One video stream of a camera. `main` is the full quality, `sub` a smaller one."""

    id: str
    label: str
    source: str  # a go2rtc source: rtsp://..., ffmpeg:..., onvif://..., tapo://...


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

    def capabilities(self) -> set[Capability]:
        caps = {Capability.SNAPSHOT}
        if self.streams():
            caps.add(Capability.LIVE)
        return caps

    async def start(self) -> None:
        """Connect to the camera, if the driver needs a session. Must not raise for an offline camera."""

    async def stop(self) -> None:
        pass

    async def controls(self) -> list[Control]:
        return []

    async def set_control(self, control_id: str, value: Any) -> None:
        raise NotSupportedError(f"{self.label} has no control {control_id!r}")

    async def presets(self) -> list[Preset]:
        return []

    async def ptz(self, command: PtzCommand) -> None:
        raise NotSupportedError(f"{self.label} cannot pan, tilt or zoom")
