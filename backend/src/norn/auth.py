"""Sign-in: users with a role, signed-in devices (sessions) and API tokens.

Off until the first user exists (`users:` in config.yaml): Norn then trusts its network, as
before. Once there is a user, every request to /api needs one, at home too: behind a reverse
proxy every request comes from the proxy, so "the home network" can't be told apart safely.

- Users: `users: {name: {role: admin|viewer, password: <scrypt hash>}}` in config.yaml. The
  API never returns the hash. An admin changes everything; a viewer watches (live video,
  recordings), steers pan/tilt cameras, records a clip, keeps a recording, switches away mode,
  and manages their own devices and tokens.
- Sessions: a random token in an HttpOnly cookie, stored hashed in `.norn/sessions.json`, valid
  while used within SESSION_DAYS. Signing out or changing the password ends them.
- API tokens: for webhooks and scripts (`Authorization: Bearer <token>`), stored hashed in
  `.norn/tokens.json`, with their user's role.
- Failed sign-ins slow down: after a few, the name is locked for a while.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("norn.auth")

Role = Literal["admin", "viewer"]
COOKIE = "norn_session"
SESSION_DAYS = 30
SEEN_EVERY = 300  # seconds: how often a used session's "last seen" is written down
FAILURES = 5  # failed sign-ins for a name before it is locked
LOCK_SECONDS = 300
TOKEN_PREFIX = "norn_"

# scrypt: about 50 ms and 16 MB per check; enough against guessing, cheap on a Raspberry Pi.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        want = base64.b64decode(digest)
        got = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(want)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def check_new_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("the password needs at least 8 characters")
    if len(password) > 256:
        raise ValueError("the password is too long")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def device_name(agent: str) -> str:
    """ "Chrome on Mac", "Safari on iPhone": a signed-in device, from its browser."""
    agent = agent or ""
    os = next(
        (
            name
            for pattern, name in (
                (r"iPhone", "iPhone"),
                (r"iPad", "iPad"),
                (r"Android", "Android"),
                (r"Mac OS X|Macintosh", "Mac"),
                (r"Windows", "Windows"),
                (r"Linux", "Linux"),
            )
            if re.search(pattern, agent)
        ),
        "",
    )
    browser = next(
        (
            name
            for pattern, name in (
                (r"Edg/", "Edge"),
                (r"Firefox/|FxiOS", "Firefox"),
                (r"Chrome/|CriOS", "Chrome"),
                (r"Safari/", "Safari"),
                (r"curl/", "curl"),
                (r"python|httpx|aiohttp", "a script"),
            )
            if re.search(pattern, agent, re.I)
        ),
        "",
    )
    if browser and os:
        return f"{browser} on {os}"
    return browser or os or "Unknown device"


@dataclass
class Session:
    id: str  # a short public id (for the list of devices), not the token
    user: str
    created: float
    seen: float
    device: str


@dataclass
class Token:
    id: str
    user: str
    name: str
    created: float
    used: float | None = None


@dataclass
class Who:
    """Who makes a request: a user and their role, and how they signed in."""

    name: str
    role: Role
    session: str | None = None  # the session's id
    token: str | None = None  # the API token's id


@dataclass
class Auth:
    """Sessions and tokens, kept in files of the runtime folder; users come from the config."""

    folder: Path
    sessions: dict[str, Session] = field(default_factory=dict)  # by token digest
    tokens: dict[str, Token] = field(default_factory=dict)  # by token digest
    _failures: dict[str, tuple[int, float]] = field(default_factory=dict)  # name -> (count, until)
    _written: float = 0.0

    def __post_init__(self) -> None:
        self.sessions = {k: Session(**v) for k, v in self._read("sessions.json").items()}
        self.tokens = {k: Token(**v) for k, v in self._read("tokens.json").items()}
        self._expire()

    # Storage
    def _read(self, name: str) -> dict[str, Any]:
        try:
            data = json.loads((self.folder / name).read_text())
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError) as e:
            log.warning("%s: %s; starting empty", name, e)
            return {}

    def _write(self, name: str, data: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.chmod(0o600)
        tmp.replace(path)

    def _save(self) -> None:
        self._write("sessions.json", {k: vars(s) for k, s in self.sessions.items()})
        self._write("tokens.json", {k: vars(t) for k, t in self.tokens.items()})
        self._written = time.time()

    def _expire(self) -> None:
        old = time.time() - SESSION_DAYS * 86400
        self.sessions = {k: s for k, s in self.sessions.items() if s.seen >= old}

    # Signing in
    def locked(self, name: str) -> float:
        """Seconds until the name may try again (0: now)."""
        count, until = self._failures.get(name.lower(), (0, 0.0))
        return max(0.0, until - time.time()) if count >= FAILURES else 0.0

    def failed(self, name: str) -> None:
        count, _ = self._failures.get(name.lower(), (0, 0.0))
        self._failures[name.lower()] = (count + 1, time.time() + LOCK_SECONDS)

    def succeeded(self, name: str) -> None:
        self._failures.pop(name.lower(), None)

    def start_session(self, user: str, agent: str) -> str:
        """A new signed-in device; returns its secret token (for the cookie)."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.sessions[_digest(token)] = Session(
            id=secrets.token_hex(6), user=user, created=now, seen=now, device=device_name(agent)
        )
        self._expire()
        self._save()
        return token

    def end_session(self, token: str) -> None:
        if self.sessions.pop(_digest(token), None):
            self._save()

    def end_sessions(self, user: str, keep: str | None = None, session_id: str | None = None) -> int:
        """End a user's sessions: all, all but `keep` (a session id), or just `session_id`."""
        before = len(self.sessions)
        self.sessions = {
            k: s
            for k, s in self.sessions.items()
            if s.user != user or s.id == keep or (session_id is not None and s.id != session_id)
        }
        if len(self.sessions) != before:
            self._save()
        return before - len(self.sessions)

    def rename_user(self, old: str, new: str) -> None:
        for s in self.sessions.values():
            if s.user == old:
                s.user = new
        for t in self.tokens.values():
            if t.user == old:
                t.user = new
        self._save()

    def forget_user(self, user: str) -> None:
        self.sessions = {k: s for k, s in self.sessions.items() if s.user != user}
        self.tokens = {k: t for k, t in self.tokens.items() if t.user != user}
        self._save()

    # Tokens
    def new_token(self, user: str, name: str) -> tuple[Token, str]:
        secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = Token(
            id=secrets.token_hex(6), user=user, name=name.strip()[:60] or "Token", created=time.time()
        )
        self.tokens[_digest(secret)] = token
        self._save()
        return token, secret

    def remove_token(self, user: str | None, token_id: str) -> bool:
        for key, t in list(self.tokens.items()):
            if t.id == token_id and (user is None or t.user == user):
                del self.tokens[key]
                self._save()
                return True
        return False

    # Who is it
    def by_session(self, token: str) -> Session | None:
        session = self.sessions.get(_digest(token))
        if session is None:
            return None
        now = time.time()
        if now - session.seen > SESSION_DAYS * 86400:
            self.end_session(token)
            return None
        if now - session.seen > SEEN_EVERY:
            session.seen = now
            self._save()
        return session

    def by_token(self, secret: str) -> Token | None:
        token = self.tokens.get(_digest(secret))
        if token and (token.used is None or time.time() - token.used > SEEN_EVERY):
            token.used = time.time()
            self._save()
        return token


# What a viewer may do besides reading: (method, path pattern). Everything else that changes
# something is for admins. GET is open to every user except these (they show the whole system).
VIEWER_WRITES = [
    ("POST", r"/api/cameras/[^/]+/ptz"),
    ("POST", r"/api/cameras/[^/]+/presets/[^/]+/goto"),
    ("POST", r"/api/cameras/[^/]+/record"),
    ("DELETE", r"/api/cameras/[^/]+/record"),
    ("POST", r"/api/circles/[^/]+/record"),
    ("DELETE", r"/api/circles/[^/]+/record"),
    ("PUT", r"/api/recordings/[^/]+/[^/]+/[^/]+/pin"),
    ("PUT", r"/api/settings"),  # away mode only: the route checks the body
    ("POST", r"/api/auth/logout"),
    ("PUT", r"/api/auth/password"),
    ("DELETE", r"/api/auth/sessions/[^/]+"),
    ("POST", r"/api/auth/tokens"),
    ("DELETE", r"/api/auth/tokens/[^/]+"),
    ("POST", r"/api/push/.*"),
    ("PUT", r"/api/push/.*"),
    ("DELETE", r"/api/push/.*"),
]
ADMIN_READS = [r"/api/logs(/.*)?", r"/api/users", r"/api/discover(/.*)?"]
# Open without signing in: whether sign-in is on, signing in, and the app's health check.
PUBLIC = [
    ("GET", r"/api/health"),
    ("GET", r"/api/auth"),
    ("POST", r"/api/auth/login"),
    ("POST", r"/api/users/first"),
]


def _matches(rules: list[tuple[str, str]], method: str, path: str) -> bool:
    return any(m == method and re.fullmatch(p, path) for m, p in rules)


def is_public(method: str, path: str) -> bool:
    return _matches(PUBLIC, method, path)


def allowed(role: Role, method: str, path: str) -> bool:
    """May a user with this role make this request? (Signed in; checked by the middleware.)"""
    if role == "admin":
        return True
    if method in ("GET", "HEAD", "WS"):
        return not any(re.fullmatch(p, path) for p in ADMIN_READS)
    return _matches(VIEWER_WRITES, method, path)
