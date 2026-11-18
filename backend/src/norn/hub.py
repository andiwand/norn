"""The hub ties the parts together: config, drivers, go2rtc, recorder and events."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from collections import OrderedDict
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from . import __version__
from .config import (
    CAMERA_ID,
    CameraConfig,
    CircleConfig,
    Config,
    ConfigError,
    ConfigStore,
    MqttSettings,
    NornPreset,
    short_error,
)
from .detect import OBJECT_KINDS, Detectors, MotionDetector, Tracker, gray_from_bgr
from .drivers import DRIVERS
from .drivers.base import (
    Capability,
    Control,
    DeviceInfo,
    Driver,
    Event,
    NotSupportedError,
    Preset,
    Stream,
)
from .events import EventBus
from .firmware import FirmwareStatus, check
from .forecast import forecast, history
from .go2rtc import Go2rtc, Go2rtcUnavailableError
from .gop import GopCache
from .labels import LABELS
from .mqtt import Mqtt
from .mqtt import defaults as mqtt_defaults
from .pilot import Pilot
from .probe import StreamProbe, probe_all, probeable
from .recorder import Recorder, ffprobe_of
from .recordings import Library
from .resources import Resources
from .secrets import public
from .settings import Settings
from .stills import Stills, StillStream

log = logging.getLogger("norn")

DEVICE_INTERVAL = 300  # seconds between two reads of each camera's state
# The transcoded stream for weak connections: small H.264 at a low, capped bitrate.
LOW = "low"
GOP_LINGER = 300.0  # seconds a GOP cache of a stream watched on demand stays after its last viewer
LOW_SOURCE = (
    "ffmpeg:{base}#video=h264#width=480"
    "#raw=-r 12 -g 24 -b:v 350k -maxrate 400k -bufsize 800k -preset superfast"
)
HOLD_INTERVAL = 5  # seconds between two extensions of a clip while a detection lasts
STORAGE_CACHE = 15  # seconds a storage report stays fresh; it walks the folders
RESOURCES_INTERVAL = 4  # seconds at least between two CPU measurements (each covers the time since the last)


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
    # Newer firmware the vendor offered at the last online check, and the camera's firmware then.
    online_latest: tuple[str | None, str] | None = None
    device_time: float = 0
    firmware_time: float = 0
    update: dict[str, Any] | None = field(default=None)  # a running or failed firmware update
    # The last controls and presets read from the camera, so a page opens complete at once.
    controls: list[Control] | None = None
    presets: list[Preset] | None = None
    controls_time: float = 0
    controls_task: asyncio.Task[None] | None = field(default=None, repr=False)
    # What the camera detects right now: event kind -> who detects it ("camera", "norn").
    detecting: dict[str, set[str]] = field(default_factory=dict)
    events_task: asyncio.Task[None] | None = field(default=None, repr=False)
    stills_task: asyncio.Task[None] | None = field(default=None, repr=False)  # Norn's detection
    detect_ms: float | None = None  # how long Norn's object detection takes on its stills
    # What probing found: each stream's resolution (or why it failed), and whether the camera
    # serves its streams at the same time. None: not probed (yet, or not RTSP).
    probe: dict[str, StreamProbe] | None = None
    concurrent: bool | None = None
    probe_task: asyncio.Task[None] | None = field(default=None, repr=False)
    web_url: str | None = None  # the camera's own web page, when it answers
    probe_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def camera_kinds(self) -> list[str]:
        driver = self.driver
        if driver and self.config.enabled and Capability.EVENTS in driver.capabilities():
            return driver.event_kinds()
        return []

    def events_json(self, norn: list[str] | None = None) -> dict[str, Any] | None:
        """What the camera can detect (by the camera itself, and by Norn), and what it detects now."""
        norn = norn or []
        camera = self.camera_kinds()
        if not camera and not norn:
            return None
        kinds = [k for k in LABELS if k in camera or k in norn]
        return {
            "kinds": kinds,
            "camera": camera,
            "norn": norn,
            "active": sorted(self.detecting),
            "detect_ms": round(self.detect_ms, 1) if self.detect_ms is not None else None,
        }

    def to_json(self, recording: dict[str, Any] | None) -> dict[str, Any]:
        driver = self.driver
        caps = sorted(driver.capabilities()) if driver and self.config.enabled else []
        return {
            "id": self.id,
            "name": self.config.name,
            "driver": self.config.driver,
            "enabled": self.config.enabled,
            "record": self.config.record,
            # Never the passwords: which secrets are set, and addresses with the password hidden.
            "options": public(self.config.options)[0],
            "secrets": public(self.config.options)[1],
            "error": self.error,
            "capabilities": caps,
            "recording": recording,
            "auto_update": self.config.auto_update,
            "picture_seconds": self.config.picture_seconds,
            "prebuffer_seconds": self.config.prebuffer_seconds,
            "clip_seconds": self.config.clip_seconds,
            "triggers": self.config.triggers,
            "stream_selection": self.config.streams,
            "ready_streams": self.config.ready_streams,
            "presets_norn": {k: v.model_dump() for k, v in self.config.presets.items()},
            "patrol": self.config.patrol.model_dump(by_alias=True) if self.config.patrol else None,
            "default_preset": self.config.default_preset,
            "reactions": [r.model_dump() for r in self.config.reactions],
            "follow": self.config.follow,
            "detection": self.config.detection.model_dump(exclude_none=True)
            if self.config.detection
            else None,
            "schedule": [w.model_dump(by_alias=True) for w in self.config.schedule]
            if self.config.schedule is not None
            else None,
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
        self.recorder.preset_of = self.preset_of
        self.cameras: dict[str, Camera] = {}
        self.config_error: str | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._poller: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._storage: tuple[float, dict[str, Any]] | None = None
        # Cameras recording because of detections: what holds each one (camera, kind), and the
        # task that keeps its clip going.
        self.detectors = Detectors(settings)
        self.pilots: dict[str, Pilot] = {}  # pan/tilt: presets, patrol, reactions, following
        self.stills = Stills(settings.ffmpeg_bin)
        self._still_cache: dict[str, tuple[bytes, float]] = {}
        self._leases: dict[str, float] = {}  # camera -> until when someone wants its stills
        self._lease_tasks: dict[str, asyncio.Task[None]] = {}
        self._preset_locks: dict[str, asyncio.Lock] = {}  # camera -> one preset change at a time
        self._tasks: set[asyncio.Task[Any]] = set()  # background tasks nobody waits for
        self.away = False  # away mode is on (now, or planned for now)
        self._away_task: asyncio.Task[None] | None = None
        self._held: dict[str, set[tuple[str, str]]] = {}
        self._holds: dict[str, asyncio.Task[None]] = {}
        self._resources = Resources()
        self._resources_lock = asyncio.Lock()
        self._resources_last: dict[str, Any] | None = None
        # Instant live video: each tile's stream kept ready from its newest keyframe; other
        # streams while watched, and a while after.
        self.gops: dict[str, GopCache] = {}
        self._gop_task: asyncio.Task[None] | None = None
        # Frames of recordings for the timeline: a few at a time, the latest kept.
        self._frames: OrderedDict[tuple[Path, float], bytes] = OrderedDict()
        self._frame_slots = asyncio.Semaphore(2)
        # Home Assistant and other home automation: config.yaml's `mqtt`, over the environment's.
        self.mqtt_defaults = mqtt_defaults(settings)
        self.mqtt = Mqtt(self.mqtt_defaults, self)

    @property
    def config(self) -> Config:
        return self.store.config

    def mqtt_settings(self) -> MqttSettings:
        return self.config.mqtt.over(self.mqtt_defaults)

    async def _apply_mqtt(self) -> None:
        """Connect again if the MQTT settings changed."""
        options = self.mqtt_settings()
        if options == self.mqtt.options:
            return
        await self.mqtt.stop()
        self.mqtt = Mqtt(options, self)
        await self.mqtt.start()
        log.info("MQTT %s", f"to {self.mqtt.broker.host}" if self.mqtt.broker else "off")
        self.bus.publish("mqtt.changed", {"connected": False})

    async def start(self) -> None:
        try:
            self.store.load()
        except ConfigError as e:
            # Start anyway, so the UI can show what's wrong instead of a dead page.
            self.config_error = str(e)
            log.error("%s", e)
        await self._build_cameras()
        await self.go2rtc.start(self.streams())
        self.away = self.config.away.now()
        await self.recorder.start(self.config, self.streams(), self.transcoded(), self.away)
        self._watcher = asyncio.create_task(self._watch_config(), name="config-watcher")
        self._poller = asyncio.create_task(self._poll_devices(), name="device-poller")
        self._away_task = asyncio.create_task(self._watch_away(), name="away")
        if self.go2rtc.enabled:
            self._gop_task = asyncio.create_task(self._keep_gops(), name="gop-keeper")
        self.mqtt = Mqtt(self.mqtt_settings(), self)
        await self.mqtt.start()
        log.info("Norn %s with %d cameras", __version__, len(self.cameras))

    async def stop(self) -> None:
        await self.mqtt.stop()  # first: it says "offline" while the broker still listens
        for pilot in self.pilots.values():
            pilot.stop()
        tasks = [self._watcher, self._poller, self._away_task, self._gop_task, *self._holds.values()]
        tasks += [p.task for p in self.pilots.values()]
        tasks += [*self._lease_tasks.values(), *self._tasks]
        for camera in self.cameras.values():
            tasks += [camera.events_task, camera.stills_task, camera.probe_task, camera.controls_task]
        running = [t for t in tasks if t and not t.done()]
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await asyncio.gather(*(cache.stop() for cache in self.gops.values()))
        self.gops.clear()
        await self.recorder.stop()
        await self.stills.stop()
        for camera in self.cameras.values():
            if camera.driver:
                with contextlib.suppress(Exception):
                    await camera.driver.stop()
        await self.go2rtc.stop()

    def streams(self) -> dict[str, str]:
        """All go2rtc streams: name -> source. Besides the camera's own, a `low` one, transcoded
        for weak connections; go2rtc runs its FFmpeg only while someone watches it."""
        found = {}
        for cid, cam in self.cameras.items():
            own = self.go2rtc_streams(cam)
            for sid, s in own:
                found[stream_name(cid, sid)] = s.source
            if own and self.needs_low(cam):
                found[stream_name(cid, LOW)] = LOW_SOURCE.format(base=stream_name(cid, own[-1][0]))
        return found

    def transcoded(self) -> set[str]:
        """Cameras whose main stream must be encoded to record it (MJPEG)."""
        return {
            cid
            for cid, cam in self.cameras.items()
            if (own := self.go2rtc_streams(cam)) and own[0][1].codec == "mjpeg"
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
        camera.web_url = await reachable(camera.driver.web_url()) if device.online else None
        camera.device_time = time.time()
        if device.online:
            camera.firmware = check(device.manufacturer, device.model, device.firmware)
            if camera.online_latest and camera.online_latest[0] == device.firmware:  # not updated since
                camera.firmware.latest, camera.firmware.status = camera.online_latest[1], "update"
        if was_online is not None and was_online != device.online:
            log.warning(
                "%s is %s", camera_id, "online again" if device.online else f"offline: {device.error}"
            )
        self.bus.publish("camera.device", {"camera": camera_id})

    async def get_controls(self, camera_id: str, max_age: float = 30) -> tuple[list[Control], list[Preset]]:
        """The camera's controls: from the cache, refreshed in the background when older than max_age."""
        camera = self.cameras[camera_id]
        if camera.controls is None and not camera.controls_time:  # never tried yet
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
            if self.cameras.get(camera_id) is camera:
                camera.controls_time = time.time()  # the next ask doesn't wait for it again
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
            camera.online_latest = None
        except Exception as e:
            log.error("%s: firmware update failed: %s", camera_id, e)
            camera.update = {"state": "failed", "error": str(e), "finished": time.time()}
            raise
        finally:
            self.bus.publish("camera.device", {"camera": camera_id})

    async def _poll_devices(self) -> None:
        while True:
            try:
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
            except Exception:
                log.exception("polling the cameras")
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
        camera.online_latest = (camera.device.firmware if camera.device else None, latest) if latest else None
        if latest and camera.firmware:
            camera.firmware.latest = latest
            camera.firmware.status = "update"
        if latest and camera.config.auto_update:  # a download can take minutes: not in the poller
            self._background(self.update_firmware(camera_id), f"firmware-{camera_id}")

    def norn_kinds(self, camera_id: str) -> list[str]:
        """What Norn's own detection looks for on the camera."""
        d = self.config.detection_for(camera_id)
        kinds = ["motion"] if d.motion else []
        if d.objects and self.detectors.unavailable is None:
            kinds += list(OBJECT_KINDS)
        return kinds

    # Streams: the camera's own (probed, enabled by the user) and the transcoded low one.
    def active_streams(self, camera: Camera) -> list[Stream]:
        """The streams Norn uses for the camera, best first. The first one is the camera's
        main stream in go2rtc (named after the camera), whatever its id."""
        driver = camera.driver
        if not driver or not camera.config.enabled:
            return []
        base = driver.streams()
        probe = camera.probe
        if probe is None:
            working = base  # not probed: trust the driver
        else:
            known = [*base, *driver.extra_streams()]
            working = [s for s in known if ((p := probe.get(s.id)) is None and s in base) or (p and p.ok)]
            working.sort(key=lambda s: -(probe[s.id].pixels if s.id in probe else 1 << 40))
        wanted = camera.config.streams
        chosen = [s for s in working if wanted is None or s.id in wanted]
        if camera.concurrent is False:
            chosen = chosen[:1]  # it serves one stream at a time
        return chosen or working[:1] or base[:1]

    def go2rtc_streams(self, camera: Camera) -> list[tuple[str, Stream]]:
        """(the id the web app uses, the stream): the first is "main"."""
        active = self.active_streams(camera)
        return [("main" if i == 0 else s.id, s) for i, s in enumerate(active)]

    def needs_low(self, camera: Camera) -> bool:
        """A transcoded stream only when the camera has no small one of its own."""
        streams = self.active_streams(camera)
        if not streams:
            return False
        smallest = streams[-1]
        probe = (camera.probe or {}).get(smallest.id)
        if smallest.codec == "mjpeg" or (probe and probe.codec == "mjpeg"):
            return True
        if probe and probe.width:
            return probe.width > 640
        return len(streams) == 1

    def stream_ids(self, camera_id: str) -> set[str]:
        camera = self.cameras.get(camera_id)
        if camera is None:
            return set()
        ids = {sid for sid, _ in self.go2rtc_streams(camera)}
        return ids | ({LOW} if self.needs_low(camera) else set())

    def streams_json(self, camera: Camera) -> list[dict[str, Any]]:
        found = []
        for sid, s in self.go2rtc_streams(camera):
            p = (camera.probe or {}).get(s.id)
            found.append(
                {
                    "id": sid,
                    "label": s.label,
                    "name": stream_name(camera.id, sid),
                    "codec": s.codec or (p.codec if p else None),
                    **({"width": p.width, "height": p.height, "fps": p.fps} if p and p.ok else {}),
                }
            )
        if self.needs_low(camera):
            found.append(
                {"id": LOW, "label": "Low", "name": stream_name(camera.id, LOW), "codec": "h264",
                 "transcoded": True}
            )  # fmt: skip
        return found

    def stream_options(self, camera: Camera) -> list[dict[str, Any]]:
        """Every stream the camera may have, for the user to switch on and off."""
        if not camera.driver:
            return []
        active = {s.id for s in self.active_streams(camera)}
        ready = self.ready_streams(camera)
        options = []
        for s in [*camera.driver.streams(), *camera.driver.extra_streams()]:
            p = (camera.probe or {}).get(s.id)
            if p is not None and not p.ok and s not in camera.driver.streams():
                continue  # an extra stream this camera doesn't have
            options.append(
                {
                    "id": s.id,
                    "label": s.label,
                    "active": s.id in active,
                    "probe": p.to_json() if p else None,
                    "ready": s.id in ready,
                    "can_be_ready": self._instant_capable(camera, s),
                }
            )
        return options

    async def _probe(self, camera: Camera, retry: bool = True) -> None:
        """Find out which streams work, and whether at the same time; then offer them. When no
        stream works (the camera is off, say), it stays unprobed and Norn tries again later."""
        driver = camera.driver
        ffprobe = ffprobe_of(self.settings.ffmpeg_bin)
        if not driver or not self.recorder.available or shutil.which(ffprobe) is None:
            return
        sources = {s.id: s.source for s in [*driver.streams(), *driver.extra_streams()]}
        if not any(probeable(s) for s in sources.values()):
            return
        delay = 60.0
        while True:
            await self.go2rtc.ready.wait()
            async with camera.probe_lock:  # one probe at a time, or the camera sees double
                probes, concurrent = await probe_all(ffprobe, sources)
            if any(p.ok for p in probes.values()) or not retry:
                break
            log.info("%s: no stream answers; testing again in %.0f s", camera.id, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 1800)
        if self.cameras.get(camera.id) is not camera or not any(p.ok for p in probes.values()):
            return
        camera.probe, camera.concurrent = probes, concurrent
        found = ", ".join(
            f"{i} {p.width}x{p.height}" if p.ok else f"{i}: {p.error}" for i, p in probes.items()
        )
        log.info("%s: streams %s%s", camera.id, found, "" if concurrent is not False else " (one at a time)")
        async with self._lock:
            await self._restream()

    async def probe_streams(self, camera_id: str) -> None:
        camera = self.cameras[camera_id]
        try:
            await asyncio.wait_for(self.go2rtc.ready.wait(), 10)
        except TimeoutError:
            raise RuntimeError("go2rtc isn't running") from None
        await self._probe(camera, retry=False)

    async def _restream(self) -> None:
        """Hand go2rtc and the recorder the streams as they are now."""
        streams = self.streams()
        try:
            await self.go2rtc.apply(streams)
        except Go2rtcUnavailableError as e:
            log.error("go2rtc didn't take the new streams: %s", e)
        await self.recorder.apply(self.config, streams, self.transcoded(), self.away)
        self.bus.publish("cameras.changed")

    def camera_json(self, camera_id: str) -> dict[str, Any]:
        camera = self.cameras[camera_id]
        data = camera.to_json(self.recorder.status(camera_id))
        data["streams"] = self.streams_json(camera)
        data["stream_options"] = self.stream_options(camera)
        data["concurrent"] = camera.concurrent
        data["web_url"] = camera.web_url
        data["events"] = camera.events_json(self.norn_kinds(camera_id) if camera.config.enabled else [])
        data["buffered"] = self.recorder.prebuffer_now(camera_id)
        return data

    async def resources(self) -> dict[str, Any]:
        # CPU is counted between two measurements: one at a time, and at most one every few
        # seconds (others get the last one), so pages that ask at once don't read tiny windows.
        async with self._resources_lock:
            last = self._resources_last
            if last is None or time.time() - last["time"] >= RESOURCES_INTERVAL:
                self._resources_last = last = await asyncio.to_thread(self._resources.report)
            return last

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
            recordings = storage["recordings"]
            return forecast(self.config, items, bitrates, recordings["free"], now, recordings["used"])

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
        driver_options(camera)
        async with self._lock:
            self.store.put_camera(camera_id, camera)
            await self._apply()

    async def save_preset(
        self, camera_id: str, preset_id: str, name: str, slot: str | None, controls: list[str]
    ) -> NornPreset:
        """Make or change a Norn preset from what the camera shows now: the view goes into a
        preset slot of the camera (a free one, unless `slot`), the `controls` named keep their
        current values, and a picture shows the view."""
        if not CAMERA_ID.fullmatch(preset_id):
            raise ConfigError(f"id {preset_id!r} must be lowercase letters, digits and dashes")
        async with self._preset_lock(camera_id):  # two at once would take the same free slot
            return await self._save_preset(camera_id, preset_id, name, slot, controls)

    def _preset_lock(self, camera_id: str) -> asyncio.Lock:
        return self._preset_locks.setdefault(camera_id, asyncio.Lock())

    async def _save_preset(
        self, camera_id: str, preset_id: str, name: str, slot: str | None, controls: list[str]
    ) -> NornPreset:
        driver = self.get_driver(camera_id)
        camera = self.cameras[camera_id]
        existing = camera.config.presets.get(preset_id)
        if slot is None:
            slot = existing.slot if existing else None
        if slot is None and not driver.preset_slots():
            slot = f"norn-{preset_id}"  # the camera takes any id (a name)
        if slot is None:
            taken = {p.slot for p in camera.config.presets.values()}
            free = [s for s in driver.preset_slots() if s not in taken]
            if not free:
                raise ValueError("the camera has no free preset slot")
            slot = free[-1]  # from the end: the camera's own presets usually start at the front
        slot = await driver.save_preset(slot, name) or slot  # ONVIF: the camera picks the token
        if self.cameras[camera_id].controls is None:  # an earlier read failed: try again, and wait
            await self.refresh_controls(camera_id)
        current, _ = await self.get_controls(camera_id, max_age=0)
        values = {c.id: c.value for c in current if c.id in controls and c.kind != "button"}
        # A new view and settings; what it records at the preset stays.
        update = {"name": name, "slot": slot, "controls": values}
        preset = existing.model_copy(update=update) if existing else NornPreset(**update)
        jpeg = await self.still_jpeg(camera_id, max_age=2)
        pilot = self.pilots[camera_id]
        if jpeg:
            path = pilot.picture(preset_id)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, jpeg)
        presets = {**camera.config.presets, preset_id: preset}
        await self.put_camera(camera_id, camera.config.model_copy(update={"presets": presets}))
        return preset

    async def remove_preset(self, camera_id: str, preset_id: str) -> None:
        async with self._preset_lock(camera_id):
            cfg = self.cameras[camera_id].config
            if preset_id not in cfg.presets:
                raise KeyError(preset_id)
            presets = {k: v for k, v in cfg.presets.items() if k != preset_id}
            patrol = cfg.patrol
            if patrol and preset_id in patrol.presets:
                patrol = patrol.model_copy(update={"presets": [p for p in patrol.presets if p != preset_id]})
            default = None if cfg.default_preset == preset_id else cfg.default_preset
            update = {"presets": presets, "patrol": patrol, "default_preset": default}
            await self.put_camera(camera_id, cfg.model_copy(update=update))
        self.pilots[camera_id].picture(preset_id).unlink(missing_ok=True)

    async def set_preset_recording(
        self, camera_id: str, preset_id: str, values: dict[str, Any]
    ) -> NornPreset:
        """What records while the camera is at a preset: triggers, clip_seconds and
        prebuffer_seconds (None: the camera's)."""
        cfg = self.cameras[camera_id].config
        if preset_id not in cfg.presets:
            raise KeyError(preset_id)
        try:
            preset = NornPreset.model_validate({**cfg.presets[preset_id].model_dump(), **values})
        except ValidationError as e:
            raise ConfigError(short_error(e)) from e
        await self.put_camera(
            camera_id, cfg.model_copy(update={"presets": {**cfg.presets, preset_id: preset}})
        )
        return preset

    async def set_default_preset(self, camera_id: str, preset_id: str | None) -> None:
        cfg = self.cameras[camera_id].config
        if preset_id is not None and preset_id not in cfg.presets:
            raise KeyError(preset_id)
        await self.put_camera(camera_id, cfg.model_copy(update={"default_preset": preset_id}))

    async def order_cameras(self, ids: list[str]) -> None:
        async with self._lock:
            self.store.order_cameras(ids)
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
        if not self.store.changed_on_disk():
            self.config_error = None  # Norn runs what the file says: an earlier load's error is gone
        await self._build_cameras()
        streams = self.streams()
        try:
            await self.go2rtc.apply(streams)
        except Go2rtcUnavailableError as e:
            # The config is saved; go2rtc picks the streams up from its file when it restarts.
            log.error("go2rtc didn't take the new streams: %s", e)
        away = self.config.away.now()
        if away != self.away:
            self.away = away
            log.warning("away mode %s", "on" if away else "off")
            self.bus.publish("away.changed", {"away": away})
        await self.recorder.apply(self.config, streams, self.transcoded(), away)
        await self._apply_mqtt()
        self.bus.publish("cameras.changed")
        # Read new cameras right away instead of at the next poll.
        self._background(self.refresh_devices(only_new=True), "refresh-devices")

    def _background(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        """A task nobody waits for: kept until it ends (stop() cancels it), its error logged."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (e := task.exception()):
            log.warning("%s: %s", task.get_name(), e)

    async def _build_cameras(self) -> None:
        """Create drivers for new or changed cameras; keep the ones that didn't change."""
        old = self.cameras
        new: dict[str, Camera] = {}
        for cid, cfg in self.config.cameras.items():
            previous = old.get(cid)
            if previous and previous.config == cfg:
                new[cid] = previous
                continue
            if previous and _same_device(previous.config, cfg):
                # Only Norn's own settings changed (name, triggers, schedule, streams, ...):
                # keep the driver, its connection, its probe and its watchers.
                previous.config = cfg
                new[cid] = previous
                continue
            new[cid] = self._make_camera(cid, cfg)
        # New drivers start together: a camera that doesn't answer mustn't hold up the others.
        starting = [c for cid, c in new.items() if c is not old.get(cid) and c.driver and c.config.enabled]
        results = await asyncio.gather(
            *(asyncio.wait_for(c.driver.start(), 20) for c in starting if c.driver), return_exceptions=True
        )
        for camera, result in zip(starting, results, strict=True):
            if isinstance(result, Exception):
                log.warning("%s: starting failed: %s", camera.id, str(result) or type(result).__name__)
        for cid, camera in old.items():
            if new.get(cid) is not camera:
                tasks = [camera.events_task, camera.stills_task, camera.probe_task, camera.controls_task]
                for task in [*tasks, self._lease_tasks.pop(cid, None)]:
                    if task:
                        task.cancel()
                self._leases.pop(cid, None)
                self._release(cid, gone=cid not in new)
                self._still_cache.pop(cid, None)
                if cid not in new:
                    await self.stills.forget(cid)
                    if pilot := self.pilots.pop(cid, None):
                        pilot.stop()
                if camera.driver:
                    with contextlib.suppress(Exception):
                        await camera.driver.stop()
        self.cameras = new
        for camera in new.values():
            if camera.id not in self.pilots:
                self.pilots[camera.id] = Pilot(self, camera.id)
            if camera.probe_task is None and camera.driver and camera.config.enabled:
                camera.probe_task = asyncio.create_task(self._probe(camera), name=f"probe-{camera.id}")
            if camera.stills_task is None and camera.driver and camera.config.enabled:
                camera.stills_task = asyncio.create_task(
                    self._watch_stills(camera), name=f"detect-{camera.id}"
                )
            driver = camera.driver
            if (
                camera.events_task is None
                and driver
                and camera.config.enabled
                and Capability.EVENTS in driver.capabilities()
            ):
                camera.events_task = asyncio.create_task(
                    self._watch_events(camera), name=f"events-{camera.id}"
                )

    def _release(self, camera_id: str, gone: bool) -> None:
        """A camera was replaced or removed: what it detected ends, and so do the clips it held."""
        for held in self._held.values():
            for source in [s for s in held if s[0] == camera_id]:
                held.discard(source)
        if gone:
            self._held.pop(camera_id, None)
            if task := self._holds.pop(camera_id, None):
                task.cancel()

    # Camera events (motion, people, ...) as recording triggers.
    async def _watch_events(self, camera: Camera) -> None:
        """Listen to a camera's detections for as long as it exists; reconnect when it drops."""
        delay = 5.0
        while True:
            assert camera.driver is not None
            connected = time.monotonic()
            try:
                async for event in camera.driver.events():
                    delay = 5.0
                    self.on_event(camera.id, event, "camera")
            except asyncio.CancelledError:
                raise
            except NotSupportedError:
                return
            except Exception as e:
                log.info("%s: events stopped: %s; again in %.0f s", camera.id, e, delay)
            for kind in list(camera.detecting):  # without a connection, nothing is detected
                self.on_event(camera.id, Event(kind=kind, active=False), "camera")
            if time.monotonic() - connected > 60:
                delay = 5.0  # it was up a while: a camera that closes quiet streams now and then
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    def triggers_of(self, camera_id: str) -> set[str]:
        """What starts a clip on the camera now (its schedule and away mode included)."""
        return self.config.triggers(camera_id, preset=self.preset_of(camera_id))

    def preset_of(self, camera_id: str) -> str | None:
        """The Norn preset the camera is at, if it's a pan/tilt camera that sits at one."""
        pilot = self.pilots.get(camera_id)
        return pilot.at_preset if pilot is not None else None

    async def _watch_away(self) -> None:
        """Planned away times start and end by the clock: notice it, and apply the change."""
        while True:
            await asyncio.sleep(30)
            try:
                if self.config.away.now() != self.away:
                    async with self._lock:
                        await self._apply()
            except Exception:
                log.exception("away mode")

    def on_event(self, camera_id: str, event: Event, by: str = "camera") -> None:
        """Something was detected on a camera (by the camera itself, or by Norn), or stopped:
        publish it, and record if it is a trigger. A kind counts as long as anyone detects it.
        Never raises: the watchers that call it must keep running."""
        try:
            self._on_event(camera_id, event, by)
        except Exception:
            log.exception("%s: handling %s failed", camera_id, event.kind)

    def _on_event(self, camera_id: str, event: Event, by: str) -> None:
        camera = self.cameras.get(camera_id)
        if camera is None:
            return
        was = event.kind in camera.detecting
        sources = camera.detecting.setdefault(event.kind, set())
        if event.active:
            sources.add(by)
        else:
            sources.discard(by)
            if not sources:
                del camera.detecting[event.kind]
        now = event.kind in camera.detecting
        if was != now:
            self.bus.publish(
                "camera.event", {"camera": camera_id, "kind": event.kind, "active": now, "by": by}
            )
        source = (camera_id, event.kind)
        if not now:
            for held in self._held.values():
                held.discard(source)
            return
        if not was:
            self._react(camera_id, event.kind)
        if event.kind not in self.triggers_of(camera_id):
            return
        # The camera records; in a circle that records together, all its cameras do.
        targets = {camera_id}
        for circle_id in self.config.circles_of(camera_id):
            if self.config.circles[circle_id].together:
                targets |= set(self.circle_members(circle_id))
        for target in targets:
            self._held.setdefault(target, set()).add(source)
            task = self._holds.get(target)
            if task is None or task.done():
                self._holds[target] = asyncio.create_task(self._hold(target, event.kind))

    def _react(self, source: str, kind: str) -> None:
        """Cameras with a reaction to this detection turn to one of its presets."""
        for cid, cfg in self.config.cameras.items():
            pilot = self.pilots.get(cid)
            if pilot is None or not cfg.enabled:
                continue
            for reaction in cfg.reactions:
                watched = reaction.cameras or [cid]
                if kind in reaction.kinds and source in watched:
                    self._background(pilot.react(reaction.presets, reaction.hold_seconds), f"react-{cid}")
                    break

    async def still_jpeg(self, camera_id: str, max_age: float = 15) -> bytes | None:
        """The camera's newest still, fast: from a running still stream, else the RAM buffer's
        newest keyframe (no new connection), else go2rtc. Kept a few seconds for other viewers."""
        self._lease_stills(camera_id)
        jpeg = self.stills.latest(camera_id, "jpeg", max_age)
        if jpeg is not None:
            return jpeg
        cached = self._still_cache.get(camera_id)
        if cached and time.monotonic() - cached[1] < min(max_age, 5):
            return cached[0]
        jpeg = None
        cache = self._gop_of(camera_id)  # the newest keyframe, without waiting for the next
        if cache is not None and time.monotonic() - cache.keyframe_at <= max(max_age, 2):
            jpeg = await self._gop_jpeg(cache)
            if jpeg:
                self._still_cache[camera_id] = (jpeg, time.monotonic())
                return jpeg
        piece = self.recorder.keyframe_piece(camera_id)
        if piece is not None:
            jpeg = await self.recorder.piece_jpeg(piece)
        if jpeg is None:
            with contextlib.suppress(Go2rtcUnavailableError):
                jpeg = await self.go2rtc.frame(camera_id)
        if jpeg:
            self._still_cache[camera_id] = (jpeg, time.monotonic())
        return jpeg

    # Instant live video

    def _instant_capable(self, camera: Camera, s: Stream) -> bool:
        """Not MJPEG (MSE can't play it), not made by FFmpeg (it would encode all the time)."""
        p = (camera.probe or {}).get(s.id)
        return (s.codec or (p.codec if p else None)) != "mjpeg" and not s.source.startswith("ffmpeg:")

    def ready_streams(self, camera: Camera) -> set[str]:
        """The camera's stream ids kept ready: as set, else the Live page's (sub, else main)."""
        if camera.config.ready_streams is not None:
            return set(camera.config.ready_streams)
        ids = dict(self.go2rtc_streams(camera))
        tile = ids.get("sub") or ids.get("main")
        return {tile.id} if tile else set()

    def _gop_streams(self) -> dict[str, tuple[Stream, bool]]:
        """go2rtc name -> (stream, kept ready) of each stream a cache may serve."""
        found = {}
        for camera in self.cameras.values():
            ready = self.ready_streams(camera)
            for sid, s in self.go2rtc_streams(camera):
                if self._instant_capable(camera, s):
                    found[stream_name(camera.id, sid)] = (s, s.id in ready)
        return found

    def _new_gop(self, name: str, s: Stream) -> GopCache:
        cache = self.gops[name] = GopCache(self.go2rtc.ws_url(name), name, s.source)
        return cache

    def gop(self, camera_id: str, stream_id: str) -> GopCache | None:
        """The stream's cache, started now if needed (None: not for this stream)."""
        camera = self.cameras.get(camera_id)
        if camera is None or not self.go2rtc.enabled:
            return None
        s = dict(self.go2rtc_streams(camera)).get(stream_id)
        if s is None or not self._instant_capable(camera, s):
            return None
        name = stream_name(camera_id, stream_id)
        cache = self.gops.get(name) or self._new_gop(name, s)
        cache.last_used = time.monotonic()
        return cache

    async def _keep_gops(self) -> None:
        """Ready streams always, others while watched and GOP_LINGER after; a new source restarts."""
        while True:
            await self.go2rtc.ready.wait()
            try:
                wanted, now = self._gop_streams(), time.monotonic()
                for name, cache in list(self.gops.items()):
                    s, ready = wanted.get(name, (None, False))
                    idle = cache.viewers == 0 and now - cache.last_used > GOP_LINGER
                    if s is None or s.source != cache.source or (not ready and idle):
                        del self.gops[name]
                        await cache.stop()
                for name, (s, ready) in wanted.items():
                    if ready and name not in self.gops:
                        self._new_gop(name, s)
            except Exception:
                log.exception("instant live video")
            await asyncio.sleep(5)

    def _gop_of(self, camera_id: str) -> GopCache | None:
        """A cache of the camera with a keyframe: the sub stream's, else a ready one's."""
        camera = self.cameras.get(camera_id)
        if camera is None:
            return None
        ready = self.ready_streams(camera)
        found = [
            (sid != "sub", s.id not in ready, cache)
            for sid, s in self.go2rtc_streams(camera)
            if (cache := self.gops.get(stream_name(camera_id, sid))) and cache.keyframe()
        ]
        return min(found, key=lambda f: f[:2])[2] if found else None

    async def _gop_jpeg(self, cache: GopCache) -> bytes | None:
        """A still of the cache's newest keyframe, decoded once per keyframe."""
        if (jpeg := cache.cached_jpeg()) is not None:
            return jpeg
        if (frames := cache.keyframe()) is None:
            return None
        process = await asyncio.create_subprocess_exec(
            self.settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", "mp4", "-i", "pipe:0",
            "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(process.communicate(frames[0] + frames[1]), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
            return None
        if process.returncode != 0 or not out:
            return None
        cache.keep_jpeg(frames[1], out)
        return out

    async def video_frame(self, path: Path, at: float) -> bytes | None:
        """The frame `at` seconds into a video file, 480 pixels wide, as a JPEG."""
        key = (path, round(at, 1))
        if (jpeg := self._frames.get(key)) is not None:
            self._frames.move_to_end(key)
            return jpeg
        async with self._frame_slots:
            process = await asyncio.create_subprocess_exec(
                self.settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-ss", str(key[1]),
                "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "5",
                "-f", "image2", "-c:v", "mjpeg", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            try:
                jpeg, _ = await asyncio.wait_for(process.communicate(), 10)
            except TimeoutError:
                return None
            finally:
                if process.returncode is None:  # timed out, or the request was cancelled
                    process.kill()
                    await process.wait()
        if process.returncode != 0 or not jpeg:
            return None
        self._frames[key] = jpeg
        while len(self._frames) > 200:
            self._frames.popitem(last=False)
        return jpeg

    def _lease_stills(self, camera_id: str, seconds: float = 30) -> None:
        """Someone asks for stills of the camera (a tile of the Live page, every few seconds):
        keep its keyframe still stream running for a while, so the next ones come from there,
        nearly free, instead of decoding a keyframe of the buffer each time."""
        camera = self.cameras.get(camera_id)
        if camera is None or not self.recorder.available:
            return
        self._leases[camera_id] = time.monotonic() + seconds
        task = self._lease_tasks.get(camera_id)
        if task is None or task.done():

            async def hold() -> None:
                stream = self.still_stream(camera, "keyframe")
                async with stream.subscribe("jpeg", 1):
                    # Sleep until the lease runs out; a request meanwhile moves its end.
                    while (left := self._leases.get(camera_id, 0) - time.monotonic()) > 0:  # noqa: ASYNC110
                        await asyncio.sleep(left)

            self._lease_tasks[camera_id] = asyncio.create_task(hold(), name=f"still-lease-{camera_id}")

    def still_aspect(self, camera: Camera) -> float:
        """Width over height of the stream the stills come from (16:9 when not known)."""
        own = self.go2rtc_streams(camera)
        probe = (camera.probe or {}).get(own[-1][1].id) if own else None
        return probe.width / probe.height if probe and probe.width and probe.height else 16 / 9

    def still_source(self, camera: Camera) -> str:
        """Where the camera's still streams read from: its smallest stream of its own."""
        own = self.go2rtc_streams(camera)
        return self.go2rtc.rtsp_url(stream_name(camera.id, own[-1][0] if own else "main"))

    def still_stream(self, camera: Camera, mode: str) -> StillStream:
        return self.stills.stream(camera.id, self.still_source(camera), mode)  # type: ignore[arg-type]

    async def _watch_stills(self, camera: Camera) -> None:
        """Norn's own detection on one camera, on its still stream. The settings are read on
        every still, so a change takes effect without a restart; with detection off, nothing
        subscribes and the stream idles."""
        motion = MotionDetector()
        tracker = Tracker()
        active: dict[str, float] = {}  # kind -> when Norn last saw it

        def end(kind: str) -> None:
            del active[kind]
            self.on_event(camera.id, Event(kind=kind, active=False), "norn")

        gap = 0.0  # the measured time between stills (keyframes can be far apart)
        pilot = self.pilots.get(camera.id)

        def norn_follows() -> bool:
            """Norn steers the camera after people: following is wanted, and the camera can't
            track by itself."""
            return bool(
                pilot
                and pilot.follow_wanted()
                and not pilot.own_tracking()
                and self.detectors.unavailable is None
            )

        def settings() -> Any:
            """The detection settings now; following needs people, often."""
            d = self.config.detection_for(camera.id)
            if norn_follows():
                d = d.model_copy(update={"objects": True, "stills": "live", "every_seconds": 0.5})
            return d

        while True:
            d = settings()
            objects = d.objects and self.detectors.unavailable is None
            if not (d.motion or objects) or not self.go2rtc.ready.is_set() or not self.recorder.available:
                for kind in list(active):
                    end(kind)
                await asyncio.sleep(2)
                continue
            fmt = "bgr" if objects else "gray"
            mode = "live" if d.stills == "live" else "keyframe"
            wanted = (fmt, mode, d.every_seconds)
            stream = self.still_stream(camera, mode)
            last_still = None
            async with stream.subscribe(fmt, d.every_seconds) as sub:
                while True:
                    quiet = max(10.0, 3 * d.every_seconds, 2.5 * gap)
                    try:
                        data: bytes | None = await asyncio.wait_for(sub.queue.get(), quiet)
                    except TimeoutError:
                        data = None  # no stills (the camera is gone?): detections end below
                    now = time.monotonic()
                    if data is not None:
                        if last_still is not None:
                            gap = now - last_still if gap == 0 else gap * 0.8 + (now - last_still) * 0.2
                        last_still = now
                    d = settings()
                    following = norn_follows()
                    seen: set[str] = set()
                    try:
                        if data and d.motion:
                            motion.sensitivity = d.sensitivity
                            if motion.update(data if fmt == "gray" else gray_from_bgr(data)):
                                seen.add("motion")
                        if data and d.objects and fmt == "bgr":
                            found, ms = await self.detectors.detect(d.model, data, d.min_score)
                            before = camera.detect_ms
                            camera.detect_ms = ms if before is None else before * 0.8 + ms * 0.2
                            # Following steers by every sighting; recording waits for confirmation.
                            seen |= tracker.update(found, now, d.confirm_seconds)
                            if following and pilot:
                                people = [f for f in found if f.kind == "person"]
                                await pilot.nudge(people, self.still_aspect(camera))
                    except Exception as e:
                        log.warning("%s: detection failed: %s", camera.id, e)
                    for kind in seen:
                        if kind not in active:
                            self.on_event(camera.id, Event(kind=kind, active=True), "norn")
                        active[kind] = now
                    for kind, last in list(active.items()):
                        if now - last > quiet:
                            end(kind)
                    objects = d.objects and self.detectors.unavailable is None
                    changed = ("bgr" if objects else "gray", "live" if d.stills == "live" else "keyframe")
                    if not (d.motion or objects) or (*changed, d.every_seconds) != wanted:
                        break  # subscribe again with the new settings
                    if self.still_source(camera) != stream.source:
                        break  # the camera's streams changed (probing, the user): follow them

    async def _hold(self, camera_id: str, trigger: str) -> None:
        """Keep a camera's clip going while what triggered it lasts; it then runs `clip_seconds`
        longer, like after a button press."""
        held = self._held.setdefault(camera_id, set())
        while held and camera_id in self.cameras:
            try:
                kinds = sorted({kind for _, kind in held})
                for kind in [trigger, *[k for k in kinds if k != trigger]]:
                    await self.recorder.record_clip(camera_id, kind)
            except RuntimeError as e:  # no FFmpeg or go2rtc
                log.info("%s: can't record %s: %s", camera_id, trigger, e)
                held.clear()
                return
            except Exception:
                log.exception("%s: recording on %s failed", camera_id, trigger)
            await asyncio.sleep(HOLD_INTERVAL)

    def _make_camera(self, cid: str, cfg: CameraConfig) -> Camera:
        try:
            cls, options = driver_options(cfg)
        except ConfigError as e:
            return Camera(cid, cfg, None, str(e))
        return Camera(cid, cfg, cls(cid, options, self._driver_event))

    def _driver_event(self, type_: str, data: dict[str, Any]) -> None:
        """An event from a driver, for the bus. New streams (a camera that was offline when Norn
        started) also go to go2rtc and the recorder."""
        self.bus.publish(type_, data)
        if type_ == "camera.streams":
            self._background(self._streams_changed(data["camera"]), f"streams-{data['camera']}")

    async def _streams_changed(self, camera_id: str) -> None:
        async with self._lock:
            await self._restream()
        camera = self.cameras.get(camera_id)  # read after the lock: an edit may have replaced it
        if (
            camera is not None
            and camera.probe is None
            and camera.probe_task is not None
            and camera.probe_task.done()
        ):
            camera.probe_task = asyncio.create_task(self._probe(camera), name=f"probe-{camera_id}")

    async def _watch_config(self) -> None:
        # Polling the mtime every two seconds costs nothing and works on every file system,
        # including the bind mounts of Docker Desktop, where inotify often doesn't.
        while True:
            await asyncio.sleep(2)
            try:
                if self.store.changed_on_disk():
                    await self.reload()
            except Exception:
                log.exception("reloading the config")


async def reachable(url: str | None, timeout: float = 2) -> str | None:
    """`url` if something answers on its port, else None."""
    if not url:
        return None
    parts = urlsplit(url)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:  # not a valid port (or an IPv6 address without brackets)
        return None
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(parts.hostname, port), timeout)
    except (OSError, TimeoutError):
        return None
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return url


def _same_device(a: CameraConfig, b: CameraConfig) -> bool:
    """The same camera, connected the same way: only Norn's settings for it differ."""
    return (a.driver, a.enabled, a.options) == (b.driver, b.enabled, b.options)


def _alike(a: Control, b: Control) -> bool:
    """Two cameras' controls that one value fits: same kind, same choices or range."""
    return (
        a.kind == b.kind
        and [o.value for o in a.options or []] == [o.value for o in b.options or []]
        and (a.min, a.max) == (b.min, b.max)
    )


def driver_options(camera: CameraConfig) -> tuple[type[Driver], BaseModel]:
    """The camera's driver and its options; ConfigError if either is wrong."""
    cls = DRIVERS.get(camera.driver)
    if cls is None:
        raise ConfigError(f"unknown driver {camera.driver!r}")
    try:
        return cls, cls.Options.model_validate(camera.options)
    except ValidationError as e:
        raise ConfigError(short_error(e)) from e
