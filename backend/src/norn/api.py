"""The HTTP API and the web UI.

Everything is under /api. The built web UI is served from / with a fallback to index.html, so
the client-side routes work on reload. Live video goes through /api/stream, a WebSocket that
forwards to go2rtc, so the browser only needs this one port (plus the WebRTC port for media).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import websockets
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.websockets import WebSocketState

from . import __version__, logs
from .config import (
    CAMERA_ID,
    AwaySettings,
    CameraConfig,
    CircleConfig,
    ConfigError,
    DetectionSettings,
    FirmwareSettings,
    RecordingSettings,
)
from .detect import MODELS
from .drivers import DRIVERS, describe
from .drivers.base import Capability, DriverError, NotSupportedError, PtzCommand
from .go2rtc import Go2rtcUnavailableError
from .hub import Hub, stream_name
from .labels import describe as describe_labels
from .recorder import RESERVED
from .recordings import InvalidPathError
from .secrets import keep as keep_secrets
from .settings import Settings

log = logging.getLogger("norn.api")


class CameraBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    driver: str
    enabled: bool = True
    record: Literal["off", "continuous"] = "off"
    auto_update: bool = False
    picture_seconds: int | None = None
    prebuffer_seconds: int | None = None
    triggers: list[str] | None = None
    schedule: list[dict[str, Any]] | None = None
    detection: dict[str, Any] | None = None
    streams: list[str] | None = None
    presets: dict[str, Any] | None = None
    patrol: dict[str, Any] | None = None
    reactions: list[dict[str, Any]] | None = None
    follow: str | None = None


class NewCamera(CameraBody):
    id: str = Field(pattern=CAMERA_ID.pattern)


class NewCircle(CircleConfig):
    id: str = Field(pattern=CAMERA_ID.pattern)


class SettingsBody(BaseModel):
    """The global settings the web app edits. Sections left out stay as they are."""

    model_config = ConfigDict(extra="forbid")

    recording: RecordingSettings | None = None
    firmware: FirmwareSettings | None = None
    away: AwaySettings | None = None
    detection: DetectionSettings | None = None


class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    slot: str | None = None  # the camera's preset slot; None: the preset's, or a free one
    controls: list[str] = []  # controls whose current values the preset applies


class OrderBody(BaseModel):
    ids: list[str]


class PinBody(BaseModel):
    pinned: bool = True


class ControlBody(BaseModel):
    value: Any = None


class RecordBody(BaseModel):
    trigger: str = Field("manual", pattern=r"^[a-z0-9-]{1,32}$")
    seconds: int | None = Field(None, ge=5, le=3600)

    @field_validator("trigger")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED:
            raise ValueError(f"{value!r} is a trigger Norn uses itself")
        return value


OPTIONAL_LISTS = ("presets", "reactions", "follow")


def camera_config(data: dict[str, Any]) -> CameraConfig:
    """A camera from an API body; the config's own checks fail as a 422 (ConfigError)."""
    # Left out (null): the defaults (no presets, patrol, reactions; following off).
    data = {k: v for k, v in data.items() if not (k in OPTIONAL_LISTS and v is None)}
    try:
        return CameraConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(
            "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        ) from e


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
            # The server's clock, which schedules and away times follow.
            "time": {
                "zone": time.tzname[time.localtime().tm_isdst > 0],
                "offset_minutes": round(datetime.now().astimezone().utcoffset().total_seconds() / 60),
            },
            "config_path": str(settings.config_path),
            "go2rtc": await hub.go2rtc.info(),
            "recording_available": hub.recorder.available,
            "recording": hub.config.recording.model_dump(by_alias=True),
            "detection": {
                **hub.config.detection.model_dump(),
                "objects_unavailable": hub.detectors.unavailable,
                "models": {name: m.label for name, m in MODELS.items()},
            },
            "away": {"now": hub.away, **hub.config.away.model_dump()},
        }

    def settings_json() -> dict[str, Any]:
        sections = {name: getattr(hub.config, name) for name in SettingsBody.model_fields}
        return {
            "values": {name: value.model_dump(by_alias=True) for name, value in sections.items()},
            "defaults": {name: type(value)().model_dump(by_alias=True) for name, value in sections.items()},
        }

    @api.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return settings_json()

    @api.put("/settings")
    async def put_settings(body: SettingsBody) -> dict[str, Any]:
        # Fields left out keep their value, instead of falling back to the default.
        sections = {
            name: type(value).model_validate(
                {
                    **getattr(hub.config, name).model_dump(by_alias=True),
                    **value.model_dump(exclude_unset=True, by_alias=True),
                }
            )
            for name, value in body
            if value is not None
        }
        await hub.put_settings(sections)
        return settings_json()

    @api.get("/labels")
    async def labels() -> list[dict[str, Any]]:
        """What cameras detect, under Norn's names: the event kinds that triggers use."""
        return describe_labels()

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
            await hub.put_camera(camera_id, camera_config(data))
        except ConfigError as e:
            raise HTTPException(422, str(e)) from e
        return hub.camera_json(camera_id)

    @api.put("/cameras/order")
    async def order_cameras(body: OrderBody) -> list[dict[str, Any]]:
        """Arrange the cameras: their order in config.yaml, which the app shows."""
        await hub.order_cameras(body.ids)
        return [hub.camera_json(cid) for cid in hub.cameras]

    @api.get("/cameras/{camera_id}")
    async def camera(camera_id: str) -> dict[str, Any]:
        camera_or_404(camera_id)
        return hub.camera_json(camera_id)

    @api.put("/cameras/{camera_id}")
    async def update_camera(camera_id: str, body: CameraBody) -> dict[str, Any]:
        camera_or_404(camera_id)
        data = body.model_dump()
        # What the body leaves out (null) of the pan/tilt setup stays as it is: forms that edit
        # other things don't send it.
        current = hub.cameras[camera_id].config
        keep = current.model_dump(include={"presets", "patrol", "reactions", "follow"}, by_alias=True)
        data |= {key: value for key, value in keep.items() if data.get(key) is None}
        # Passwords the form didn't send (it never gets them) stay as they are.
        options = {k: v for k, v in data.items() if k not in CameraConfig.model_fields}
        data |= keep_secrets(options, current.options)
        try:
            await hub.put_camera(camera_id, camera_config(data))
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
        driver_of(camera_id)
        if stream not in hub.stream_ids(camera_id):
            raise HTTPException(404, f"no stream {stream!r}")
        try:
            jpeg = await hub.go2rtc.frame(stream_name(camera_id, stream))
        except Go2rtcUnavailableError as e:
            raise HTTPException(503, str(e)) from e
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @api.get("/cameras/{camera_id}/still.jpg")
    async def still(camera_id: str, max_age: float = Query(15, ge=0, le=3600)) -> Response:
        """The camera's newest still, at once: from a running still stream if it has one that
        recent, else a frame from go2rtc. For a picture to show before the video plays."""
        driver_of(camera_id)
        jpeg = await hub.still_jpeg(camera_id, max_age)
        if jpeg is None:
            raise HTTPException(503, "no picture of the camera right now")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @api.get("/cameras/{camera_id}/stills")
    async def stills(
        camera_id: str,
        every: float = Query(1, ge=0.5, le=60),
        mode: Literal["keyframe", "live"] = "keyframe",
    ) -> StreamingResponse:
        """The camera as a stream of stills (MJPEG: an <img> shows it). Light on the network and
        the CPU; the stream idles when nobody watches."""
        driver_of(camera_id)
        stream = hub.still_stream(hub.cameras[camera_id], mode)

        async def parts() -> AsyncIterator[bytes]:
            async with stream.subscribe("jpeg", every) as sub:
                async for jpeg in sub:
                    head = f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n"
                    yield head.encode() + jpeg + b"\r\n"

        return StreamingResponse(
            parts(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    @api.post("/cameras/{camera_id}/streams/probe")
    async def probe(camera_id: str) -> dict[str, Any]:
        """Find out again which of the camera's streams work, and whether at the same time."""
        driver_of(camera_id)
        try:
            await hub.probe_streams(camera_id)
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        return hub.camera_json(camera_id)

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
    async def controls(camera_id: str, fresh: bool = False) -> dict[str, Any]:
        """The controls and presets. From a cache that the hub keeps warm; `fresh` reads the camera."""
        driver_of(camera_id)
        if fresh:
            await hub.refresh_controls(camera_id)
        controls, presets = await hub.get_controls(camera_id)
        return {
            "controls": [c.model_dump(exclude_none=True) for c in controls],
            "presets": [p.model_dump() for p in presets],
        }

    @api.post("/cameras/{camera_id}/controls/{control_id}")
    async def set_control(camera_id: str, control_id: str, body: ControlBody) -> dict[str, Any]:
        driver = driver_of(camera_id)
        try:
            await driver.set_control(control_id, body.value)
            hub.remember_control(camera_id, control_id, body.value)
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
        if pilot := hub.pilots.get(camera_id):
            pilot.manual()  # someone steers: a patrol waits
            pilot.moved(command)
        return {"ok": True}

    @api.put("/cameras/{camera_id}/presets/{preset_id}")
    async def save_preset(camera_id: str, preset_id: str, body: PresetBody) -> dict[str, Any]:
        """Save what the camera shows now as a Norn preset (into a camera preset slot), with the
        current values of `controls` and a picture."""
        driver = driver_of(camera_id)
        if Capability.PRESET_SAVE not in driver.capabilities():
            raise HTTPException(409, "this camera can't save presets")
        try:
            preset = await hub.save_preset(camera_id, preset_id, body.name, body.slot, body.controls)
        except NotSupportedError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"id": preset_id, **preset.model_dump()}

    @api.delete("/cameras/{camera_id}/presets/{preset_id}", status_code=204)
    async def remove_preset(camera_id: str, preset_id: str) -> Response:
        camera_or_404(camera_id)
        try:
            await hub.remove_preset(camera_id, preset_id)
        except KeyError as e:
            raise HTTPException(404, f"no preset {preset_id!r}") from e
        return Response(status_code=204)

    @api.post("/cameras/{camera_id}/presets/{preset_id}/goto")
    async def goto_preset(camera_id: str, preset_id: str) -> dict[str, Any]:
        """Go to a Norn preset: its view, then its settings. A patrol waits a while."""
        driver_of(camera_id)
        pilot = hub.pilots[camera_id]
        try:
            await pilot.goto(preset_id)
        except KeyError as e:
            raise HTTPException(404, f"no preset {preset_id!r}") from e
        pilot.manual()
        return {"ok": True}

    @api.get("/cameras/{camera_id}/presets/{preset_id}.jpg")
    async def preset_picture(camera_id: str, preset_id: str) -> FileResponse:
        camera_or_404(camera_id)
        if not CAMERA_ID.match(preset_id):
            raise HTTPException(400, "bad preset id")
        path = hub.pilots[camera_id].picture(preset_id)
        if not path.is_file():
            raise HTTPException(404, "no picture")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

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
        camera: str | None = None,
        day: str | None = None,
        limit: int = Query(500, ge=1, le=20000),
        since: datetime | None = None,
        until: datetime | None = None,
        kind: Literal["video", "picture"] | None = None,
        trigger: str | None = Query(None, pattern=r"^[a-z0-9-]{1,32}$"),
        pictures: int | None = Query(None, ge=1, le=5000),
    ) -> dict[str, Any]:
        """Recordings, newest first. `since`/`until` (ISO times) keep the ones that overlap the
        range; `trigger` filters (`clips`: videos a trigger started); `pictures` thins pictures to
        about that many per camera. `truncated` says that `limit` cut the list."""
        args = (camera, day, limit + 1, _local(since), _local(until), kind, trigger, pictures)
        try:
            items = await asyncio.to_thread(hub.library.list, *args)
            # What is being recorded right now: the continuous files in the temporary storage.
            live = [
                r for r in await asyncio.to_thread(hub.recorder.temp.list, *args) if r.trigger == "continuous"
            ]
            days = hub.library.days(camera) if camera else []
        except InvalidPathError as e:
            raise HTTPException(400, str(e)) from e
        retention = hub.config.recording.retention_days
        found = [{**r.to_json(retention), "live": True} for r in live]
        found += [r.to_json(retention) for r in items]
        found.sort(key=lambda r: r["start"], reverse=True)
        return {"recordings": found[:limit], "days": days, "truncated": len(found) > limit}

    def circle_or_404(circle_id: str) -> None:
        if circle_id not in hub.config.circles:
            raise HTTPException(404, f"no circle {circle_id!r}")

    def circle_json(circle_id: str) -> dict[str, Any]:
        return {"id": circle_id, **hub.config.circles[circle_id].model_dump(by_alias=True)}

    @api.get("/circles")
    async def circles() -> list[dict[str, Any]]:
        return [circle_json(cid) for cid in hub.config.circles]

    @api.post("/circles", status_code=201)
    async def add_circle(body: NewCircle) -> dict[str, Any]:
        if body.id in hub.config.circles:
            raise HTTPException(409, f"circle {body.id!r} exists")
        await hub.put_circle(body.id, CircleConfig.model_validate(body.model_dump(exclude={"id"})))
        return circle_json(body.id)

    @api.put("/circles/{circle_id}")
    async def update_circle(circle_id: str, body: CircleConfig) -> dict[str, Any]:
        circle_or_404(circle_id)
        await hub.put_circle(circle_id, body)
        return circle_json(circle_id)

    @api.delete("/circles/{circle_id}", status_code=204)
    async def delete_circle(circle_id: str) -> Response:
        circle_or_404(circle_id)
        await hub.remove_circle(circle_id)
        return Response(status_code=204)

    @api.get("/circles/{circle_id}/controls")
    async def circle_controls(circle_id: str) -> dict[str, Any]:
        """The controls all cameras of the circle share, to set them on all at once."""
        circle_or_404(circle_id)
        return {"controls": await hub.circle_controls(circle_id)}

    @api.post("/circles/{circle_id}/controls/{control_id}")
    async def set_circle_control(circle_id: str, control_id: str, body: ControlBody) -> dict[str, Any]:
        circle_or_404(circle_id)
        errors = await hub.set_circle_control(circle_id, control_id, body.value)
        if errors and len(errors) == len(hub.circle_members(circle_id)):
            raise HTTPException(502, "; ".join(f"{c}: {e}" for c, e in errors.items()))
        return {"ok": not errors, "errors": errors}

    @api.post("/circles/{circle_id}/record")
    async def record_circle(circle_id: str, body: RecordBody | None = None) -> dict[str, Any]:
        """Start a clip on every camera of the circle. Also a webhook, like a camera's."""
        circle_or_404(circle_id)
        body = body or RecordBody()
        clips, errors = [], {}
        for camera_id in hub.circle_members(circle_id):
            try:
                clips.append(
                    (await hub.recorder.record_clip(camera_id, body.trigger, body.seconds)).to_json()
                )
            except RuntimeError as e:
                errors[camera_id] = str(e)
        if errors and not clips:
            raise HTTPException(503, "; ".join(errors.values()))
        return {"clips": clips, "errors": errors}

    @api.delete("/circles/{circle_id}/record")
    async def stop_circle(circle_id: str) -> dict[str, Any]:
        circle_or_404(circle_id)
        stopped = [c for c in hub.circle_members(circle_id) if await hub.recorder.stop_clip(c)]
        return {"stopped": stopped}

    @api.get("/logs")
    async def get_logs(
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
        after: int = Query(0, ge=0),
        limit: int = Query(500, ge=1, le=2000),
        text: str = "",
    ) -> dict[str, Any]:
        """The last log lines (credentials scrubbed), newest last; `after`: only newer than that id."""
        return {
            "lines": logs.recent.query(level, after, limit, text),
            "file": str(settings.log_file) if settings.log_file else None,
        }

    @api.get("/logs/file")
    async def log_file() -> FileResponse:
        """The current log file, to download."""
        if not settings.log_file or not settings.log_file.is_file():
            raise HTTPException(404, "no log file")
        return FileResponse(settings.log_file, media_type="text/plain", filename="norn.log")

    @api.get("/resources")
    async def resources() -> dict[str, Any]:
        """CPU and memory of Norn, go2rtc and each FFmpeg; and the GPU."""
        return await hub.resources()

    @api.get("/forecast")
    async def forecast() -> dict[str, Any]:
        """Bytes per day of each trigger, measured or estimated, and where that leads."""
        return await hub.forecast()

    @api.get("/storage")
    async def storage() -> dict[str, Any]:
        """What the buffer (RAM), the temporary storage and the recordings hold."""
        return await hub.storage()

    @api.get("/recordings/{camera}/{day}/{name}")
    async def recording_file(camera: str, day: str, name: str, small: bool = False) -> FileResponse:
        """A recording's file. `small`: a picture's small copy, for lists and timelines."""
        try:
            if small and name.endswith(".jpg"):
                thumb = hub.library.thumb_path(camera, day, name)
                if thumb.is_file():
                    return FileResponse(thumb, headers={"Cache-Control": "max-age=86400"})
            path = hub.library.path(camera, day, name)
            if not path.is_file():
                path = hub.recorder.temp.path(camera, day, name)  # still being recorded
        except InvalidPathError as e:
            raise HTTPException(400, str(e)) from e
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)  # supports range requests, so the video can seek

    @api.put("/recordings/{camera}/{day}/{name}/pin")
    async def pin_recording(camera: str, day: str, name: str, body: PinBody) -> dict[str, Any]:
        """Pin a recording (Norn never deletes it), or unpin it."""
        try:
            recording = hub.library.set_pinned(camera, day, name, body.pinned)
        except InvalidPathError as e:
            raise HTTPException(400, str(e)) from e
        if recording is None:
            raise HTTPException(404, "not found")
        hub.bus.publish("recording.pinned", {"id": recording.id, "pinned": body.pinned})
        return recording.to_json(hub.config.recording.retention_days)

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
            hub.get_driver(camera)
        except (KeyError, LookupError):
            await ws.close(code=4404)
            return
        if stream not in hub.stream_ids(camera):
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
            # The browser may have gone already (a quality switch, a closed tab): then closing
            # fails, and that is fine.
            if ws.application_state != WebSocketState.DISCONNECTED:
                with contextlib.suppress(RuntimeError, WebSocketDisconnect):
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


def _local(value: datetime | None) -> datetime | None:
    """A time from the browser as the server's naive local time, which the folders use."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


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
