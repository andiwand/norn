"""config.yaml: the cameras and the recording rules.

The file is the single source of truth. The UI writes changes back into it with ruamel.yaml's
round-trip mode, so comments and formatting that a person wrote by hand survive. Norn also
watches the file and reloads it when someone edits it while the server runs.
"""

from __future__ import annotations

import contextlib
import functools
import io
import itertools
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Concatenate, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark, MarkedYAMLError
from ruamel.yaml.tokens import CommentToken

from .labels import LabelId

CAMERA_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")  # use fullmatch: `$` also matches before a "\n"


def check_ids(ids: Any) -> None:
    """Ids of cameras, circles and presets: they become names of files and folders."""
    for key in ids:
        if not CAMERA_ID.fullmatch(key):
            raise ValueError(f"id {key!r} must be lowercase letters, digits and dashes")


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
        if self.start == self.end:  # 00:00 to 00:00: the whole day
            return today in self.days
        if self.start < self.end:
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

    @field_validator("start", "end")
    @classmethod
    def _local(cls, value: datetime | None) -> datetime | None:
        """Times with a zone become the server's local time, like the rest of Norn's times."""
        if value is not None and value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value

    def now(self, moment: datetime | None = None) -> bool:
        if self.active:
            return True
        moment = moment or datetime.now()
        return self.start is not None and self.start <= moment and (self.end is None or moment < self.end)


Stills = Literal["auto", "keyframe", "live"]
# The camera's own AI alarms (person, vehicle, animal): `check` records them and has Norn's AI
# look too (the clip says whether it agreed); `require` records only what Norn's AI confirms;
# `off` takes the camera's word.
CheckCamera = Literal["off", "check", "require"]


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
    # objects: how long one must be seen before it counts (0: on the first still)
    confirm_seconds: float = Field(0, ge=0, le=60)
    check_camera: CheckCamera = "check"
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
    confirm_seconds: float | None = Field(None, ge=0, le=60)
    check_camera: CheckCamera | None = None


class NornPreset(BaseModel):
    """A named view of a pan/tilt camera: one of the camera's own preset slots, plus settings
    to apply when it gets there (night mode, spotlight, ...)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    slot: str = Field(min_length=1)  # the camera's preset id
    controls: dict[str, Any] = Field(default_factory=dict)
    # What records while the camera is at this preset; None: the camera's setting.
    triggers: list[EventKind] | None = None
    clip_seconds: int | None = Field(None, ge=5, le=3600)
    prebuffer_seconds: int | None = Field(None, ge=0, le=300)


class Patrol(BaseModel):
    """Turning through presets: in order or at random, a while at each, in its schedule."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    presets: list[str] = Field(default_factory=list)  # Norn preset ids
    order: Literal["sequence", "random"] = "sequence"
    dwell_seconds: int = Field(60, ge=5, le=86400)
    schedule: list[Window] = Field(default_factory=list)  # when; empty: always
    # After someone moves the camera by hand, the patrol waits this long.
    pause_after_manual: int = Field(120, ge=0, le=86400)


class Reaction(BaseModel):
    """When a camera detects something, turn this one to a preset for a while."""

    model_config = ConfigDict(extra="forbid")

    kinds: list[EventKind] = Field(min_length=1)
    cameras: list[str] = Field(default_factory=list)  # whose detections; empty: this camera's
    presets: list[str] = Field(min_length=1)  # one of them (at random, if more)
    hold_seconds: int = Field(60, ge=5, le=3600)


Follow = Literal["off", "always", "recording", "away"]


class FirmwareSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # How often to ask the vendors for new firmware (and auto-update). 0: never.
    check_hours: int = Field(24, ge=0, le=24 * 90)


TOPIC_LEVEL = r"^[A-Za-z0-9_-]+$"  # one MQTT topic level: the topics Norn parses have no room for more
HOST = r"^[^\s/@]*$"  # a host name or address, nothing else (no mqtt://, no user)


class MqttSettings(BaseModel):
    """MQTT, for Home Assistant and other home automation (mqtt.py). The defaults come from the
    NORN_MQTT* environment variables (`mqtt.defaults`); config.yaml has what differs from them
    (`MqttOverride`)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    host: str = Field("", pattern=HOST)
    port: int = Field(0, ge=0, le=65535)  # 0: 1883, or 8883 with TLS
    tls: bool = False
    username: str = ""
    password: str = ""
    prefix: str = Field("norn", pattern=TOPIC_LEVEL)  # Norn's topics: <prefix>/...
    discovery: bool = True  # Home Assistant's MQTT discovery
    discovery_prefix: str = Field("homeassistant", pattern=TOPIC_LEVEL)
    stills_seconds: int = Field(0, ge=0, le=86400)  # each camera's still this often; 0: none


class MqttOverride(BaseModel):
    """The `mqtt` section of config.yaml: what differs from the environment's defaults."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    host: str | None = Field(None, pattern=HOST)
    port: int | None = Field(None, ge=0, le=65535)
    tls: bool | None = None
    username: str | None = None
    password: str | None = None
    prefix: str | None = Field(None, pattern=TOPIC_LEVEL)
    discovery: bool | None = None
    discovery_prefix: str | None = Field(None, pattern=TOPIC_LEVEL)
    stills_seconds: int | None = Field(None, ge=0, le=86400)

    def over(self, defaults: MqttSettings) -> MqttSettings:
        return defaults.model_copy(update=self.model_dump(exclude_none=True))


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
    clip_seconds: int | None = Field(None, ge=5, le=3600)
    triggers: list[EventKind] | None = None
    schedule: list[Window] | None = None
    detection: DetectionOverride | None = None
    # The streams Norn uses, by id (main, sub, ...); None: all that work.
    streams: list[str] | None = None
    # The streams kept ready from their newest keyframe, so live video starts at once (each
    # holds a connection to the camera open). None: the one the Live page shows (the small one).
    ready_streams: list[str] | None = None
    # Pan/tilt cameras: Norn's presets (by id), patrol, reactions to detections, following.
    presets: dict[str, NornPreset] = Field(default_factory=dict)
    patrol: Patrol | None = None
    reactions: list[Reaction] = Field(default_factory=list)
    follow: Follow = "off"
    # A Norn preset the camera returns to when nothing else steers it.
    default_preset: str | None = None

    @field_validator("presets")
    @classmethod
    def _preset_ids(cls, value: dict[str, NornPreset]) -> dict[str, NornPreset]:
        check_ids(value)
        return value

    @model_validator(mode="after")
    def _default_is_a_preset(self) -> CameraConfig:
        if self.default_preset is not None and self.default_preset not in self.presets:
            raise ValueError(f"default_preset {self.default_preset!r} is not one of its presets")
        return self

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
    clip_seconds: int | None = Field(None, ge=5, le=3600)
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


Override = Literal["picture_seconds", "prebuffer_seconds", "clip_seconds", "triggers", "schedule"]
PRESET_OVERRIDES = frozenset({"prebuffer_seconds", "clip_seconds", "triggers"})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    firmware: FirmwareSettings = Field(default_factory=FirmwareSettings)
    away: AwaySettings = Field(default_factory=AwaySettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    mqtt: MqttOverride = Field(default_factory=MqttOverride)
    circles: dict[str, CircleConfig] = Field(default_factory=dict)
    cameras: dict[str, CameraConfig] = Field(default_factory=dict)

    @field_validator(
        "recording", "firmware", "away", "detection", "mqtt", "cameras", "circles", mode="before"
    )
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("cameras", "circles")
    @classmethod
    def _valid_ids(cls, value: dict[str, Any]) -> dict[str, Any]:
        check_ids(value)
        return value

    def circles_of(self, camera_id: str) -> list[str]:
        return [cid for cid, circle in self.circles.items() if camera_id in circle.cameras]

    def triggers(self, camera_id: str, moment: datetime | None = None, preset: str | None = None) -> set[str]:
        """What starts a clip on the camera now: the away triggers while away, else its triggers
        (at `preset`, the preset's) within its schedule."""
        moment = moment or datetime.now()
        if self.away.now(moment):
            return set(self.away.triggers)
        if not in_schedule(self.setting(camera_id, "schedule")[0] or [], moment):
            return set()
        return set(self.setting(camera_id, "triggers", preset)[0] or [])

    def detection_for(self, camera_id: str) -> DetectionSettings:
        """The camera's detection settings: the global ones, changed by its first circle that
        sets any, then by its own."""
        values = self.detection.model_dump()
        layers = [d for c in self.circles_of(camera_id) if (d := self.circles[c].detection)][:1]
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

    def setting(self, camera_id: str, name: Override, preset: str | None = None) -> tuple[Any, bool]:
        """A recording setting of a camera: its preset's (at `preset`), else its own, else its
        first circle's, else the global one. The flag says whether it was set explicitly."""
        camera = self.cameras.get(camera_id)
        at = camera.presets.get(preset) if camera is not None and preset else None
        if at is not None and name in PRESET_OVERRIDES and getattr(at, name) is not None:
            return getattr(at, name), True
        if camera is not None and getattr(camera, name) is not None:
            return getattr(camera, name), True
        for circle_id in self.circles_of(camera_id):
            value = getattr(self.circles[circle_id], name)
            if value is not None:
                return value, True
        return getattr(self.recording, name), False

    def longest_prebuffer(self, camera_id: str) -> tuple[int, bool]:
        """The pre-recording time a camera's buffer must hold: the longest of its own and its
        presets'. The flag: set explicitly."""
        length, explicit = self.setting(camera_id, "prebuffer_seconds")
        camera = self.cameras.get(camera_id)
        for preset in camera.presets.values() if camera else []:
            if preset.prebuffer_seconds is not None and preset.prebuffer_seconds > length:
                length, explicit = preset.prebuffer_seconds, True
        return length, explicit


class ConfigError(Exception):
    pass


def short_error(e: ValidationError) -> str:
    """A validation error in one line: where and what, never the value (it may be a password)."""
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'options'}: {err['msg']}" for err in e.errors())


def _parse_error(e: Exception) -> str:
    """A YAML error without the lines it quotes (they may hold a password): what, and where."""
    if not isinstance(e, MarkedYAMLError):
        return str(e)
    mark = e.problem_mark or e.context_mark
    where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
    return f"{e.problem or e.context}{where}"


def _plain(value: Any) -> Any:
    """ruamel types to plain Python, so pydantic sees ordinary dicts and lists."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _tail(node: Any) -> tuple[Any, Any] | None:
    """The mapping or list, and key or index, whose line ends the block of `node`: the last
    entry, as deep as it goes."""
    found = None
    while True:
        if isinstance(node, CommentedMap | CommentedSeq) and node.fa.flow_style():
            return found  # `{...}` on one line: comments go after it, not inside
        if isinstance(node, CommentedMap) and len(node):
            key: Any = next(reversed(node))
        elif isinstance(node, CommentedSeq) and len(node):
            key = len(node) - 1
        else:
            return found
        found = (node, key)
        node = node[key]


def _tail_token(node: Any, key: Any, create: bool = False) -> tuple[list[Any] | None, int]:
    """ruamel's comment slots of an entry, and the slot of the comment after its line (third
    for a mapping's entry, first for a list's)."""
    slot = 2 if isinstance(node, CommentedMap) else 0
    item = node.ca.items.setdefault(key, [None] * (slot + 2)) if create else node.ca.items.get(key)
    if item is not None and len(item) <= slot:
        item.extend([None] * (slot + 1 - len(item)))
    return item, slot


def _commented(value: Any) -> Any:
    """Plain dicts and lists as ruamel's, so comments can attach to their last line."""
    if isinstance(value, dict) and not isinstance(value, CommentedMap):
        return CommentedMap((k, _commented(v)) for k, v in value.items())
    if isinstance(value, list) and not isinstance(value, CommentedSeq):
        return CommentedSeq(_commented(v) for v in value)
    return value


def _last(node: Any, key: Any) -> tuple[Any, Any]:
    """Where the line that ends the entry `key` of `node` is: its block's last entry, or itself."""
    return _tail(node[key]) or (node, key)


def _put_tail_comment(doc: Any, text: str) -> None:
    """Attach comment lines after the last line of the block of `doc`."""
    if (tail := _tail(doc)) is not None:
        _put_comment(*tail, text)


def _put_comment(node: Any, key: Any, text: str) -> None:
    """Attach comment lines after the line of the entry `key`."""
    item, slot = _tail_token(node, key, create=True)
    assert item is not None
    if item[slot] is None:
        item[slot] = CommentToken("\n" + text, CommentMark(0), None)
    else:
        item[slot].value += text


def _split_tail(node: Any) -> str:
    """Detach the comment lines after the block of `node` (an end-of-line comment stays)."""
    tail = _tail(node)
    return _split_comment(*tail) if tail else ""


def _split_comment(node: Any, key: Any) -> str:
    """Detach the comment lines after the line of the entry `key` (an end-of-line comment stays)."""
    item, slot = _tail_token(node, key)
    if not item or item[slot] is None:
        return ""
    text: str = item[slot].value
    newline = text.find("\n")
    if newline < 0:
        return ""
    keep, rest = text[: newline + 1], text[newline + 1 :]
    if keep.startswith("#"):
        item[slot].value = keep
    else:
        item[slot] = None
    return rest


def _delete(mapping: CommentedMap, key: Any, parent: CommentedMap | None = None) -> None:
    """Delete a key with the comment lines above it; the lines after its block stay. ruamel
    keeps the lines above a key on the entry before it (for the first key: on the mapping and
    on the `parent`'s entry; the top level's are the file's header and stay)."""
    keys = list(mapping)
    i = keys.index(key)
    after = _split_comment(*_last(mapping, key))
    if i:
        _split_comment(*_last(mapping, keys[i - 1]))
    elif parent is not None and mapping.ca.comment and (first := mapping.ca.comment[1]):
        mapping.ca.comment[1] = None
        for item in parent.ca.items.values():
            if len(item) > 3 and item[3] is first:
                item[3] = None
    del mapping[key]
    if not after.strip():
        return
    if i:
        _put_comment(*_last(mapping, keys[i - 1]), after)
    elif len(mapping):
        mapping.ca.items.setdefault(keys[1], [None, None, None, None])[1] = [
            CommentToken(after, CommentMark(0), None)
        ]


def _merge(node: CommentedMap, data: dict[str, Any], parent: CommentedMap | None = None) -> None:
    """Make `node` (in `parent`) hold `data`, changing only what differs, nested mappings too,
    so the comments in it stay."""
    for key in [k for k in node if k not in data]:
        _delete(node, key, parent)
    for key, value in data.items():
        old = node.get(key)
        if isinstance(old, CommentedMap) and isinstance(value, dict):
            _merge(old, value, node)
        elif key not in node or old != value:
            node[key] = _commented(value)


def _edit[**P](
    method: Callable[Concatenate[ConfigStore, P], Config],
) -> Callable[Concatenate[ConfigStore, P], Config]:
    """A change to the file: made to the file as it is now (a hand edit since the last load
    stays; a broken file raises ConfigError and stays as it is), and all or nothing (when it
    fails, Norn's copy is the file's again)."""

    @functools.wraps(method)
    def edit(self: ConfigStore, *args: P.args, **kwargs: P.kwargs) -> Config:
        if self.changed_on_disk():
            self.load()
        try:
            return method(self, *args, **kwargs)
        except BaseException:
            with contextlib.suppress(Exception):
                self.load()
            # The hub reloads too: a hand edit loaded above must still be applied (and if
            # loading failed, the next change loads first).
            self._mtime = None
            raise

    return edit


def _indented(text: str, indent: str) -> str:
    return "".join(
        indent + line.lstrip() if line.strip() else line for line in text.splitlines(keepends=True)
    )


def _reorder(doc: CommentedMap, mapping: CommentedMap, order: list[Any]) -> None:
    """Put the keys of `mapping` (a top-level key's block) in `order`, each with the comment
    lines above it, and the lines after the block (above the next top-level key) where they are.

    ruamel keeps the lines above a key on the key before it (on the deepest last line of its
    block), or on the mapping for the first key, so moving keys alone would move comments to
    the wrong ones."""
    keys = list(mapping)
    if not keys:
        return
    above: dict[Any, str] = {}
    first = mapping.ca.comment[1] if mapping.ca.comment else None
    above[keys[0]] = "".join(t.value for t in first) if first else ""
    if first:
        mapping.ca.comment[1] = None
        for item in doc.ca.items.values():  # the same lines, also kept on the parent key
            if len(item) > 3 and item[3] is first:
                item[3] = None
    for before, key in itertools.pairwise(keys):
        text = _split_tail(mapping[before])
        item = mapping.ca.items.get(key)
        if item and item[1]:
            text += "".join(t.value for t in item[1])
            item[1] = None
        above[key] = text
    after = _split_tail(mapping[keys[-1]])
    for key in order:
        mapping.move_to_end(key)
    for key in order:
        text = above.get(key, "")
        if text.strip():
            text = _indented(text.lstrip("\n") if key == order[0] else text, "  ")
            item = mapping.ca.items.setdefault(key, [None, None, None, None])
            item[1] = [CommentToken(text, CommentMark(0), None)]
    if after:
        _put_tail_comment(mapping, after)


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
        try:
            doc = self._yaml.load(self.path.read_text())
        except Exception as e:
            raise ConfigError(f"{self.path}: {_parse_error(e)}") from e
        if doc is None:
            doc = CommentedMap()
        if not isinstance(doc, CommentedMap):
            raise ConfigError(f"{self.path}: the top level must be a mapping")
        try:
            config = Config.model_validate(_plain(doc))
        except ValidationError as e:
            raise ConfigError(f"{self.path}: {short_error(e)}") from e
        self._doc = doc
        self.config = config
        self._mtime = self._stat()
        return config

    def changed_on_disk(self) -> bool:
        return self._stat() != self._mtime

    def put_camera(self, camera_id: str, camera: CameraConfig) -> Config:
        data = camera.model_dump(exclude_defaults=True, by_alias=True)
        if data.get("patrol") == {}:  # a patrol of defaults is none: off, without presets
            del data["patrol"]
        return self._put_entry("cameras", camera_id, data)

    @_edit
    def order_cameras(self, ids: list[str]) -> Config:
        """Put the cameras in this order (the order of the Live page). Ones not named keep their
        place after these; each keeps its comments."""
        cameras = self._doc.get("cameras")
        if not isinstance(cameras, CommentedMap):
            return self.config
        unknown = [i for i in ids if i not in cameras]
        if unknown:
            raise ConfigError(f"no camera {', '.join(unknown)}")
        _reorder(self._doc, cameras, [*dict.fromkeys(ids), *[k for k in cameras if k not in ids]])
        return self._commit()

    def put_circle(self, circle_id: str, circle: CircleConfig) -> Config:
        data = circle.model_dump(exclude_defaults=True, by_alias=True)
        data["cameras"] = list(circle.cameras)
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

    @_edit
    def _put_entry(self, section: str, entry_id: str, data: dict[str, Any]) -> Config:
        if not CAMERA_ID.fullmatch(entry_id):
            raise ConfigError(f"id {entry_id!r} must be lowercase letters, digits and dashes")
        # Comments after the last camera belong to the end of the block, not to its last key.
        tail = _split_tail(self._doc) or None
        entries = self._section(section)
        entries.fa.set_block_style()
        existing = entries.get(entry_id)
        if isinstance(existing, CommentedMap):
            _merge(existing, data, entries)
        else:
            entries[entry_id] = _commented(data)
        if tail:
            _put_tail_comment(self._doc, tail)
        return self._commit()

    @_edit
    def put_section(self, name: str, values: BaseModel) -> Config:
        """Write a settings section (`recording`, ...). Keys at their default stay out of the
        file (one written by hand at its default stays, with its comment)."""
        if name not in Config.model_fields or name == "cameras":
            raise ConfigError(f"no settings section {name!r}")
        data = values.model_dump(by_alias=True)
        defaults = type(values)().model_dump(by_alias=True)
        tail = _split_tail(self._doc) or None
        section = self._section(name)
        for key in [k for k in section if k not in data]:
            _delete(section, key, self._doc)
        for key, value in data.items():
            if key in section and section[key] == value:
                continue
            if value == defaults[key]:
                if key in section:
                    _delete(section, key, self._doc)
            else:
                section[key] = _commented(value)
        if not section:
            _delete(self._doc, name)
        if tail:
            _put_tail_comment(self._doc, tail)
        return self._commit()

    def remove_camera(self, camera_id: str) -> Config:
        return self._remove_entry("cameras", camera_id)

    @_edit
    def _remove_entry(self, section: str, entry_id: str) -> Config:
        entries = self._doc.get(section)
        if not isinstance(entries, CommentedMap) or entry_id not in entries:
            raise KeyError(entry_id)
        tail = _split_tail(self._doc) or None
        _delete(entries, entry_id, self._doc)
        if not entries and section != "cameras":
            _delete(self._doc, section)  # an empty circles block is just noise
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
        try:
            config = Config.model_validate(_plain(self._doc))
        except ValidationError as e:
            raise ConfigError(short_error(e)) from e
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
