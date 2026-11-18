"""Norn's own detection, on stills taken every few seconds.

Watching every frame would mean decoding every camera's stream all the time. Norn instead looks
at one still every `every_seconds` (by default the newest keyframe of the camera's RAM buffer,
which costs one decoded frame and no new connection). The pre-recording buffer makes up for the
delay: a clip still starts seconds before the detection.

- Motion: the difference between a small grayscale still and a slowly updated background.
  Pure Python, no extra packages; FFmpeg scales the still down to 160x90.
- Objects: YOLOX (Apache-2.0, https://github.com/Megvii-BaseDetection/YOLOX), a small detector
  trained on COCO, run with ONNX Runtime on one CPU thread. Needs `pip install norn-hub[detect]`
  (the Docker image has it). People, vehicles and animals become the event kinds `person`,
  `vehicle` and `animal`. Something that stands still (a parked car) stops counting after a
  minute, until it moves. With `confirm_seconds`, an object counts only once it has been seen on
  stills that far apart (like the delay of a camera's own AI): a moth in the infrared light or
  a shadow that the model takes for a person for one still doesn't start a clip.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .labels import COCO

log = logging.getLogger("norn.detect")

MOTION_SIZE = (160, 90)
OBJECT_SIZE = 416  # the input of the YOLOX nano and tiny models
PAD = 114  # YOLOX pads the letterboxed image with this gray


@dataclass(frozen=True)
class Model:
    file: str
    url: str
    sha256: str
    label: str


MODELS = {
    "nano": Model(
        "yolox_nano.onnx",
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx",
        "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d",
        "YOLOX nano (3.7 MB, fast)",
    ),
    "tiny": Model(
        "yolox_tiny.onnx",
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx",
        "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7",
        "YOLOX tiny (20 MB, more accurate, about 4x the CPU)",
    ),
}

OBJECT_KINDS = ("person", "vehicle", "animal")


def objects_unavailable() -> str | None:
    """Why object detection can't run here, or None when it can."""
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return "needs the optional packages: pip install 'norn-hub[detect]'"
    return None


# Motion


def motion_threshold(sensitivity: int) -> float:
    """The share of pixels that must change: 5 % at sensitivity 0, 0.5 % at 50, 0.05 % at 100."""
    return 0.05 * 10 ** (-2 * sensitivity / 100)


class MotionDetector:
    """Compares each still with a background that follows slow changes (clouds, dusk)."""

    LEVEL = 18  # a pixel changed when it differs this much (of 255) from the background
    LIGHTING = 0.6  # more than this much changed at once: the light changed (IR, a lamp)

    def __init__(self, sensitivity: int = 50) -> None:
        self.sensitivity = sensitivity
        self.background: list[float] | None = None

    def update(self, gray: bytes) -> bool:
        """Feed a MOTION_SIZE grayscale still; True when something moved."""
        if self.background is None or len(self.background) != len(gray):
            self.background = [float(p) for p in gray]
            return False
        background = self.background
        changed = 0
        for i, p in enumerate(gray):
            b = background[i]
            if abs(p - b) > self.LEVEL:
                changed += 1
            background[i] = b * 0.7 + p * 0.3
        share = changed / len(gray)
        if share > self.LIGHTING:
            self.background = [float(p) for p in gray]  # start over from the new light
            return False
        return share >= motion_threshold(self.sensitivity)


# Objects


@dataclass
class Detection:
    kind: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in the letterboxed input's pixels


def model_path(name: str, folders: list[Path], download_to: Path) -> Path:
    """The model file: from one of `folders`, else downloaded once into `download_to` and checked."""
    model = MODELS[name]
    for folder in folders:
        if (path := folder / model.file).is_file():
            return path
    target = download_to / model.file
    if not target.is_file():
        log.warning("downloading the object detection model %s", model.url)
        response = httpx.get(model.url, follow_redirects=True, timeout=120)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != model.sha256:
            raise RuntimeError(f"{model.file}: the download doesn't match its checksum")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(response.content)
        tmp.replace(target)
    return target


class ObjectDetector:
    """YOLOX on ONNX Runtime, one thread. Not thread safe: one call at a time."""

    def __init__(self, path: Path) -> None:
        import numpy as np
        import onnxruntime as ort

        self.np = np
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        # The output is relative to a grid of cells per stride; precompute where they are.
        grids, strides = [], []
        for stride in (8, 16, 32):
            cells = OBJECT_SIZE // stride
            ys, xs = np.meshgrid(np.arange(cells), np.arange(cells), indexing="ij")
            grids.append(np.stack((xs, ys), 2).reshape(-1, 2))
            strides.append(np.full((cells * cells, 1), stride))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(strides).astype(np.float32)

    def detect(self, bgr: bytes, min_score: float = 0.5) -> list[Detection]:
        """Feed an OBJECT_SIZE square BGR still (letterboxed, padded with PAD)."""
        np = self.np
        image = np.frombuffer(bgr, dtype=np.uint8).reshape(OBJECT_SIZE, OBJECT_SIZE, 3)
        blob = image.transpose(2, 0, 1)[None].astype(np.float32)
        out = self.session.run(None, {self.input: blob})[0][0]
        return decode(np, out, self.grids, self.strides, min_score)


def decode(np: Any, out: Any, grids: Any, strides: Any, min_score: float) -> list[Detection]:
    """YOLOX's raw output (cells x 85) into detections of the kinds Norn knows."""
    xy = (out[:, :2] + grids) * strides
    wh = np.exp(out[:, 2:4]) * strides
    scores = out[:, 4:5] * out[:, 5:]
    classes = scores.argmax(1)
    best = scores[np.arange(len(scores)), classes]
    keep = (best >= min_score) & np.isin(classes, list(COCO))
    found = []
    for (cx, cy), (w, h), cls, score in zip(xy[keep], wh[keep], classes[keep], best[keep], strict=True):
        box = (float(cx - w / 2), float(cy - h / 2), float(cx + w / 2), float(cy + h / 2))
        found.append(Detection(COCO[int(cls)], float(score), box))
    return nms(found)


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(found: list[Detection], overlap: float = 0.45) -> list[Detection]:
    """One detection per object: drop boxes that mostly cover a better one of the same kind."""
    kept: list[Detection] = []
    for d in sorted(found, key=lambda d: -d.score):
        if all(k.kind != d.kind or iou(k.box, d.box) < overlap for k in kept):
            kept.append(d)
    return kept


@dataclass
class Track:
    kind: str
    box: tuple[float, float, float, float]
    seen: float
    still_since: float
    first: float  # when it was first seen


@dataclass
class Tracker:
    """Which detected objects count: new or moving ones. One that stays where it is for
    `still_after` seconds stops counting until it moves (a parked car, a garden gnome). One seen
    for less than `confirm` seconds doesn't count yet."""

    still_after: float = 60
    forget_after: float = 30
    tracks: list[Track] = field(default_factory=list)

    def update(self, found: list[Detection], now: float | None = None, confirm: float = 0) -> set[str]:
        now = time.monotonic() if now is None else now
        for d in found:
            match = max(
                (t for t in self.tracks if t.kind == d.kind),
                key=lambda t: iou(t.box, d.box),
                default=None,
            )
            if match is not None and iou(match.box, d.box) > 0.3:
                if iou(match.box, d.box) < 0.85:  # it moved
                    match.still_since = now
                match.box, match.seen = d.box, now
            else:
                self.tracks.append(Track(d.kind, d.box, now, now, now))
        self.tracks = [t for t in self.tracks if now - t.seen <= self.forget_after]
        return {
            t.kind
            for t in self.tracks
            if t.seen == now and now - t.still_since < self.still_after and now - t.first >= confirm
        }


def gray_from_bgr(bgr: bytes) -> bytes:
    """A small grayscale still for motion from the detector's input (numpy, which object
    detection brings anyway): the mean of the colors, 4x4 pixels into one."""
    import numpy as np

    image = np.frombuffer(bgr, dtype=np.uint8).reshape(OBJECT_SIZE, OBJECT_SIZE, 3).mean(axis=2)
    small = image.reshape(OBJECT_SIZE // 4, 4, OBJECT_SIZE // 4, 4).mean(axis=(1, 3))
    return small.astype(np.uint8).tobytes()


# FFmpeg filters for the stills: small and gray for motion; for objects letterboxed into the
# detector's square input as YOLOX expects (scaled to fit, at the top left, padded with gray).
MOTION_FILTER = f"scale={MOTION_SIZE[0]}:{MOTION_SIZE[1]}:flags=area,format=gray"
OBJECT_FILTER = (
    f"scale={OBJECT_SIZE}:{OBJECT_SIZE}:force_original_aspect_ratio=decrease,"
    f"pad={OBJECT_SIZE}:{OBJECT_SIZE}:0:0:color=0x{PAD:02x}{PAD:02x}{PAD:02x}"
)


class Detectors:
    """The object detectors, loaded on first use (one per model), used one at a time: the
    detection costs one CPU core at most, whatever the number of cameras."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._missing = objects_unavailable()
        self._failure: str | None = None
        self._loaded: dict[str, ObjectDetector] = {}
        self._lock = asyncio.Lock()
        self._retry_at = 0.0

    @property
    def unavailable(self) -> str | None:
        """Why object detection can't run now (missing packages, a model that didn't load in the
        last hour), or None."""
        if self._missing:
            return self._missing
        return self._failure if time.monotonic() < self._retry_at else None

    def folders(self) -> list[Path]:
        folders = [Path(p) for p in os.environ.get("NORN_MODELS", "").split(os.pathsep) if p]
        return [*folders, Path("/usr/local/share/norn/models")]

    async def detect(self, model: str, bgr: bytes, min_score: float) -> tuple[list[Detection], float]:
        """Detections in a still, and how many milliseconds it took."""
        async with self._lock:
            if model not in self._loaded:
                if self.unavailable:
                    raise RuntimeError(self.unavailable)
                try:
                    path = await asyncio.to_thread(
                        model_path, model, self.folders(), self.settings.runtime_dir / "models"
                    )
                    self._loaded[model] = await asyncio.to_thread(ObjectDetector, path)
                except Exception as e:
                    # No model (offline, say): don't try again with every still.
                    self._retry_at = time.monotonic() + 3600
                    self._failure = f"the model couldn't be loaded ({e}); Norn tries again in an hour"
                    raise
            detector = self._loaded[model]
            start = time.perf_counter()
            found = await asyncio.to_thread(detector.detect, bgr, min_score)
            return found, (time.perf_counter() - start) * 1000
