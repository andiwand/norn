"""Recording with FFmpeg, without re-encoding the video.

FFmpeg reads the camera's stream from go2rtc's local RTSP server, so recording doesn't open a
second connection to the camera. The video is copied as is (`-c:v copy`). Audio is converted to
AAC, because MP4 can't hold the G.711 audio many cameras send; that costs very little CPU.

- Continuous: one FFmpeg per camera writes a new file every `segment_minutes`, on the clock.
- Clips: a triggered recording of `clip_seconds` (manual button, webhook, later motion events),
  with a thumbnail and a JSON sidecar.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .events import EventBus
from .go2rtc import Go2rtc, Go2rtcUnavailableError
from .recordings import Library
from .settings import Settings

log = logging.getLogger("norn.recorder")

FRAGMENTED = "movflags=+frag_keyframe+empty_moov+default_base_moof"


def segment_command(ffmpeg: str, source: str, folder: Path, seconds: int) -> list[str]:
    """FFmpeg arguments for a continuous recording into day folders."""
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-rtsp_transport", "tcp", "-i", source,
        "-map", "0:v", "-map", "0:a?", "-c:v", "copy", "-c:a", "aac",
        "-f", "segment", "-segment_time", str(seconds), "-segment_atclocktime", "1",
        "-reset_timestamps", "1", "-strftime", "1", "-segment_format", "mp4",
        # Fragmented MP4, so the file that is still being written already plays.
        "-segment_format_options", FRAGMENTED,
        str(folder / "%Y-%m-%d" / "%H-%M-%S_continuous.mp4"),
    ]  # fmt: skip


def clip_command(ffmpeg: str, source: str, path: Path, seconds: int) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", source, "-t", str(seconds),
        "-map", "0:v", "-map", "0:a?", "-c:v", "copy", "-c:a", "aac",
        "-movflags", "+faststart", "-y", str(path),
    ]  # fmt: skip


@dataclass
class Clip:
    camera: str
    path: Path
    trigger: str
    start: datetime
    seconds: int
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "camera": self.camera,
            "id": f"{self.camera}/{self.path.parent.name}/{self.path.name}",
            "trigger": self.trigger,
            "start": self.start.astimezone().isoformat(timespec="seconds"),
            "seconds": self.seconds,
        }


class Recorder:
    def __init__(self, settings: Settings, go2rtc: Go2rtc, library: Library, bus: EventBus) -> None:
        self.settings = settings
        self.go2rtc = go2rtc
        self.library = library
        self.bus = bus
        self.available = settings.go2rtc_mode != "off" and shutil.which(settings.ffmpeg_bin) is not None
        self._continuous: dict[str, asyncio.Task[None]] = {}
        self._continuous_args: dict[str, tuple[str, int]] = {}
        self.clips: dict[str, Clip] = {}
        self._housekeeping: asyncio.Task[None] | None = None
        self._config = Config()

    async def start(self, config: Config, streams: dict[str, str]) -> None:
        if not self.available and self.settings.go2rtc_mode != "off":
            log.error("ffmpeg not found (%s); recording is off", self.settings.ffmpeg_bin)
        self._housekeeping = asyncio.create_task(self._housekeep(), name="recorder-housekeeping")
        await self.apply(config, streams)

    async def stop(self) -> None:
        tasks = [*self._continuous.values(), *(c.task for c in self.clips.values() if c.task)]
        if self._housekeeping:
            tasks.append(self._housekeeping)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._continuous.clear()

    async def apply(self, config: Config, streams: dict[str, str]) -> None:
        """Start and stop continuous recordings to match the config."""
        self._config = config
        seconds = config.recording.segment_minutes * 60
        wanted = {
            cid: (cid, seconds)
            for cid, cam in config.cameras.items()
            if cam.enabled and cam.record == "continuous" and cid in streams
        }
        for cid in list(self._continuous):
            if self._continuous_args.get(cid) != wanted.get(cid):
                self._continuous.pop(cid).cancel()
                self._continuous_args.pop(cid, None)
        if not self.available:
            return
        for cid, args in wanted.items():
            if cid not in self._continuous:
                self._ensure_days(cid)
                self._continuous_args[cid] = args
                self._continuous[cid] = asyncio.create_task(self._run_continuous(*args), name=f"rec-{cid}")

    def is_recording(self, camera: str) -> bool:
        return camera in self._continuous or camera in self.clips

    def status(self, camera: str) -> dict[str, Any] | None:
        if camera in self.clips:
            return {"mode": "clip", **self.clips[camera].to_json()}
        if camera in self._continuous:
            return {"mode": "continuous", "camera": camera}
        return None

    async def record_clip(self, camera: str, trigger: str = "manual", seconds: int | None = None) -> Clip:
        if not self.available:
            raise RuntimeError("recording needs go2rtc and ffmpeg")
        if camera in self.clips:
            return self.clips[camera]  # a second trigger during a clip joins it
        seconds = seconds or self._config.recording.clip_seconds
        start = datetime.now().replace(microsecond=0)
        path = self.library.clip_path(camera, start, trigger)
        path.parent.mkdir(parents=True, exist_ok=True)
        clip = Clip(camera=camera, path=path, trigger=trigger, start=start, seconds=seconds)
        self.clips[camera] = clip
        clip.task = asyncio.create_task(self._run_clip(clip), name=f"clip-{camera}")
        self.bus.publish("recording.started", clip.to_json())
        return clip

    async def stop_clip(self, camera: str) -> bool:
        clip = self.clips.get(camera)
        if not clip or not clip.process or clip.process.returncode is not None:
            return False
        # SIGINT makes FFmpeg finish the file properly, unlike a kill.
        with contextlib.suppress(ProcessLookupError):
            clip.process.send_signal(2)
        return True

    async def _run_clip(self, clip: Clip) -> None:
        source = self.go2rtc.rtsp_url(clip.camera)
        meta: dict[str, Any] = {
            "trigger": clip.trigger,
            "start": clip.start.astimezone().isoformat(),
            "camera": clip.camera,
        }
        try:
            snapshot = asyncio.create_task(self._thumbnail(clip))
            cmd = clip_command(self.settings.ffmpeg_bin, source, clip.path, clip.seconds)
            clip.process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            _, stderr = await clip.process.communicate()
            await snapshot
            if clip.process.returncode not in (0, 255) or not clip.path.exists():
                log.warning("clip of %s failed: %s", clip.camera, stderr.decode(errors="replace").strip())
                meta["error"] = stderr.decode(errors="replace").strip()[-500:] or "ffmpeg failed"
            meta["duration"] = round((datetime.now() - clip.start).total_seconds(), 1)
        except asyncio.CancelledError:
            if clip.process and clip.process.returncode is None:
                clip.process.send_signal(2)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(clip.process.wait(), 5)
            raise
        finally:
            self.clips.pop(clip.camera, None)
            if clip.path.exists():
                clip.path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
            self.bus.publish("recording.finished", {**clip.to_json(), **meta})

    async def _thumbnail(self, clip: Clip) -> None:
        try:
            jpeg = await self.go2rtc.frame(clip.camera)
        except Go2rtcUnavailableError as e:
            log.info("no thumbnail for %s: %s", clip.camera, e)
            return
        clip.path.with_suffix(".jpg").write_bytes(jpeg)

    async def _run_continuous(self, camera: str, seconds: int) -> None:
        delay = 2.0
        folder = self.library.path(camera)
        while True:
            await self.go2rtc.ready.wait()
            cmd = segment_command(self.settings.ffmpeg_bin, self.go2rtc.rtsp_url(camera), folder, seconds)
            log.info("recording %s continuously", camera)
            self.bus.publish("recording.continuous", {"camera": camera, "active": True})
            process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            try:
                _, stderr = await process.communicate()
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError):
                    process.send_signal(2)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), 5)
                self.bus.publish("recording.continuous", {"camera": camera, "active": False})
                raise
            log.warning(
                "recording of %s stopped (%s): %s; retrying in %.0fs",
                camera, process.returncode, stderr.decode(errors="replace").strip()[-300:], delay,
            )  # fmt: skip
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    def _ensure_days(self, camera: str) -> None:
        # The segment muxer can't make folders, so today's and tomorrow's must exist in advance.
        today = date.today()
        for day in (today, today + timedelta(days=1)):
            self.library.path(camera, day.isoformat()).mkdir(parents=True, exist_ok=True)

    async def _housekeep(self) -> None:
        last_prune: date | None = None
        while True:
            for camera in list(self._continuous):
                self._ensure_days(camera)
            if last_prune != date.today():
                last_prune = date.today()
                deleted = await asyncio.to_thread(self.library.prune, self._config.recording.retention_days)
                for item in deleted:
                    log.info("deleted old recordings %s", item)
            await asyncio.sleep(600)
