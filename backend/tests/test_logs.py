from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from norn import logs


def test_scrub() -> None:
    assert logs.scrub("rtsp://admin:p%23w@10.0.0.1:554/x") == "rtsp://***@10.0.0.1:554/x"
    assert logs.scrub("http://user@cam/a and rtsps://a:b@c/d") == "http://***@cam/a and rtsps://***@c/d"
    assert logs.scrub("no url here: a@b") == "no url here: a@b"


def test_file_memory_and_api(tmp_path: Path, client: TestClient) -> None:
    file = logs.setup("info", tmp_path / "logs" / "norn.log")
    logging.getLogger("norn.test").warning("camera at rtsp://admin:secret@10.0.0.9/stream fell over")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert file is not None and "rtsp://***@10.0.0.9" in file.read_text()
    assert "secret" not in file.read_text()
    lines = client.get("/api/logs", params={"level": "WARNING", "text": "fell over"}).json()["lines"]
    assert lines and "secret" not in lines[-1]["message"] and lines[-1]["level"] == "WARNING"
    newest = lines[-1]["id"]
    assert client.get("/api/logs", params={"after": newest, "text": "fell over"}).json()["lines"] == []
