"""TP-Link Tapo cameras (C100, C200, C210, C310, C500, ...).

Video: RTSP with the "camera account" you create in the Tapo app (Advanced settings > Camera
account): rtsp://<account>:<password>@<host>:554/stream1 (stream2: the substream).
Control: Tapo's local, encrypted API through pytapo (the library behind Home Assistant's Tapo
integration), with the user "admin" and the password of your TP-Link cloud account. pytapo is
synchronous, so every call runs in a thread.

Firmware: the camera asks TP-Link's cloud itself (checkFirmwareVersionByCloud) and installs the
update by itself (fw_download), so both the check and the one-click update work.

Tested against pytapo's documented functions, not yet against a real camera.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from pydantic import Field

from . import register
from .base import (
    Capability,
    Control,
    DeviceInfo,
    Driver,
    DriverError,
    DriverOptions,
    NotSupportedError,
    Option,
    Preset,
    PtzCommand,
    Stream,
    userinfo,
)

log = logging.getLogger("norn.tapo")

DAY_NIGHT = {"auto": "Auto", "off": "Day", "on": "Night"}
# After a failed login, wait this long before the next: Tapo locks the account after a few.
LOGIN_PAUSE = 60
AUTH_WORDS = ("auth", "password", "login", "suspension")


def find(data: Any, key: str) -> Any:
    """The first value of `key` anywhere in nested dicts and lists (Tapo nests answers deeply)."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        values = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return None
    for value in values:
        found = find(value, key)
        if found is not None:
            return found
    return None


class TapoOptions(DriverOptions):
    host: str = Field(title="Address", description="IP address or host name")
    camera_username: str = Field(title="Camera account", description="Created in the Tapo app, for RTSP")
    camera_password: str = Field(title="Camera account password")
    cloud_password: str = Field(title="TP-Link cloud password", description="For settings, PTZ and firmware")


@register
class TapoDriver(Driver):
    name = "tapo"
    label = "TP-Link Tapo"
    description = "Tapo cameras: video, pan/tilt and presets, night vision, privacy mode, firmware updates."
    Options = TapoOptions
    options: TapoOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tapo: Any = None
        self._lock = asyncio.Lock()
        self._login_failed: tuple[float, str] | None = None  # when, and why
        self._siren: asyncio.Task[None] | None = None  # stops the siren after 10 s
        self.has_ptz = True

    def _client(self) -> Any:
        if self._tapo is None:
            from pytapo import Tapo  # imported late: it logs in on construction

            self._tapo = Tapo(self.options.host, "admin", self.options.cloud_password)
        return self._tapo

    async def _call(self, method: str, *args: Any) -> Any:
        async with self._lock:
            client = self._tapo
            if client is None:
                if self._login_failed and time.monotonic() - self._login_failed[0] < LOGIN_PAUSE:
                    raise DriverError(self._login_failed[1])
                try:
                    client = await asyncio.to_thread(self._client)
                except Exception as e:  # pytapo raises plain Exceptions
                    self._login_failed = (time.monotonic(), f"login failed: {e}")
                    raise DriverError(self._login_failed[1]) from e
                self._login_failed = None
            try:
                return await asyncio.to_thread(getattr(client, method), *args)
            except Exception as e:
                # A lost connection (requests' errors are OSErrors) or session: log in again.
                if isinstance(e, OSError) or any(word in str(e).lower() for word in AUTH_WORDS):
                    self._tapo = None
                raise DriverError(str(e)) from e

    async def stop(self) -> None:
        if self._siren is not None and not self._siren.done():
            self._siren.cancel()
            await self._stop_siren(wait=0)
        if self._tapo is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._tapo.close)

    def web_url(self) -> str | None:
        return None  # Tapo cameras have no web page for users

    def streams(self) -> list[Stream]:
        o = self.options
        auth = userinfo(o.camera_username, o.camera_password)
        return [
            Stream(id="main", label="Main", source=f"rtsp://{auth}{o.host}:554/stream1", codec="h264"),
            Stream(id="sub", label="Sub", source=f"rtsp://{auth}{o.host}:554/stream2", codec="h264"),
        ]

    def capabilities(self) -> set[Capability]:
        caps = super().capabilities() | {Capability.CONTROLS, Capability.FIRMWARE_ONLINE}
        if self.has_ptz:
            caps |= {Capability.PTZ, Capability.PRESETS}
        return caps

    async def info(self) -> DeviceInfo:
        try:
            basic = find(await self._call("getBasicInfo"), "basic_info") or {}
        except DriverError as e:
            return DeviceInfo(online=False, error=str(e))
        model = basic.get("device_model")
        # Fixed cameras (C100, C110, C310, ...) don't pan; the pan/tilt ones are C2xx and C5xx.
        self.has_ptz = bool(model and model.upper().startswith(("C2", "C5", "TC7")))
        return DeviceInfo(
            manufacturer="TP-Link",
            model=model,
            firmware=basic.get("sw_version"),
            hardware=basic.get("hw_version"),
            serial=basic.get("dev_id"),
            mac=(basic.get("mac") or "").replace("-", ":").lower() or None,
            name=basic.get("device_alias"),
        )

    async def controls(self) -> list[Control]:
        controls: list[Control] = []
        try:
            mode = await self._call("getDayNightMode")
            controls.append(
                Control(
                    id="daynight",
                    label="Night vision",
                    kind="select",
                    group="Image",
                    icon="moon",
                    value=mode,
                    options=[Option(value=k, label=v) for k, v in DAY_NIGHT.items()],
                )
            )
        except DriverError:
            pass
        for control_id, method, label, group, icon in (
            ("privacy", "getPrivacyMode", "Privacy mode", "General", "eye-off"),
            ("led", "getLED", "Status light", "Light", None),
            ("autotrack", "getAutoTrackTarget", "Follow motion", "Pan and tilt", "activity"),
            ("motion", "getMotionDetection", "Motion detection", "Alarm", "activity"),
        ):
            try:
                state = await self._call(method)
            except DriverError:
                continue
            enabled = find(state, "enabled")
            controls.append(
                Control(
                    id=control_id, label=label, kind="toggle", group=group, icon=icon, value=enabled == "on"
                )
            )
        controls.append(Control(id="alarm", label="Siren (10 s)", kind="button", group="Alarm", icon="siren"))
        return controls

    async def set_control(self, control_id: str, value: Any) -> None:
        if control_id == "daynight":
            if value not in DAY_NIGHT:
                raise ValueError(f"{value!r} is not one of {', '.join(DAY_NIGHT)}")
            await self._call("setDayNightMode", value)
        elif control_id == "privacy":
            await self._call("setPrivacyMode", bool(value))
        elif control_id == "led":
            await self._call("setLEDEnabled", bool(value))
        elif control_id == "autotrack":
            await self._call("setAutoTrackTarget", bool(value))
        elif control_id == "motion":
            await self._call("setMotionDetection", bool(value))
        elif control_id == "alarm":
            await self._call("startManualAlarm")
            if self._siren is not None:
                self._siren.cancel()
            self._siren = asyncio.create_task(self._stop_siren())
        else:
            raise NotSupportedError(f"no control {control_id!r}")
        self.emit("camera.control", {"control": control_id, "value": value})

    async def _stop_siren(self, wait: float = 10) -> None:
        await asyncio.sleep(wait)
        try:
            await self._call("stopManualAlarm")
        except DriverError as e:
            log.warning("%s: couldn't stop the siren: %s", self.camera_id, e)

    async def presets(self) -> list[Preset]:
        if not self.has_ptz:
            return []
        try:
            found = await self._call("getPresets")
        except DriverError:
            return []
        return [Preset(id=str(k), name=str(v)) for k, v in (found or {}).items()]

    async def ptz(self, command: PtzCommand) -> None:
        # Tapo motors move in steps (moveMotor x, y in degrees), not continuously: a press moves
        # one step in its direction, and stop has nothing to do.
        if command.action == "stop":
            return
        if command.action == "home":
            await self._call("calibrateMotor")
        elif command.action == "goto":
            if not command.preset:
                raise ValueError("which preset?")
            await self._call("setPreset", command.preset)
        else:
            x = round(command.pan * 30)
            y = round(command.tilt * 15)
            if not x and not y:
                raise NotSupportedError("Tapo cameras can't zoom")
            await self._call("moveMotor", x, y)

    async def firmware_online_check(self) -> str | None:
        answer = await self._call("isUpdateAvailable")
        info = find(answer, "upgrade_info") or {}
        if find(answer, "need_to_upgrade") is False or not info.get("version"):
            return None
        return str(info["version"])

    async def firmware_online_update(self) -> None:
        """The camera downloads and installs the update from TP-Link by itself."""
        await self._call("startFirmwareUpgrade")
