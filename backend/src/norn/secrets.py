"""Camera passwords never leave Norn through the API.

Responses leave out the options that are secrets (password, token, API key) and hide the
password in addresses (rtsp://user:•••@host). When a camera is saved, a secret left out (or
empty) and an address with the hidden password keep what config.yaml has.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SECRET = re.compile(r"pass|secret|token|api_?key", re.IGNORECASE)
HIDDEN = "•••"


def is_secret(key: str) -> bool:
    return bool(SECRET.search(key))


def hide_url(value: str) -> str:
    """rtsp://user:password@host/x -> rtsp://user:•••@host/x"""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.password:
        return value
    netloc = f"{parts.username}:{HIDDEN}@{parts.hostname or ''}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def public(options: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The options for a response, and the names of the secrets that are set."""
    shown, secrets = {}, []
    for key, value in options.items():
        if is_secret(key):
            if value:
                secrets.append(key)
        elif isinstance(value, str) and "://" in value:
            shown[key] = hide_url(value)
        else:
            shown[key] = value
    return shown, secrets


def keep(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """`new` options from a form, with the secrets it left out or hid taken from `old`."""
    merged = dict(new)
    for key, value in old.items():
        if is_secret(key) and not merged.get(key):
            merged[key] = value
        elif isinstance(value, str) and merged.get(key) == hide_url(value) != value:
            # The address came back with the password hidden: put the real one back. (An address
            # that changed otherwise is taken as typed.)
            merged[key] = value
    return merged
