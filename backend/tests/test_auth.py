"""Sign-in: off until the first user, then every request to /api needs a user, and the role
decides what they may change."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from norn.api import create_app
from norn.auth import check_password, device_name, hash_password
from norn.settings import Settings

ADMIN = {"name": "anna", "password": "correct horse"}


@pytest.fixture
def app(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def other(app: TestClient) -> TestClient:
    """A second browser on the same server (its own cookies)."""
    return TestClient(app.app)


def test_without_users_everything_is_open(app: TestClient) -> None:
    assert app.get("/api/auth").json() == {"enabled": False, "user": None}
    assert app.get("/api/cameras").status_code == 200
    assert app.get("/api/logs").status_code == 200


def test_the_first_user_turns_sign_in_on(app: TestClient, settings: Settings) -> None:
    r = app.post("/api/users/first", json=ADMIN)
    assert r.status_code == 201 and r.json() == {"name": "anna", "role": "admin"}
    assert (
        "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    )
    assert app.get("/api/auth").json() == {"enabled": True, "user": {"name": "anna", "role": "admin"}}
    # A stranger: no access, but the sign-in status and the page itself.
    stranger = other(app)
    assert stranger.get("/api/cameras").status_code == 401
    assert stranger.get("/api/auth").json() == {"enabled": True, "user": None}
    assert stranger.get("/api/health").status_code == 200
    assert stranger.post("/api/users/first", json={"name": "eve", "password": "12345678"}).status_code == 409
    with pytest.raises(WebSocketDisconnect) as closed, stranger.websocket_connect("/api/events"):
        pass
    assert closed.value.code == 4401
    # config.yaml has the hash, never the password; the settings don't show users at all.
    text = settings.config_path.read_text()
    assert "users:" in text and "correct horse" not in text and "scrypt$" in text
    assert "users" not in app.get("/api/settings").json()["values"]


def test_signing_in_and_out(app: TestClient) -> None:
    app.post("/api/users/first", json=ADMIN)
    phone = other(app)
    assert phone.post("/api/auth/login", json={**ADMIN, "password": "wrong"}).status_code == 401
    assert phone.post("/api/auth/login", json={"name": "nobody", "password": "x"}).status_code == 401
    assert phone.post("/api/auth/login", json={**ADMIN, "name": "Anna"}).status_code == 200  # any case
    assert phone.get("/api/cameras").status_code == 200
    devices = phone.get("/api/auth/sessions").json()
    assert len(devices) == 2 and sum(d["current"] for d in devices) == 1
    assert phone.post("/api/auth/logout").status_code == 204
    assert phone.get("/api/cameras").status_code == 401
    assert app.get("/api/cameras").status_code == 200  # the other device stays signed in


def test_guessing_is_slowed_down(app: TestClient) -> None:
    app.post("/api/users/first", json=ADMIN)
    guesser = other(app)
    for _ in range(5):
        assert guesser.post("/api/auth/login", json={**ADMIN, "password": "guess"}).status_code == 401
    # Locked now, even with the right password.
    assert guesser.post("/api/auth/login", json=ADMIN).status_code == 429


def test_a_viewer_watches_and_steers_but_changes_nothing(app: TestClient) -> None:
    app.post("/api/users/first", json=ADMIN)
    assert (
        app.post("/api/users", json={"name": "ben", "password": "viewer pass", "role": "viewer"}).status_code
        == 201
    )
    app.post("/api/cameras", json={"id": "door", "name": "Door", "driver": "demo"})
    viewer = other(app)
    viewer.post("/api/auth/login", json={"name": "ben", "password": "viewer pass"})
    assert viewer.get("/api/cameras").status_code == 200
    assert viewer.get("/api/recordings").status_code == 200
    assert viewer.put("/api/settings", json={"away": {"active": True}}).status_code == 200
    assert viewer.put("/api/settings", json={"recording": {"retention_days": 1}}).status_code == 403
    assert viewer.put("/api/cameras/door", json={"name": "Mine", "driver": "demo"}).status_code == 403
    assert viewer.delete("/api/cameras/door").status_code == 403
    assert viewer.get("/api/logs").status_code == 403
    assert viewer.get("/api/users").status_code == 403
    assert viewer.post("/api/users", json={"name": "eve", "password": "12345678"}).status_code == 403
    assert viewer.post("/api/cameras/door/ptz", json={"action": "stop"}).status_code != 403


def test_api_tokens_for_webhooks(app: TestClient) -> None:
    app.post("/api/users/first", json=ADMIN)
    r = app.post("/api/auth/tokens", json={"name": "Doorbell"})
    assert r.status_code == 201
    secret, token_id = r.json()["token"], r.json()["id"]
    assert secret.startswith("norn_")
    script = other(app)
    assert script.get("/api/cameras", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
    assert "token" not in app.get("/api/auth/tokens").json()[0]  # shown once only
    assert app.delete(f"/api/auth/tokens/{token_id}").status_code == 204
    assert script.get("/api/cameras", headers={"Authorization": f"Bearer {secret}"}).status_code == 401


def test_a_new_password_signs_out_the_other_devices(app: TestClient) -> None:
    app.post("/api/users/first", json=ADMIN)
    phone = other(app)
    phone.post("/api/auth/login", json=ADMIN)
    assert (
        app.put("/api/auth/password", json={"current": "wrong", "password": "new password"}).status_code
        == 403
    )
    assert (
        app.put("/api/auth/password", json={"current": ADMIN["password"], "password": "short"}).status_code
        == 422
    )
    assert (
        app.put(
            "/api/auth/password", json={"current": ADMIN["password"], "password": "new password"}
        ).status_code
        == 204
    )
    assert app.get("/api/cameras").status_code == 200  # this device stays
    assert phone.get("/api/cameras").status_code == 401


def test_norn_keeps_an_admin(app: TestClient) -> None:
    app.post("/api/users/first", json=ADMIN)
    app.post("/api/users", json={"name": "ben", "password": "viewer pass"})
    assert app.put("/api/users/anna", json={"role": "viewer"}).status_code == 409
    assert app.delete("/api/users/anna").status_code == 409
    assert app.put("/api/users/ben", json={"role": "admin"}).json()["role"] == "admin"
    assert app.put("/api/users/anna", json={"role": "viewer"}).status_code == 200
    assert (
        app.post("/api/users", json={"name": "Not Valid!", "password": "12345678"}).status_code == 403
    )  # a viewer now


def test_passwords_and_devices() -> None:
    stored = hash_password("secret pass")
    assert check_password("secret pass", stored) and not check_password("secret", stored)
    assert not check_password("x", "garbage")
    assert (
        device_name("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit Safari/604.1")
        == "Safari on iPhone"
    )
    assert (
        device_name("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/131.0 Safari/537.36")
        == "Chrome on Mac"
    )
    assert device_name("curl/8.7.1") == "curl"
