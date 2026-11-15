from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from norn.recorder import clip_command, segment_command
from norn.recordings import InvalidPathError, Library


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


def test_prune(library: Library) -> None:
    assert library.prune(1, today=date(2026, 11, 16)) == ["door/2026-11-14"]
    assert library.prune(0, today=date(2030, 1, 1)) == []  # 0 keeps forever


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
