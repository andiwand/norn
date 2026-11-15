"""Is a camera's firmware current?

Vendors have no common, public API for this, so Norn keeps a small catalogue of the newest
firmware it knows per model, with where it comes from. A driver reports the model and version
(DeviceInfo); `check` compares them. Update the catalogue when a vendor releases firmware.

`checked` is the date someone last confirmed `latest`; the UI shows it, so nobody mistakes an
old entry for a live check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

Status = Literal["current", "update", "end-of-life", "unknown"]


@dataclass(frozen=True)
class Entry:
    manufacturer: str
    model: re.Pattern[str]  # matched against DeviceInfo.model
    latest: str | None  # None: no firmware is published (end of life)
    released: str | None
    url: str | None
    checked: str
    notes: tuple[str, ...] = ()


CATALOGUE: list[Entry] = [
    Entry(
        manufacturer="Hikvision",
        model=re.compile(r"^DS-2CD2[01]42WD"),  # R6 platform: DS-2CD2042WD, DS-2CD2142WD, ...
        latest="V5.5.82 build 190909",
        released="2019-09-09",
        url="https://www.hikvision.com/en/support/download/firmware/",
        checked="2026-11-16",
        notes=(
            "Firmware before V5.4.5 has a known login bypass (CVE-2017-7921). Update soon.",
            "Older firmware can't jump to the latest version: update in steps (V5.4.x, then V5.5.x).",
            "Cameras bought for the Chinese market can refuse or break with EU/US firmware.",
        ),
    ),
    Entry(
        manufacturer="Reolink",
        model=re.compile(r"^E1 Pro$"),
        latest="v3.1.0.5112_2507081475",
        released="2025-07-08",
        url="https://reolink.com/download-center/",
        checked="2026-11-16",
        notes=("For hardware IPC_566SD54MP; the driver also asks Reolink live for the camera's hardware.",),
    ),
    Entry(
        manufacturer="supra",
        model=re.compile(r"^IPC-(1A|100HD)$"),
        latest=None,
        released=None,
        url=None,
        checked="2026-11-16",
        notes=("The vendor publishes no firmware any more. Keep the camera off the internet.",),
    ),
]


class FirmwareStatus(BaseModel):
    status: Status
    current: str | None = None
    latest: str | None = None
    released: str | None = None
    url: str | None = None
    checked: str | None = None
    notes: list[str] = []


def version_key(version: str) -> tuple[int, ...]:
    """The numbers of a version, for comparing: "V5.3.8 build 151224" -> (5, 3, 8, 151224)."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def check(manufacturer: str | None, model: str | None, current: str | None) -> FirmwareStatus:
    if not model:
        return FirmwareStatus(status="unknown", current=current)
    for entry in CATALOGUE:
        if manufacturer and entry.manufacturer.lower() != manufacturer.lower():
            continue
        if not entry.model.search(model):
            continue
        common = {
            "current": current,
            "latest": entry.latest,
            "released": entry.released,
            "url": entry.url,
            "checked": entry.checked,
            "notes": list(entry.notes),
        }
        if entry.latest is None:
            return FirmwareStatus(status="end-of-life", **common)
        if current is None:
            return FirmwareStatus(status="unknown", **common)
        newer = version_key(entry.latest) > version_key(current)
        if not newer:
            # Up to date: the warnings about old versions don't apply.
            common["notes"] = [n for n in entry.notes if "before" not in n and "Older" not in n]
        return FirmwareStatus(status="update" if newer else "current", **common)
    return FirmwareStatus(status="unknown", current=current)
