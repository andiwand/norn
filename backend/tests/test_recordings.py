from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from norn.recorder import buffer_command, clip_command, segment_command
from norn.recordings import InvalidPathError, Library, expires


def touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def library(tmp_path: Path) -> Library:
    root = tmp_path / "rec"
    touch(root / "door" / "2026-11-14" / "08-00-00_continuous.mp4", b"12345")
    video = touch(root / "door" / "2026-11-15" / "14-32-07_manual.mp4")
    video.with_suffix(".json").write_text(json.dumps({"duration": 30.5, "trigger": "manual"}))
    touch(video.with_suffix(".jpg"))
    touch(root / "door" / "2026-11-15" / "notes.txt")
    (root / "door" / "2026-11-16").mkdir()  # made in advance by the recorder, still empty
    touch(root / "yard" / "2026-11-15" / "09-00-00_motion.mp4")
    return Library(root)


def test_list(library: Library) -> None:
    items = library.list()
    assert [r.id for r in items] == [
        "door/2026-11-15/14-32-07_manual.mp4",
        "yard/2026-11-15/09-00-00_motion.mp4",
        "door/2026-11-14/08-00-00_continuous.mp4",
    ]
    clip = items[0]
    assert clip.duration == 30.5
    assert clip.thumbnail
    assert clip.start == datetime(2026, 11, 15, 14, 32, 7)
    assert items[2].size == 5 and items[2].duration is None
    assert [r.id for r in library.list(camera="door", day="2026-11-14")] == [items[2].id]


def test_days_skip_empty(library: Library) -> None:
    assert library.days("door") == ["2026-11-15", "2026-11-14"]
    assert library.days("nobody") == []


def test_delete_removes_sidecars(library: Library) -> None:
    assert library.delete("door", "2026-11-15", "14-32-07_manual.mp4")
    folder = library.root / "door" / "2026-11-15"
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt"]
    assert not library.delete("door", "2026-11-15", "14-32-07_manual.mp4")


def test_prune_keeps_manual(library: Library) -> None:
    assert library.prune(0, now=datetime(2030, 1, 1)) == []  # 0 keeps forever
    assert library.prune(1, now=datetime(2026, 11, 16, 9, 30)) == [
        "door/2026-11-14/08-00-00_continuous.mp4",
        "yard/2026-11-15/09-00-00_motion.mp4",
    ]
    # A clip recorded by hand stays until someone deletes it.
    assert library.prune(1, now=datetime(2030, 1, 1)) == []
    assert [r.id for r in library.list()] == ["door/2026-11-15/14-32-07_manual.mp4"]


def test_expires() -> None:
    start = datetime(2026, 11, 15, 10)
    assert expires(start, "continuous", 14) == datetime(2026, 11, 29, 10)
    assert expires(start, "manual", 14) is None
    assert expires(start, "interval", 0) is None


def test_pictures(library: Library) -> None:
    picture = touch(library.root / "yard" / "2026-11-15" / "10-00-00_interval.jpg", b"jpeg")
    items = {r.id: r for r in library.list(camera="yard")}
    assert items["yard/2026-11-15/10-00-00_interval.jpg"].kind == "picture"
    assert items["yard/2026-11-15/09-00-00_motion.mp4"].kind == "video"
    # The thumbnail of a video isn't a picture of its own.
    assert "door/2026-11-15/14-32-07_manual.jpg" not in {r.id for r in library.list()}
    assert [r.kind for r in library.list(kind="picture")] == ["picture"]
    assert library.delete("yard", "2026-11-15", picture.name)
    assert not picture.exists()


def test_time_range(library: Library) -> None:
    since, until = datetime(2026, 11, 15, 0), datetime(2026, 11, 15, 12)
    assert [r.id for r in library.list(since=since, until=until)] == ["yard/2026-11-15/09-00-00_motion.mp4"]


def test_usage(library: Library) -> None:
    usage = library.usage()
    assert usage["used"] > 0 and usage["files"] == 6
    assert usage["free"] is not None


@pytest.mark.parametrize(
    ("camera", "day", "name"),
    [
        ("..", None, None),
        ("door", "../x", None),
        ("door", "2026-11-15", "../../etc.mp4"),
        ("door", "2026-11-15", "a.sh"),
    ],
)
def test_path_rejects_escapes(library: Library, camera: str, day: str | None, name: str | None) -> None:
    with pytest.raises(InvalidPathError):
        library.path(camera, day, name)


def test_commands_copy_video() -> None:
    seg = segment_command("ffmpeg", "rtsp://127.0.0.1:8554/door", Path("/rec/door"), 600)
    assert seg[seg.index("-c:v") + 1] == "copy"
    assert seg[-1] == "/rec/door/%Y-%m-%d/%H-%M-%S_continuous.mp4"
    clip = clip_command("ffmpeg", "rtsp://x/door", Path("/rec/a.mp4"), 30)
    assert clip[clip.index("-c:v") + 1] == "copy"
    assert clip[clip.index("-t") + 1] == "30"


def test_describe_ffmpeg() -> None:
    from norn.resources import describe

    class Fake:
        pid = -1

        def __init__(self, cmd: list[str]) -> None:
            self.cmd = cmd

        def cmdline(self) -> list[str]:
            return self.cmd

        def name(self) -> str:
            return "x"

    buffer = buffer_command("/usr/bin/ffmpeg", "rtsp://127.0.0.1:8554/door", Path("/b/door"), 0)
    assert describe(Fake(buffer)) == ("Buffer", "door")  # type: ignore[arg-type]
    seg = segment_command("ffmpeg", "rtsp://127.0.0.1:8554/door", Path("/t/door"), 600)
    assert describe(Fake(seg)) == ("Continuous", "door")  # type: ignore[arg-type]
    assert describe(Fake(["/usr/local/bin/go2rtc", "-c", "x"])) == ("go2rtc", None)  # type: ignore[arg-type]


def test_filters_and_thinning(library: Library) -> None:
    for minute in range(10):
        touch(library.root / "yard" / "2026-11-15" / f"10-{minute:02d}-00_interval.jpg", b"j")
    assert [r.trigger for r in library.list(trigger="clips")] == ["manual", "motion"]
    assert len(library.list(trigger="interval")) == 10
    thinned = library.list(pictures=3)
    assert sum(r.kind == "picture" for r in thinned) == 3
    assert sum(r.kind == "video" for r in thinned) == 3  # videos all stay
    thumb = touch(library.thumb_path("yard", "2026-11-15", "10-00-00_interval.jpg"))
    assert library.delete("yard", "2026-11-15", "10-00-00_interval.jpg") and not thumb.exists()
    assert "yard" in library.cameras() and ".thumbs" not in library.cameras()


def test_describe_stills() -> None:
    from norn.resources import describe
    from norn.stills import still_command

    class Fake:
        pid = -1

        def cmdline(self) -> list[str]:
            source = "rtsp://127.0.0.1:8554/door_sub"
            return still_command("ffmpeg", source, "keyframe", 1, {"jpeg": "pipe:1"})

        def name(self) -> str:
            return "ffmpeg"

    assert describe(Fake()) == ("Stills", "door")  # type: ignore[arg-type]


def test_evict_oldest_automatic_first(library: Library) -> None:
    from norn.recordings import folder_size

    assert library.evict() == ([], 0)  # no limits
    total = folder_size(library.root)[0]
    # 3 bytes too much: the oldest automatic recording (the 5-byte continuous file) goes.
    deleted, excess = library.evict(max_bytes=total - 3)
    assert deleted == ["door/2026-11-14/08-00-00_continuous.mp4"] and excess == 0
    deleted, excess = library.evict(max_bytes=1)
    assert deleted == ["yard/2026-11-15/09-00-00_motion.mp4"]
    assert excess > 0  # the manual clip stays, whatever the limit
    assert [r.trigger for r in library.list()] == ["manual"]
