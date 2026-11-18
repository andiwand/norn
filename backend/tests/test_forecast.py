from __future__ import annotations

from datetime import datetime, timedelta

from norn.config import Config
from norn.forecast import forecast
from norn.recordings import Recording

NOW = datetime(2026, 11, 16, 12)


def rec(camera: str, trigger: str, hours_ago: float, size: int, kind: str = "video") -> Recording:
    start = NOW - timedelta(hours=hours_ago)
    return Recording(camera, start.date().isoformat(), "x", kind, start, trigger, size, 600, False, {})  # type: ignore[arg-type]


def config(**recording: int) -> Config:
    return Config.model_validate(
        {
            "recording": {"retention_days": 10, **recording},
            "cameras": {
                "door": {"name": "Door", "driver": "demo", "record": "continuous"},
                "yard": {"name": "Yard", "driver": "demo"},
            },
        }
    )


def test_estimate_before_any_recording() -> None:
    result = forecast(config(picture_seconds=60), [], {"door": 1000.0}, free=10**12, now=NOW)
    triggers = {t["trigger"]: t for t in result["triggers"]}
    assert triggers["continuous"]["per_day"] == 1000 * 86400
    assert triggers["continuous"]["steady"] == 1000 * 86400 * 10
    assert triggers["continuous"]["cameras"][0]["basis"] == "estimated"
    assert triggers["interval"]["per_day"] == 250_000 * 1440 * 2  # two cameras
    assert result["days_until_full"] is None  # everything levels off, and it fits


def test_measured_replaces_estimate_and_manual_grows() -> None:
    items = [rec("door", "continuous", h, 6_000_000) for h in range(1, 25)]  # 24 h, 6 MB each
    items += [rec("yard", "manual", 2, 50_000_000)]
    result = forecast(config(), items, {"door": 1000.0}, free=1_000_000_000, now=NOW)
    triggers = {t["trigger"]: t for t in result["triggers"]}
    door = triggers["continuous"]["cameras"][0]
    assert door["basis"] == "measured"
    assert abs(door["per_day"] - 144_000_000) < 1_000_000
    assert triggers["manual"]["steady"] is None and triggers["manual"]["kept"]
    assert result["growing_per_day"] == triggers["manual"]["per_day"]
    # 1 GB free, continuous wants ~1.4 GB at its level: full in about 7 days.
    assert 5 < result["days_until_full"] < 8


def test_off_triggers_are_left_out() -> None:
    cfg = config()
    cfg.cameras["door"].record = "off"
    items = [rec("door", "continuous", h, 1000) for h in range(1, 5)]
    assert forecast(cfg, items, {}, free=None, now=NOW)["triggers"] == []


def test_limits() -> None:
    items = [rec("door", "continuous", h, 6_000_000) for h in range(1, 25)]
    cfg = config()
    cfg.recording.max_gb = 1.0
    result = forecast(cfg, items, {}, free=10**12, now=NOW, used=144_000_000)
    # 856 MB to go at ~144 MB a day; at its level it would need 1.3 GB more: the limit comes first.
    assert result["limit"] == 856_000_000 and 5 < result["days_until_limit"] < 7
    assert result["days_until_full"] is None


def test_a_timed_trigger_is_measured_from_its_own_first_recording() -> None:
    # Clips for a week, continuous only for the last two hours: 12 MB in 2 h is 144 MB a day.
    items = [rec("door", "motion", 144, 1000)] + [rec("door", "continuous", h, 6_000_000) for h in (1, 2)]
    triggers = {t["trigger"]: t for t in forecast(config(), items, {}, free=None, now=NOW)["triggers"]}
    assert abs(triggers["continuous"]["per_day"] - 144_000_000) < 1_000_000
