"""How much each trigger records, and how much that will be.

For each camera and trigger Norn takes the measured rate (bytes per day over the last week of
recordings) once there is enough of it; before that, an estimate from the settings and the
camera's bitrate, which the RAM buffer measures. Recordings that expire level off at
`rate * retention days`; clips recorded by hand only grow.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .config import Config
from .recordings import KEPT, Recording

DAY = 86400
WINDOW = timedelta(days=7)
MIN_MEASURED = 3600  # seconds of history before a measured rate counts
PICTURE_GUESS = 250_000  # bytes of a picture before the first one is taken


@dataclass
class Rate:
    camera: str
    trigger: str
    per_day: float  # bytes
    basis: str  # "measured" or "estimated"
    count_per_day: float = 0

    def steady(self, retention_days: int) -> float | None:
        """What it holds once old recordings expire as fast as new ones come; None: no limit."""
        if self.trigger in KEPT or retention_days <= 0:
            return None
        return self.per_day * retention_days


def measured(recordings: list[Recording], now: datetime) -> list[Rate]:
    """Bytes per day by camera and trigger, from the recordings of the last week."""
    since = now - WINDOW
    groups: dict[tuple[str, str], list[Recording]] = defaultdict(list)
    first_of: dict[str, datetime] = {}  # since when each camera has recordings at all
    for r in recordings:
        if r.start >= since:
            groups[(r.camera, r.trigger)].append(r)
            first_of[r.camera] = min(first_of.get(r.camera, r.start), r.start)
    rates = []
    for (camera, trigger), items in groups.items():
        timed = trigger in ("continuous", "interval")
        # A timed trigger records from when it was switched on; events since the camera records.
        first = min(r.start for r in items) if timed else first_of[camera]
        seconds = (now - first).total_seconds()
        if timed and seconds < MIN_MEASURED:
            continue  # too early to tell: the estimate is better
        # Events (clips) come when they come: one clip isn't a rate until a day has passed.
        seconds = max(seconds, MIN_MEASURED if timed else DAY)
        size = sum(r.size for r in items)
        rates.append(Rate(camera, trigger, size / seconds * DAY, "measured", len(items) / seconds * DAY))
    return rates


def estimated(config: Config, bitrates: dict[str, float], picture_sizes: dict[str, float]) -> list[Rate]:
    """What the settings will record, from each camera's bitrate (bytes per second)."""
    rates = []
    for camera_id, camera in config.cameras.items():
        if not camera.enabled:
            continue
        if camera.record == "continuous" and camera_id in bitrates:
            rates.append(Rate(camera_id, "continuous", bitrates[camera_id] * DAY, "estimated"))
        every, _ = config.setting(camera_id, "picture_seconds")
        if every > 0:
            size = picture_sizes.get(camera_id, PICTURE_GUESS)
            rates.append(Rate(camera_id, "interval", size * DAY / every, "estimated", DAY / every))
    return rates


def forecast(
    config: Config,
    recordings: list[Recording],
    bitrates: dict[str, float],
    free: int | None,
    now: datetime | None = None,
    used: int | None = None,
) -> dict[str, Any]:
    """`free`: bytes free on the recordings' disk; `used`: bytes the recordings take now."""
    now = now or datetime.now()
    retention = config.recording.retention_days
    pictures: dict[str, list[int]] = defaultdict(list)
    for r in recordings:
        if r.kind == "picture":
            pictures[r.camera].append(r.size)
    picture_sizes = {c: sum(s) / len(s) for c, s in pictures.items()}

    rates = {(r.camera, r.trigger): r for r in estimated(config, bitrates, picture_sizes)}
    # A measured rate replaces the estimate, as soon as there is one.
    for rate in measured(recordings, now):
        rates[(rate.camera, rate.trigger)] = rate
    # A trigger that is off now records nothing more, whatever it did last week.
    for key, rate in list(rates.items()):
        camera = config.cameras.get(rate.camera)
        off = camera is None or not camera.enabled
        if rate.trigger == "continuous" and camera is not None and camera.record != "continuous":
            off = True
        if rate.trigger == "interval" and config.setting(rate.camera, "picture_seconds")[0] == 0:
            off = True
        if off:
            del rates[key]

    by_trigger: dict[str, dict[str, Any]] = {}
    for rate in sorted(rates.values(), key=lambda r: (r.trigger, r.camera)):
        entry = by_trigger.setdefault(
            rate.trigger,
            {"trigger": rate.trigger, "per_day": 0.0, "steady": 0.0, "kept": rate.trigger in KEPT,
             "cameras": []},
        )  # fmt: skip
        steady = rate.steady(retention)
        entry["per_day"] += rate.per_day
        if steady is not None:
            entry["steady"] += steady
        entry["cameras"].append(
            {
                "camera": rate.camera,
                "per_day": round(rate.per_day),
                "steady": round(steady) if steady is not None else None,
                "count_per_day": round(rate.count_per_day, 1),
                "basis": rate.basis,
            }
        )
    triggers = sorted(by_trigger.values(), key=lambda t: -t["per_day"])
    for t in triggers:
        t["per_day"] = round(t["per_day"])
        t["steady"] = None if t["kept"] or retention <= 0 else round(t["steady"])

    per_day = sum(t["per_day"] for t in triggers)
    growing = sum(t["per_day"] for t in triggers if t["steady"] is None)  # never levels off
    steady = sum(t["steady"] or 0 for t in triggers)
    # Expiring recordings grow from what they hold now up to their level; the rest keeps growing.
    expiring_now = sum(r.size for r in recordings if not r.kept)
    days_full = None
    if free is not None and per_day > 0:
        headroom = free - max(0, steady - expiring_now)
        if headroom < 0:
            days_full = free / per_day  # full before the expiring ones level off
        elif growing > 0:
            days_full = headroom / growing
    r = config.recording
    room = []  # bytes until each limit
    if r.max_gb and used is not None:
        room.append(r.max_gb * 1e9 - used)
    if r.min_free_gb and free is not None:
        room.append(free - r.min_free_gb * 1e9)
    limit = round(min(room)) if room else None
    days_limit = None
    if limit is not None:
        # It is reached when something only grows, or when the expiring ones level off beyond it.
        reaches = growing > 0 or steady - expiring_now > limit
        if limit <= 0:
            days_limit = 0.0
        elif per_day > 0 and reaches:
            days_limit = round(limit / per_day, 1)
    return {
        "retention_days": retention,
        "per_day": per_day,
        "steady": steady,
        "growing_per_day": growing,
        "days_until_full": round(days_full, 1) if days_full is not None and limit is None else None,
        # With a size or free-space limit, the disk doesn't fill up: old recordings go earlier
        # than their retention time once the limit is reached.
        "limit": limit,
        "days_until_limit": days_limit,
        "triggers": triggers,
    }


def history(retention_days: int) -> timedelta:
    """How far back the forecast needs recordings: the week it measures, and everything that
    still expires (it is all younger than the retention time)."""
    return max(WINDOW, timedelta(days=retention_days))
