"""Frames of recordings for scrubbing the timeline."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from norn.settings import Settings

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def test_a_frame_of_a_video(client: TestClient, settings: Settings) -> None:
    folder = settings.recordings_path / "demo" / "2026-11-16"
    folder.mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
         "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(folder / "12-00-00_manual.mp4")],
        check=True,
    )  # fmt: skip
    url = "/api/recordings/demo/2026-11-16/12-00-00_manual.mp4/frame"
    hub = client.app.state.hub  # type: ignore[attr-defined]
    response = client.get(url, params={"at": 1.5})
    assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"
    assert client.get(url, params={"at": 1.5}).content == response.content
    assert len(hub._frames) == 1  # the second came from the cache
    assert client.get(url, params={"at": 60}).status_code == 404  # past its end
    assert client.get("/api/recordings/demo/2026-11-16/13-00-00_manual.mp4/frame").status_code == 404
