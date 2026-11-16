"""Instant live video: each stream's newest keyframe, and what followed, kept ready.

A viewer can start decoding only at a keyframe, and cameras send one every few seconds. A
GopCache reads a stream from go2rtc as fMP4 (MSE's format) all the time and keeps the init
segment and the fragments since the newest video keyframe. New MSE viewers get those at once;
the player catches up to live. The keyframe also gives a still without waiting.

go2rtc sends one frame per message (moof + mdat), video and audio separately; the fragment's
track header (tfhd) flags keyframes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
import time
from collections.abc import Iterator

import websockets

log = logging.getLogger("norn.gop")

# What Norn asks go2rtc for: H.264/H.265, and the audio go2rtc sends without transcoding (AAC;
# FLAC for G.711; Opus). The same list as the player's.
CODECS = "avc1.640029,avc1.64002A,avc1.640033,hvc1.1.6.L153.B0,mp4a.40.2,mp4a.40.5,flac,opus"
MAX_BYTES = 12 * 1024 * 1024  # a GOP larger than this isn't kept
QUEUE = 512  # fragments a viewer may lag behind before it's dropped
CONTAINERS = {b"moov", b"trak", b"mdia", b"moof", b"traf"}
NON_SYNC = 0x00010000  # sample_is_non_sync_sample


def _boxes(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[bytes, int, int]]:
    """(type, content start, end) of each box in data[start:end]."""
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
    """(content start, end) of the boxes at `path`, e.g. moof/traf/tfhd."""
    for kind, body, stop in _boxes(data, start, end):
        if kind == path[0]:
            if len(path) == 1:
                yield body, stop
            elif kind in CONTAINERS:
                yield from _find(data, path[1:], body, stop)


def video_track(init: bytes) -> int | None:
    """The id of the track with a 'vide' handler."""
    for trak, trak_end in _find(init, [b"moov", b"trak"]):
        handler = next(_find(init, [b"mdia", b"hdlr"], trak, trak_end), None)
        header = next(_find(init, [b"tkhd"], trak, trak_end), None)
        if handler and header and init[handler[0] + 8 : handler[0] + 12] == b"vide":
            version = init[header[0]]
            return int(struct.unpack_from(">I", init, header[0] + (12 if version == 0 else 20))[0])
    return None


def fragment_info(fragment: bytes) -> tuple[int | None, bool]:
    """The track of a fragment, and whether its first sample is a keyframe."""
    traf = next(_find(fragment, [b"moof", b"traf"]), None)
    tfhd = traf and next(_find(fragment, [b"tfhd"], *traf), None)
    if not traf or not tfhd:
        return None, False
    body = tfhd[0]
    flags, track = struct.unpack_from(">II", fragment, body)
    flags &= 0xFFFFFF
    offset = body + 8 + sum(size for bit, size in ((0x1, 8), (0x2, 4), (0x8, 4), (0x10, 4)) if flags & bit)
    sample = struct.unpack_from(">I", fragment, offset)[0] if flags & 0x20 else None
    for run, _ in _find(fragment, [b"trun"], *traf):  # its first-sample flags win
        run_flags = struct.unpack_from(">I", fragment, run)[0] & 0xFFFFFF
        if run_flags & 0x4:
            sample = struct.unpack_from(">I", fragment, run + 8 + (4 if run_flags & 0x1 else 0))[0]
    return int(track), sample is not None and not sample & NON_SYNC


def codecs_fit(offered: str, wanted: str) -> bool:
    """Whether a browser offering `offered` (an MSE codec list) plays the MSE type `wanted`."""
    have = {c.strip().split(".")[0] for c in offered.split(",")}
    inner = wanted.split("codecs=")[-1].strip('"')
    return all(c.strip().split(".")[0] in have for c in inner.split(","))


class GopCache:
    """One go2rtc stream: its newest GOP kept, its fragments passed on to viewers."""

    def __init__(self, url: str, name: str, source: str = "", connect: bool = True) -> None:
        self.url, self.name, self.source = url, name, source  # source: restart when it changes
        self.codec: str | None = None  # the MSE type go2rtc chose
        self.init: bytes | None = None
        self.gop: list[bytes] = []  # from the newest video keyframe on
        self.gop_bytes = 0
        self.keyframe_at = 0.0  # monotonic
        self.last_used = time.monotonic()
        self._video: int | None = None
        self._viewers: set[asyncio.Queue[bytes | None]] = set()
        self._jpeg: tuple[bytes, bytes] | None = None  # (keyframe, its still)
        self.task = asyncio.create_task(self._run(), name=f"gop-{name}") if connect else None

    @property
    def ready(self) -> bool:
        return bool(self.codec and self.init and self.gop)

    @property
    def viewers(self) -> int:
        return len(self._viewers)

    def keyframe(self) -> tuple[bytes, bytes] | None:
        """The init segment and the newest keyframe."""
        return (self.init, self.gop[0]) if self.init and self.gop else None

    def cached_jpeg(self) -> bytes | None:
        return self._jpeg[1] if self._jpeg and self.gop and self._jpeg[0] is self.gop[0] else None

    def keep_jpeg(self, keyframe: bytes, jpeg: bytes) -> None:
        self._jpeg = (keyframe, jpeg)

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self._end_viewers()

    def subscribe(self) -> tuple[str, bytes, asyncio.Queue[bytes | None]]:
        """(MSE type, init + GOP as one message, a queue of the fragments after it). None in the
        queue: the stream restarted or the viewer fell behind; it must start over."""
        if not self.codec or not self.init or not self.gop:
            raise LookupError("not ready")
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE)
        self._viewers.add(queue)
        self.last_used = time.monotonic()
        return self.codec, self.init + b"".join(self.gop), queue

    def unsubscribe(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._viewers.discard(queue)
        self.last_used = time.monotonic()

    def _drop(self, queue: asyncio.Queue[bytes | None]) -> None:
        """End a viewer: room for the None that tells it, even in a full queue."""
        self._viewers.discard(queue)
        with contextlib.suppress(asyncio.QueueEmpty):
            if queue.full():
                queue.get_nowait()
        queue.put_nowait(None)

    def _end_viewers(self) -> None:
        for queue in list(self._viewers):
            self._drop(queue)

    def _take(self, data: bytes) -> None:
        if data[4:8] == b"ftyp":  # a new init segment, a new timeline
            self.init, self._video = data, video_track(data)
            self.gop, self.gop_bytes = [], 0
            self._end_viewers()
            return
        track, key = fragment_info(data)
        if track == self._video and key:
            self.gop, self.gop_bytes, self.keyframe_at = [data], len(data), time.monotonic()
        elif self.gop:
            self.gop.append(data)
            self.gop_bytes += len(data)
            if self.gop_bytes > MAX_BYTES:
                self.gop, self.gop_bytes = [], 0
        for queue in list(self._viewers):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                self._drop(queue)

    async def _run(self) -> None:
        delay = 2.0
        while True:
            try:
                async with websockets.connect(self.url, max_size=None, open_timeout=10) as ws:
                    await ws.send(json.dumps({"type": "mse", "value": CODECS}))
                    async for message in ws:
                        if isinstance(message, bytes):
                            self._take(message)
                            delay = 2.0
                            continue
                        msg = json.loads(message)
                        if msg.get("type") == "mse":
                            self.codec = msg.get("value")
                        elif msg.get("type") == "error":
                            raise OSError(msg.get("value"))
            except Exception as e:
                log.info("%s: %s", self.name, e)
            self.codec, self.init, self.gop, self.gop_bytes = None, None, [], 0
            self._end_viewers()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
