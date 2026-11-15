"""The recordings folder. The folders are the index; there is no database.

    <root>/<camera>/<YYYY-MM-DD>/<HH-MM-SS>_<trigger>.mp4
                                  <HH-MM-SS>_<trigger>.json   optional: details of a clip
                                  <HH-MM-SS>_<trigger>.jpg    optional: thumbnail

The trigger is `continuous` for the files of a continuous recording, else what started the clip
(`manual`, `webhook`, `motion`, ...). Times are the local time of the server.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import CAMERA_ID

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FILE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})_([a-z0-9-]{1,32})\.mp4$")
TRIGGER = re.compile(r"^[a-z0-9-]{1,32}$")


@dataclass(frozen=True)
class Recording:
    camera: str
    day: str
    name: str  # file name of the video
    start: datetime
    trigger: str
    size: int
    duration: float | None
    thumbnail: bool
    meta: dict[str, Any]

    @property
    def id(self) -> str:
        return f"{self.camera}/{self.day}/{self.name}"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "camera": self.camera,
            "day": self.day,
            "name": self.name,
            "start": self.start.astimezone().isoformat(),  # with the offset, for the browser
            "trigger": self.trigger,
            "size": self.size,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "meta": self.meta,
        }


class InvalidPathError(ValueError):
    pass


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, camera: str, day: str | None = None, name: str | None = None) -> Path:
        """The path of a camera, day or file, after checking each part, so no request leaves the root."""
        if not CAMERA_ID.match(camera):
            raise InvalidPathError(f"bad camera {camera!r}")
        path = self.root / camera
        if day is not None:
            if not DAY.match(day):
                raise InvalidPathError(f"bad day {day!r}")
            path = path / day
        if name is not None:
            stem = name.rsplit(".", 1)[0]
            if not FILE.match(stem + ".mp4") or name.rsplit(".", 1)[-1] not in ("mp4", "jpg", "json"):
                raise InvalidPathError(f"bad file {name!r}")
            path = path / name
        return path

    def clip_path(self, camera: str, start: datetime, trigger: str) -> Path:
        if not TRIGGER.match(trigger):
            raise InvalidPathError(f"bad trigger {trigger!r}")
        return self.path(camera, start.strftime("%Y-%m-%d"), f"{start.strftime('%H-%M-%S')}_{trigger}.mp4")

    def cameras(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and CAMERA_ID.match(p.name))

    def days(self, camera: str) -> list[str]:
        folder = self.path(camera)
        if not folder.is_dir():
            return []
        # The recorder makes tomorrow's folder in advance; a day without videos isn't a day to show.
        return sorted(
            (
                p.name
                for p in folder.iterdir()
                if p.is_dir() and DAY.match(p.name) and any(f.suffix == ".mp4" for f in p.iterdir())
            ),
            reverse=True,
        )

    def list(self, camera: str | None = None, day: str | None = None, limit: int = 500) -> list[Recording]:
        """Recordings, newest first."""
        found: list[Recording] = []
        for cam in [camera] if camera else self.cameras():
            for d in [day] if day else self.days(cam):
                found.extend(self._day(cam, d))
        found.sort(key=lambda r: r.start, reverse=True)
        return found[:limit]

    def get(self, camera: str, day: str, name: str) -> Recording | None:
        path = self.path(camera, day, name)
        return self._recording(camera, day, path) if path.is_file() else None

    def delete(self, camera: str, day: str, name: str) -> bool:
        video = self.path(camera, day, name)
        if not video.is_file():
            return False
        for suffix in (".mp4", ".json", ".jpg"):
            video.with_suffix(suffix).unlink(missing_ok=True)
        folder = video.parent
        if not any(folder.iterdir()):
            folder.rmdir()
        return True

    def prune(self, retention_days: int, today: date | None = None) -> list[str]:
        """Delete the day folders older than `retention_days`. Returns what it deleted."""
        if retention_days <= 0:
            return []
        cutoff = (today or date.today()) - timedelta(days=retention_days)
        deleted = []
        for camera in self.cameras():
            for day in self.days(camera):
                if date.fromisoformat(day) < cutoff:
                    shutil.rmtree(self.path(camera, day))
                    deleted.append(f"{camera}/{day}")
        return deleted

    def _day(self, camera: str, day: str) -> list[Recording]:
        folder = self.path(camera, day)
        if not folder.is_dir():
            return []
        return [
            r
            for p in folder.iterdir()
            if p.suffix == ".mp4" and FILE.match(p.name)
            for r in [self._recording(camera, day, p)]
            if r is not None
        ]

    def _recording(self, camera: str, day: str, path: Path) -> Recording | None:
        match = FILE.match(path.name)
        if not match:
            return None
        hh, mm, ss, trigger = match.groups()
        try:
            start = datetime.fromisoformat(f"{day}T{hh}:{mm}:{ss}")
            size = path.stat().st_size
        except (ValueError, FileNotFoundError):
            return None
        meta: dict[str, Any] = {}
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            try:
                meta = json.loads(sidecar.read_text())
            except (ValueError, OSError):
                meta = {}
        duration = meta.get("duration")
        return Recording(
            camera=camera,
            day=day,
            name=path.name,
            start=start,
            trigger=trigger,
            size=size,
            duration=float(duration) if isinstance(duration, int | float) else None,
            thumbnail=path.with_suffix(".jpg").is_file(),
            meta=meta,
        )
