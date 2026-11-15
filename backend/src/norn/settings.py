"""Process settings from environment variables.

Everything a user configures about cameras and recording lives in config.yaml (see config.py).
These settings only say where things are and how the process runs, so they come from the
environment, which is what Docker and compose expect.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Go2rtcMode = Literal["managed", "external", "off"]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    config_path: Path = Path("data/config/config.yaml")
    recordings_path: Path = Path("data/recordings")
    static_path: Path | None = None
    host: str = "0.0.0.0"
    port: int = 8000
    # managed: Norn starts go2rtc itself; external: go2rtc runs elsewhere; off: no video (tests)
    go2rtc_mode: Go2rtcMode = "managed"
    go2rtc_bin: str = "go2rtc"
    go2rtc_api: str = "http://127.0.0.1:1984"
    go2rtc_rtsp: str = "rtsp://127.0.0.1:8554"
    webrtc_port: int = 8555
    ffmpeg_bin: str = "ffmpeg"
    log_level: str = "info"

    @property
    def runtime_dir(self) -> Path:
        """Files Norn generates for itself (the go2rtc config). Not meant to be edited."""
        return self.config_path.parent / ".norn"

    @classmethod
    def from_env(cls) -> Settings:
        mode = _env("NORN_GO2RTC", "managed")
        if mode not in ("managed", "external", "off"):
            raise ValueError(f"NORN_GO2RTC must be managed, external or off, not {mode!r}")
        static = os.environ.get("NORN_STATIC", "").strip()
        return cls(
            config_path=Path(_env("NORN_CONFIG", "data/config/config.yaml")),
            recordings_path=Path(_env("NORN_RECORDINGS", "data/recordings")),
            static_path=Path(static) if static else None,
            host=_env("NORN_HOST", "0.0.0.0"),
            port=int(_env("NORN_PORT", "8000")),
            go2rtc_mode=mode,  # type: ignore[arg-type]
            go2rtc_bin=_env("NORN_GO2RTC_BIN", "go2rtc"),
            go2rtc_api=_env("NORN_GO2RTC_API", "http://127.0.0.1:1984").rstrip("/"),
            go2rtc_rtsp=_env("NORN_GO2RTC_RTSP", "rtsp://127.0.0.1:8554").rstrip("/"),
            webrtc_port=int(_env("NORN_WEBRTC_PORT", "8555")),
            ffmpeg_bin=_env("NORN_FFMPEG", "ffmpeg"),
            log_level=_env("NORN_LOG_LEVEL", "info").lower(),
        )
