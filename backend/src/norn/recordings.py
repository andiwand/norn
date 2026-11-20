"""The recordings folder. The folders are the index; there is no database.

    <root>/<camera>/<YYYY-MM-DD>/<HH-MM-SS>_<trigger>.mp4    a video
                                  <HH-MM-SS>_<trigger>.json   optional: details of a clip
                                  <HH-MM-SS>_<trigger>.jpg    its thumbnail, or a picture of its own
                                  <HH-MM-SS>_<trigger>.objects.json   optional: what Norn's AI
                                                              found on the stills during a clip

The trigger is `continuous` for the files of a continuous recording, `interval` for the pictures
taken on a timer, else what started the clip (`manual`, `webhook`, `motion`, ...). A .jpg without
a video next to it is a picture. Times are the local time of the server.

Recordings that Norn made by itself expire after the retention time; `manual` ones are kept until
someone deletes them. The temporary storage (see recorder.py) has the same layout.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import psutil

from .config import CAMERA_ID

# Used with fullmatch: `$` with match would let a trailing newline through.
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
STEM = re.compile(r"(\d{2})-(\d{2})-(\d{2})_([a-z0-9-]{1,32})")
TRIGGER = re.compile(r"[a-z0-9-]{1,32}")
OBJECTS = ".objects.json"  # a clip's boxes: [{"at": seconds into the video, "objects": [...]}]
SUFFIXES = (".mp4", ".jpg", ".json", OBJECTS)
KEPT = frozenset({"manual"})  # triggers whose recordings never expire


def expires(start: datetime, trigger: str, retention_days: int) -> datetime | None:
    if retention_days <= 0 or trigger in KEPT:
        return None
    return start + timedelta(days=retention_days)


@dataclass(frozen=True)
class Recording:
    camera: str
    day: str
    name: str  # file name of the video or picture
    kind: Literal["video", "picture"]
    start: datetime
    trigger: str
    size: int
    duration: float | None
    thumbnail: bool
    meta: dict[str, Any]

    @property
    def id(self) -> str:
        return f"{self.camera}/{self.day}/{self.name}"

    @property
    def pinned(self) -> bool:
        """Kept until someone unpins it, whatever the limits (in the sidecar: "pinned": true)."""
        return self.meta.get("pinned") is True

    @property
    def kept(self) -> bool:
        """Never deleted by Norn: recorded by hand, or pinned."""
        return self.trigger in KEPT or self.pinned

    def to_json(self, retention_days: int = 0) -> dict[str, Any]:
        end = None if self.pinned else expires(self.start, self.trigger, retention_days)
        return {
            "id": self.id,
            "camera": self.camera,
            "day": self.day,
            "name": self.name,
            "kind": self.kind,
            "start": self.start.astimezone().isoformat(),  # with the offset, for the browser
            "trigger": self.trigger,
            "size": self.size,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "expires": end.astimezone().isoformat() if end else None,
            "pinned": self.pinned,
            "meta": self.meta,
        }


class InvalidPathError(ValueError):
    pass


def folder_size(root: Path, skip: Path | None = None) -> tuple[int, int]:
    """Bytes and number of files under `root`, without the folder `skip`."""
    total = count = 0
    for folder, folders, files in os.walk(root):
        if skip is not None:
            folders[:] = [f for f in folders if Path(folder, f) != skip]
        for name in files:
            try:
                total += os.stat(os.path.join(folder, name)).st_size
                count += 1
            except FileNotFoundError:
                pass
    return total, count


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, camera: str, day: str | None = None, name: str | None = None) -> Path:
        """The path of a camera, day or file, after checking each part, so no request leaves the root."""
        if not CAMERA_ID.fullmatch(camera):
            raise InvalidPathError(f"bad camera {camera!r}")
        path = self.root / camera
        if day is not None:
            if not DAY.fullmatch(day):
                raise InvalidPathError(f"bad day {day!r}")
            path = path / day
        if name is not None:
            stem, dot, suffix = name.rpartition(".")
            if not dot or not STEM.fullmatch(stem) or f".{suffix}" not in SUFFIXES:
                raise InvalidPathError(f"bad file {name!r}")
            path = path / name
        return path

    def file_path(self, camera: str, start: datetime, trigger: str, suffix: str = ".mp4") -> Path:
        if not TRIGGER.fullmatch(trigger):
            raise InvalidPathError(f"bad trigger {trigger!r}")
        name = f"{start.strftime('%H-%M-%S')}_{trigger}{suffix}"
        return self.path(camera, start.strftime("%Y-%m-%d"), name)

    def cameras(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and CAMERA_ID.fullmatch(p.name))

    def days(self, camera: str) -> list[str]:
        folder = self.path(camera)
        if not folder.is_dir():
            return []
        # The recorder makes tomorrow's folder in advance; a day without recordings isn't a day to show.
        return sorted(
            (
                p.name
                for p in folder.iterdir()
                if p.is_dir()
                and DAY.fullmatch(p.name)
                and any(f.suffix in (".mp4", ".jpg") for f in p.iterdir())
            ),
            reverse=True,
        )

    def list(
        self,
        camera: str | None = None,
        day: str | None = None,
        limit: int = 500,
        since: datetime | None = None,
        until: datetime | None = None,
        kind: str | None = None,
        trigger: str | None = None,
        pictures: int | None = None,
    ) -> list[Recording]:
        """Recordings, newest first. `since` and `until` (naive, local) keep the ones that overlap;
        `trigger` is a trigger or `clips` (videos a trigger started); `pictures` thins the pictures
        of each camera to about that many, evenly over the time, so a timeline stays light."""
        found: list[Recording] = []
        for cam in [camera] if camera else self.cameras():
            for d in [day] if day else self.days(cam):
                # A video can start the day before and run past midnight, so look one day further back.
                if since and d < (since.date() - timedelta(days=1)).isoformat():
                    continue
                if until and d > until.date().isoformat():
                    continue
                found.extend(self._day(cam, d))
        if since:
            found = [r for r in found if r.start + timedelta(seconds=r.duration or 0) >= since]
        if until:
            found = [r for r in found if r.start <= until]
        if kind:
            found = [r for r in found if r.kind == kind]
        if trigger == "clips":
            found = [r for r in found if r.kind == "video" and r.trigger != "continuous"]
        elif trigger:
            found = [r for r in found if r.trigger == trigger]
        found.sort(key=lambda r: r.start, reverse=True)
        if pictures:
            found = _thin(found, pictures)
        return found[:limit]

    def thumb_path(self, camera: str, day: str, name: str) -> Path:
        """Where the small copy of a picture lives (hidden, next to the camera folders)."""
        return self.root / ".thumbs" / self.path(camera, day, name).relative_to(self.root)

    def get(self, camera: str, day: str, name: str) -> Recording | None:
        path = self.path(camera, day, name)
        return self._recording(camera, day, path) if path.is_file() else None

    def delete(self, camera: str, day: str, name: str) -> bool:
        """Delete a video or picture with its sidecar and thumbnail."""
        path = self._file(camera, day, name)
        if not path:
            return False
        for suffix in SUFFIXES:
            path.with_suffix(suffix).unlink(missing_ok=True)
        if path.suffix == ".jpg":
            self.thumb_path(camera, day, name).unlink(missing_ok=True)
        folder = path.parent
        if not any(folder.iterdir()) and folder.name != date.today().isoformat():
            folder.rmdir()
        return True

    def prune(self, retention_days: int, now: datetime | None = None) -> list[str]:
        """Delete the recordings that expired. Returns what it deleted."""
        if retention_days <= 0:
            return []
        now = now or datetime.now()
        # Nothing in a day folder newer than this can have expired yet.
        newest_day = (now - timedelta(days=retention_days)).date().isoformat()
        deleted = []
        for camera in self.cameras():
            for day in self.days(camera):
                if day > newest_day:
                    continue
                for recording in self._day(camera, day):
                    if recording.pinned:
                        continue
                    end = expires(recording.start, recording.trigger, retention_days)
                    if end and end <= now and self.delete(camera, day, recording.name):
                        deleted.append(recording.id)
        return deleted

    def excess(self, max_bytes: int = 0, min_free: int = 0) -> int:
        """Bytes over the size limit or short of the free space (0: within both)."""
        used = folder_size(self.root)[0] if max_bytes and self.root.is_dir() else 0
        free = disk(self.root)["free"] if min_free else None
        over = used - max_bytes if max_bytes else 0
        short = min_free - free if free is not None else 0
        return max(over, short, 0)

    def evict(self, max_bytes: int = 0, min_free: int = 0, most: int = 200) -> tuple[list[str], int]:
        """Delete the oldest recordings that may go (not kept by hand, not pinned) until the
        folder holds at most `max_bytes` and its disk has `min_free` free (0: no limit), at most
        `most` of them in one go. Returns what it deleted, and the bytes still over (by the
        sizes deleted; the caller measures again)."""
        if not max_bytes and not min_free:
            return [], 0
        excess = self.excess(max_bytes, min_free)
        deleted: list[str] = []
        if not excess:
            return deleted, 0
        # Day by day from the oldest, so a big library isn't read all at once.
        days = sorted({(day, camera) for camera in self.cameras() for day in self.days(camera)})
        for day, camera in days:
            for recording in sorted(self._day(camera, day), key=lambda r: r.start):
                if excess <= 0 or len(deleted) >= most:
                    return deleted, max(excess, 0)
                fresh = self.get(camera, day, recording.name)  # pinned meanwhile?
                if fresh is None or fresh.kept:
                    continue
                video = self.path(camera, day, recording.name)
                size = sum(p.stat().st_size for x in SUFFIXES if (p := video.with_suffix(x)).exists())
                if self.delete(camera, day, recording.name):
                    deleted.append(recording.id)
                    excess -= size
        return deleted, max(excess, 0)

    def set_pinned(self, camera: str, day: str, name: str, pinned: bool) -> Recording | None:
        """Pin or unpin a recording: a flag in its JSON sidecar (made for it if it has none)."""
        path = self._file(camera, day, name)
        if not path:
            return None
        sidecar = path.with_suffix(".json")
        meta = _sidecar(path)
        if pinned:
            meta["pinned"] = True
        else:
            meta.pop("pinned", None)
        tmp = sidecar.with_name(f".{sidecar.name}.tmp")
        tmp.write_text(json.dumps(meta, indent=2) + "\n")
        tmp.replace(sidecar)
        return self.get(camera, day, name)

    def usage(self) -> dict[str, Any]:
        """How much the folder holds, and how much room its disk has."""
        used, files = folder_size(self.root) if self.root.is_dir() else (0, 0)
        return {"path": str(self.root), "used": used, "files": files, **disk(self.root)}

    def iter_files(self) -> Iterator[tuple[str, str, Path]]:
        """Every recording file: (camera, day, path)."""
        for camera in self.cameras():
            folder = self.path(camera)
            for day_dir in sorted(folder.iterdir()):
                if not (day_dir.is_dir() and DAY.fullmatch(day_dir.name)):
                    continue
                for path in sorted(day_dir.iterdir()):
                    if path.suffix in SUFFIXES and STEM.fullmatch(path.stem):
                        yield camera, day_dir.name, path

    def _file(self, camera: str, day: str, name: str) -> Path | None:
        """The path of a video or picture, if there is one."""
        path = self.path(camera, day, name)
        return path if path.suffix in (".mp4", ".jpg") and path.is_file() else None

    def _day(self, camera: str, day: str) -> list[Recording]:
        folder = self.path(camera, day)
        if not folder.is_dir():
            return []
        files = {p.name for p in folder.iterdir()}
        found = []
        for name in files:
            stem, _, suffix = name.rpartition(".")
            # A .jpg next to a video is the video's thumbnail, not a picture of its own.
            if suffix == "mp4" or (suffix == "jpg" and f"{stem}.mp4" not in files):
                recording = self._recording(camera, day, folder / name)
                if recording is not None:
                    found.append(recording)
        return found

    def _recording(self, camera: str, day: str, path: Path) -> Recording | None:
        match = STEM.fullmatch(path.stem)
        if not match or path.suffix not in (".mp4", ".jpg"):
            return None
        hh, mm, ss, trigger = match.groups()
        try:
            start = datetime.fromisoformat(f"{day}T{hh}:{mm}:{ss}")
            stat = path.stat()
        except (ValueError, FileNotFoundError):
            return None
        meta = _sidecar(path)
        if path.suffix == ".jpg":
            return Recording(
                camera=camera,
                day=day,
                name=path.name,
                kind="picture",
                start=start,
                trigger=trigger,
                size=stat.st_size,
                duration=None,
                thumbnail=True,
                meta=meta,
            )
        duration = meta.get("duration")
        if not isinstance(duration, int | float):
            # A continuous file has no sidecar: it was last written when it ended.
            seconds = datetime.fromtimestamp(stat.st_mtime) - start
            duration = seconds.total_seconds() if 0 < seconds.total_seconds() < 6 * 3600 else None
        return Recording(
            camera=camera,
            day=day,
            name=path.name,
            kind="video",
            start=start,
            trigger=trigger,
            size=stat.st_size,
            duration=float(duration) if duration is not None else None,
            thumbnail=path.with_suffix(".jpg").is_file(),
            meta=meta,
        )


def _sidecar(path: Path) -> dict[str, Any]:
    """The details in a recording's JSON sidecar, if it has one."""
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
    except (ValueError, OSError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _thin(found: list[Recording], keep: int) -> list[Recording]:
    """At most about `keep` pictures per camera, spread evenly; videos all stay."""
    per_camera: dict[str, list[Recording]] = {}
    for r in found:
        if r.kind == "picture":
            per_camera.setdefault(r.camera, []).append(r)
    dropped: set[int] = set()
    for items in per_camera.values():
        if len(items) > keep:
            step = len(items) / keep
            kept = {id(items[int(i * step)]) for i in range(keep)}
            dropped |= {id(r) for r in items if id(r) not in kept}
    return [r for r in found if id(r) not in dropped]


def disk(path: Path) -> dict[str, Any]:
    """Total and free bytes of the file system that holds `path` (or its nearest parent), and
    whether it lives in RAM (tmpfs)."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return {"total": None, "free": None, "ram": False}
    return {"total": usage.total, "free": usage.free, "ram": in_ram(probe)}


def in_ram(path: Path) -> bool:
    """Whether `path` is on a tmpfs or ramfs: the deepest mount point holding it decides."""
    try:
        mounts = psutil.disk_partitions(all=True)
    except (OSError, RuntimeError):
        return False
    resolved = str(path.resolve())
    best, depth = None, -1
    for mount in mounts:
        point = mount.mountpoint.rstrip("/")
        holds = resolved == point or resolved.startswith(point + "/") or not point
        if holds and len(point) > depth:
            best, depth = mount, len(point)
    return best is not None and best.fstype in ("tmpfs", "ramfs")
