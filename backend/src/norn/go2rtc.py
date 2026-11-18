"""go2rtc: the media relay.

go2rtc reads each camera once and repackages the stream for every viewer (WebRTC, MSE, HLS) and
for the recorder (RTSP on localhost). It transcodes only when a source asks for it, like the demo
camera's test pattern or a camera with a codec browsers can't play.

In `managed` mode Norn runs go2rtc as a child process and restarts it when it exits. In
`external` mode go2rtc runs elsewhere and Norn only talks to its API. Either way, Norn keeps the
streams of go2rtc in sync with config.yaml through the API, so a camera change doesn't interrupt
the other cameras.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import shutil

import httpx
from ruamel.yaml import YAML

from .events import EventBus
from .settings import Settings

log = logging.getLogger("norn.go2rtc")

Streams = dict[str, str]  # go2rtc stream name -> source


class Go2rtcUnavailableError(Exception):
    pass


class Go2rtc:
    def __init__(self, settings: Settings, bus: EventBus) -> None:
        self.settings = settings
        self.bus = bus
        self.enabled = settings.go2rtc_mode != "off"
        self.config_path = settings.runtime_dir / "go2rtc.yaml"
        self._wanted: Streams = {}  # the streams go2rtc should have
        self._streams: Streams = {}  # those it has, as far as Norn knows (what it put there)
        self._process: asyncio.subprocess.Process | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._client = httpx.AsyncClient(base_url=settings.go2rtc_api, timeout=10)
        self._lock = asyncio.Lock()
        self.ready = asyncio.Event()

    # The go2rtc config. Norn writes it; nobody should edit it.
    def config(self, streams: Streams) -> dict:
        api_host = self.settings.go2rtc_api.split("://", 1)[-1]
        rtsp_host = self.settings.go2rtc_rtsp.split("://", 1)[-1]
        if self.settings.rtsp_share:  # Norn itself still connects as configured, the others on the network
            rtsp_host = f":{self.settings.rtsp_port}"
        return {
            "api": {"listen": api_host},
            "rtsp": {"listen": rtsp_host},
            "webrtc": {"listen": f":{self.settings.webrtc_port}"},
            "ffmpeg": {"bin": self.settings.ffmpeg_bin},
            "log": {"format": "text", "level": "info"},
            "streams": dict(streams),
        }

    def write_config(self, streams: Streams) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        # Block-style YAML: go2rtc edits this file itself when streams are added through its API,
        # and its editor fails on flow style (JSON).
        yaml = YAML(typ="safe", pure=True)
        yaml.default_flow_style = False
        buffer = io.StringIO()
        yaml.dump(self.config(streams), buffer)
        self.config_path.write_text("# Written by Norn from config.yaml. Don't edit.\n" + buffer.getvalue())

    async def start(self, streams: Streams) -> None:
        self._wanted = dict(streams)
        if not self.enabled:
            return
        if self.settings.go2rtc_mode == "managed":
            if not shutil.which(self.settings.go2rtc_bin):
                log.error(
                    "go2rtc not found (%s). Install it or set NORN_GO2RTC_BIN; live video is off.",
                    self.settings.go2rtc_bin,
                )
                return
            self._supervisor = asyncio.create_task(self._supervise(), name="go2rtc")
        else:
            self._supervisor = asyncio.create_task(self._sync_when_ready(), name="go2rtc-sync")

    async def stop(self) -> None:
        if self._supervisor:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
        await self._client.aclose()

    async def apply(self, streams: Streams) -> None:
        """Make go2rtc's streams match `streams`, adding, changing and removing only what differs."""
        async with self._lock:
            self._wanted = dict(streams)
            if not self.enabled:
                return
            if self.settings.go2rtc_mode == "managed":
                self.write_config(streams)
            if self.ready.is_set():  # else the sync after start picks up the new streams
                await self._push()

    async def _push(self) -> None:
        """Send go2rtc what differs. `_streams` follows each request that worked, so one that
        failed is tried again with the next push; the others go ahead. Holds the lock."""
        errors = []
        gone: dict[str, str | None] = dict.fromkeys(self._streams.keys() - self._wanted.keys())
        for name, source in (gone | self._wanted).items():
            if self._streams.get(name) == source:
                continue
            try:
                if name in self._streams:
                    await self._request("DELETE", "/api/streams", params={"src": name})
                    del self._streams[name]
                if source is not None:
                    await self._request("PUT", "/api/streams", params={"name": name, "src": source})
                    self._streams[name] = source
            except Go2rtcUnavailableError as e:
                errors.append(str(e))
        if errors:
            raise Go2rtcUnavailableError("; ".join(errors))

    async def _catch_up(self, have: Streams | None = None) -> bool:
        """After go2rtc started with `have`: send it what changed since. False if it failed."""
        async with self._lock:
            if have is not None:
                self._streams = have
            try:
                await self._push()
                return True
            except Go2rtcUnavailableError as e:
                log.error("go2rtc didn't take the streams: %s", e)
                return False

    async def frame(self, stream: str) -> bytes:
        """One JPEG frame of a stream."""
        response = await self._request("GET", "/api/frame.jpeg", params={"src": stream}, timeout=15)
        return response.content

    async def info(self) -> dict:
        if not self.ready.is_set():
            return {"running": False}
        try:
            response = await self._request("GET", "/api")
            return {"running": True, **response.json()}
        except Go2rtcUnavailableError:
            return {"running": False}

    def ws_url(self, stream: str) -> str:
        base = self.settings.go2rtc_api.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        return f"{base}/api/ws?src={stream}"

    def rtsp_url(self, stream: str) -> str:
        return f"{self.settings.go2rtc_rtsp}/{stream}"

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.enabled:
            raise Go2rtcUnavailableError("go2rtc is off")
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise Go2rtcUnavailableError(f"go2rtc: {e}") from e
        if response.status_code >= 400:
            raise Go2rtcUnavailableError(f"go2rtc {method} {path}: {response.status_code} {response.text}")
        return response

    async def _wait_api(self, timeout: float = 15) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            try:
                await self._client.get("/api", timeout=1)
                return True
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
        return False

    async def _sync_when_ready(self) -> None:
        while not await self._wait_api():
            log.warning("go2rtc at %s does not answer yet", self.settings.go2rtc_api)
        self.ready.set()
        # Of the streams go2rtc has, only those with Norn's names are Norn's: it may serve others
        # too (Frigate, Home Assistant), which Norn must leave alone.
        existing: Streams = {}
        with contextlib.suppress(Go2rtcUnavailableError, ValueError):  # ValueError: not JSON
            names = (await self._request("GET", "/api/streams")).json()
            existing = {k: "" for k in names if k in self._wanted}
        done, delay = await self._catch_up(existing), 5.0
        while not done:
            await asyncio.sleep(delay)
            done, delay = await self._catch_up(), min(delay * 2, 60)
        self.bus.publish("go2rtc.ready")

    async def _supervise(self) -> None:
        delay = 1.0
        while True:
            self.ready.clear()
            log.info("starting go2rtc")
            async with self._lock:
                started_with = dict(self._wanted)
                self.write_config(started_with)
            self._process = await asyncio.create_subprocess_exec(
                self.settings.go2rtc_bin,
                "-config",
                str(self.config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            logger = asyncio.create_task(self._pipe_log(self._process))
            try:
                if await self._wait_api():
                    self.ready.set()
                    # Catch up on changes that came in while go2rtc was starting.
                    await self._catch_up(started_with)
                    self.bus.publish("go2rtc.ready")
                    delay = 1.0
                code = await self._process.wait()
                log.warning("go2rtc exited with %s; restarting in %.0fs", code, delay)
            except asyncio.CancelledError:
                await _terminate(self._process)
                raise
            finally:
                logger.cancel()
            self.bus.publish("go2rtc.stopped")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def _pipe_log(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout
        async for line in process.stdout:
            text = line.decode(errors="replace").rstrip()
            if text:
                log.info("%s", text)


async def _terminate(process: asyncio.subprocess.Process, timeout: float = 5) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
