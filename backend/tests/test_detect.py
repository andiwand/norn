"""Norn's own detection and still streams, without cameras: the pieces with made-up data."""

from __future__ import annotations

import numpy as np
import pytest

from norn.config import Config
from norn.detect import (
    OBJECT_SIZE,
    Detection,
    MotionDetector,
    Tracker,
    decode,
    gray_from_bgr,
    motion_threshold,
)
from norn.stills import split_jpegs, still_command


def test_motion() -> None:
    detector = MotionDetector(sensitivity=50)
    still = bytes(160 * 90)
    assert not detector.update(still)  # the first still is the background
    assert not detector.update(still)
    moved = bytearray(still)
    moved[100:400] = b"\xff" * 300  # 2 % of the picture changes
    assert detector.update(bytes(moved))
    assert not detector.update(bytes([200]) * len(still))  # all of it: the light, not motion
    assert motion_threshold(0) > motion_threshold(50) > motion_threshold(100)


def test_decode_and_tracker() -> None:
    grids = np.zeros((2, 2), dtype=np.float32)
    strides = np.full((2, 1), 8, dtype=np.float32)
    out = np.zeros((2, 85), dtype=np.float32)
    out[0, :4] = [10, 10, np.log(4), np.log(8)]  # a box at (80, 80), 32 x 64
    out[0, 4], out[0, 5] = 0.9, 0.9  # objectness, class 0 (person)
    out[1, 4], out[1, 5 + 62] = 0.9, 0.9  # class 62 (a tv): not a kind Norn knows
    [found] = decode(np, out, grids, strides, 0.5)
    assert found.kind == "person" and found.score == pytest.approx(0.81)
    assert found.box == pytest.approx((64, 48, 96, 112))

    tracker = Tracker(still_after=60)
    car = Detection("vehicle", 0.9, (0, 0, 100, 50))
    assert tracker.update([car], now=0) == {"vehicle"}
    assert tracker.update([car], now=30) == {"vehicle"}
    assert tracker.update([car], now=61) == set()  # parked: no longer counts
    moved = Detection("vehicle", 0.9, (40, 0, 140, 50))
    assert tracker.update([moved], now=62) == {"vehicle"}  # it drives off


def test_gray_from_bgr() -> None:
    bgr = bytes([30]) * (OBJECT_SIZE * OBJECT_SIZE * 3)
    gray = gray_from_bgr(bgr)
    assert len(gray) == (OBJECT_SIZE // 4) ** 2 and set(gray) == {30}


def test_still_command_and_jpegs() -> None:
    cmd = still_command("ffmpeg", "rtsp://x/door_sub", "keyframe", 2, {"jpeg": "pipe:1", "bgr": "pipe:5"})
    assert cmd[cmd.index("-skip_frame") + 1] == "nokey"
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "split=2" in graph and "gte(t-prev_selected_t\\,2.00)" in graph
    assert cmd[-1] == "pipe:5" and "pipe:1" in cmd
    live = still_command("ffmpeg", "rtsp://x/door", "live", 1, {"gray": "pipe:4"})
    assert "-skip_frame" not in live
    a, b = b"\xff\xd8one\xff\xd9", b"\xff\xd8two\xff\xd9"
    jpegs, rest = split_jpegs(a + b + b"\xff\xd8thr")
    assert jpegs == [a, b] and rest == b"\xff\xd8thr"


def test_detection_settings_and_labels() -> None:
    config = Config.model_validate(
        {
            "detection": {"motion": True, "every_seconds": 3},
            "circles": {"out": {"name": "Out", "cameras": ["door"], "detection": {"objects": True}}},
            "cameras": {"door": {"name": "Door", "driver": "demo", "detection": {"every_seconds": 1}}},
        }
    )
    d = config.detection_for("door")
    assert (d.motion, d.objects, d.every_seconds) == (True, True, 1)
    with pytest.raises(ValueError, match="not one of"):
        Config.model_validate({"recording": {"triggers": ["ufo"]}})
