"""Instant live video: the newest keyframe of a stream, and what followed, kept ready.

A viewer can start decoding only at a keyframe. A camera sends one every few seconds, so a new
viewer waits up to that long for the first picture. A GopCache reads a stream from go2rtc as
fMP4 (the format of MSE) all the time and keeps the init segment and every fragment since the
last video keyframe. A new MSE viewer gets those at once: its browser decodes them in a blink
and plays faster until it reaches the live end (the player does that already), then follows
the live fragments from here. The same keyframe gives a still without waiting.

go2rtc sends one frame per message (moof + mdat), the video and audio tracks separately; a
fragment says in its track header (tfhd) whether its frame is a keyframe.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
import time
from collections.abc import AsyncIterator, Iterator

import websockets

log = logging.getLogger("norn.gop")

# What Norn asks go2rtc for: H.264 and H.265 video, AAC audio (no transcoding).
CODECS = "avc1.640029,avc1.64002A,avc1.640033,hvc1.1.6.L153.B0,mp4a.40.2,mp4a.40.5"
MAX_BYTES = 12 * 1024 * 1024  # a GOP larger than this isn't kept (a stream without keyframes)
QUEUE = 512  # fragments a slow viewer may lag behind before it's dropped
CONTAINERS = {b"moov", b"trak", b"mdia", b"moof", b"traf"}
NON_SYNC = 0x00010000  # sample_is_non_sync_sample: not a keyframe


def _boxes(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[bytes, int, int]]:
    """(type, start of its content, end) of each box in data[start:end]."""
    end = len(data) if end is None else end
    while start + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, start)
        if size < 8 or start + size > end:
            return
        yield kind, start + 8, start + size
        start += size


def _find(
    data: bytes, path: list[bytes], start: int = 0, end: int | None = None
) -> Iterator[tuple[int, int]]:
    """The boxes at `path` (e.g. moof/traf/tfhd), as (content start, end)."""
    for kind, body, stop in _boxes(data, start, end):
        if kind == path[0]:
            if len(path) == 1:
                yield body, stop
            elif kind in CONTAINERS:
                yield from _find(data, path[1:], body, stop)


def video_track(init: bytes) -> int | None:
    """The track id of the video in an init segment (moov/trak with a 'vide' handler)."""
    for trak, trak_end in _find(init, [b"moov", b"trak"]):
        handler = next(_find(init, [b"mdia", b"hdlr"], trak, trak_end), None)
        header = next(_find(init, [b"tkhd"], trak, trak_end), None)
        if handler and header and init[handler[0] + 8 : handler[0] + 12] == b"vide":
            version = init[header[0]]
            return int(struct.unpack_from(">I", init, header[0] + (12 if version == 0 else 20))[0])
    return None


def fragment_info(fragment: bytes) -> tuple[int | None, bool]:
    """The track of a fragment, and whether its first sample is a keyframe."""
    for body, _ in _find(fragment, [b"moof", b"traf", b"tfhd"]):
        flags = struct.unpack_from(">I", fragment, body)[0] & 0xFFFFFF
        track = int(struct.unpack_from(">I", fragment, body + 4)[0])
        offset = body + 8
        for bit, size in ((0x1, 8), (0x2, 4), (0x8, 4), (0x10, 4)):
            if flags & bit:
                offset += size
        sample_flags = struct.unpack_from(">I", fragment, offset)[0] if flags & 0x20 else None
        # A trun can override the flags of its first sample.
        for run, _ in _find(fragment, [b"moof", b"traf", b"trun"]):
            run_flags = struct.unpack_from(">I", fragment, run)[0] & 0xFFFFFF
            if run_flags & 0x4:
                sample_flags = struct.unpack_from(">I", fragment, run + 8 + (4 if run_flags & 0x1 else 0))[0]
        return track, sample_flags is not None and not sample_flags & NON_SYNC
    return None, False


def codecs_fit(offered: str, wanted: str) -> bool:
    """Whether a browser that can play `offered` (its MSE codec list) can play the stream
    whose MSE type is `wanted` (video/mp4; codecs="avc1.640029,mp4a.40.2")."""
    have = [c.strip() for c in offered.split(",")]
    inner = wanted.split("codecs=")[-1].strip('"')
    for codec in (c.strip() for c in inner.split(",")):
        family = codec.split(".")[0]
        if not any(h.split(".")[0] == family for h in have):
            return False
    return True


class GopCache:
    """One stream from go2rtc, its newest GOP kept, and its fragments passed on to viewers."""

    def __init__(self, url: str, name: str, connect: bool = True) -> None:
        self.url = url
        self.name = name
        self.codec: str | None = None  # the MSE type go2rtc chose
        self.init: bytes | None = None
        self.gop: list[bytes] = []  # from the newest video keyframe on
        self.gop_bytes = 0
        self.keyframe_at = 0.0  # monotonic time of the newest keyframe
        self.last_used = time.monotonic()
        self._video: int | None = None
        self._viewers: set[asyncio.Queue[bytes | None]] = set()
        self._jpeg: tuple[int, bytes] | None = None  # (id of the keyframe, its still)
        self.task: asyncio.Task[None] | None = (
            asyncio.create_task(self._run(), name=f"gop-{name}") if connect else None
        )

    @property
    def ready(self) -> bool:
        return bool(self.codec and self.init and self.gop)

    def keyframe(self) -> tuple[bytes, bytes] | None:
        """The init segment and the newest keyframe, to decode a still from."""
        if not self.init or not self.gop:
            return None
        return self.init, self.gop[0]

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self._end_viewers()

    @contextlib.asynccontextmanager
    async def watch(self) -> AsyncIterator[tuple[str, bytes, asyncio.Queue[bytes | None]]]:
        """For a viewer: the MSE type, the init segment with the GOP so far (one message, so
        the browser appends it at once), and a queue of the fragments after it (None: the
        stream restarted; the viewer must start over)."""
        if not self.ready:
            raise LookupError("not ready")
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE)
        assert self.codec and self.init
        start = self.init + b"".join(self.gop)
        self._viewers.add(queue)
        self.last_used = time.monotonic()
        try:
            yield self.codec, start, queue
        finally:
            self._viewers.discard(queue)
            self.last_used = time.monotonic()

    @property
    def viewers(self) -> int:
        return len(self._viewers)

    def still_key(self) -> int | None:
        return id(self.gop[0]) if self.gop else None

    def cached_jpeg(self) -> bytes | None:
        key = self.still_key()
        return self._jpeg[1] if self._jpeg and self._jpeg[0] == key else None

    def keep_jpeg(self, key: int, jpeg: bytes) -> None:
        self._jpeg = (key, jpeg)

    def _end_viewers(self) -> None:
        for queue in list(self._viewers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        self._viewers.clear()

    def _take(self, data: bytes) -> None:
        if data[4:8] == b"ftyp" or next(_find(data, [b"moov"]), None):
            # A new init segment: a new timeline. Viewers of the old one start over.
            self.init = data
            self._video = video_track(data)
            self.gop, self.gop_bytes = [], 0
            self._end_viewers()
            return
        track, key = fragment_info(data)
        if track == self._video and key:
            self.gop, self.gop_bytes = [data], len(data)
            self.keyframe_at = time.monotonic()
        elif self.gop:
            self.gop.append(data)
            self.gop_bytes += len(data)
            if self.gop_bytes > MAX_BYTES:
                self.gop, self.gop_bytes = [], 0
        for queue in list(self._viewers):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:  # too slow: it starts over
                self._viewers.discard(queue)
                with contextlib.suppress(asyncio.QueueFull):
                    queue.get_nowait()
                    queue.put_nowait(None)

    async def _run(self) -> None:
        delay = 2.0
        while True:
            try:
                async with websockets.connect(self.url, max_size=None, open_timeout=10) as ws:
                    await ws.send(json.dumps({"type": "mse", "value": CODECS}))
                    async for message in ws:
                        if isinstance(message, str):
                            msg = json.loads(message)
                            if msg.get("type") == "mse":
                                self.codec = msg.get("value")
                            elif msg.get("type") == "error":
                                raise OSError(msg.get("value"))
                            continue
                        self._take(message)
                        delay = 2.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.info("%s: %s", self.name, e)
            self.codec, self.init, self.gop, self.gop_bytes = None, None, [], 0
            self._end_viewers()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
