"""Where pan/tilt cameras look: Norn's presets, patrols, reactions to detections, following.

One Pilot per camera. It reads the camera's settings each time, so changes apply at once.

- A Norn preset is one of the camera's preset slots plus settings to apply there (night mode,
  spotlight, ...), with a picture of the view (presets/<camera>/<preset>.jpg in Norn's folder).
- Patrol: through presets in order or at random, `dwell_seconds` at each, in its schedule. It
  waits while someone steers the camera by hand, while a reaction holds it, while it follows.
- Reactions: a detection (on this camera or others) turns it to one of some presets for a while.
- Following: with the camera's own tracking where it has it (a control `autotrack`), else with
  Norn's person detection on stills: a short nudge toward the person, again and again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import in_schedule
from .drivers.base import Capability, PtzCommand

if TYPE_CHECKING:
    from .detect import Detection
    from .hub import Hub

log = logging.getLogger("norn.pilot")

MOVE_TIMEOUT = 8.0  # seconds a move from the API runs without a new command (the page renews it)
NUDGE_SECONDS = 0.35  # how long one nudge toward a followed person turns the camera
DEAD_ZONE = 0.15  # how far off the middle (of -1..1) a person may be before Norn turns


class Pilot:
    def __init__(self, hub: Hub, camera_id: str) -> None:
        self.hub = hub
        self.camera_id = camera_id
        self.paused_until = 0.0  # manual steering, a reaction's hold, following
        self.patrol_index = -1
        self.following = False  # the camera's own tracking is on because of Norn
        self._paused = asyncio.Event()  # set by pause(): a dwell ends at once
        self._auto_stop: asyncio.Task[None] | None = None
        self.task = asyncio.create_task(self._run(), name=f"pilot-{camera_id}")

    @property
    def config(self) -> Any:
        return self.hub.config.cameras.get(self.camera_id)

    def stop(self) -> None:
        self.task.cancel()
        if self._auto_stop:
            self._auto_stop.cancel()

    def picture(self, preset_id: str) -> Path:
        return self.hub.settings.runtime_dir / "presets" / self.camera_id / f"{preset_id}.jpg"

    def moved(self, command: PtzCommand) -> None:
        """A move from the API: if no new command follows within MOVE_TIMEOUT, stop it. A page
        that lost its connection, or a stop that never came, must not leave the camera turning."""
        if self._auto_stop:
            self._auto_stop.cancel()
            self._auto_stop = None
        if command.action == "move":
            self._auto_stop = asyncio.create_task(self._stop_later())

    async def _stop_later(self) -> None:
        await asyncio.sleep(MOVE_TIMEOUT)
        log.info("%s: a move without a stop; stopping it", self.camera_id)
        try:
            await self.hub.get_driver(self.camera_id).ptz(PtzCommand(action="stop"))
        except Exception as e:
            log.warning("%s: stopping failed: %s", self.camera_id, e)

    def manual(self) -> None:
        """Someone steered the camera: patrol waits."""
        patrol = self.config.patrol if self.config else None
        self.pause(patrol.pause_after_manual if patrol else 120)

    def pause(self, seconds: float) -> None:
        self.paused_until = max(self.paused_until, time.monotonic() + seconds)
        self._paused.set()

    async def goto(self, preset_id: str) -> None:
        """Go to a Norn preset: its slot, then its settings."""
        cfg = self.config
        preset = cfg.presets.get(preset_id) if cfg else None
        if preset is None:
            raise KeyError(preset_id)
        driver = self.hub.get_driver(self.camera_id)
        await driver.ptz(PtzCommand(action="goto", preset=preset.slot))
        for control_id, value in preset.controls.items():
            try:
                await driver.set_control(control_id, value)
                self.hub.remember_control(self.camera_id, control_id, value)
            except Exception as e:
                log.info("%s: preset %s: %s not set: %s", self.camera_id, preset_id, control_id, e)

    async def react(self, presets: list[str], hold: float) -> None:
        """A reaction: one of `presets`, then hold it for `hold` seconds."""
        usable = [p for p in presets if self.config and p in self.config.presets]
        if not usable:
            return
        self.pause(hold)
        try:
            await self.goto(random.choice(usable))
        except Exception as e:
            log.info("%s: reaction failed: %s", self.camera_id, e)

    # Following

    def follow_wanted(self) -> bool:
        cfg = self.config
        if not cfg or cfg.follow == "off":
            return False
        if cfg.follow == "recording":
            return self.hub.recorder.is_recording(self.camera_id)
        if cfg.follow == "away":
            return self.hub.away
        return True

    def own_tracking(self) -> bool:
        cached = self.hub.cameras.get(self.camera_id)
        return bool(cached and any(c.id == "autotrack" for c in cached.controls or []))

    async def nudge(self, people: list[Detection], aspect: float) -> None:
        """Norn's following: turn a little toward the largest person in the still (the
        detector's letterboxed input: the picture fills the width, from the top)."""
        if not people:
            return
        from .detect import OBJECT_SIZE

        target = max(people, key=lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]))
        content_h = OBJECT_SIZE / aspect if aspect >= 1 else OBJECT_SIZE
        content_w = OBJECT_SIZE if aspect >= 1 else OBJECT_SIZE * aspect
        x = ((target.box[0] + target.box[2]) / 2) / content_w * 2 - 1
        y = ((target.box[1] + target.box[3]) / 2) / content_h * 2 - 1
        self.pause(15)  # no patrol while following someone
        if abs(x) < DEAD_ZONE and abs(y) < DEAD_ZONE:
            return
        driver = self.hub.get_driver(self.camera_id)
        pan = max(-1.0, min(1.0, x * 0.8)) if abs(x) >= DEAD_ZONE else 0.0
        tilt = max(-1.0, min(1.0, -y * 0.8)) if abs(y) >= DEAD_ZONE else 0.0
        await driver.ptz(PtzCommand(action="move", pan=pan, tilt=tilt))
        await asyncio.sleep(NUDGE_SECONDS)
        await driver.ptz(PtzCommand(action="stop"))

    async def _own_tracking(self) -> None:
        """Switch the camera's own tracking on while following is wanted, back off after."""
        wanted = self.follow_wanted()
        if wanted == self.following or not self.own_tracking():
            return
        try:
            await self.hub.get_driver(self.camera_id).set_control("autotrack", wanted)
            self.hub.remember_control(self.camera_id, "autotrack", wanted)
            self.following = wanted
            if wanted:
                self.pause(30)
        except Exception as e:
            log.info("%s: tracking not switched: %s", self.camera_id, e)

    # Patrol

    async def _run(self) -> None:
        while True:
            cfg = self.config
            try:
                if cfg is None or not cfg.enabled or not self.hub.has(self.camera_id, Capability.PTZ):
                    await asyncio.sleep(10)
                    continue
                await self._own_tracking()
                if self.following:
                    self.pause(10)
                patrol = cfg.patrol
                stops = [p for p in (patrol.presets if patrol else []) if p in cfg.presets]
                if not patrol or not patrol.enabled or not stops:
                    await asyncio.sleep(5)
                    continue
                if time.monotonic() < self.paused_until or not in_schedule(patrol.schedule, _now()):
                    await asyncio.sleep(5)
                    continue
                if patrol.order == "random":
                    choices = [p for p in stops if len(stops) == 1 or stops.index(p) != self.patrol_index]
                    self.patrol_index = stops.index(random.choice(choices))
                else:
                    self.patrol_index = (self.patrol_index + 1) % len(stops)
                await self.goto(stops[self.patrol_index])
                # Dwell, but stop at once when someone steers or a reaction takes over.
                self._paused.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._paused.wait(), patrol.dwell_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.info("%s: patrol: %s", self.camera_id, e)
                await asyncio.sleep(30)


def _now() -> Any:
    from datetime import datetime

    return datetime.now()
