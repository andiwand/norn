"""Sign-in over the API: the middleware that guards /api, and the routes for signing in, the
users, the signed-in devices and the API tokens. See auth.py."""

from __future__ import annotations

import json
import logging
import re
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import (
    COOKIE,
    SESSION_DAYS,
    TOKEN_PREFIX,
    Auth,
    Who,
    allowed,
    check_new_password,
    check_password,
    hash_password,
    is_public,
)
from .config import CAMERA_ID, UserConfig

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from .hub import Hub

log = logging.getLogger("norn.auth")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=64)
    password: str = Field(max_length=256)


class FirstUserBody(LoginBody):
    pass


class NewUserBody(LoginBody):
    role: Literal["admin", "viewer"] = "viewer"


class UserChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "viewer"] | None = None
    password: str | None = Field(None, max_length=256)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: str = Field(max_length=256)
    password: str = Field(max_length=256)


class TokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=60)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def identify(auth: Auth, hub: Hub, scope: Scope) -> Who | None:
    """The user a request comes from: by its session cookie or an API token."""
    users = hub.config.users
    bearer = _header(scope, b"authorization")
    if bearer.lower().startswith("bearer "):
        secret = bearer[7:].strip()
        token = auth.by_token(secret) if secret.startswith(TOKEN_PREFIX) else None
        user = users.get(token.user) if token else None
        return Who(token.user, user.role, token=token.id) if token and user else None
    cookie = SimpleCookie()
    try:
        cookie.load(_header(scope, b"cookie"))
    except Exception:
        return None
    if COOKIE not in cookie:
        return None
    session = auth.by_session(cookie[COOKIE].value)
    user = users.get(session.user) if session else None
    return Who(session.user, user.role, session=session.id) if session and user else None


class AuthMiddleware:
    """Every request to /api needs a signed-in user once users exist (WebSockets too), and the
    user's role must allow it. The web app's files stay open: they show the sign-in page."""

    def __init__(self, app: ASGIApp, auth: Auth, hub: Hub) -> None:
        self.app, self.auth, self.hub = app, auth, hub

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not scope["path"].startswith("/api"):
            return await self.app(scope, receive, send)
        method = "WS" if scope["type"] == "websocket" else scope["method"]
        path = scope["path"].rstrip("/") or "/"
        who = identify(self.auth, self.hub, scope) if self.hub.config.users else None
        scope.setdefault("state", {})["who"] = who
        if not self.hub.config.users or is_public(method, path):
            return await self.app(scope, receive, send)
        if who is None or not allowed(who.role, method, path):
            status, detail = (401, "Sign in first") if who is None else (403, "Only an admin may do this")
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4000 + status})
                return
            body = json.dumps({"detail": detail}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def who_of(request: Request) -> Who | None:
    return getattr(request.state, "who", None)


def _https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or proto == "https"


def _set_cookie(request: Request, response: Response, token: str) -> None:
    # Strict: no other site's page can make requests (or open WebSockets) with it; the app's
    # own requests are same-site, so they carry it.
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=_https(request),
        path="/",
    )


def _session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def router(auth: Auth, hub: Hub) -> APIRouter:
    api = APIRouter(prefix="/api")

    def me(request: Request) -> Who:
        who = who_of(request)
        if who is None:
            raise HTTPException(401, "Sign in first")
        return who

    def admins() -> list[str]:
        return [n for n, u in hub.config.users.items() if u.role == "admin"]

    def user_json(name: str, user: UserConfig, who: Who | None) -> dict[str, Any]:
        return {
            "name": name,
            "role": user.role,
            "devices": sum(1 for s in auth.sessions.values() if s.user == name),
            "tokens": sum(1 for t in auth.tokens.values() if t.user == name),
            "you": who is not None and who.name == name,
        }

    @api.get("/auth")
    async def status(request: Request) -> dict[str, Any]:
        """Whether sign-in is on, and who is signed in here."""
        who = who_of(request)
        return {
            "enabled": bool(hub.config.users),
            "user": {"name": who.name, "role": who.role} if who else None,
        }

    @api.post("/auth/login")
    async def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        name = body.name.strip().lower()
        if wait := auth.locked(name):
            raise HTTPException(429, f"Too many tries: wait {int(wait // 60) + 1} min and try again")
        user = hub.config.users.get(name)
        # The hash is checked also for unknown names, so the time doesn't tell which exist.
        ok = check_password(body.password, user.password if user else _DUMMY)
        if not (ok and user):
            auth.failed(name)
            log.warning("failed sign-in for %r", name)
            raise HTTPException(401, "Wrong name or password")
        auth.succeeded(name)
        _set_cookie(request, response, auth.start_session(name, request.headers.get("user-agent", "")))
        log.info("%s signed in", name)
        return {"name": name, "role": user.role}

    @api.post("/auth/logout", status_code=204)
    async def logout(request: Request, response: Response) -> None:
        if token := _session_token(request):
            auth.end_session(token)
        response.delete_cookie(COOKIE, path="/")

    @api.put("/auth/password", status_code=204)
    async def change_password(body: PasswordBody, request: Request) -> None:
        who = me(request)
        user = hub.config.users[who.name]
        if not check_password(body.current, user.password):
            raise HTTPException(403, "The current password is wrong")
        await set_password(who.name, body.password, keep=who.session)

    async def set_password(name: str, password: str, keep: str | None) -> None:
        try:
            check_new_password(password)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        user = hub.config.users[name]
        await hub.put_user(name, user.model_copy(update={"password": hash_password(password)}))
        auth.end_sessions(name, keep=keep)  # the other devices sign in again

    @api.get("/auth/sessions")
    async def sessions(request: Request) -> list[dict[str, Any]]:
        who = me(request)
        return [
            {
                "id": s.id,
                "device": s.device,
                "created": s.created,
                "seen": s.seen,
                "current": s.id == who.session,
            }
            for s in sorted(auth.sessions.values(), key=lambda s: -s.seen)
            if s.user == who.name
        ]

    @api.delete("/auth/sessions/{session_id}", status_code=204)
    async def end_session(session_id: str, request: Request) -> None:
        who = me(request)
        if not auth.end_sessions(who.name, session_id=session_id):
            raise HTTPException(404, "no such device")

    @api.get("/auth/tokens")
    async def tokens(request: Request) -> list[dict[str, Any]]:
        who = me(request)
        return [
            {"id": t.id, "name": t.name, "created": t.created, "used": t.used}
            for t in auth.tokens.values()
            if t.user == who.name
        ]

    @api.post("/auth/tokens", status_code=201)
    async def new_token(body: TokenBody, request: Request) -> dict[str, Any]:
        who = me(request)
        token, secret = auth.new_token(who.name, body.name)
        # The secret is shown once; Norn keeps only its hash.
        return {"id": token.id, "name": token.name, "created": token.created, "used": None, "token": secret}

    @api.delete("/auth/tokens/{token_id}", status_code=204)
    async def remove_token(token_id: str, request: Request) -> None:
        who = me(request)
        if not auth.remove_token(who.name, token_id):
            raise HTTPException(404, "no such token")

    # Users (admins only: the middleware checks; the first user is open while there is none).
    def valid_name(name: str) -> str:
        name = name.strip().lower()
        if not CAMERA_ID.fullmatch(name) or len(name) > 32:
            raise HTTPException(422, "The name: lowercase letters, digits and dashes, like anna or jo-2")
        return name

    @api.get("/users")
    async def users(request: Request) -> list[dict[str, Any]]:
        who = who_of(request)
        return [user_json(n, u, who) for n, u in hub.config.users.items()]

    @api.post("/users/first", status_code=201)
    async def first_user(body: FirstUserBody, request: Request, response: Response) -> dict[str, Any]:
        """The first user turns sign-in on: an admin, signed in here at once."""
        if hub.config.users:
            raise HTTPException(409, "There are users already: an admin adds more")
        name = valid_name(body.name)
        try:
            check_new_password(body.password)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        await hub.put_user(name, UserConfig(role="admin", password=hash_password(body.password)))
        _set_cookie(request, response, auth.start_session(name, request.headers.get("user-agent", "")))
        log.info("sign-in is on: %s is the first admin", name)
        return {"name": name, "role": "admin"}

    @api.post("/users", status_code=201)
    async def add_user(body: NewUserBody, request: Request) -> dict[str, Any]:
        name = valid_name(body.name)
        if name in hub.config.users:
            raise HTTPException(409, f"There is a user {name!r} already")
        try:
            check_new_password(body.password)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        user = UserConfig(role=body.role, password=hash_password(body.password))
        await hub.put_user(name, user)
        return user_json(name, user, who_of(request))

    @api.put("/users/{name}")
    async def change_user(name: str, body: UserChangeBody, request: Request) -> dict[str, Any]:
        user = hub.config.users.get(name)
        if user is None:
            raise HTTPException(404, f"no user {name!r}")
        if body.role == "viewer" and user.role == "admin" and admins() == [name]:
            raise HTTPException(409, "Norn needs an admin: make someone else an admin first")
        if body.role:
            await hub.put_user(name, user.model_copy(update={"role": body.role}))
        if body.password:
            who = who_of(request)
            await set_password(name, body.password, keep=who.session if who and who.name == name else None)
        return user_json(name, hub.config.users[name], who_of(request))

    @api.delete("/users/{name}", status_code=204)
    async def remove_user(name: str) -> None:
        user = hub.config.users.get(name)
        if user is None:
            raise HTTPException(404, f"no user {name!r}")
        if user.role == "admin" and admins() == [name] and len(hub.config.users) > 1:
            raise HTTPException(409, "Norn needs an admin: make someone else an admin first")
        await hub.remove_user(name)
        auth.forget_user(name)
        # Their phones get no more notifications.
        for device in [d for d in hub.notifier.store.devices.values() if d.user == name]:
            hub.notifier.store.remove(device.id)
        if not hub.config.users:
            log.warning("the last user is gone: sign-in is off, Norn trusts its network again")

    return api


# A hash to check against for unknown names (its password is random and never used).
_DUMMY = hash_password(re.sub(r"\W", "", __name__) + "-not-a-password")
