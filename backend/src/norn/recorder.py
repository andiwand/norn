"""Recording with FFmpeg, without re-encoding the video, through three storage stages.

FFmpeg reads the camera's stream from go2rtc's local RTSP server, so recording doesn't open a
second connection to the camera. The video is copied as is (`-c:v copy`). Audio is converted to
AAC, because MP4 can't hold the G.711 audio many cameras send; that costs very little CPU.

The stages:

1. **Buffer** (RAM; `NORN_BUFFER`, /dev/shm in Docker): for each camera with a pre-recording
   time, FFmpeg keeps writing MPEG-TS pieces of about two seconds, and Norn deletes the ones older
   than that time. A clip starts with the pieces already there, so it begins *before* its trigger.
2. **Temporary storage** (`NORN_TEMP`): what is being recorded. A clip collects its pieces here,
   a continuous recording writes its current file here.
3. **Recordings** (`NORN_RECORDINGS`): finished files move here, with the layout of recordings.py.

Kinds of recordings:

- Continuous: one FFmpeg per camera writes a new file every `segment_minutes`, on the clock.
- Clips: a triggered recording of `clip_seconds` (the button, a webhook, a detection), with a
  thumbnail and a JSON sidecar. A trigger during a clip makes it longer. The clip length and
  pre-recording are the camera's preset's, else its own, its circle's or the global one.
- Pictures: a JPEG every `picture_seconds` (the `interval` trigger), straight from go2rtc.

MJPEG cameras need encoding to H.264 to record; Norn buffers them only when the camera's own
`prebuffer_seconds` (or its circle's or a preset's) asks for it, since that encodes all the time.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import logging
import os
import shutil
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .events import EventBus
from .go2rtc import Go2rtc, Go2rtcUnavailableError
from .recordings import Library, disk, folder_size
from .settings import Settings

log = logging.getLogger("norn.recorder")

FRAGMENTED = "movflags=+frag_keyframe+empty_moov+default_base_moof"
PIECE_SECONDS = 2  # length of a buffer piece; FFmpeg cuts at the next keyframe after it
MAX_CLIP_SECONDS = 4 * 3600  # however often triggers extend a clip

# Video arguments: copy the stream; or, for MJPEG (which browsers can't play from an MP4),
# encode to H.264 as cheaply as possible.
COPY = ["-c:v", "copy"]
ENCODE = [
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-tune",
    "zerolatency",
    "-crf",
    "27",
    "-pix_fmt",
    "yuv420p",
]


def _input(ffmpeg: str, source: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-rtsp_transport", "tcp", "-i", source]


def segment_command(
    ffmpeg: str, source: str, folder: Path, seconds: int, transcode: bool = False
) -> list[str]:
    """FFmpeg arguments for a continuous recording into day folders."""
    video = [*ENCODE, "-force_key_frames", f"expr:gte(t,n_forced*{seconds})"] if transcode else COPY
    return [
        *_input(ffmpeg, source),
        "-map", "0:v", "-map", "0:a?", *video, "-c:a", "aac",
        "-f", "segment", "-segment_time", str(seconds), "-segment_atclocktime", "1",
        "-reset_timestamps", "1", "-strftime", "1", "-segment_format", "mp4",
        # Fragmented MP4, so the file that is still being written already plays.
        "-segment_format_options", FRAGMENTED,
        str(folder / "%Y-%m-%d" / "%H-%M-%S_continuous.mp4"),
    ]  # fmt: skip


def buffer_command(
    ffmpeg: str, source: str, folder: Path, start_number: int, transcode: bool = False
) -> list[str]:
    """FFmpeg arguments for the RAM buffer: numbered MPEG-TS pieces with continuous timestamps,
    so pieces in a row can simply be joined."""
    video = [*ENCODE, "-force_key_frames", f"expr:gte(t,n_forced*{PIECE_SECONDS})"] if transcode else COPY
    return [
        *_input(ffmpeg, source),
        "-map", "0:v", "-map", "0:a?", *video, "-c:a", "aac",
        "-f", "segment", "-segment_time", str(PIECE_SECONDS), "-segment_format", "mpegts",
        "-segment_start_number", str(start_number),
        str(folder / "%010d.ts"),
    ]  # fmt: skip


def clip_command(ffmpeg: str, source: str, path: Path, seconds: int, transcode: bool = False) -> list[str]:
    """A clip straight from the stream, for cameras without a buffer."""
    return [
        *_input(ffmpeg, source), "-t", str(seconds),
        "-map", "0:v", "-map", "0:a?", *(ENCODE if transcode else COPY), "-c:a", "aac",
        "-movflags", "+faststart", "-y", str(path),
    ]  # fmt: skip


def remux_command(ffmpeg: str, source: Path, path: Path) -> list[str]:
    """MPEG-TS from the buffer into an MP4 that browsers play, without touching the video."""
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-fflags", "+genpts",
        "-i", str(source), "-map", "0", "-c", "copy", "-movflags", "+faststart", "-y", str(path),
    ]  # fmt: skip


def thumbnail_command(ffmpeg: str, video: Path, path: Path, width: int | None = 640) -> list[str]:
    """The first frame of a video as a JPEG (small by default): one frame decoded, nearly free."""
    scale = ["-vf", f"scale={width}:-2"] if width else []
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(video),
        "-frames:v", "1", *scale, "-q:v", "4" if width else "3", "-y", str(path),
    ]  # fmt: skip


def ffprobe_of(ffmpeg: str) -> str:
    """ffprobe next to ffmpeg (they come together), else from the PATH."""
    sibling = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
    return str(sibling) if sibling.is_file() else "ffprobe"


async def duration_of(ffmpeg: str, video: Path) -> float | None:
    code, out = await run(
        [ffprobe_of(ffmpeg), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        timeout=30,
        stdout=True,
    )
    try:
        return round(float(out), 1) if code == 0 else None
    except ValueError:
        return None


async def run(cmd: list[str], timeout: float = 120, stdout: bool = False) -> tuple[int, str]:
    """Run a command; its exit code and stderr (or stdout, with `stdout`)."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if stdout else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return -1, "timed out"
    text = out if stdout else err
    return process.returncode or 0, (text or b"").decode(errors="replace").strip()


def finish(process: asyncio.subprocess.Process) -> None:
    """Ask FFmpeg to stop: SIGINT makes it finish the file properly, unlike a kill."""
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.send_signal(signal.SIGINT)


async def interrupt(process: asyncio.subprocess.Process, grace: float = 5) -> None:
    """Stop FFmpeg the clean way (it finishes the file), and for sure after `grace`."""
    if process.returncode is not None:
        return
    finish(process)
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


RESERVED = frozenset({"continuous", "interval"})  # triggers Norn uses itself


@dataclass(frozen=True)
class Piece:
    index: int
    path: Path
    end: float  # when FFmpeg last wrote it


class Buffer:
    """The last seconds of one camera in RAM, as numbered MPEG-TS pieces."""

    def __init__(self, recorder: Recorder, camera: str, seconds: int, transcode: bool) -> None:
        self.recorder = recorder
        self.camera = camera
        self.seconds = seconds
        self.transcode = transcode
        self.folder = recorder.settings.buffer_path / camera
        # Clips collecting pieces: the last piece each has taken. Later pieces stay until taken.
        self.claims: dict[int, int] = {}
        self.running = False
        # The first piece of the current FFmpeg run. Pieces of different runs don't join: each
        # run's timestamps start anew.
        self.run_first = 0
        self.task = asyncio.create_task(self._run(), name=f"buffer-{camera}")

    def pieces(self) -> list[Piece]:
        found = []
        for path in self.folder.glob("*.ts"):
            try:
                found.append(Piece(int(path.stem), path, path.stat().st_mtime))
            except (ValueError, FileNotFoundError):
                continue
        return sorted(found, key=lambda p: p.index)

    def bitrate(self) -> float | None:
        """Bytes per second of the camera's stream, measured from the finished pieces."""
        pieces = [p for p in self.pieces()[:-1] if p.index >= self.run_first]
        if len(pieces) < 3:
            return None
        seconds = pieces[-1].end - pieces[0].end
        if seconds <= 0:
            return None
        size = 0
        for piece in pieces[1:]:  # the first piece's own time lies before pieces[0].end
            try:
                size += piece.path.stat().st_size
            except FileNotFoundError:
                return None
        return size / seconds

    def prune(self) -> None:
        pieces = self.pieces()
        horizon = time.time() - self.seconds - PIECE_SECONDS
        claimed = min(self.claims.values(), default=None)
        for piece in pieces[:-3]:  # the newest few always stay; the last one is being written
            if piece.end < horizon and (claimed is None or piece.index <= claimed):
                piece.path.unlink(missing_ok=True)

    async def stop(self) -> None:
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task
        shutil.rmtree(self.folder, ignore_errors=True)

    async def _run(self) -> None:
        settings = self.recorder.settings
        go2rtc = self.recorder.go2rtc
        shutil.rmtree(self.folder, ignore_errors=True)
        self.folder.mkdir(parents=True, exist_ok=True)
        delay = 2.0
        while True:
            await go2rtc.ready.wait()
            pieces = self.pieces()
            start = pieces[-1].index + 1 if pieces else 0  # numbers keep rising across restarts
            self.run_first = start
            cmd = buffer_command(
                settings.ffmpeg_bin, go2rtc.rtsp_url(self.camera), self.folder, start, self.transcode
            )
            process = None
            pruner = asyncio.create_task(self._prune_loop())
            try:
                process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
                self.running = True
                _, stderr = await process.communicate()
                error = f"({process.returncode}) {stderr.decode(errors='replace').strip()[-300:]}"
            except OSError as e:  # FFmpeg missing, too many open files, ...
                error = f"can't start FFmpeg: {e}"
            except asyncio.CancelledError:
                if process:
                    await interrupt(process)
                raise
            finally:
                self.running = False
                pruner.cancel()
            log.warning("buffer of %s stopped %s; retrying in %.0fs", self.camera, error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            try:
                self.prune()
            except OSError as e:
                log.warning("pruning the buffer of %s failed: %s", self.camera, e)


@dataclass
class Clip:
    camera: str
    path: Path  # in the temporary storage; it moves to the recordings when finished
    trigger: str
    start: datetime  # when the recording begins, before the trigger when there was a buffer
    triggered: datetime
    seconds: int
    end: float = 0  # time.time() when the clip should end
    events: set[str] = field(default_factory=set)  # every trigger that started or extended it
    closing: bool = False  # its end is fixed: a trigger now starts a new clip
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "camera": self.camera,
            "id": f"{self.camera}/{self.path.parent.name}/{self.path.name}",
            "trigger": self.trigger,
            "start": self.triggered.astimezone().isoformat(timespec="seconds"),
            "seconds": self.seconds,
        }


class Recorder:
    def __init__(self, settings: Settings, go2rtc: Go2rtc, library: Library, bus: EventBus) -> None:
        self.settings = settings
        self.go2rtc = go2rtc
        self.library = library
        self.temp = Library(settings.temp_path)
        self.bus = bus
        self.available = settings.go2rtc_mode != "off" and shutil.which(settings.ffmpeg_bin) is not None
        self._continuous: dict[str, asyncio.Task[None]] = {}
        self._continuous_args: dict[str, tuple[str, int, bool]] = {}
        # Continuous recordings that were stopped and whose FFmpeg may still finish its file.
        self._stopping: dict[str, asyncio.Task[None]] = {}
        self._buffers: dict[str, Buffer] = {}
        self._pictures: dict[str, tuple[int, asyncio.Task[None]]] = {}
        self.transcode: set[str] = set()
        self.clips: dict[str, Clip] = {}  # the current clip of each camera
        self._clip_tasks: set[asyncio.Task[None]] = set()  # with clips that are still closing
        self._housekeeping: asyncio.Task[None] | None = None
        self._evict_paused_until = 0.0
        self._config = Config()
        self.preset_of: Callable[[str], str | None] = lambda camera: None  # its Norn preset now

    async def start(
        self, config: Config, streams: dict[str, str], transcode: set[str] | None = None, away: bool = False
    ) -> None:
        if not self.available and self.settings.go2rtc_mode != "off":
            log.error("ffmpeg not found (%s); recording is off", self.settings.ffmpeg_bin)
        if self.available:
            await self._recover()
        self._housekeeping = asyncio.create_task(self._housekeep(), name="recorder-housekeeping")
        await self.apply(config, streams, transcode, away)

    async def stop(self) -> None:
        tasks = [
            *self._continuous.values(),
            *self._clip_tasks,
            *(task for _, task in self._pictures.values()),
        ]
        if self._housekeeping:
            tasks.append(self._housekeeping)
        for task in tasks:
            task.cancel()
        # Stopped ones are already finishing their file: cancelling again would cut that short.
        await asyncio.gather(*tasks, *self._stopping.values(), return_exceptions=True)
        await asyncio.gather(*(b.stop() for b in self._buffers.values()), return_exceptions=True)
        self._continuous.clear()
        self._continuous_args.clear()
        self._stopping.clear()
        self._buffers.clear()
        self._pictures.clear()
        if self.available:
            await self._move_finished(everything=True)

    async def apply(
        self, config: Config, streams: dict[str, str], transcode: set[str] | None = None, away: bool = False
    ) -> None:
        """Start and stop continuous recordings, buffers and pictures to match the config."""
        self._config = config
        self.transcode = transcode or set()
        seconds = config.recording.segment_minutes * 60
        live = {cid: cam for cid, cam in config.cameras.items() if cam.enabled and cid in streams}

        wanted = {
            cid: (cid, seconds, cid in self.transcode)
            for cid, cam in live.items()
            if cam.record == "continuous"
        }
        for cid in list(self._continuous):
            if self._continuous_args.get(cid) != wanted.get(cid):
                task = self._continuous.pop(cid)
                task.cancel()
                self._stopping[cid] = task
                self._continuous_args.pop(cid, None)

        buffers = {}
        for cid in live:
            length, explicit = config.longest_prebuffer(cid)
            # Encoding all the time costs CPU: only when the camera or its circle asks for it.
            if length > 0 and (cid not in self.transcode or explicit):
                buffers[cid] = (length, cid in self.transcode)
        for cid in list(self._buffers):
            buffer = self._buffers[cid]
            if buffers.get(cid) != (buffer.seconds, buffer.transcode):
                if buffers.get(cid) and buffers[cid][1] == buffer.transcode:
                    buffer.seconds = buffers[cid][0]  # only the length changed: keep what it holds
                    continue
                await self._buffers.pop(cid).stop()

        pictures = {cid: config.pictures(cid, away) for cid in live}
        pictures = {cid: every for cid, every in pictures.items() if every > 0}
        for cid in list(self._pictures):
            if pictures.get(cid) != self._pictures[cid][0]:
                self._pictures.pop(cid)[1].cancel()

        if not self.available:
            return
        for cid, args in wanted.items():
            if cid not in self._continuous:
                self._ensure_days(cid)
                self._continuous_args[cid] = args
                self._continuous[cid] = asyncio.create_task(self._run_continuous(*args), name=f"rec-{cid}")
        for cid, (length, encode) in buffers.items():
            if cid not in self._buffers:
                self._buffers[cid] = Buffer(self, cid, length, encode)
        for cid, every in pictures.items():
            if cid not in self._pictures:
                task = asyncio.create_task(self._take_pictures(cid, every), name=f"pictures-{cid}")
                self._pictures[cid] = (every, task)

    def is_recording(self, camera: str) -> bool:
        return camera in self._continuous or camera in self.clips

    def status(self, camera: str) -> dict[str, Any] | None:
        if camera in self.clips:
            return {"mode": "clip", **self.clips[camera].to_json()}
        if camera in self._continuous:
            return {"mode": "continuous", "camera": camera}
        return None

    def buffered(self, camera: str) -> int:
        """Seconds of the camera's past that a clip started now would include."""
        buffer = self._buffers.get(camera)
        if not buffer or not buffer.running:
            return 0
        pieces = [p for p in buffer.pieces() if p.index >= buffer.run_first]  # a clip joins only these
        if len(pieces) < 2:
            return 0
        return min(buffer.seconds, max(0, round(time.time() - pieces[0].end)))

    def prebuffer_now(self, camera: str) -> int:
        """What a clip started now includes from before: the buffer holds the longest
        pre-recording of the camera's presets; the one it is at may want less."""
        wanted = self._config.setting(camera, "prebuffer_seconds", self.preset_of(camera))[0]
        return min(self.buffered(camera), wanted)

    def bitrates(self) -> dict[str, float]:
        """Bytes per second of each camera with a running buffer."""
        rates = {cid: b.bitrate() for cid, b in self._buffers.items() if b.running}
        return {cid: rate for cid, rate in rates.items() if rate}

    def usage(self) -> dict[str, Any]:
        """What each storage stage holds. Walks the folders: call it in a thread."""
        stages = {}
        buffer, temp = self.settings.buffer_path, self.settings.temp_path
        for key, path in (("buffer", buffer), ("temp", temp)):
            # The buffer may sit inside the temporary storage (when /dev/shm is too small).
            used, files = (
                folder_size(path, skip=buffer if key == "temp" else None) if path.is_dir() else (0, 0)
            )
            stages[key] = {"path": str(path), "used": used, "files": files, **disk(path)}
        stages["recordings"] = self.library.usage()
        return stages

    async def record_clip(self, camera: str, trigger: str = "manual", seconds: int | None = None) -> Clip:
        if trigger in RESERVED:
            raise ValueError(f"the trigger {trigger!r} is Norn's own")
        if not self.available:
            raise RuntimeError("recording needs go2rtc and ffmpeg")
        preset = self.preset_of(camera)
        seconds = seconds or self._config.setting(camera, "clip_seconds", preset)[0]
        clip = self.clips.get(camera)
        if clip and not clip.closing:
            # A trigger during a clip (a detection, the button, a webhook) makes it last long
            # enough for this one too: one longer video, not a second. Up to a limit.
            clip.end = min(max(clip.end, time.time() + seconds), clip.start.timestamp() + MAX_CLIP_SECONDS)
            clip.seconds = round(clip.end - clip.triggered.timestamp())
            clip.events.add(trigger)
            return clip
        now = datetime.now().replace(microsecond=0)
        buffer = self._buffers.get(camera)
        before = self.prebuffer_now(camera)
        start = now - timedelta(seconds=before)
        path = self.temp.file_path(camera, start, trigger)
        path.parent.mkdir(parents=True, exist_ok=True)
        clip = Clip(
            camera=camera,
            path=path,
            trigger=trigger,
            start=start,
            triggered=now,
            seconds=seconds,
            end=time.time() + seconds,
            events={trigger},
        )
        self.clips[camera] = clip
        runner = self._run_buffered_clip(clip, buffer) if buffer and before else self._run_clip(clip)
        clip.task = asyncio.create_task(runner, name=f"clip-{camera}")
        self._clip_tasks.add(clip.task)
        clip.task.add_done_callback(self._clip_tasks.discard)
        self.bus.publish("recording.started", clip.to_json())
        return clip

    async def stop_clip(self, camera: str) -> bool:
        clip = self.clips.get(camera)
        if not clip:
            return False
        clip.end = min(clip.end, time.time())
        self._close(clip)
        return True

    def _close(self, clip: Clip) -> None:
        """The clip's end is fixed: a trigger from now on starts a new one."""
        clip.closing = True
        if clip.process:
            finish(clip.process)

    async def _run_clip(self, clip: Clip) -> None:
        """A clip without a buffer: FFmpeg records from now on."""
        meta = self._meta(clip)
        snapshot = asyncio.create_task(self._thumbnail(clip))
        try:
            cmd = clip_command(
                self.settings.ffmpeg_bin,
                self.go2rtc.rtsp_url(clip.camera),
                clip.path,
                MAX_CLIP_SECONDS,  # a cap; _stop_at_end stops it, later when triggers extend it
                clip.camera in self.transcode,
            )
            clip.process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            watcher = asyncio.create_task(self._stop_at_end(clip))
            try:
                _, stderr = await clip.process.communicate()
            finally:
                watcher.cancel()
                clip.closing = True
            ok = clip.process.returncode in (0, 255)
            await self._check_video(clip, meta, ok, stderr.decode(errors="replace").strip())
        except asyncio.CancelledError:
            snapshot.cancel()  # Norn stops: no waiting for a thumbnail
            if clip.process:
                await interrupt(clip.process)
            raise
        except Exception as e:
            log.exception("clip of %s failed", clip.camera)
            meta["error"] = str(e)
        finally:
            await self._finish_clip(clip, meta, snapshot)

    async def _stop_at_end(self, clip: Clip) -> None:
        while clip.process and clip.process.returncode is None:
            if time.time() >= clip.end:
                self._close(clip)
                return
            await asyncio.sleep(0.5)

    async def _check_video(self, clip: Clip, meta: dict[str, Any], ok: bool, error: str) -> None:
        """Note in the clip's details whether FFmpeg made its video, and how long it is."""
        if not ok or not clip.path.exists():
            log.warning("clip of %s failed: %s", clip.camera, error)
            meta["error"] = error[-500:] or "ffmpeg failed"
        meta["duration"] = (
            await duration_of(self.settings.ffmpeg_bin, clip.path) if clip.path.exists() else None
        ) or round(time.time() - clip.start.timestamp(), 1)

    async def _run_buffered_clip(self, clip: Clip, buffer: Buffer) -> None:
        """A clip from the buffer: the pieces since `start` go into one file in the temporary
        storage as FFmpeg finishes them, then become an MP4.

        If Norn stops meanwhile, the joined pieces stay in the temporary storage, and the next
        start makes them into the clip (`_recover`)."""
        meta = self._meta(clip)
        meta["before"] = round((clip.triggered - clip.start).total_seconds())
        joined = clip.path.with_suffix(".ts")
        claim = id(clip)
        buffer.claims[claim] = -1
        snapshot = asyncio.create_task(self._thumbnail(clip))
        try:
            try:
                await self._collect(clip, buffer, joined, claim)
            except Exception as e:
                log.exception("clip of %s: collecting the buffer failed", clip.camera)
                meta["error"] = str(e)
            finally:
                buffer.claims.pop(claim, None)
                clip.closing = True
            size = joined.stat().st_size if joined.exists() else 0
            if size == 0:
                meta.setdefault("error", "the buffer had no video")
            else:
                # Remuxing only copies, but a long clip on a slow disk takes a while.
                timeout = max(120, size / 5_000_000)
                code, error = await run(remux_command(self.settings.ffmpeg_bin, joined, clip.path), timeout)
                await self._check_video(clip, meta, code == 0, error)
            joined.unlink(missing_ok=True)
        except asyncio.CancelledError:
            # Norn stops: the joined pieces stay for _recover, with the thumbnail if there are any.
            snapshot.cancel()
            await asyncio.wait([snapshot])
            if not joined.exists():
                clip.path.with_suffix(".jpg").unlink(missing_ok=True)
            if self.clips.get(clip.camera) is clip:
                del self.clips[clip.camera]
            raise
        except Exception as e:
            log.exception("clip of %s failed", clip.camera)
            meta["error"] = str(e)
        await self._finish_clip(clip, meta, snapshot)

    async def _collect(self, clip: Clip, buffer: Buffer, joined: Path, claim: int) -> None:
        """Append the buffer's finished pieces from the clip's start to its end to `joined`."""
        since = clip.start.timestamp() - PIECE_SECONDS
        first = buffer.run_first  # pieces of this FFmpeg run only
        taken = -1
        last: int | None = None  # the piece being written when the clip ended
        deadline = 0.0
        while True:
            pieces = [p for p in buffer.pieces() if p.index >= first]
            if buffer.run_first != first and last is None:
                # The buffer restarted: its new pieces can't be joined to these. End here.
                last = buffer.run_first - 1
                deadline = time.time()
                self._close(clip)
            elif last is None and time.time() >= clip.end:
                last = pieces[-1].index if pieces else taken
                deadline = time.time() + PIECE_SECONDS * 5
                self._close(clip)
            done = [p for p in pieces[:-1] if p.index > taken and p.end >= since]
            if last is not None:
                done = [p for p in done if p.index <= last]
            for piece in done:
                try:
                    await asyncio.to_thread(_append, piece.path, joined)
                except FileNotFoundError:
                    log.warning("clip of %s: piece %d was gone", clip.camera, piece.index)
                taken = buffer.claims[claim] = piece.index
            if last is not None and (taken >= last or time.time() > deadline or not buffer.running):
                return
            await asyncio.sleep(0.5)

    def _meta(self, clip: Clip) -> dict[str, Any]:
        return {
            "trigger": clip.trigger,
            "start": clip.start.astimezone().isoformat(),
            "triggered": clip.triggered.astimezone().isoformat(),
            "camera": clip.camera,
        }

    async def _finish_clip(self, clip: Clip, meta: dict[str, Any], snapshot: asyncio.Task[None]) -> None:
        if self.clips.get(clip.camera) is clip:  # not a new clip a trigger started meanwhile
            del self.clips[clip.camera]
        if not clip.path.exists():
            snapshot.cancel()
        await asyncio.wait([snapshot])  # its .jpg is written now, or never
        if clip.events != {clip.trigger}:
            meta["events"] = sorted(clip.events)
        moved = None
        if clip.path.exists():
            clip.path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
            moved = await self._to_library(clip.camera, clip.path)
        else:
            clip.path.with_suffix(".jpg").unlink(missing_ok=True)
        data = {**clip.to_json(), **meta}
        if moved:
            data["id"] = _id(moved)
        self.bus.publish("recording.finished", data)

    async def _thumbnail(self, clip: Clip) -> None:
        try:
            jpeg = await self.go2rtc.frame(clip.camera)
            clip.path.with_suffix(".jpg").write_bytes(jpeg)
        except (Go2rtcUnavailableError, OSError) as e:
            log.info("no thumbnail for %s: %s", clip.camera, e)

    async def _take_pictures(self, camera: str, every: int) -> None:
        """A picture every `every` seconds, on the local clock (every hour: at :00)."""
        while True:
            offset = datetime.now().astimezone().utcoffset()
            local = time.time() + (offset.total_seconds() if offset else 0)
            await asyncio.sleep(every - local % every)
            if not self.go2rtc.ready.is_set():
                continue
            try:
                now = datetime.now().replace(microsecond=0)
                path = self.temp.file_path(camera, now, "interval", ".jpg")
                path.parent.mkdir(parents=True, exist_ok=True)
                if not await self._picture(camera, path):
                    continue
                moved = await self._to_library(camera, path)
                if moved:
                    await self._small_copy(moved)
                    self.bus.publish("recording.picture", {"camera": camera, "id": _id(moved)})
            except Exception:
                log.exception("picture of %s failed", camera)

    async def _small_copy(self, picture: Path) -> None:
        """A small copy of a picture for lists and the timeline: one JPEG decoded, cheap."""
        camera, day, name = _id(picture).split("/")
        thumb = self.library.thumb_path(camera, day, name)
        thumb.parent.mkdir(parents=True, exist_ok=True)
        code, error = await run(
            thumbnail_command(self.settings.ffmpeg_bin, picture, thumb, width=480), timeout=20
        )
        if code != 0:
            log.info("no small copy of %s: %s", name, error)

    def keyframe_piece(self, camera: str, stills: str = "auto") -> Piece | None:
        """The buffer piece whose first frame (a keyframe) is the camera's still, if the
        setting `stills` takes keyframes and the camera has a running buffer."""
        if stills == "live":
            return None
        buffer = self._buffers.get(camera)
        pieces = buffer.pieces()[:-1] if buffer and buffer.running else []
        return pieces[-1] if pieces else None

    async def piece_jpeg(self, piece: Piece, width: int = 960) -> bytes | None:
        """The first frame (a keyframe) of a buffer piece as a JPEG."""
        process = await asyncio.create_subprocess_exec(
            self.settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(piece.path), "-frames:v", "1", "-vf", f"scale='min({width},iw)':-2",
            "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(process.communicate(), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
            return None
        return out if process.returncode == 0 and out else None

    async def _picture(self, camera: str, path: Path) -> bool:
        """A full-size picture of the camera now: as the `stills` setting says, from the newest
        finished piece of its buffer (one decoded frame, no new connection), or from go2rtc."""
        piece = self.keyframe_piece(camera, self._config.detection_for(camera).stills)
        if piece:
            code, error = await run(
                thumbnail_command(self.settings.ffmpeg_bin, piece.path, path, width=None), timeout=20
            )
            if code == 0 and await asyncio.to_thread(path.exists):
                return True
            log.info("no picture of %s from the buffer: %s", camera, error)
        try:
            jpeg = await self.go2rtc.frame(camera)
            await asyncio.to_thread(path.write_bytes, jpeg)
        except Go2rtcUnavailableError as e:
            log.info("no picture of %s: %s", camera, e)
            return False
        return True

    async def _to_library(self, camera: str, path: Path) -> Path | None:
        """Move a finished recording (video or picture, with its sidecars) from the temporary
        storage into the recordings. The video moves first: a .jpg alone would look like a picture."""

        def move() -> Path:
            target = _unused(self.library.path(camera, path.parent.name, path.name))
            target.parent.mkdir(parents=True, exist_ok=True)
            for suffix in (path.suffix, ".jpg", ".json"):
                source = path.with_suffix(suffix)
                if source.exists():
                    _move(source, target.with_suffix(suffix))
            return target

        try:
            return await asyncio.to_thread(move)
        except OSError as e:
            log.error("can't move %s into the recordings: %s", path, e)
            return None

    async def _run_continuous(self, camera: str, seconds: int, transcode: bool) -> None:
        delay = 2.0
        folder = self.temp.path(camera)
        while True:
            await self.go2rtc.ready.wait()
            cmd = segment_command(
                self.settings.ffmpeg_bin, self.go2rtc.rtsp_url(camera), folder, seconds, transcode
            )
            log.info("recording %s continuously", camera)
            self.bus.publish("recording.continuous", {"camera": camera, "active": True})
            process = None
            try:
                process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
                _, stderr = await process.communicate()
                error = f"({process.returncode}) {stderr.decode(errors='replace').strip()[-300:]}"
            except OSError as e:  # FFmpeg missing, too many open files, ...
                error = f"can't start FFmpeg: {e}"
            except asyncio.CancelledError:
                if process:
                    await interrupt(process)
                self.bus.publish("recording.continuous", {"camera": camera, "active": False})
                raise
            log.warning("recording of %s stopped %s; retrying in %.0fs", camera, error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _move_finished(self, everything: bool = False) -> None:
        """Move the continuous files FFmpeg has finished into the recordings, with a thumbnail.
        A file is finished when a newer one exists for the camera, or when nothing records it."""
        files = [
            (camera, path)
            for camera, _, path in self.temp.iter_files()
            if path.suffix == ".mp4" and path.stem.endswith("_continuous")
        ]
        # The newest by time written, not by name: in the hour after the clocks go back, names repeat.
        newest: dict[str, Path] = {}
        written: dict[Path, float] = {}
        for camera, path in files:
            with contextlib.suppress(FileNotFoundError):
                written[path] = path.stat().st_mtime
                if camera not in newest or written[path] >= written[newest[camera]]:
                    newest[camera] = path
        for cid, task in list(self._stopping.items()):
            if task.done():
                del self._stopping[cid]
        active = set(self._continuous) | set(self._stopping)  # FFmpeg may still write their newest
        for camera, path in files:
            if not everything and camera in active and newest.get(camera) == path:
                continue
            if path.stat().st_size == 0:
                path.unlink(missing_ok=True)
                continue
            code, error = await run(
                thumbnail_command(self.settings.ffmpeg_bin, path, path.with_suffix(".jpg")), timeout=30
            )
            if code != 0:
                log.info("no thumbnail for %s: %s", path.name, error)
            moved = await self._to_library(camera, path)
            if moved:
                self.bus.publish(
                    "recording.finished",
                    {"camera": camera, "id": _id(moved), "trigger": "continuous"},
                )

    async def _recover(self) -> None:
        """After a stop or crash: finish what the temporary storage still holds."""
        # Clips whose pieces were joined but not yet made into an MP4.
        for joined in sorted(self.settings.temp_path.glob("*/*/*.ts")):
            mp4 = joined.with_suffix(".mp4")
            code, error = await run(remux_command(self.settings.ffmpeg_bin, joined, mp4), 3600)
            joined.unlink(missing_ok=True)
            if code == 0 and mp4.exists():
                trigger = mp4.stem.partition("_")[2]
                meta = {"trigger": trigger, "duration": await duration_of(self.settings.ffmpeg_bin, mp4)}
                mp4.with_suffix(".json").write_text(json.dumps({**meta, "recovered": True}, indent=2) + "\n")
            else:
                log.warning("can't recover %s: %s", joined.name, error)
                mp4.unlink(missing_ok=True)
                joined.with_suffix(".jpg").unlink(missing_ok=True)
        for camera, _, path in list(self.temp.iter_files()):
            clip = path.suffix == ".mp4" and not path.stem.endswith("_continuous")
            alone = path.suffix == ".jpg" and not path.with_suffix(".mp4").exists()
            if clip or (alone and path.stem.endswith("_interval")):
                await self._to_library(camera, path)
            elif alone:
                path.unlink(missing_ok=True)  # the thumbnail of a clip that never got a video
        await self._move_finished(everything=True)

    def _ensure_days(self, camera: str) -> None:
        # The segment muxer can't make folders, so today's and tomorrow's must exist in advance.
        today = date.today()
        for day in (today, today + timedelta(days=1)):
            self.temp.path(camera, day.isoformat()).mkdir(parents=True, exist_ok=True)

    async def _evict(self) -> None:
        """Keep the recordings within their size limit and the disk's free space."""
        r = self._config.recording
        max_bytes, min_free = int(r.max_gb * 1e9), int(r.min_free_gb * 1e9)
        if (not max_bytes and not min_free) or time.time() < self._evict_paused_until:
            return
        try:
            free_before = disk(self.library.root)["free"] if min_free else None
            deleted, excess = await asyncio.to_thread(self.library.evict, max_bytes, min_free)
        except Exception:
            log.exception("keeping the recordings within their limits failed")
            return
        if deleted:
            log.warning("deleted %d old recordings to stay within the storage limits", len(deleted))
            self.bus.publish("recording.deleted", {"ids": deleted})
            if free_before is not None and (disk(self.library.root)["free"] or 0) <= (free_before or 0):
                # Deleting freed nothing: snapshots, a recycle bin on a NAS, another program.
                # Going on would delete everything; stop for an hour.
                self._evict_paused_until = time.time() + 3600
                log.error(
                    "deleting recordings doesn't free disk space (snapshots or a recycle bin?); "
                    "Norn stops deleting for an hour"
                )
        elif excess:
            log.error(
                "the storage limits can't be met: %.1f GB too much, all of it kept by hand or pinned",
                excess / 1e9,
            )

    async def _housekeep(self) -> None:
        last_evict = 0.0
        last_prune = 0.0
        while True:
            # Each step on its own: one failing must not stop the others, nor the loop.
            try:
                for camera in list(self._continuous):
                    self._ensure_days(camera)
            except OSError:
                log.exception("making day folders failed")
            if self.available:
                try:
                    await self._move_finished()
                except Exception:
                    log.exception("moving finished recordings failed")
            if time.time() - last_prune >= 600:
                last_prune = time.time()
                try:
                    retention = self._config.recording.retention_days
                    deleted = await asyncio.to_thread(self.library.prune, retention)
                except Exception:
                    log.exception("deleting expired recordings failed")
                    deleted = []
                for item in deleted:
                    log.info("deleted expired recording %s", item)
                if deleted:
                    self.bus.publish("recording.deleted", {"ids": deleted})
            if time.time() - last_evict >= 60:
                last_evict = time.time()
                await self._evict()
            await asyncio.sleep(5)


def _id(path: Path) -> str:
    """The id of a recording from its path: camera/day/name."""
    return f"{path.parent.parent.name}/{path.parent.name}/{path.name}"


def _append(piece: Path, joined: Path) -> None:
    with piece.open("rb") as source, joined.open("ab") as out:
        shutil.copyfileobj(source, out)


def _unused(target: Path) -> Path:
    """`target`, else the same name a second later (and so on), so a move never overwrites a
    recording: in the hour after the clocks go back, names repeat."""
    while any(target.with_suffix(s).exists() for s in (".mp4", ".jpg", ".json")):
        when, _, rest = target.name.partition("_")
        later = datetime.strptime(when, "%H-%M-%S") + timedelta(seconds=1)
        target = target.with_name(f"{later:%H-%M-%S}_{rest}")
    return target


def _move(source: Path, target: Path) -> None:
    """Move a file; across file systems via a hidden temporary name, so a half-copied file never
    shows under its real name."""
    try:
        os.replace(source, target)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    part = target.with_name(f".{target.name}.part")
    shutil.copy2(source, part)
    os.replace(part, target)
    source.unlink()
