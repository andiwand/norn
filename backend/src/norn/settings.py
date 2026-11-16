"""Process settings from environment variables.

Everything a user configures about cameras and recording lives in config.yaml (see config.py).
These settings only say where things are and how the process runs, so they come from the
environment, which is what Docker and compose expect.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

Go2rtcMode = Literal["managed", "external", "off"]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def default_buffer() -> str:
    """A folder in RAM: /dev/shm on Linux, if it is big enough (Docker gives 64 MB unless
    `shm_size` says more). Else a folder beside the temporary storage, on disk."""
    shm = Path("/dev/shm")
    try:
        big = shutil.disk_usage(shm).total >= 128_000_000 and os.access(shm, os.W_OK)
    except OSError:
        big = False
    if big:
        return str(shm / "norn")
    return str(Path(_env("NORN_TEMP", "data/tmp")).with_name("buffer"))


def _log_file(config: Path) -> Path | None:
    value = os.environ.get("NORN_LOG_FILE", "").strip()
    if value.lower() in ("off", "none", "0", "false"):
        return None
    return Path(value) if value else config.parent / ".norn" / "logs" / "norn.log"


@dataclass(frozen=True)
class Settings:
    config_path: Path = Path("data/config/config.yaml")
    recordings_path: Path = Path("data/recordings")
    # The three storage stages: the pre-recording buffer in RAM (a tmpfs), the temporary storage
    # that recordings are written to, and the recordings folder they move to when finished.
    buffer_path: Path = Path("data/buffer")
    temp_path: Path = Path("data/tmp")
    static_path: Path | None = None
    host: str = "0.0.0.0"
    port: int = 8000
    # managed: Norn starts go2rtc itself; external: go2rtc runs elsewhere; off: no video (tests)
    go2rtc_mode: Go2rtcMode = "managed"
    go2rtc_bin: str = "go2rtc"
    go2rtc_api: str = "http://127.0.0.1:1984"
    go2rtc_rtsp: str = "rtsp://127.0.0.1:8554"
    # Serve the RTSP streams on every network interface, for Home Assistant and other players.
    rtsp_share: bool = False
    webrtc_port: int = 8555
    ffmpeg_bin: str = "ffmpeg"
    log_level: str = "info"
    log_file: Path | None = None  # None: no file
    access_log: bool = False  # one line per HTTP request

    @property
    def rtsp_port(self) -> int:
        return urlsplit(self.go2rtc_rtsp).port or 554

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
            buffer_path=Path(_env("NORN_BUFFER", default_buffer())),
            temp_path=Path(_env("NORN_TEMP", "data/tmp")),
            static_path=Path(static) if static else None,
            host=_env("NORN_HOST", "0.0.0.0"),
            port=int(_env("NORN_PORT", "8000")),
            go2rtc_mode=mode,  # type: ignore[arg-type]
            go2rtc_bin=_env("NORN_GO2RTC_BIN", "go2rtc"),
            go2rtc_api=_env("NORN_GO2RTC_API", "http://127.0.0.1:1984").rstrip("/"),
            go2rtc_rtsp=_env("NORN_GO2RTC_RTSP", "rtsp://127.0.0.1:8554").rstrip("/"),
            rtsp_share=_env("NORN_RTSP_SHARE", "0").lower() in ("1", "true", "yes"),
            webrtc_port=int(_env("NORN_WEBRTC_PORT", "8555")),
            ffmpeg_bin=_env("NORN_FFMPEG", "ffmpeg"),
            log_level=_env("NORN_LOG_LEVEL", "info").lower(),
            log_file=_log_file(Path(_env("NORN_CONFIG", "data/config/config.yaml"))),
            access_log=_env("NORN_ACCESS_LOG", "0").lower() in ("1", "true", "yes"),
        )
