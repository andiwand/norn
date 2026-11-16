"""Logging: to the console, to a rotating file, and the last lines in memory for the web app.

Every line is scrubbed of credentials first: camera addresses carry them (rtsp://user:pass@),
and so do some error messages. The file is <config dir>/.norn/logs/norn.log by default
(NORN_LOG_FILE, or `off`), five files of 5 MB.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+(?::[^/@\s]*)?@", re.IGNORECASE)
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def scrub(text: str) -> str:
    """rtsp://admin:secret@host -> rtsp://***@host"""
    return CREDENTIALS.sub(r"\g<scheme>***@", text)


class Scrub(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.error" and record.levelno < logging.WARNING:
            record.name = "uvicorn"  # its normal messages, not errors
        message = record.getMessage()
        clean = scrub(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_text is None:
            record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
        return True


class Recent(logging.Handler):
    """The last log lines, for GET /api/logs."""

    def __init__(self, size: int = 2000) -> None:
        super().__init__()
        self.lines: deque[dict[str, Any]] = deque(maxlen=size)
        self.counter = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.counter += 1
        text = record.getMessage()
        if record.exc_text:
            text += "\n" + record.exc_text
        self.lines.append(
            {
                "id": self.counter,
                "time": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": text,
            }
        )

    def query(
        self, level: str = "INFO", after: int = 0, limit: int = 500, text: str = ""
    ) -> list[dict[str, Any]]:
        floor = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        needle = text.lower()
        found = [
            line
            for line in self.lines
            if line["id"] > after
            and logging.getLevelNamesMapping()[line["level"]] >= floor
            and (not needle or needle in line["message"].lower() or needle in line["logger"].lower())
        ]
        return found[-limit:]


recent = Recent()


def setup(level: str = "info", file: Path | None = None, access: bool = False) -> Path | None:
    """Console, file and memory; returns the log file, if there is one."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(FORMAT)
    scrubber = Scrub()
    console = logging.StreamHandler()
    handlers: list[logging.Handler] = [console, recent]
    if file is not None:
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    file, maxBytes=5_000_000, backupCount=4, encoding="utf-8"
                )
            )
        except OSError as e:
            file = None
            logging.getLogger("norn").warning("no log file: %s", e)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(scrubber)
        root.addHandler(handler)
    # uvicorn logs through the same handlers; one line per request only when asked for.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.INFO if access else logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per go2rtc call is noise
    logging.Formatter.converter = time.localtime
    return file
