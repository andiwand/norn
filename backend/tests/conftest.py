from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from norn.api import create_app
from norn.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # go2rtc off: the tests don't need video, so they don't need go2rtc or ffmpeg.
    return Settings(
        config_path=tmp_path / "config" / "config.yaml",
        recordings_path=tmp_path / "recordings",
        go2rtc_mode="off",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client
