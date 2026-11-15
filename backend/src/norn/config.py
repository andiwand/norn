"""config.yaml: the cameras and the recording rules.

The file is the single source of truth. The UI writes changes back into it with ruamel.yaml's
round-trip mode, so comments and formatting that a person wrote by hand survive. Norn also
watches the file and reloads it when someone edits it while the server runs.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

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


class RecordingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(14, ge=0)
    segment_minutes: int = Field(10, ge=1, le=60)
    clip_seconds: int = Field(30, ge=5, le=3600)


class CameraConfig(BaseModel):
    """One camera. Fields besides these are options of its driver (url, host, ...)."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    driver: str = Field(min_length=1)
    enabled: bool = True
    record: Literal["off", "continuous"] = "off"

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    cameras: dict[str, CameraConfig] = Field(default_factory=dict)

    @field_validator("cameras", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("cameras")
    @classmethod
    def _valid_ids(cls, value: dict[str, CameraConfig]) -> dict[str, CameraConfig]:
        for camera_id in value:
            if not CAMERA_ID.match(camera_id):
                raise ValueError(f"camera id {camera_id!r} must be lowercase letters, digits and dashes")
        return value


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
        if not CAMERA_ID.match(camera_id):
            raise ConfigError(f"camera id {camera_id!r} must be lowercase letters, digits and dashes")
        data = camera.model_dump(exclude_defaults=True)
        data["name"], data["driver"] = camera.name, camera.driver
        # Comments after the last camera belong to the end of the block, not to its last key.
        tail = _take_tail_comment(self._doc)
        cameras = self._doc.get("cameras")
        if not isinstance(cameras, CommentedMap):
            cameras = CommentedMap()
            self._doc["cameras"] = cameras
        cameras.fa.set_block_style()
        existing = cameras.get(camera_id)
        if isinstance(existing, CommentedMap):
            for key in [k for k in existing if k not in data]:
                del existing[key]
            for key, value in data.items():
                if existing.get(key) != value:
                    existing[key] = value
        else:
            cameras[camera_id] = CommentedMap(data)
        if tail:
            _put_tail_comment(self._doc, tail)
        return self._commit()

    def remove_camera(self, camera_id: str) -> Config:
        cameras = self._doc.get("cameras")
        if not isinstance(cameras, CommentedMap) or camera_id not in cameras:
            raise KeyError(camera_id)
        tail = _take_tail_comment(self._doc)
        del cameras[camera_id]
        if tail and cameras:
            _put_tail_comment(self._doc, tail)
        if not cameras:
            # An empty block mapping after comments dumps as invalid YAML; `{}` is valid.
            cameras.fa.set_flow_style()
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
