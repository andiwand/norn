"""Still streams: a camera's video as a slow stream of pictures, for whoever wants it.

One FFmpeg per camera and mode reads the camera from go2rtc (its sub-stream when it has one)
and makes stills from it, in up to three forms from the same decoded frame: a JPEG (for the web
app), small grayscale (for motion) and the object detector's input. It runs only while someone
subscribes, and stops ("idles") a little after the last one leaves.

Two modes:

- `keyframe`: FFmpeg decodes only the keyframes (`-skip_frame nokey`), one every few seconds
  depending on the camera. That costs next to nothing.
- `live`: FFmpeg decodes every frame and keeps one per interval. Exact timing, more CPU.

Each subscriber says how often it wants a still and gets the newest one when it is due; a slow
subscriber never holds up the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from .detect import MOTION_FILTER, MOTION_SIZE, OBJECT_FILTER, OBJECT_SIZE

log = logging.getLogger("norn.stills")

Format = Literal["jpeg", "gray", "bgr"]  # a JPEG; small gray for motion; the detector input
Mode = Literal["keyframe", "live"]
IDLE_AFTER = 10.0  # seconds a stream keeps running after its last subscriber left
JPEG_FILTER = "scale='min(960,iw)':-2"
FRAME_BYTES = {"gray": MOTION_SIZE[0] * MOTION_SIZE[1], "bgr": OBJECT_SIZE * OBJECT_SIZE * 3}


@dataclass(eq=False)
class Subscription:
    format: Format
    every: float
    queue: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    last: float = 0.0

    def offer(self, data: bytes, now: float) -> None:
        if now - self.last < self.every * 0.9:
            return
        self.last = now
        if self.queue.full():
            self.queue.get_nowait()  # only the newest still counts
        self.queue.put_nowait(data)

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        while True:
            yield await self.queue.get()


def still_command(
    ffmpeg: str, source: str, mode: Mode, every: float, outputs: dict[Format, str]
) -> list[str]:
    """FFmpeg arguments: stills of `source` at most one per `every` seconds, into `outputs`
    (format -> pipe:N)."""
    pick = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{every:.2f})'"
    filters = {"jpeg": JPEG_FILTER, "gray": MOTION_FILTER, "bgr": OBJECT_FILTER}
    names = list(outputs)
    graph = f"[0:v]{pick},split={len(names)}" + "".join(f"[s{i}]" for i in range(len(names)))
    for i, name in enumerate(names):
        graph += f";[s{i}]{filters[name]}[{name}]"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if mode == "keyframe":
        cmd += ["-skip_frame", "nokey"]
    cmd += ["-rtsp_transport", "tcp", "-i", source, "-filter_complex", graph]
    for name, target in outputs.items():
        cmd += ["-map", f"[{name}]", "-fps_mode", "passthrough"]
        if name == "jpeg":
            cmd += ["-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "6", target]
        else:
            cmd += ["-f", "rawvideo", "-pix_fmt", "gray" if name == "gray" else "bgr24", target]
    return cmd


def split_jpegs(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Whole JPEGs from the start of `buffer` (FFmpeg writes them back to back), and the rest."""
    found = []
    while True:
        start = buffer.find(b"\xff\xd8")
        end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
        if start < 0 or end < 0:
            return found, buffer[start:] if start >= 0 else b""
        found.append(buffer[start : end + 2])
        buffer = buffer[end + 2 :]


class StillStream:
    def __init__(self, ffmpeg: str, source: str, mode: Mode, name: str) -> None:
        self.ffmpeg = ffmpeg
        self.source = source
        self.mode = mode
        self.name = name
        self.subscriptions: set[Subscription] = set()
        self.latest: dict[Format, tuple[bytes, float]] = {}
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.running = False

    def wanted(self) -> tuple[dict[Format, None], float]:
        formats: dict[Format, None] = {s.format: None for s in self.subscriptions}
        every = min((s.every for s in self.subscriptions), default=2.0)
        return formats, max(0.5, every)

    @contextlib.asynccontextmanager
    async def subscribe(self, format: Format, every: float) -> AsyncIterator[Subscription]:
        sub = Subscription(format, every)
        self.subscriptions.add(sub)
        self._changed.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"stills-{self.name}")
        try:
            yield sub
        finally:
            self.subscriptions.discard(sub)
            self._changed.set()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        """Run FFmpeg for what the subscribers want; again when that changes; idle without them."""
        delay = 2.0
        idle_since: float | None = None
        while True:
            if not self.subscriptions:
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= IDLE_AFTER:
                    return  # idle: the next subscriber starts it again
                self._changed.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._changed.wait(), IDLE_AFTER)
                continue
            idle_since = None
            formats, every = self.wanted()
            started = time.monotonic()
            error = await self._ffmpeg(list(formats), every)
            if error is None:
                delay = 2.0
                continue  # the subscribers changed
            if time.monotonic() - started > 60:
                delay = 2.0
            log.info("stills of %s stopped: %s; again in %.0f s", self.name, error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _ffmpeg(self, formats: list[Format], every: float) -> str | None:
        """Run FFmpeg until the wanted formats or interval change (None) or it fails (why)."""
        pipes: dict[Format, tuple[int, int]] = {f: os.pipe() for f in formats if f != "jpeg"}
        outputs: dict[Format, str] = {f: "pipe:1" if f == "jpeg" else f"pipe:{pipes[f][1]}" for f in formats}
        cmd = still_command(self.ffmpeg, self.source, self.mode, every, outputs)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                pass_fds=[w for _, w in pipes.values()],
            )
        finally:
            for _, w in pipes.values():
                os.close(w)
        self.running = True
        loop = asyncio.get_running_loop()
        readers: list[asyncio.Task[None]] = []
        transports = []
        try:
            if "jpeg" in formats and process.stdout:
                readers.append(asyncio.create_task(self._read_jpegs(process.stdout)))
            for fmt, (r, _) in pipes.items():
                reader = asyncio.StreamReader(limit=FRAME_BYTES[fmt] * 4)
                transport, _ = await loop.connect_read_pipe(
                    lambda reader=reader: asyncio.StreamReaderProtocol(reader), os.fdopen(r, "rb", 0)
                )
                transports.append(transport)
                readers.append(asyncio.create_task(self._read_frames(reader, fmt)))
            wanted = (dict.fromkeys(formats), every)
            exited = asyncio.create_task(process.wait())
            while True:
                self._changed.clear()
                change = asyncio.create_task(self._changed.wait())
                done, _ = await asyncio.wait({exited, change}, return_when=asyncio.FIRST_COMPLETED)
                change.cancel()
                if exited in done:
                    err = await process.stderr.read() if process.stderr else b""
                    return err.decode(errors="replace").strip()[-300:] or f"exit {process.returncode}"
                if not self.subscriptions or self.wanted() != wanted:
                    return None
        finally:
            self.running = False
            for task in readers:
                task.cancel()
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            for transport in transports:
                transport.close()

    def _deliver(self, fmt: Format, data: bytes) -> None:
        now = time.monotonic()
        self.latest[fmt] = (data, now)
        for sub in list(self.subscriptions):
            if sub.format == fmt:
                sub.offer(data, now)

    async def _read_jpegs(self, stream: asyncio.StreamReader) -> None:
        buffer = b""
        while chunk := await stream.read(65536):
            jpegs, buffer = split_jpegs(buffer + chunk)
            for jpeg in jpegs:
                self._deliver("jpeg", jpeg)

    async def _read_frames(self, stream: asyncio.StreamReader, fmt: Format) -> None:
        size = FRAME_BYTES[fmt]
        with contextlib.suppress(asyncio.IncompleteReadError):
            while True:
                self._deliver(fmt, await stream.readexactly(size))


class Stills:
    """The still streams of all cameras, made on first use."""

    def __init__(self, ffmpeg: str) -> None:
        self.ffmpeg = ffmpeg
        self.streams: dict[tuple[str, Mode], StillStream] = {}

    def stream(self, camera: str, source: str, mode: Mode) -> StillStream:
        key = (camera, mode)
        stream = self.streams.get(key)
        if stream is None or stream.source != source:
            stream = StillStream(self.ffmpeg, source, mode, f"{camera}/{mode}")
            self.streams[key] = stream
        return stream

    def latest(self, camera: str, fmt: Format, max_age: float) -> bytes | None:
        """The newest still of the camera in any mode, if it is at most `max_age` seconds old."""
        best: tuple[bytes, float] | None = None
        for (cam, _), stream in self.streams.items():
            if cam == camera and (item := stream.latest.get(fmt)) and (best is None or item[1] > best[1]):
                best = item
        if best and time.monotonic() - best[1] <= max_age:
            return best[0]
        return None

    def running(self, camera: str) -> bool:
        return any(s.running for (cam, _), s in self.streams.items() if cam == camera)

    async def stop(self) -> None:
        await asyncio.gather(*(s.stop() for s in self.streams.values()), return_exceptions=True)
