"""The hub ties the parts together: config, drivers, go2rtc, recorder and events."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from . import __version__
from .config import CameraConfig, Config, ConfigError, ConfigStore
from .drivers import DRIVERS
from .drivers.base import Capability, DeviceInfo, Driver
from .events import EventBus
from .firmware import FirmwareStatus, check
from .go2rtc import Go2rtc, Go2rtcUnavailableError
from .recorder import Recorder
from .recordings import Library
from .settings import Settings

log = logging.getLogger("norn")

DEVICE_INTERVAL = 300  # seconds between two reads of each camera's state
FIRMWARE_INTERVAL = 24 * 3600  # seconds between two firmware checks (and auto-updates)


def stream_name(camera_id: str, stream_id: str) -> str:
    """The go2rtc name of a stream. The main stream has the camera's id, so the RTSP path is simple."""
    return camera_id if stream_id == "main" else f"{camera_id}_{stream_id}"


@dataclass
class Camera:
    id: str
    config: CameraConfig
    driver: Driver | None
    error: str | None = None
    device: DeviceInfo | None = None
    firmware: FirmwareStatus | None = None
    device_time: float = 0
    firmware_time: float = 0
    update: dict[str, Any] | None = field(default=None)  # a running or failed firmware update

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
            "streams": [
                {"id": s.id, "label": s.label, "name": stream_name(self.id, s.id), "codec": s.codec}
                for s in streams
            ],
            "recording": recording,
            "auto_update": self.config.auto_update,
            "device": self.device.model_dump() if self.device else None,
            "firmware": self.firmware.model_dump() if self.firmware else None,
            "update": self.update,
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
        self._poller: asyncio.Task[None] | None = None
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
        await self.recorder.start(self.config, self.streams(), self.transcoded())
        self._watcher = asyncio.create_task(self._watch_config(), name="config-watcher")
        self._poller = asyncio.create_task(self._poll_devices(), name="device-poller")
        log.info("Norn %s with %d cameras", __version__, len(self.cameras))

    async def stop(self) -> None:
        for task in (self._watcher, self._poller):
            if task:
                task.cancel()
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

    def transcoded(self) -> set[str]:
        """Cameras whose main stream must be encoded to record it (MJPEG)."""
        return {
            cid
            for cid, cam in self.cameras.items()
            if cam.driver and any(s.id == "main" and s.codec == "mjpeg" for s in cam.driver.streams())
        }

    async def refresh_device(self, camera_id: str) -> None:
        """Read a camera's state and check its firmware against the catalogue."""
        camera = self.cameras.get(camera_id)
        if not camera or not camera.driver or not camera.config.enabled:
            return
        try:
            device = await asyncio.wait_for(camera.driver.info(), 20)
        except TimeoutError:
            device = DeviceInfo(online=False, error="no answer within 20 s")
        except Exception as e:  # a driver bug must not stop the poller
            log.exception("%s: reading the device failed", camera_id)
            device = DeviceInfo(online=False, error=str(e))
        if self.cameras.get(camera_id) is not camera:
            return  # the camera changed meanwhile
        was_online = camera.device.online if camera.device else None
        camera.device = device
        camera.device_time = time.time()
        if device.online:
            camera.firmware = check(device.manufacturer, device.model, device.firmware)
        if was_online is not None and was_online != device.online:
            log.warning(
                "%s is %s", camera_id, "online again" if device.online else f"offline: {device.error}"
            )
        self.bus.publish("camera.device", {"camera": camera_id})

    async def refresh_devices(self, only_new: bool = False) -> None:
        ids = [cid for cid, cam in self.cameras.items() if not only_new or cam.device is None]
        await asyncio.gather(*(self.refresh_device(cid) for cid in ids))

    async def update_firmware(self, camera_id: str, image: bytes | None = None) -> None:
        """Install firmware: `image` from the user, or the driver's online update without it."""
        camera = self.cameras[camera_id]
        driver = self.get_driver(camera_id)
        if camera.update and camera.update.get("state") == "running":
            raise RuntimeError("an update is already running")
        camera.update = {"state": "running", "started": time.time(), "source": "file" if image else "online"}
        self.bus.publish("camera.device", {"camera": camera_id})
        log.warning("%s: installing firmware (%s)", camera_id, camera.update["source"])
        try:
            if image is not None:
                await driver.firmware_upload(image)
            else:
                await driver.firmware_online_update()
            camera.update = {"state": "done", "finished": time.time(), "source": camera.update["source"]}
        except Exception as e:
            log.error("%s: firmware update failed: %s", camera_id, e)
            camera.update = {"state": "failed", "error": str(e), "finished": time.time()}
            raise
        finally:
            self.bus.publish("camera.device", {"camera": camera_id})

    async def _poll_devices(self) -> None:
        while True:
            await self.refresh_devices()
            now = time.time()
            for cid, camera in list(self.cameras.items()):
                if now - camera.firmware_time >= FIRMWARE_INTERVAL:
                    camera.firmware_time = now
                    await self._check_online_firmware(cid, camera)
            await asyncio.sleep(DEVICE_INTERVAL)

    async def _check_online_firmware(self, camera_id: str, camera: Camera) -> None:
        """Ask the vendor for new firmware, where the driver can; auto-update if the camera wants it."""
        driver = camera.driver
        if not driver or Capability.FIRMWARE_ONLINE not in driver.capabilities():
            return
        try:
            latest = await driver.firmware_online_check()
        except Exception as e:
            log.info("%s: online firmware check failed: %s", camera_id, e)
            return
        if latest and camera.firmware:
            camera.firmware.latest = latest
            camera.firmware.status = "update"
        if latest and camera.config.auto_update:
            with contextlib.suppress(Exception):
                await self.update_firmware(camera_id)

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
        try:
            await self.go2rtc.apply(streams)
        except Go2rtcUnavailableError as e:
            # The config is saved; go2rtc picks the streams up from its file when it restarts.
            log.error("go2rtc didn't take the new streams: %s", e)
        await self.recorder.apply(self.config, streams, self.transcoded())
        self.bus.publish("cameras.changed")
        # Read new cameras right away instead of at the next poll.
        asyncio.create_task(self.refresh_devices(only_new=True))  # noqa: RUF006

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
