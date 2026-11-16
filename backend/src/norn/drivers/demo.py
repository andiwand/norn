"""A camera without a camera: a test pattern from FFmpeg and controls that only change state.

It lets people try Norn before they connect a real camera, and it exercises every widget of the
UI in development and tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import Field

from . import register
from .base import (
    Capability,
    Control,
    Driver,
    DriverOptions,
    Event,
    NotSupportedError,
    Option,
    Preset,
    PtzCommand,
    Stream,
)


class DemoOptions(DriverOptions):
    pattern: Literal["testsrc2", "smptehdbars", "mandelbrot", "life"] = Field(
        "testsrc2", title="Pattern", description="The FFmpeg test source to show."
    )
    event_seconds: int = Field(
        120, title="Pretend motion every", ge=5, description="Seconds between pretend detections."
    )


PRESETS = [Preset(id="door", name="Front door"), Preset(id="drive", name="Driveway")]
PRESET_POSITIONS = {"door": (-0.4, 0.0, 0.0), "drive": (0.5, -0.2, 0.3)}


@register
class DemoDriver(Driver):
    name = "demo"
    label = "Demo camera"
    description = "A test pattern with pretend controls. Try Norn without a camera."
    Options = DemoOptions
    options: DemoOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.state: dict[str, Any] = {
            "ir": "auto",
            "spotlight": False,
            "brightness": 50,
            "motion": True,
            "privacy": False,
        }
        self.position = [0.0, 0.0, 0.0]  # pan, tilt, zoom
        self._move: asyncio.Task[None] | None = None

    def streams(self) -> list[Stream]:
        # FFmpeg makes the pattern and encodes it to H.264 once; go2rtc shares it with all viewers.
        def source(size: str) -> str:
            return f"ffmpeg:virtual?video={self.options.pattern}&size={size}#video=h264"

        return [
            Stream(id="main", label="Main", source=source("1920x1080")),
            Stream(id="sub", label="Sub", source=source("640x360")),
        ]

    def capabilities(self) -> set[Capability]:
        caps = {Capability.PTZ, Capability.PRESETS, Capability.CONTROLS, Capability.EVENTS}
        return super().capabilities() | caps

    def event_kinds(self) -> list[str]:
        return ["motion", "person"]

    async def events(self) -> AsyncIterator[Event]:
        """Pretend motion every `event_seconds` (with a person in every other one), 8 s each."""
        n = 0
        while True:
            await asyncio.sleep(self.options.event_seconds)
            n += 1
            kinds = ["motion", "person"] if n % 2 == 0 else ["motion"]
            for kind in kinds:
                yield Event(kind=kind, active=True)
            await asyncio.sleep(8)
            for kind in kinds:
                yield Event(kind=kind, active=False)

    async def stop(self) -> None:
        if self._move:
            self._move.cancel()

    async def controls(self) -> list[Control]:
        s = self.state
        return [
            Control(
                id="ir",
                label="Night vision",
                kind="select",
                group="Image",
                value=s["ir"],
                icon="moon",
                options=[
                    Option(value="auto", label="Auto"),
                    Option(value="on", label="On"),
                    Option(value="off", label="Off"),
                ],
            ),
            Control(
                id="brightness",
                label="Brightness",
                kind="range",
                group="Image",
                value=s["brightness"],
                min=0,
                max=100,
                step=1,
                unit="%",
                icon="sun",
            ),
            Control(
                id="spotlight",
                label="Spotlight",
                kind="toggle",
                group="Light",
                value=s["spotlight"],
                icon="lamp",
            ),
            Control(id="siren", label="Siren", kind="button", group="Alarm", icon="siren"),
            Control(
                id="motion",
                label="Motion detection",
                kind="toggle",
                group="Alarm",
                value=s["motion"],
                icon="activity",
            ),
            Control(
                id="privacy",
                label="Privacy mode",
                kind="toggle",
                group="General",
                value=s["privacy"],
                icon="eye-off",
            ),
        ]

    async def set_control(self, control_id: str, value: Any) -> None:
        if control_id == "siren":
            self.emit("camera.siren", {})
            return
        if control_id not in self.state:
            raise NotSupportedError(f"the demo camera has no control {control_id!r}")
        controls = {c.id: c for c in await self.controls()}
        control = controls[control_id]
        if control.kind == "toggle":
            value = bool(value)
        elif control.kind == "range":
            value = max(control.min or 0, min(control.max or 100, float(value)))
        elif control.kind == "select" and value not in {o.value for o in control.options or []}:
            raise ValueError(f"{value!r} is not an option of {control_id}")
        self.state[control_id] = value
        self.emit("camera.control", {"control": control_id, "value": value})

    async def presets(self) -> list[Preset]:
        return PRESETS

    async def ptz(self, command: PtzCommand) -> None:
        if self._move:
            self._move.cancel()
            self._move = None
        if command.action == "move":
            self._move = asyncio.create_task(self._moving(command))
        elif command.action == "home":
            self._set_position(0.0, 0.0, 0.0)
        elif command.action == "goto":
            if command.preset not in PRESET_POSITIONS:
                raise ValueError(f"unknown preset {command.preset!r}")
            self._set_position(*PRESET_POSITIONS[command.preset])

    async def _moving(self, command: PtzCommand) -> None:
        # Pretend to move until a stop arrives, like a real motor would.
        while True:
            p, t, z = self.position
            self._set_position(p + command.pan * 0.05, t + command.tilt * 0.05, z + command.zoom * 0.05)
            await asyncio.sleep(0.1)

    def _set_position(self, pan: float, tilt: float, zoom: float) -> None:
        self.position = [max(-1.0, min(1.0, pan)), max(-1.0, min(1.0, tilt)), max(0.0, min(1.0, zoom))]
        self.emit("camera.ptz", {"position": self.position})
