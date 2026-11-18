"""What Norn sends to a push service, decrypted like a browser would: no network."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, ClassVar

import http_ece
import pytest
import pywebpush
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from norn.config import NotificationSettings
from norn.notify import Notifier


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


async def test_messages_are_encrypted_for_the_browser_and_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The message encrypted for the browser's keys (RFC 8291, aes128gcm), with a VAPID token
    signed with Norn's key (RFC 8292). Decrypted here with the browser's private key."""
    browser = ec.generate_private_key(ec.SECP256R1())
    raw = browser.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    posted: dict[str, Any] = {}

    class Response:
        status_code = 201
        text = ""
        headers: ClassVar[dict[str, str]] = {}

    def post(url: str, data: bytes, headers: dict[str, str], timeout: Any = None) -> Response:
        posted.update(url=url, data=data, headers=headers)
        return Response()

    monkeypatch.setattr(pywebpush.requests, "post", post)
    n = Notifier(tmp_path, NotificationSettings, lambda c: asyncio.sleep(0, None))
    keys = {"p256dh": b64(raw), "auth": b64(auth)}
    n.store.add("https://fcm.googleapis.com/fcm/send/q", keys, "Phone", None)
    assert await n.test(list(n.store.devices.values())) == 1
    assert posted["url"] == "https://fcm.googleapis.com/fcm/send/q"
    message = json.loads(http_ece.decrypt(posted["data"], private_key=browser, auth_secret=auth))
    assert message["title"] == "Norn" and message["tag"] == "norn-test"
    assert posted["headers"]["Urgency"] == "high" and str(posted["headers"]["TTL"]) == "3600"
    token = posted["headers"]["Authorization"]
    assert token.startswith("vapid t=") and f"k={n.public_key}" in token
