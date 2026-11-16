"""config.yaml: the cameras and the recording rules.

The file is the single source of truth. The UI writes changes back into it with ruamel.yaml's
round-trip mode, so comments and formatting that a person wrote by hand survive. Norn also
watches the file and reloads it when someone edits it while the server runs.
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from .labels import LabelId

CAMERA_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

DEFAULT_CONFIG = """\
# Norn configuration. Edit this file by hand or from the web UI; both keep each other's changes.
# Docs: https://andiwand.github.io/norn/

recording:
  retention_days: 14     # delete recordings older than this; 0 keeps them forever
  segment_minutes: 10    # length of one file of a continuous recording
  clip_seconds: 30       # length of a triggered clip (manual button, webhook, motion)

cameras:
  # The demo camera shows a test pattern and fake controls, so you can try Norn without a camera.
  # Remove it once you have added a real one.
  demo:
    name: Demo camera
    driver: demo

  # A plain RTSP camera:
  # front-door:
  #   name: Front door
  #   driver: rtsp
  #   url: rtsp://user:password@192.168.1.20:554/stream1
  #   substream: rtsp://user:password@192.168.1.20:554/stream2   # optional, used for the grid
  #   record: continuous                                           # off (default) or continuous
"""


# What a camera detects, as Norn names it (labels.py maps each source's own names onto these).
EventKind = LabelId


Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS: tuple[Day, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


class Window(BaseModel):
    """A time of the week: `from` to `to` on the given days. `to` before `from` runs past
    midnight (20:00 to 07:00: the night that starts on each of the days)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    days: list[Day] = Field(default_factory=lambda: list(DAYS))
    start: str = Field(alias="from", pattern=TIME)
    end: str = Field(alias="to", pattern=TIME)

    def contains(self, moment: datetime) -> bool:
        now = moment.strftime("%H:%M")
        today = DAYS[moment.weekday()]
        yesterday = DAYS[(moment.weekday() - 1) % 7]
        if self.start <= self.end:
            return today in self.days and self.start <= now < self.end
        # Overnight: the evening part belongs to today, the morning part to yesterday's night.
        return (today in self.days and now >= self.start) or (yesterday in self.days and now < self.end)


def in_schedule(windows: list[Window], moment: datetime) -> bool:
    """No windows: always."""
    return not windows or any(w.contains(moment) for w in windows)


def _check_picture_interval(value: int | None) -> int | None:
    if value is not None and 0 < value < 10:
        raise ValueError("take a picture at most every 10 seconds")
    return value


class RecordingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Recordings Norn makes by itself expire after this; clips recorded by hand stay. 0: never.
    retention_days: int = Field(14, ge=0)
    # Besides the age: the most the recordings may take, and the least the disk must keep free,
    # in GB. When either is crossed, the oldest automatic recordings go first. 0: no limit.
    max_gb: float = Field(0, ge=0)
    min_free_gb: float = Field(0, ge=0)
    segment_minutes: int = Field(10, ge=1, le=60)
    clip_seconds: int = Field(30, ge=5, le=3600)
    # The last seconds of each camera, kept in RAM, so a clip starts before its trigger. 0: off.
    prebuffer_seconds: int = Field(10, ge=0, le=300)
    # Take a picture every this many seconds (the `interval` trigger). 0: off.
    picture_seconds: int = Field(0, ge=0, le=86400)
    # What the cameras detect that starts a clip (the trigger is the kind: `motion`, ...).
    triggers: list[EventKind] = Field(default_factory=list)
    # When detections start clips; empty: always.
    schedule: list[Window] = Field(default_factory=list)

    @field_validator("picture_seconds")
    @classmethod
    def _picture_interval(cls, value: int) -> int:
        return _check_picture_interval(value) or 0


class AwaySettings(BaseModel):
    """Away (holiday) mode: on now, or planned from `start` to `end`. While away, detections
    record whatever the schedules say, with their own triggers, and pictures can come faster."""

    model_config = ConfigDict(extra="forbid")

    active: bool = False
    start: datetime | None = None  # planned: local time
    end: datetime | None = None
    triggers: list[EventKind] = Field(default_factory=lambda: ["motion", "person"])
    picture_seconds: int = Field(0, ge=0, le=86400)  # 0: as usual

    @field_validator("picture_seconds")
    @classmethod
    def _picture_interval(cls, value: int) -> int:
        return _check_picture_interval(value) or 0

    def now(self, moment: datetime | None = None) -> bool:
        if self.active:
            return True
        moment = moment or datetime.now()
        return self.start is not None and self.start <= moment and (self.end is None or moment < self.end)


Stills = Literal["auto", "keyframe", "live"]


class DetectionSettings(BaseModel):
    """Norn's own detection on stills (detect.py), and where stills come from.

    `stills`: `keyframe` takes the newest keyframe of the camera's RAM buffer (one decoded frame,
    no new connection, up to a few seconds old); `live` asks go2rtc for the current frame; `auto`
    takes the keyframe when the camera has a buffer. Pictures on the timer use it too."""

    model_config = ConfigDict(extra="forbid")

    stills: Stills = "auto"
    motion: bool = False  # Norn compares stills for motion
    objects: bool = False  # Norn finds people, vehicles and animals (norn-hub[detect])
    every_seconds: float = Field(2, ge=0.5, le=60)
    sensitivity: int = Field(50, ge=0, le=100)  # motion: higher reacts to smaller changes
    min_score: float = Field(0.5, ge=0.1, le=0.95)  # objects: how sure the detector must be
    model: Literal["nano", "tiny"] = "nano"


class DetectionOverride(BaseModel):
    """A circle's or camera's own detection settings; fields left out come from above."""

    model_config = ConfigDict(extra="forbid")

    stills: Stills | None = None
    motion: bool | None = None
    objects: bool | None = None
    every_seconds: float | None = Field(None, ge=0.5, le=60)
    sensitivity: int | None = Field(None, ge=0, le=100)
    min_score: float | None = Field(None, ge=0.1, le=0.95)


class FirmwareSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # How often to ask the vendors for new firmware (and auto-update). 0: never.
    check_hours: int = Field(24, ge=0, le=24 * 90)


class CameraConfig(BaseModel):
    """One camera. Fields besides these are options of its driver (url, host, ...)."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    driver: str = Field(min_length=1)
    enabled: bool = True
    record: Literal["off", "continuous"] = "off"
    # Install new firmware by itself, where the driver can fetch it from the vendor.
    auto_update: bool = False
    # Overrides of the global recording settings for this camera; None: the global value.
    picture_seconds: int | None = Field(None, ge=0, le=86400)
    prebuffer_seconds: int | None = Field(None, ge=0, le=300)
    triggers: list[EventKind] | None = None
    schedule: list[Window] | None = None
    detection: DetectionOverride | None = None
    # The streams Norn uses, by id (main, sub, ...); None: all that work.
    streams: list[str] | None = None

    @field_validator("picture_seconds")
    @classmethod
    def _picture_interval(cls, value: int | None) -> int | None:
        return _check_picture_interval(value)

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class CircleConfig(BaseModel):
    """A group of cameras: one trigger records them all, settings apply to all, and controls
    they have in common can be set on all at once."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    cameras: list[str] = Field(default_factory=list)
    # Settings for the cameras in the circle, between the global ones and a camera's own.
    picture_seconds: int | None = Field(None, ge=0, le=86400)
    prebuffer_seconds: int | None = Field(None, ge=0, le=300)
    triggers: list[EventKind] | None = None
    schedule: list[Window] | None = None
    detection: DetectionOverride | None = None
    # When one camera of the circle detects a trigger, all of them record.
    together: bool = False

    @field_validator("picture_seconds")
    @classmethod
    def _picture_interval(cls, value: int | None) -> int | None:
        return _check_picture_interval(value)

    @field_validator("cameras")
    @classmethod
    def _once_each(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


Override = Literal["picture_seconds", "prebuffer_seconds", "triggers", "schedule"]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    firmware: FirmwareSettings = Field(default_factory=FirmwareSettings)
    away: AwaySettings = Field(default_factory=AwaySettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    circles: dict[str, CircleConfig] = Field(default_factory=dict)
    cameras: dict[str, CameraConfig] = Field(default_factory=dict)

    @field_validator("recording", "firmware", "away", "detection", "cameras", "circles", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("cameras", "circles")
    @classmethod
    def _valid_ids(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if not CAMERA_ID.match(key):
                raise ValueError(f"id {key!r} must be lowercase letters, digits and dashes")
        return value

    def circles_of(self, camera_id: str) -> list[str]:
        return [cid for cid, circle in self.circles.items() if camera_id in circle.cameras]

    def triggers(self, camera_id: str, moment: datetime | None = None) -> set[str]:
        """What starts a clip on the camera now: the away triggers while away, else its triggers
        within its schedule."""
        moment = moment or datetime.now()
        if self.away.now(moment):
            return set(self.away.triggers)
        if not in_schedule(self.setting(camera_id, "schedule")[0] or [], moment):
            return set()
        return set(self.setting(camera_id, "triggers")[0] or [])

    def detection_for(self, camera_id: str) -> DetectionSettings:
        """The camera's detection settings: the global ones, changed by its first circle that
        sets any, then by its own."""
        values = self.detection.model_dump()
        layers = [self.circles[c].detection for c in self.circles_of(camera_id)][:1]
        camera = self.cameras.get(camera_id)
        layers.append(camera.detection if camera else None)
        for layer in layers:
            if layer is not None:
                values |= layer.model_dump(exclude_none=True)
        return DetectionSettings.model_validate(values)

    def pictures(self, camera_id: str, away: bool = False) -> int:
        if away and self.away.picture_seconds:
            return self.away.picture_seconds
        return self.setting(camera_id, "picture_seconds")[0]

    def setting(self, camera_id: str, name: Override) -> tuple[Any, bool]:
        """A recording setting of a camera: its own, else its first circle's, else the global one.
        The flag says whether the camera or a circle set it explicitly."""
        camera = self.cameras.get(camera_id)
        if camera is not None and getattr(camera, name) is not None:
            return getattr(camera, name), True
        for circle_id in self.circles_of(camera_id):
            value = getattr(self.circles[circle_id], name)
            if value is not None:
                return value, True
        return getattr(self.recording, name), False


class ConfigError(Exception):
    pass


def _plain(value: Any) -> Any:
    """ruamel types to plain Python, so pydantic sees ordinary dicts and lists."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _tail(node: Any) -> tuple[CommentedMap, Any] | None:
    """The mapping and key whose line ends the block of `node`: the last key, as deep as it goes."""
    found = None
    while isinstance(node, CommentedMap) and len(node):
        key = next(reversed(node))
        found = (node, key)
        node = node[key]
    return found


def _take_tail_comment(doc: CommentedMap) -> str | None:
    """Detach the comment lines after the last line of the document.

    ruamel keeps them on the last key, so a key added after it would land below the comment.
    An end-of-line comment on that last line stays where it is.
    """
    tail = _tail(doc)
    if tail is None:
        return None
    node, key = tail
    item = node.ca.items.get(key)
    if not item or len(item) < 3 or item[2] is None:
        return None
    text: str = item[2].value
    newline = text.find("\n")
    if newline < 0:
        return None
    keep, rest = text[: newline + 1], text[newline + 1 :]
    if not rest.strip():
        return None
    if keep.startswith("#"):
        item[2].value = keep
    else:
        item[2] = None
    return rest


def _put_tail_comment(doc: CommentedMap, text: str) -> None:
    tail = _tail(doc)
    if tail is None:
        return
    node, key = tail
    item = node.ca.items.setdefault(key, [None, None, None, None])
    if item[2] is None:
        item[2] = CommentToken("\n" + text, CommentMark(0), None)
    else:
        item[2].value += text


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._yaml = YAML()
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml.preserve_quotes = True
        self._doc: CommentedMap = CommentedMap()
        self._mtime: int | None = None
        self.config = Config()

    def load(self) -> Config:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(DEFAULT_CONFIG)
        text = self.path.read_text()
        try:
            doc = self._yaml.load(text)
        except Exception as e:
            raise ConfigError(f"{self.path}: {e}") from e
        if doc is None:
            doc = CommentedMap()
        if not isinstance(doc, CommentedMap):
            raise ConfigError(f"{self.path}: the top level must be a mapping")
        try:
            config = Config.model_validate(_plain(doc))
        except ValueError as e:
            raise ConfigError(f"{self.path}: {e}") from e
        self._doc = doc
        self.config = config
        self._mtime = self._stat()
        return config

    def changed_on_disk(self) -> bool:
        return self._stat() != self._mtime

    def put_camera(self, camera_id: str, camera: CameraConfig) -> Config:
        data = camera.model_dump(exclude_defaults=True, by_alias=True)
        data["name"], data["driver"] = camera.name, camera.driver
        return self._put_entry("cameras", camera_id, data)

    def put_circle(self, circle_id: str, circle: CircleConfig) -> Config:
        data = circle.model_dump(exclude_defaults=True, by_alias=True)
        data["name"], data["cameras"] = circle.name, list(circle.cameras)
        return self._put_entry("circles", circle_id, data)

    def remove_circle(self, circle_id: str) -> Config:
        return self._remove_entry("circles", circle_id)

    def _section(self, name: str) -> CommentedMap:
        """A top-level mapping, made if missing: before the cameras, the long part of the file."""
        section = self._doc.get(name)
        if not isinstance(section, CommentedMap):
            section = CommentedMap()
            keys = list(self._doc)
            if name != "cameras" and "cameras" in keys:
                self._doc.insert(keys.index("cameras"), name, section)
            else:
                self._doc[name] = section
        return section

    def _put_entry(self, section: str, entry_id: str, data: dict[str, Any]) -> Config:
        if not CAMERA_ID.match(entry_id):
            raise ConfigError(f"id {entry_id!r} must be lowercase letters, digits and dashes")
        # Comments after the last camera belong to the end of the block, not to its last key.
        tail = _take_tail_comment(self._doc)
        entries = self._section(section)
        entries.fa.set_block_style()
        existing = entries.get(entry_id)
        if isinstance(existing, CommentedMap):
            for key in [k for k in existing if k not in data]:
                del existing[key]
            for key, value in data.items():
                if existing.get(key) != value:
                    existing[key] = value
        else:
            entries[entry_id] = CommentedMap(data)
        if tail:
            _put_tail_comment(self._doc, tail)
        return self._commit()

    def put_section(self, name: str, values: BaseModel) -> Config:
        """Write a settings section (`recording`, ...). Keys at their default stay out of the file."""
        if name not in Config.model_fields or name == "cameras":
            raise ConfigError(f"no settings section {name!r}")
        data = values.model_dump(by_alias=True)
        defaults = type(values)().model_dump(by_alias=True)
        tail = _take_tail_comment(self._doc)
        section = self._section(name)
        for key, value in data.items():
            if value == defaults[key] and key not in section:
                continue
            if section.get(key) != value:
                section[key] = value
        for key in [k for k in section if k not in data]:
            del section[key]
        if not section:
            del self._doc[name]
        if tail:
            _put_tail_comment(self._doc, tail)
        return self._commit()

    def remove_camera(self, camera_id: str) -> Config:
        return self._remove_entry("cameras", camera_id)

    def _remove_entry(self, section: str, entry_id: str) -> Config:
        entries = self._doc.get(section)
        if not isinstance(entries, CommentedMap) or entry_id not in entries:
            raise KeyError(entry_id)
        tail = _take_tail_comment(self._doc)
        del entries[entry_id]
        if not entries and section != "cameras":
            del self._doc[section]  # an empty circles block is just noise
        elif not entries:
            # An empty block mapping after comments dumps as invalid YAML; `{}` is valid.
            entries.fa.set_flow_style()
        if tail and _tail(self._doc) and (entries or section != "cameras"):
            _put_tail_comment(self._doc, tail)
        return self._commit()

    def dump(self) -> str:
        buffer = io.StringIO()
        self._yaml.dump(self._doc, buffer)
        return buffer.getvalue()

    def _commit(self) -> Config:
        config = Config.model_validate(_plain(self._doc))
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(self.dump())
        os.replace(tmp, self.path)
        self.config = config
        self._mtime = self._stat()
        return config

    def _stat(self) -> int | None:
        try:
            return self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return None
