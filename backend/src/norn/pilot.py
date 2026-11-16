"""Where pan/tilt cameras look: Norn's presets, patrols, reactions to detections, following.

One Pilot per camera. It reads the camera's settings each time, so changes apply at once.

- A Norn preset is one of the camera's preset slots plus settings to apply there (night mode,
  spotlight, ...), with a picture of the view (presets/<camera>/<preset>.jpg in Norn's folder).
- Patrol: through presets in order or at random, `dwell_seconds` at each, in its schedule. It
  waits while someone steers the camera by hand, while a reaction holds it, while it follows.
- Reactions: a detection (on this camera or others) turns it to one of some presets for a while.
- Following: with the camera's own tracking where it has it (a control `autotrack`), else with
  Norn's person detection on stills: a short nudge toward the person, again and again.
- Default preset: when none of these steers the camera (no patrol in its schedule, no hold after
  a hand move or a reaction, not following), it goes back to its default preset.
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
DEFAULT_AFTER_MANUAL = 30.0  # at least this long after a hand command before going back to the default


class Pilot:
    def __init__(self, hub: Hub, camera_id: str) -> None:
        self.hub = hub
        self.camera_id = camera_id
        self.paused_until = 0.0  # manual steering, a reaction's hold, following
        self.patrol_index = -1
        self.following = False  # the camera's own tracking is on because of Norn
        self.at_preset: str | None = None  # the Norn preset it's at, as far as Norn knows
        self._moves = 0  # counts every command that moves it: a goto knows if another came meanwhile
        self.last_manual = -DEFAULT_AFTER_MANUAL
        self._missing_warned: str | None = None  # the default's slot the camera lacks (warned once)
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
        if command.action != "stop":
            self._moved()
        if command.action == "move":
            self._auto_stop = asyncio.create_task(self._stop_later())

    async def _stop_later(self) -> None:
        await asyncio.sleep(MOVE_TIMEOUT)
        log.info("%s: a move without a stop; stopping it", self.camera_id)
        try:
            await self.hub.get_driver(self.camera_id).ptz(PtzCommand(action="stop"))
        except Exception as e:
            log.warning("%s: stopping failed: %s", self.camera_id, e)

    def _moved(self) -> None:
        self._moves += 1
        self.at_preset = None

    def moving(self) -> bool:
        """A move from the page is under way (its stop hasn't come yet)."""
        return self._auto_stop is not None and not self._auto_stop.done()

    def manual(self) -> None:
        """Someone steered the camera: patrol waits (and the default preset, at least 30 s)."""
        patrol = self.config.patrol if self.config else None
        self.last_manual = time.monotonic()
        self.pause(patrol.pause_after_manual if patrol and patrol.enabled else 120)

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
        if self._auto_stop:  # a forgotten move's stop must not halt this one on its way
            self._auto_stop.cancel()
            self._auto_stop = None
        self._moved()
        mine = self._moves
        await driver.ptz(PtzCommand(action="goto", preset=preset.slot))
        if self._moves == mine:  # nothing else moved it meanwhile
            self.at_preset = preset_id
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
        self._moved()
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
                self._moved()
                self.pause(30)
        except Exception as e:
            log.info("%s: tracking not switched: %s", self.camera_id, e)

    def tracking_itself(self) -> bool:
        """The camera's own tracking is on (switched on by hand): it moves by itself."""
        cached = self.hub.cameras.get(self.camera_id)
        on = any(c.id == "autotrack" and c.value is True for c in (cached.controls if cached else None) or [])
        if on:
            self.at_preset = None
        return on

    async def _to_default(self) -> None:
        cfg = self.config
        default = cfg.default_preset if cfg else None
        if time.monotonic() - self.last_manual < DEFAULT_AFTER_MANUAL:
            return
        if not default or default not in cfg.presets or self.at_preset == default:
            return
        # A slot the camera no longer has (deleted on the camera) would send it somewhere odd.
        slot = cfg.presets[default].slot
        cached = self.hub.cameras.get(self.camera_id)
        listed = cached.presets if cached else None
        if listed is not None and slot not in {p.id for p in listed}:
            if self._missing_warned != slot:
                log.warning(
                    "%s: the default preset %s is in slot %s, which the camera doesn't have any more;"
                    " save the view again",
                    self.camera_id,
                    default,
                    slot,
                )
                self._missing_warned = slot
            return
        self._missing_warned = None
        log.info("%s: back to the default preset %s", self.camera_id, default)
        await self.goto(default)

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
                busy = self.following or self.moving() or self.tracking_itself()
                if time.monotonic() < self.paused_until or busy:
                    await asyncio.sleep(5)
                    continue
                patrol = cfg.patrol
                stops = [p for p in (patrol.presets if patrol else []) if p in cfg.presets]
                if not patrol or not patrol.enabled or not stops or not in_schedule(patrol.schedule, _now()):
                    await self._to_default()
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
