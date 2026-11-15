"""The hub ties the parts together: config, drivers, go2rtc, recorder and events."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from . import __version__
from .config import CameraConfig, Config, ConfigError, ConfigStore
from .drivers import DRIVERS
from .drivers.base import Capability, Driver
from .events import EventBus
from .go2rtc import Go2rtc
from .recorder import Recorder
from .recordings import Library
from .settings import Settings

log = logging.getLogger("norn")


def stream_name(camera_id: str, stream_id: str) -> str:
    """The go2rtc name of a stream. The main stream has the camera's id, so the RTSP path is simple."""
    return camera_id if stream_id == "main" else f"{camera_id}_{stream_id}"


@dataclass
class Camera:
    id: str
    config: CameraConfig
    driver: Driver | None
    error: str | None = None

    def to_json(self, recording: dict[str, Any] | None) -> dict[str, Any]:
        driver = self.driver
        streams = driver.streams() if driver and self.config.enabled else []
        caps = sorted(driver.capabilities()) if driver and self.config.enabled else []
        return {
            "id": self.id,
            "name": self.config.name,
            "driver": self.config.driver,
            "enabled": self.config.enabled,
            "record": self.config.record,
            "options": self.config.options,
            "error": self.error,
            "capabilities": caps,
            "streams": [{"id": s.id, "label": s.label, "name": stream_name(self.id, s.id)} for s in streams],
            "recording": recording,
        }


class Hub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bus = EventBus()
        self.store = ConfigStore(settings.config_path)
        self.library = Library(settings.recordings_path)
        self.go2rtc = Go2rtc(settings, self.bus)
        self.recorder = Recorder(settings, self.go2rtc, self.library, self.bus)
        self.cameras: dict[str, Camera] = {}
        self.config_error: str | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def config(self) -> Config:
        return self.store.config

    async def start(self) -> None:
        try:
            self.store.load()
        except ConfigError as e:
            # Start anyway, so the UI can show what's wrong instead of a dead page.
            self.config_error = str(e)
            log.error("%s", e)
        await self._build_cameras()
        await self.go2rtc.start(self.streams())
        await self.recorder.start(self.config, self.streams())
        self._watcher = asyncio.create_task(self._watch_config(), name="config-watcher")
        log.info("Norn %s with %d cameras", __version__, len(self.cameras))

    async def stop(self) -> None:
        if self._watcher:
            self._watcher.cancel()
        await self.recorder.stop()
        for camera in self.cameras.values():
            if camera.driver:
                with contextlib.suppress(Exception):
                    await camera.driver.stop()
        await self.go2rtc.stop()

    def streams(self) -> dict[str, str]:
        """All go2rtc streams: name -> source."""
        return {
            stream_name(cid, s.id): s.source
            for cid, cam in self.cameras.items()
            if cam.driver and cam.config.enabled
            for s in cam.driver.streams()
        }

    def camera_json(self, camera_id: str) -> dict[str, Any]:
        return self.cameras[camera_id].to_json(self.recorder.status(camera_id))

    def get_driver(self, camera_id: str) -> Driver:
        camera = self.cameras.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        if camera.driver is None or not camera.config.enabled:
            raise LookupError(camera.error or f"camera {camera_id} is disabled")
        return camera.driver

    def has(self, camera_id: str, capability: Capability) -> bool:
        try:
            return capability in self.get_driver(camera_id).capabilities()
        except (KeyError, LookupError):
            return False

    # Changes from the API. Each one writes config.yaml and then applies it.
    async def put_camera(self, camera_id: str, camera: CameraConfig) -> None:
        validate_options(camera)
        async with self._lock:
            self.store.put_camera(camera_id, camera)
            await self._apply()

    async def remove_camera(self, camera_id: str) -> None:
        async with self._lock:
            self.store.remove_camera(camera_id)
            await self._apply()

    async def reload(self) -> None:
        async with self._lock:
            try:
                self.store.load()
                self.config_error = None
            except ConfigError as e:
                self.config_error = str(e)
                log.error("config not reloaded: %s", e)
                self.bus.publish("config.error", {"error": str(e)})
                return
            await self._apply()
            log.info("config reloaded")

    async def _apply(self) -> None:
        await self._build_cameras()
        streams = self.streams()
        await self.go2rtc.apply(streams)
        await self.recorder.apply(self.config, streams)
        self.bus.publish("cameras.changed")

    async def _build_cameras(self) -> None:
        """Create drivers for new or changed cameras; keep the ones that didn't change."""
        old = self.cameras
        new: dict[str, Camera] = {}
        for cid, cfg in self.config.cameras.items():
            previous = old.get(cid)
            if previous and previous.config == cfg:
                new[cid] = previous
                continue
            new[cid] = self._make_camera(cid, cfg)
            if new[cid].driver and cfg.enabled:
                await new[cid].driver.start()
        for cid, camera in old.items():
            if new.get(cid) is not camera and camera.driver:
                with contextlib.suppress(Exception):
                    await camera.driver.stop()
        self.cameras = new

    def _make_camera(self, cid: str, cfg: CameraConfig) -> Camera:
        cls = DRIVERS.get(cfg.driver)
        if cls is None:
            return Camera(cid, cfg, None, f"unknown driver {cfg.driver!r}")
        try:
            options = cls.Options.model_validate(cfg.options)
        except ValidationError as e:
            return Camera(cid, cfg, None, _short_error(e))
        return Camera(cid, cfg, cls(cid, options, self.bus.publish))

    async def _watch_config(self) -> None:
        # Polling the mtime every two seconds costs nothing and works on every file system,
        # including the bind mounts of Docker Desktop, where inotify often doesn't.
        while True:
            await asyncio.sleep(2)
            if self.store.changed_on_disk():
                await self.reload()


def validate_options(camera: CameraConfig) -> None:
    cls = DRIVERS.get(camera.driver)
    if cls is None:
        raise ConfigError(f"unknown driver {camera.driver!r}")
    try:
        cls.Options.model_validate(camera.options)
    except ValidationError as e:
        raise ConfigError(_short_error(e)) from e


def _short_error(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'options'}: {err['msg']}" for err in e.errors())
