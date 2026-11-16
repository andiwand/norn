"""The GOP cache: keyframes found in go2rtc's fMP4, viewers start at the newest one."""

from __future__ import annotations

import asyncio
import struct

from norn.gop import GopCache, codecs_fit, fragment_info, video_track


def box(kind: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def trak(track: int, handler: bytes) -> bytes:
    tkhd = box(b"tkhd", b"\0\0\0\x07" + b"\0" * 8 + struct.pack(">I", track) + b"\0" * 68)
    hdlr = box(b"hdlr", b"\0" * 8 + handler + b"\0" * 13)
    return box(b"trak", tkhd + box(b"mdia", box(b"mdhd", b"\0" * 24) + hdlr))


INIT = box(b"ftyp", b"iso5\0\0\0\0") + box(
    b"moov", box(b"mvhd", b"\0" * 100) + trak(1, b"vide") + trak(2, b"soun")
)


def fragment(track: int, key: bool, size: int = 10) -> bytes:
    """Like go2rtc's: tfhd with default duration, size and sample flags (0x20038)."""
    flags = 0x02000000 if key else 0x01010000
    tfhd = box(b"tfhd", struct.pack(">IIIII", 0x20038, track, 3000, size, flags))
    traf = box(
        b"traf", tfhd + box(b"tfdt", b"\1\0\0\0" + b"\0" * 8) + box(b"trun", struct.pack(">III", 1, 1, 0))
    )
    return box(b"moof", box(b"mfhd", b"\0" * 8) + traf) + box(b"mdat", b"x" * size)


def test_parsing() -> None:
    assert video_track(INIT) == 2 - 1
    assert fragment_info(fragment(1, True)) == (1, True)
    assert fragment_info(fragment(1, False)) == (1, False)
    assert fragment_info(fragment(2, True)) == (2, True)
    assert codecs_fit("avc1.640029,mp4a.40.2", 'video/mp4; codecs="avc1.4D401F,mp4a.40.2"')
    assert not codecs_fit("avc1.640029,mp4a.40.2", 'video/mp4; codecs="hvc1.1.6.L153.B0"')


async def test_viewers_start_at_the_newest_keyframe() -> None:
    cache = GopCache("ws://unused", "cam_sub", connect=False)
    cache.codec = 'video/mp4; codecs="avc1.640029,mp4a.40.2"'
    cache._take(INIT)
    first, p1, audio = fragment(1, True), fragment(1, False), fragment(2, True)
    for data in (fragment(1, False), first, p1, audio):  # a P-frame before any keyframe is dropped
        cache._take(data)
    assert cache.ready and cache.gop == [first, p1, audio]
    assert cache.keyframe() == (INIT, first)

    codec, start, queue = cache.subscribe()
    assert codec.startswith("video/mp4") and start == INIT + first + p1 + audio
    later = fragment(1, False)
    cache._take(later)
    assert await asyncio.wait_for(queue.get(), 1) == later
    newer = fragment(1, True)
    cache._take(newer)  # a new keyframe starts a new GOP
    assert cache.gop == [newer] and await queue.get() == newer
    cache._take(INIT)  # a new init segment: viewers start over
    assert await queue.get() is None
    assert cache.viewers == 0


async def test_a_slow_viewer_is_ended_even_with_a_full_queue() -> None:
    from norn.gop import QUEUE

    cache = GopCache("ws://unused", "cam_sub", connect=False)
    cache.codec = 'video/mp4; codecs="avc1.640029"'
    cache._take(INIT)
    cache._take(fragment(1, True))
    _, _, queue = cache.subscribe()
    for _ in range(QUEUE + 1):  # it never reads: the last one doesn't fit
        cache._take(fragment(1, False))
    items = [queue.get_nowait() for _ in range(queue.qsize())]
    assert items[-1] is None and cache.viewers == 0


def _h264_fragments() -> bytes:
    """A real fragmented H.264 stream, one frame per fragment like go2rtc's, a keyframe every 10."""
    import subprocess

    source = "testsrc2=size=320x180:rate=10"
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source, "-t", "2",
         "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p",
         "-movflags", "frag_every_frame+empty_moov+default_base_moof", "-f", "mp4", "pipe:1"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


async def test_a_still_from_the_newest_keyframe(settings) -> None:  # type: ignore[no-untyped-def]
    import shutil

    import pytest

    from norn.gop import _boxes
    from norn.hub import Hub

    if not shutil.which("ffmpeg"):
        pytest.skip("needs ffmpeg")
    mp4 = _h264_fragments()
    parts = [mp4[start - 8 : end] for _, start, end in _boxes(mp4)]
    init = b"".join(p for p in parts if p[4:8] in (b"ftyp", b"moov"))
    fragments = [a + b for a, b in zip(parts[2::2], parts[3::2], strict=False) if a[4:8] == b"moof"]
    cache = GopCache("ws://unused", "demo_sub", connect=False)
    cache.codec = 'video/mp4; codecs="avc1.640029"'
    cache._take(init)
    for f in fragments[:13]:
        cache._take(f)
    assert cache.ready and len(cache.gop) == 3  # frames 10, 11, 12: from the second keyframe

    import dataclasses

    hub = Hub(dataclasses.replace(settings, ffmpeg_bin="ffmpeg"))
    jpeg = await hub._gop_jpeg(cache)
    assert jpeg and jpeg[:2] == b"\xff\xd8"
    assert cache.cached_jpeg() == jpeg  # decoded once per keyframe


def test_ready_streams_setting(client) -> None:  # type: ignore[no-untyped-def]
    hub = client.app.state.hub
    camera = hub.cameras["demo"]
    assert hub.ready_streams(camera) == {"sub"}  # by default: what the Live page shows
    options = {o["id"]: o for o in client.get("/api/cameras/demo").json()["stream_options"]}
    assert options["sub"]["ready"]
    # The demo's pattern is made by FFmpeg: keeping it ready would encode all the time.
    assert not options["sub"]["can_be_ready"]
    assert hub._gop_streams() == {}

    body = {"name": "Demo camera", "driver": "demo", "ready_streams": ["main", "sub"]}
    assert client.put("/api/cameras/demo", json=body).json()["ready_streams"] == ["main", "sub"]
    assert hub.ready_streams(hub.cameras["demo"]) == {"main", "sub"}
    # A form that leaves it out keeps it.
    client.put("/api/cameras/demo", json={"name": "Demo camera", "driver": "demo"})
    assert client.get("/api/cameras/demo").json()["ready_streams"] == ["main", "sub"]
