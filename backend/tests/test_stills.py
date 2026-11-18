from __future__ import annotations

from norn.stills import Stills, split_jpegs


def test_a_start_marker_split_between_chunks() -> None:
    a = b"\xff\xd8one\xff\xd9"
    jpegs, rest = split_jpegs(a + b"\xff")
    assert jpegs == [a] and rest == b"\xff"
    jpegs, rest = split_jpegs(rest + b"\xd8two\xff\xd9")
    assert jpegs == [b"\xff\xd8two\xff\xd9"] and rest == b""
    assert split_jpegs(b"junk") == ([], b"")


async def test_streams_of_an_old_source_are_dropped() -> None:
    stills = Stills("ffmpeg")
    stills.stream("door", "rtsp://x/door", "keyframe")
    stills.stream("yard", "rtsp://x/yard", "keyframe")
    new = stills.stream("door", "rtsp://x/door_sub", "keyframe")
    assert set(stills.streams) == {
        ("door", "keyframe", "rtsp://x/door_sub"),
        ("yard", "keyframe", "rtsp://x/yard"),
    }
    assert stills.stream("door", "rtsp://x/door_sub", "keyframe") is new
