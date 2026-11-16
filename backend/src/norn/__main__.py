"""Run Norn: `norn` or `python -m norn`. Settings come from NORN_* environment variables."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from . import __version__, logs
from .api import create_app
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="norn", description="All your home cameras in one place.")
    parser.add_argument("--version", action="version", version=f"norn {__version__}")
    parser.parse_args()

    settings = Settings.from_env()
    file = logs.setup(settings.log_level, settings.log_file, settings.access_log)
    logging.getLogger("norn").info("logging to the console%s", f" and {file}" if file else "")
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_config=None,  # logs.setup made the handlers
        access_log=settings.access_log,
        proxy_headers=True,
        ws_ping_interval=20,
    )


if __name__ == "__main__":
    main()
