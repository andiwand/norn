"""Run Norn: `norn` or `python -m norn`. Settings come from NORN_* environment variables."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from . import __version__
from .api import create_app
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="norn", description="All your home cameras in one place.")
    parser.add_argument("--version", action="version", version=f"norn {__version__}")
    parser.parse_args()

    settings = Settings.from_env()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per go2rtc call is noise
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        proxy_headers=True,
        ws_ping_interval=20,
    )


if __name__ == "__main__":
    main()
