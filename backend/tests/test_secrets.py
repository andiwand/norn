from __future__ import annotations

from fastapi.testclient import TestClient

from norn.secrets import hide_url, keep, public
from norn.settings import Settings


def test_public_and_keep() -> None:
    options = {
        "host": "10.0.0.2",
        "password": "s3cret",
        "api_key": "k",
        "url": "rtsp://admin:p%23w@cam:554/1",
    }
    shown, secrets = public(options)
    assert shown == {"host": "10.0.0.2", "url": "rtsp://admin:•••@cam:554/1"}
    assert secrets == ["password", "api_key"]
    # A form sends back what it got: the secrets come back from the config.
    assert keep(shown, options) == options
    # A new password, or a new address, is taken as given.
    assert keep({**shown, "password": "new"}, options)["password"] == "new"
    assert keep({"url": "rtsp://admin:other@cam2/1"}, options)["url"] == "rtsp://admin:other@cam2/1"
    assert hide_url("rtsp://cam/1") == "rtsp://cam/1"


def test_api_never_returns_passwords(client: TestClient, settings: Settings) -> None:
    body = {"id": "door", "name": "Door", "driver": "rtsp", "url": "rtsp://u:topsecret@cam/1"}
    created = client.post("/api/cameras", json=body).json()
    assert "topsecret" not in str(created) and created["options"]["url"] == "rtsp://u:•••@cam/1"
    assert "topsecret" not in client.get("/api/cameras").text
    # Saving the form as it came keeps the password.
    form = {"name": "Front door", "driver": "rtsp", **created["options"]}
    assert client.put("/api/cameras/door", json=form).status_code == 200
    assert "rtsp://u:topsecret@cam/1" in settings.config_path.read_text()
    assert "Front door" in settings.config_path.read_text()
