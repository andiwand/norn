"""The HTTP API and the web UI.

Everything is under /api. The built web UI is served from / with a fallback to index.html, so
the client-side routes work on reload. Live video goes through /api/stream, a WebSocket that
forwards to go2rtc, so the browser only needs this one port (plus the WebRTC port for media).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import websockets
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketState

from . import __version__
from .config import CAMERA_ID, CameraConfig, ConfigError
from .drivers import DRIVERS, describe
from .drivers.base import Capability, DriverError, NotSupportedError, PtzCommand
from .go2rtc import Go2rtcUnavailableError
from .hub import Hub, stream_name
from .recordings import InvalidPathError
from .settings import Settings

log = logging.getLogger("norn.api")


class CameraBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    driver: str
    enabled: bool = True
    record: Literal["off", "continuous"] = "off"
    auto_update: bool = False


class NewCamera(CameraBody):
    id: str = Field(pattern=CAMERA_ID.pattern)


class ControlBody(BaseModel):
    value: Any = None


class RecordBody(BaseModel):
    trigger: str = Field("manual", pattern=r"^[a-z0-9-]{1,32}$")
    seconds: int | None = Field(None, ge=5, le=3600)


def default_static() -> Path | None:
    """The web UI bundled in the Python package (pip install), if it is there."""
    path = Path(str(resources.files("norn") / "web"))
    return path if (path / "index.html").is_file() else None


def create_app(settings: Settings, hub: Hub | None = None) -> FastAPI:
    hub = hub or Hub(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()

    app = FastAPI(title="Norn", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)  # fmt: skip
    app.state.hub = hub
    api = APIRouter(prefix="/api")

    def camera_or_404(camera_id: str) -> None:
        if camera_id not in hub.cameras:
            raise HTTPException(404, f"no camera {camera_id!r}")

    def driver_of(camera_id: str):
        camera_or_404(camera_id)
        try:
            return hub.get_driver(camera_id)
        except LookupError as e:
            raise HTTPException(409, str(e)) from e

    @api.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @api.get("/info")
    async def info() -> dict[str, Any]:
        return {
            "version": __version__,
            "config_error": hub.config_error,
            "config_path": str(settings.config_path),
            "go2rtc": await hub.go2rtc.info(),
            "recording_available": hub.recorder.available,
            "recording": hub.config.recording.model_dump(),
        }

    @api.get("/drivers")
    async def drivers() -> list[dict[str, Any]]:
        return [describe(cls) for cls in DRIVERS.values()]

    @api.get("/cameras")
    async def cameras() -> list[dict[str, Any]]:
        return [hub.camera_json(cid) for cid in hub.cameras]

    @api.post("/cameras", status_code=201)
    async def add_camera(body: NewCamera) -> dict[str, Any]:
        if body.id in hub.cameras:
            raise HTTPException(409, f"camera {body.id!r} exists")
        data = body.model_dump()
        camera_id = data.pop("id")
        try:
            await hub.put_camera(camera_id, CameraConfig.model_validate(data))
        except ConfigError as e:
            raise HTTPException(422, str(e)) from e
        return hub.camera_json(camera_id)

    @api.get("/cameras/{camera_id}")
    async def camera(camera_id: str) -> dict[str, Any]:
        camera_or_404(camera_id)
        return hub.camera_json(camera_id)

    @api.put("/cameras/{camera_id}")
    async def update_camera(camera_id: str, body: CameraBody) -> dict[str, Any]:
        camera_or_404(camera_id)
        try:
            await hub.put_camera(camera_id, CameraConfig.model_validate(body.model_dump()))
        except ConfigError as e:
            raise HTTPException(422, str(e)) from e
        return hub.camera_json(camera_id)

    @api.delete("/cameras/{camera_id}", status_code=204)
    async def delete_camera(camera_id: str) -> Response:
        camera_or_404(camera_id)
        await hub.remove_camera(camera_id)
        return Response(status_code=204)

    @api.get("/cameras/{camera_id}/snapshot")
    async def snapshot(camera_id: str, stream: str = "main") -> Response:
        driver = driver_of(camera_id)
        if stream not in {s.id for s in driver.streams()}:
            raise HTTPException(404, f"no stream {stream!r}")
        try:
            jpeg = await hub.go2rtc.frame(stream_name(camera_id, stream))
        except Go2rtcUnavailableError as e:
            raise HTTPException(503, str(e)) from e
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @api.post("/cameras/{camera_id}/device")
    async def refresh_device(camera_id: str) -> dict[str, Any]:
        """Read the camera's state and firmware now, instead of waiting for the next poll."""
        driver_of(camera_id)
        await hub.refresh_device(camera_id)
        return hub.camera_json(camera_id)

    @api.post("/cameras/{camera_id}/firmware")
    async def update_firmware(camera_id: str, request: Request) -> dict[str, Any]:
        """Install firmware: the request body is the firmware file. Empty: the driver's online update."""
        driver = driver_of(camera_id)
        image = await request.body()
        needed = Capability.FIRMWARE_UPLOAD if image else Capability.FIRMWARE_ONLINE
        if needed not in driver.capabilities():
            raise HTTPException(409, f"{driver.label} can't install firmware this way")
        try:
            await hub.update_firmware(camera_id, image or None)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        except Exception as e:
            raise HTTPException(502, f"the update failed: {e}") from e
        return hub.camera_json(camera_id)

    @api.get("/cameras/{camera_id}/controls")
    async def controls(camera_id: str) -> dict[str, Any]:
        driver = driver_of(camera_id)
        return {
            "controls": [c.model_dump(exclude_none=True) for c in await driver.controls()],
            "presets": [p.model_dump() for p in await driver.presets()],
        }

    @api.post("/cameras/{camera_id}/controls/{control_id}")
    async def set_control(camera_id: str, control_id: str, body: ControlBody) -> dict[str, Any]:
        driver = driver_of(camera_id)
        try:
            await driver.set_control(control_id, body.value)
        except NotSupportedError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"ok": True}

    @api.post("/cameras/{camera_id}/ptz")
    async def ptz(camera_id: str, command: PtzCommand) -> dict[str, Any]:
        driver = driver_of(camera_id)
        if Capability.PTZ not in driver.capabilities():
            raise HTTPException(409, f"{camera_id} cannot pan, tilt or zoom")
        try:
            await driver.ptz(command)
        except NotSupportedError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"ok": True}

    @api.post("/cameras/{camera_id}/record")
    async def record(camera_id: str, body: RecordBody | None = None) -> dict[str, Any]:
        """Start a clip. Also the webhook for triggers from elsewhere (Home Assistant, a doorbell, ...)."""
        driver_of(camera_id)
        body = body or RecordBody()
        try:
            clip = await hub.recorder.record_clip(camera_id, body.trigger, body.seconds)
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        return clip.to_json()

    @api.delete("/cameras/{camera_id}/record")
    async def stop_record(camera_id: str) -> dict[str, Any]:
        camera_or_404(camera_id)
        return {"stopped": await hub.recorder.stop_clip(camera_id)}

    @api.get("/recordings")
    async def recordings(
        camera: str | None = None, day: str | None = None, limit: int = Query(500, ge=1, le=5000)
    ) -> dict[str, Any]:
        try:
            items = await asyncio.to_thread(hub.library.list, camera, day, limit)
            days = hub.library.days(camera) if camera else []
        except InvalidPathError as e:
            raise HTTPException(400, str(e)) from e
        return {"recordings": [r.to_json() for r in items], "days": days}

    @api.get("/recordings/{camera}/{day}/{name}")
    async def recording_file(camera: str, day: str, name: str) -> FileResponse:
        try:
            path = hub.library.path(camera, day, name)
        except InvalidPathError as e:
            raise HTTPException(400, str(e)) from e
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)  # supports range requests, so the video can seek

    @api.delete("/recordings/{camera}/{day}/{name}", status_code=204)
    async def delete_recording(camera: str, day: str, name: str) -> Response:
        try:
            deleted = hub.library.delete(camera, day, name)
        except InvalidPathError as e:
            raise HTTPException(400, str(e)) from e
        if not deleted:
            raise HTTPException(404, "not found")
        hub.bus.publish("recording.deleted", {"id": f"{camera}/{day}/{name}"})
        return Response(status_code=204)

    @api.websocket("/events")
    async def events(ws: WebSocket) -> None:
        await ws.accept()
        async with hub.bus.subscribe() as queue:
            receiver = asyncio.create_task(_drain(ws))
            try:
                while not receiver.done():
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
                    if getter in done:
                        await ws.send_json(getter.result())
                    else:
                        getter.cancel()
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                receiver.cancel()

    @api.websocket("/stream")
    async def stream(ws: WebSocket, camera: str, stream: str = "main") -> None:
        """go2rtc's WebSocket (WebRTC signaling and MSE video), forwarded."""
        try:
            driver = hub.get_driver(camera)
        except (KeyError, LookupError):
            await ws.close(code=4404)
            return
        if stream not in {s.id for s in driver.streams()}:
            stream = "main"
        await ws.accept()
        try:
            async with websockets.connect(
                hub.go2rtc.ws_url(stream_name(camera, stream)), max_size=None, open_timeout=5
            ) as upstream:
                await _pipe(ws, upstream)
        except (OSError, websockets.WebSocketException) as e:
            log.info("stream %s/%s: %s", camera, stream, e)
        finally:
            if ws.application_state != WebSocketState.DISCONNECTED:
                with contextlib.suppress(RuntimeError):
                    await ws.close()

    app.include_router(api)

    @app.exception_handler(DriverError)
    async def driver_error(_request: Request, e: DriverError) -> JSONResponse:
        # The camera refused or didn't answer: a bad gateway, not a bug in Norn.
        return JSONResponse({"detail": str(e)}, status_code=502)

    @app.exception_handler(ConfigError)
    async def config_error(_request: Request, e: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=422)

    static = settings.static_path or default_static()
    if static and static.is_dir():
        mount_web(app, static)
    return app


def mount_web(app: FastAPI, root: Path) -> None:
    root = root.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404)
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            # Vite puts a hash into the names of these files, so they never change.
            immutable = "/_app/immutable/" in f"/{path}"
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return FileResponse(file, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


async def _drain(ws: WebSocket) -> None:
    """Read and drop what the client sends, to notice when it goes away."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            await ws.receive_text()


async def _pipe(ws: WebSocket, upstream: websockets.ClientConnection) -> None:
    async def down() -> None:
        async for message in upstream:
            if isinstance(message, bytes):
                await ws.send_bytes(message)
            else:
                await ws.send_text(message)

    async def up() -> None:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
