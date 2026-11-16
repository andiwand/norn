"""The hub ties the parts together: config, drivers, go2rtc, recorder and events."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from . import __version__
from .config import CameraConfig, CircleConfig, Config, ConfigError, ConfigStore
from .drivers import DRIVERS
from .drivers.base import Capability, Control, DeviceInfo, Driver, Preset
from .events import EventBus
from .firmware import FirmwareStatus, check
from .forecast import forecast, history
from .go2rtc import Go2rtc, Go2rtcUnavailableError
from .recorder import Recorder
from .recordings import Library
from .resources import Resources
from .settings import Settings

log = logging.getLogger("norn")

DEVICE_INTERVAL = 300  # seconds between two reads of each camera's state
STORAGE_CACHE = 15  # seconds a storage report stays fresh; it walks the folders


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
    # The last controls and presets read from the camera, so a page opens complete at once.
    controls: list[Control] | None = None
    presets: list[Preset] | None = None
    controls_time: float = 0
    controls_task: asyncio.Task[None] | None = field(default=None, repr=False)

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
            "picture_seconds": self.config.picture_seconds,
            "prebuffer_seconds": self.config.prebuffer_seconds,
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
        self._storage: tuple[float, dict[str, Any]] | None = None
        self._resources = Resources()
        self._resources_lock = asyncio.Lock()

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

    async def get_controls(self, camera_id: str, max_age: float = 30) -> tuple[list[Control], list[Preset]]:
        """The camera's controls: from the cache, refreshed in the background when older than max_age."""
        camera = self.cameras[camera_id]
        if camera.controls is None:
            await self.refresh_controls(camera_id)
        elif time.time() - camera.controls_time > max_age and not (
            camera.controls_task and not camera.controls_task.done()
        ):
            camera.controls_task = asyncio.create_task(self.refresh_controls(camera_id))
        return camera.controls or [], camera.presets or []

    async def refresh_controls(self, camera_id: str) -> None:
        camera = self.cameras.get(camera_id)
        if not camera or not camera.driver or not camera.config.enabled:
            return
        try:
            controls = await asyncio.wait_for(camera.driver.controls(), 30)
            presets = await asyncio.wait_for(camera.driver.presets(), 15)
        except Exception as e:
            log.info("%s: reading controls failed: %s", camera_id, e)
            return
        if self.cameras.get(camera_id) is not camera:
            return
        changed = (controls, presets) != (camera.controls, camera.presets)
        camera.controls, camera.presets, camera.controls_time = controls, presets, time.time()
        if changed:
            self.bus.publish("camera.controls", {"camera": camera_id})

    def remember_control(self, camera_id: str, control_id: str, value: Any) -> None:
        """Keep the cache in step with a change made through Norn."""
        camera = self.cameras.get(camera_id)
        for control in (camera.controls or []) if camera else []:
            if control.id == control_id and control.kind != "button":
                control.value = value

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
            # Keep the controls warm too, so a camera page never waits for the camera.
            await asyncio.gather(
                *(
                    self.refresh_controls(cid)
                    for cid, cam in self.cameras.items()
                    if cam.device is None or cam.device.online
                )
            )
            now = time.time()
            for cid, camera in list(self.cameras.items()):
                interval = self.config.firmware.check_hours * 3600
                if interval and now - camera.firmware_time >= interval:
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
        data = self.cameras[camera_id].to_json(self.recorder.status(camera_id))
        data["buffered"] = self.recorder.buffered(camera_id)
        return data

    async def resources(self) -> dict[str, Any]:
        # One measurement at a time: CPU is counted between two calls.
        async with self._resources_lock:
            return await asyncio.to_thread(self._resources.report)

    async def forecast(self) -> dict[str, Any]:
        """How much each trigger records per day, and where that leads (forecast.py)."""
        storage = await self.storage()
        now = datetime.now()
        retention = self.config.recording.retention_days

        def compute() -> dict[str, Any]:
            items = self.library.list(limit=1_000_000, since=now - history(retention))
            # Bitrates of cameras without a buffer, from their recent continuous files.
            bitrates = self.recorder.bitrates()
            for r in items:
                if r.trigger == "continuous" and r.duration and r.camera not in bitrates:
                    bitrates[r.camera] = r.size / r.duration
            return forecast(self.config, items, bitrates, storage["recordings"]["free"], now)

        return await asyncio.to_thread(compute)

    async def storage(self) -> dict[str, Any]:
        if self._storage is None or time.time() - self._storage[0] > STORAGE_CACHE:
            self._storage = (time.time(), await asyncio.to_thread(self.recorder.usage))
        return self._storage[1]

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

    async def put_settings(self, sections: dict[str, BaseModel]) -> None:
        async with self._lock:
            for name, values in sections.items():
                self.store.put_section(name, values)
            await self._apply()
        self.bus.publish("settings.changed")

    async def put_circle(self, circle_id: str, circle: CircleConfig) -> None:
        unknown = [c for c in circle.cameras if c not in self.config.cameras]
        if unknown:
            raise ConfigError(f"no camera {', '.join(unknown)}")
        async with self._lock:
            self.store.put_circle(circle_id, circle)
            await self._apply()

    async def remove_circle(self, circle_id: str) -> None:
        async with self._lock:
            self.store.remove_circle(circle_id)
            await self._apply()

    def circle_members(self, circle_id: str) -> list[str]:
        """The circle's cameras that exist and are enabled."""
        circle = self.config.circles[circle_id]
        return [c for c in circle.cameras if c in self.cameras and self.cameras[c].config.enabled]

    async def circle_controls(self, circle_id: str) -> list[dict[str, Any]]:
        """The controls every camera of the circle has, alike (same kind and choices), so one
        change can go to all. `value` is null and `mixed` true where the cameras differ."""
        members = self.circle_members(circle_id)
        if not members:
            return []
        lists = await asyncio.gather(*(self.get_controls(c) for c in members), return_exceptions=True)
        # A camera that can't be read now (no controls known) doesn't hide the others' controls.
        per_camera = [
            {c.id: c for c in result[0]}
            for camera_id, result in zip(members, lists, strict=True)
            if not isinstance(result, BaseException) and self.cameras[camera_id].controls is not None
        ]
        if not per_camera:
            return []
        first, *rest = per_camera
        common = []
        for control_id, control in first.items():
            others = [other.get(control_id) for other in rest]
            if any(o is None or not _alike(control, o) for o in others):
                continue
            values = [control.value, *(o.value for o in others if o is not None)]
            mixed = any(v != values[0] for v in values)
            data = control.model_dump(exclude_none=True)
            data["value"] = None if mixed else control.value
            data["mixed"] = mixed
            common.append(data)
        return common

    async def set_circle_control(self, circle_id: str, control_id: str, value: Any) -> dict[str, str]:
        """Set a control on every camera of the circle at once. Returns the errors by camera."""

        async def one(camera_id: str) -> None:
            await self.get_driver(camera_id).set_control(control_id, value)
            self.remember_control(camera_id, control_id, value)

        members = self.circle_members(circle_id)
        results = await asyncio.gather(*(one(c) for c in members), return_exceptions=True)
        return {c: str(r) for c, r in zip(members, results, strict=True) if isinstance(r, BaseException)}

    async def remove_camera(self, camera_id: str) -> None:
        async with self._lock:
            # Out of its circles first, so they stay valid.
            for circle_id in self.config.circles_of(camera_id):
                circle = self.config.circles[circle_id]
                cameras = [c for c in circle.cameras if c != camera_id]
                self.store.put_circle(circle_id, circle.model_copy(update={"cameras": cameras}))
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


def _alike(a: Control, b: Control) -> bool:
    """Two cameras' controls that one value fits: same kind, same choices or range."""
    return (
        a.kind == b.kind
        and [o.value for o in a.options or []] == [o.value for o in b.options or []]
        and (a.min, a.max) == (b.min, b.max)
    )


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
