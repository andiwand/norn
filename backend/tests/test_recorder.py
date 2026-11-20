from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from norn.config import Config
from norn.hub import Hub
from norn.recorder import MAX_CLIP_SECONDS, Buffer, Clip, Recorder
from norn.settings import Settings


@pytest.fixture
def recorder(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Hub(settings).recorder
    recorder.available = True
    recorder._config = Config.model_validate({"cameras": {"c": {"name": "C", "driver": "demo"}}})

    async def no_video(clip: Clip) -> None:  # no FFmpeg in the tests
        pass

    monkeypatch.setattr(recorder, "_run_clip", no_video)
    return recorder


def touch(path: Path, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


async def test_a_trigger_while_a_clip_closes_starts_a_new_one(recorder: Recorder) -> None:
    old = await recorder.record_clip("c", "manual", 10)
    old.closing = True  # its end is fixed: it can't grow any more
    new = await recorder.record_clip("c", "person", 10)
    assert new is not old and old.events == {"manual"} and recorder.clips["c"] is new
    await recorder._finish_clip(old, {}, asyncio.create_task(asyncio.sleep(0)))
    assert recorder.clips["c"] is new  # finishing the old one leaves the new one alone


async def test_triggers_extend_a_clip_only_so_far(recorder: Recorder) -> None:
    clip = await recorder.record_clip("c", "manual", 10)
    clip.start -= timedelta(seconds=MAX_CLIP_SECONDS - 5)
    assert await recorder.record_clip("c", "person", 60) is clip
    assert clip.end <= clip.start.timestamp() + MAX_CLIP_SECONDS


async def test_a_failing_buffered_clip_frees_the_camera(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def collect(clip: Clip, buffer: Any, joined: Path, claim: int) -> None:
        await asyncio.to_thread(joined.write_bytes, b"ts")

    async def broken(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise OSError("ffmpeg is gone")

    monkeypatch.setattr(recorder, "_collect", collect)
    monkeypatch.setattr("norn.recorder.run", broken)
    now = datetime.now().replace(microsecond=0)
    path = recorder.temp.file_path("c", now, "manual")
    path.parent.mkdir(parents=True)
    clip = Clip("c", path, "manual", now, now, 10, time.time(), {"manual"})
    recorder.clips["c"] = clip
    await recorder._run_buffered_clip(clip, SimpleNamespace(claims={}))  # type: ignore[arg-type]
    assert "c" not in recorder.clips


async def test_buffered_counts_only_the_current_run(recorder: Recorder, settings: Settings) -> None:
    buffer = Buffer.__new__(Buffer)
    buffer.folder, buffer.seconds, buffer.running, buffer.run_first = settings.buffer_path / "c", 30, True, 4
    now = time.time()
    for index in range(6):  # 0-3 from an earlier FFmpeg run; 4 and 5 from this one
        touch(buffer.folder / f"{index:010d}.ts", now - 20 + index * 4 if index < 4 else now - 4 + index - 4)
    recorder._buffers["c"] = buffer
    assert recorder.buffered("c") == 4


async def test_moves_never_overwrite_and_newest_is_by_time(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok(*args: Any, **kwargs: Any) -> tuple[int, str]:
        return 0, ""

    monkeypatch.setattr("norn.recorder.run", ok)
    day = "2026-10-25"
    kept = touch(recorder.library.path("c", day, "02-50-00_continuous.mp4"))
    now = time.time()
    # The clocks went back: 02-50-00 is the second 02:50 (finished), 02-00-00 is being written.
    touch(recorder.temp.path("c", day, "02-50-00_continuous.mp4"), now - 600)
    writing = touch(recorder.temp.path("c", day, "02-00-00_continuous.mp4"), now)
    recorder._continuous["c"] = asyncio.get_running_loop().create_future()  # type: ignore[assignment]
    await recorder._move_finished()
    assert writing.exists() and kept.exists()
    assert recorder.library.path("c", day, "02-50-01_continuous.mp4").exists()


async def test_recover_drops_the_thumbnail_of_a_clip_without_video(recorder: Recorder) -> None:
    day = "2026-11-15"
    orphan = touch(recorder.temp.path("c", day, "08-00-00_motion.jpg"))
    touch(recorder.temp.path("c", day, "08-00-00_interval.jpg"))
    await recorder._recover()
    assert not orphan.exists()
    assert recorder.library.path("c", day, "08-00-00_interval.jpg").exists()
    assert not recorder.library.path("c", day, "08-00-00_motion.jpg").exists()


async def test_stop_lets_stopped_recordings_finish(recorder: Recorder) -> None:
    recorder.available = False
    finishing = asyncio.create_task(asyncio.sleep(0.05))
    recorder._stopping["c"] = finishing
    await recorder.stop()
    assert finishing.done() and not finishing.cancelled()


async def test_a_clip_notes_who_saw_it(recorder: Recorder) -> None:
    """A clip's notes: who detected what started it, and what Norn's AI saw while it ran (a
    camera's person with nothing seen by Norn is a likely false alarm)."""
    clip = await recorder.record_clip("c", "person", 10, by={"camera"})
    assert await recorder.record_clip("c", "person", 10, by={"norn"}) is clip
    clip.checked = True
    clip.norn_saw.add("animal")
    meta: dict[str, Any] = {}
    async with recorder.bus.subscribe() as queue:
        await recorder._finish_clip(clip, meta, asyncio.create_task(asyncio.sleep(0)))
        finished = await asyncio.wait_for(queue.get(), 1)
    assert meta["by"] == {"person": ["camera", "norn"]} and meta["norn_saw"] == ["animal"]
    assert finished["data"]["by"] == {"person": ["camera", "norn"]}


async def test_a_clip_keeps_norns_boxes(recorder: Recorder) -> None:
    """What Norn's AI found on the stills of a clip's time, from before its trigger too, goes
    next to the video (`.objects.json`) and moves into the recordings with it; the API serves it."""
    person = [{"kind": "person", "score": 0.8, "box": [0.1, 0.2, 0.3, 0.6], "status": "counts"}]
    recorder.note_objects("c", [])  # longer ago than the clip's start: not in it
    recorder._seen["c"][0] = (time.time() - 60, [])
    recorder.note_objects("c", person)  # before the trigger, within the pre-recording
    clip = await recorder.record_clip("c", "person", 10)
    clip.start -= timedelta(seconds=5)
    clip.began = clip.start.timestamp() - 2  # its first piece from the buffer began earlier
    recorder.note_objects("c", [])
    touch(clip.path)
    await recorder._finish_clip(clip, {}, asyncio.create_task(asyncio.sleep(0)))
    [video] = [p for p in recorder.library.root.rglob("*.mp4")]
    seen = json.loads(video.with_suffix(".objects.json").read_text())
    assert [s["objects"] for s in seen] == [person, []]
    assert 6 <= seen[0]["at"] <= 8 and seen[0]["at"] <= seen[1]["at"]
