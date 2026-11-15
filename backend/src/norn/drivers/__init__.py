"""The driver registry. A driver module registers its class with @register."""

from __future__ import annotations

from typing import Any

from .base import Driver

DRIVERS: dict[str, type[Driver]] = {}


def register[T: type[Driver]](cls: T) -> T:
    if cls.name in DRIVERS:
        raise ValueError(f"driver {cls.name!r} is registered twice")
    DRIVERS[cls.name] = cls
    return cls


def describe(cls: type[Driver]) -> dict[str, Any]:
    """What the UI needs to show a form for adding a camera of this kind."""
    return {
        "name": cls.name,
        "label": cls.label,
        "description": cls.description,
        "options": cls.Options.model_json_schema(),
    }


# Importing the modules registers the drivers.
from . import demo, foscam, hikvision, onvif, reolink, rtsp  # noqa: E402

__all__ = ["DRIVERS", "demo", "describe", "foscam", "hikvision", "onvif", "register", "reolink", "rtsp"]
