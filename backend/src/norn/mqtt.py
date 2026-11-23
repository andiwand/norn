"""MQTT, for Home Assistant and other home automation.

Norn connects to a broker (the `mqtt` section of config.yaml; NORN_MQTT and the other NORN_MQTT_*
variables only fill it in on a start when the file has none) and publishes what the hub knows:
each camera's detections, whether it records, whether it is online, its controls and its Norn
presets, and away mode. It listens for commands on `.../set` topics: record a clip, go to a
preset, set a control, turn away mode on or off.

With Home Assistant's MQTT discovery, every camera appears in Home Assistant as a device with its
entities, with nothing to copy. The entities come from what the drivers declare, like the web app:
a toggle is a switch, a select a select, a range a number, a button a button.

The topics, under the prefix (default `norn`):

    norn/status                                   online / offline (retained, the will)
    norn/error, norn/error/attributes             the last command that failed, and why
    norn/away, norn/away/set                      ON / OFF
    norn/camera/<id>/online                       ON / OFF
    norn/camera/<id>/available                    online / offline: its controls, presets, still
    norn/camera/<id>/recording                    ON / OFF
    norn/camera/<id>/event/<kind>                 ON / OFF (motion, person, ...)
    norn/camera/<id>/record/set                   PRESS, STOP, or {"trigger": ..., "seconds": ...}
    norn/camera/<id>/preset, .../preset/set       a Norn preset's name
    norn/camera/<id>/control/<id>, .../set        the control's value (ON / OFF, a label, a number)
    norn/camera/<id>/still                        a JPEG every `stills_seconds` (not retained)
    norn/circle/<id>/record/set                   like a camera's

A command that fails (the camera is offline, the value is wrong) sets `norn/error`, which Home
Assistant shows as the Norn device's "Last error", and sends the true state again, so a switch
in Home Assistant flips back.

Everything Norn publishes is computed from the hub's state (`desired`) and retained; `sync`
sends what changed and clears what is gone. Discovery topics are
`<discovery>/<component>/<prefix>/<object>/config`, so Norn can find the ones it published before
a restart (retained on the broker) and clear those it no longer has.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from . import __version__
from .config import AwaySettings, MqttSettings, short_error
from .drivers.base import Control
from .labels import LABELS

if TYPE_CHECKING:
    from .hub import Camera, Hub
    from .settings import Settings

log = logging.getLogger("norn.mqtt")

ON, OFF, NONE = "ON", "OFF", "None"  # "None": Home Assistant's word for an unknown state

# The drivers' icon hints, as Material Design Icons.
ICONS = {
    "activity": "mdi:pulse",
    "eye-off": "mdi:eye-off",
    "lamp": "mdi:lightbulb",
    "moon": "mdi:weather-night",
    "siren": "mdi:alarm-light",
    "sun": "mdi:white-balance-sunny",
    "volume": "mdi:volume-high",
}
EVENT_CLASSES = {"motion": "motion", "person": "occupancy", "vehicle": "occupancy", "animal": "occupancy"}
EVENT_ICONS = {
    "package": "mdi:package-variant-closed",
    "doorbell": "mdi:doorbell",
    "face": "mdi:face-recognition",
}
COMPONENTS = {"toggle": "switch", "select": "select", "range": "number", "button": "button"}


@dataclass(frozen=True)
class Broker:
    host: str
    port: int
    tls: bool
    username: str | None
    password: str | None

    @classmethod
    def parse(cls, url: str) -> Broker:
        """mqtt://user:password@host:1883, mqtts:// for TLS. A bare host means mqtt://."""
        parts = urlsplit(url if "://" in url else f"mqtt://{url}")
        if parts.scheme not in ("mqtt", "mqtts", "tcp", "ssl"):
            raise ValueError(f"NORN_MQTT must start with mqtt:// or mqtts://, not {parts.scheme}://")
        if not parts.hostname:
            raise ValueError("NORN_MQTT has no host")
        tls = parts.scheme in ("mqtts", "ssl")
        return cls(
            host=parts.hostname,
            port=parts.port or (8883 if tls else 1883),
            tls=tls,
            username=unquote(parts.username) if parts.username else None,
            password=unquote(parts.password) if parts.password else None,
        )

    @classmethod
    def of(cls, options: MqttSettings) -> Broker | None:
        """The broker the settings name; None: MQTT is off (or has no host)."""
        if not options.enabled or not options.host:
            return None
        return cls(
            host=options.host,
            port=options.port or (8883 if options.tls else 1883),
            tls=options.tls,
            username=options.username or None,
            password=(options.password or None) if options.username else None,
        )


def from_env(settings: Settings) -> MqttSettings:
    """The MQTT settings the environment gives (NORN_MQTT, ...): the initial values of
    config.yaml's `mqtt` section, written there when the file has none."""
    broker = Broker.parse(settings.mqtt_url) if settings.mqtt_url else None
    discovery = settings.mqtt_discovery.lower() != "off"
    return MqttSettings(
        enabled=broker is not None,
        host=broker.host if broker else "",
        # The port only if it isn't the usual one, so turning TLS on changes it too.
        port=broker.port if broker and broker.port != (8883 if broker.tls else 1883) else 0,
        tls=broker.tls if broker else False,
        username=(broker.username or "") if broker else "",
        password=(broker.password or "") if broker else "",
        prefix=settings.mqtt_prefix,
        discovery=discovery,
        discovery_prefix=settings.mqtt_discovery if discovery else "homeassistant",
        stills_seconds=settings.mqtt_stills,
    )


def slug(value: str) -> str:
    """A topic level and discovery object id: no wildcards, no slashes."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def on_off(value: Any) -> str:
    return ON if value else OFF


def control_state(control: Control) -> str:
    """A control's value as Home Assistant reads it."""
    if control.value is None:
        return NONE
    if control.kind == "toggle":
        return on_off(control.value)
    if control.kind == "select":
        for option in control.options or []:
            if str(option.value) == str(control.value):
                return option.label
        return NONE
    return str(control.value)


def control_value(control: Control, payload: str) -> Any:
    """A command from Home Assistant as the value the driver takes."""
    if control.kind == "toggle":
        if payload.upper() not in (ON, OFF):
            raise ValueError(f"{payload!r} is not ON or OFF")
        return payload.upper() == ON
    if control.kind == "select":
        for option in control.options or []:
            if payload in (option.label, str(option.value)):
                return option.value
        raise ValueError(f"{payload!r} is not an option")
    if control.kind == "range":
        number = float(payload)
        return int(number) if number.is_integer() and float(control.step or 1).is_integer() else number
    return None  # a button: the web app sends null too


def preset_names(camera: Camera) -> dict[str, str]:
    """Norn preset id -> the name Home Assistant shows; names that appear twice get their id."""
    presets = camera.config.presets
    names = [p.name for p in presets.values()]
    return {pid: p.name if names.count(p.name) == 1 else f"{p.name} ({pid})" for pid, p in presets.items()}


class Mqtt:
    def __init__(self, options: MqttSettings, hub: Hub) -> None:
        self.hub = hub
        self.options = options
        self.broker = Broker.of(options)
        self.prefix = options.prefix
        self.discovery = options.discovery_prefix if options.discovery else None
        # Stills every so many seconds (0: none); at least 5 s, a still is a whole JPEG.
        self.stills = max(5, options.stills_seconds) if options.stills_seconds > 0 else 0
        self.connected = False
        self.error: str | None = None  # why the last connection failed
        self.since: float | None = None  # when it connected, or failed
        self.last_error: dict[str, Any] | None = None  # the last command that failed
        self._sent: dict[str, str] = {}  # retained topic -> payload, as the broker has it
        self._publish: Callable[[str, str], Awaitable[None]] | None = None
        self._send: Callable[[str, bytes], Awaitable[None]] | None = None  # not retained
        self._dirty = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._commands: set[asyncio.Task[None]] = set()
        # Retained topics of Norn's found on the broker (from an earlier run); cleared once the
        # controls are read, unless Norn still publishes them.
        self._found: set[str] = set()
        self._ready = False
        # The kinds of events each camera reported while online: some (Reolink's AI) only know
        # theirs while connected, and their sensors must not vanish while the camera is offline.
        self._kinds: dict[str, tuple[str, set[str]]] = {}  # camera -> (driver, kinds)

    @property
    def enabled(self) -> bool:
        return self.broker is not None

    def status(self) -> dict[str, Any]:
        """For Diagnostics (GET /api/info)."""
        if not self.broker:
            if self.options.enabled:
                return {"enabled": True, "connected": False, "error": "no broker: set its host"}
            return {"enabled": False}
        return {
            "enabled": True,
            "connected": self.connected,
            "broker": f"{self.broker.host}:{self.broker.port}",
            "prefix": self.prefix,
            "discovery": self.discovery,
            "stills": self.stills,
            "error": self.error,
            "since": self.since,
            "last_error": self.last_error,
        }

    def _changed(self, connected: bool, error: str | None) -> None:
        if (connected, error) != (self.connected, self.error):
            self.connected, self.error, self.since = connected, error, time.time()
            self.hub.bus.publish("mqtt.changed", {"connected": connected})

    # What Norn publishes.

    def _config(
        self,
        out: dict[str, str],
        component: str,
        object_id: str,
        device: dict[str, Any],
        camera: str | None = None,
        **entity: Any,
    ) -> None:
        """A discovery config. With `camera`, the entity is available only while Norn and that
        camera both are: for what talks to the camera (controls, presets, its still)."""
        if not self.discovery:
            return
        object_id = slug(object_id)
        availability: dict[str, Any] = {"availability_topic": f"{self.prefix}/status"}
        if camera:
            availability = {
                "availability": [
                    {"topic": f"{self.prefix}/status"},
                    {"topic": f"{self.prefix}/camera/{camera}/available"},
                ],
                "availability_mode": "all",
            }
        payload = {
            "unique_id": f"{self.prefix}_{object_id}",
            "has_entity_name": True,
            "device": device,
            **availability,
            "origin": {"name": "Norn", "sw_version": __version__, "url": "https://andiwand.github.io/norn/"},
            **{k: v for k, v in entity.items() if v is not None},
        }
        out[f"{self.discovery}/{component}/{self.prefix}/{object_id}/config"] = json.dumps(payload)

    def desired(self) -> dict[str, str]:
        """Every retained topic Norn publishes now, with its payload: discovery configs first."""
        configs: dict[str, str] = {}
        states: dict[str, str] = {}
        p, hub = self.prefix, self.hub
        norn = {"identifiers": [p], "name": "Norn", "manufacturer": "Norn", "sw_version": __version__}

        self._config(
            configs,
            "switch",
            "away",
            norn,
            name="Away mode",
            icon="mdi:airplane",
            state_topic=f"{p}/away",
            command_topic=f"{p}/away/set",
        )
        states[f"{p}/away"] = on_off(hub.away)
        self._config(
            configs,
            "sensor",
            "error",
            norn,
            name="Last error",
            icon="mdi:alert-circle-outline",
            entity_category="diagnostic",
            state_topic=f"{p}/error",
            json_attributes_topic=f"{p}/error/attributes",
        )
        error = self.last_error
        states[f"{p}/error"] = error["error"][:255] if error else NONE
        states[f"{p}/error/attributes"] = json.dumps(
            {"command": error["command"], "time": error["time"]} if error else {}
        )
        for circle_id, circle in hub.config.circles.items():
            self._config(
                configs,
                "button",
                f"circle_{circle_id}_record",
                norn,
                name=f"{circle.name}: record",
                icon="mdi:record-rec",
                command_topic=f"{p}/circle/{circle_id}/record/set",
                payload_press="PRESS",
            )

        for cid, camera in hub.cameras.items():
            if camera.driver is None or not camera.config.enabled:
                continue
            base = f"{p}/camera/{cid}"
            info = camera.device
            device: dict[str, Any] = {
                "identifiers": [f"{p}_{cid}"],
                "name": camera.config.name,
                "via_device": p,
                "manufacturer": (info.manufacturer if info else None) or camera.driver.label,
            }
            if info:
                device |= {
                    k: v
                    for k, v in (
                        ("model", info.model),
                        ("sw_version", info.firmware),
                        ("hw_version", info.hardware),
                        ("serial_number", info.serial),
                    )
                    if v
                }

            # Offline: the camera doesn't answer Norn (its controls). Unknown counts as online.
            states[f"{base}/available"] = "offline" if info and not info.online else "online"
            if self.stills:
                self._config(
                    configs, "camera", f"{cid}_still", device, cid, name="Still", topic=f"{base}/still"
                )
            self._config(
                configs,
                "binary_sensor",
                f"{cid}_online",
                device,
                name="Online",
                device_class="connectivity",
                entity_category="diagnostic",
                state_topic=f"{base}/online",
            )
            states[f"{base}/online"] = on_off(info.online) if info else NONE

            self._config(
                configs,
                "binary_sensor",
                f"{cid}_recording",
                device,
                name="Recording",
                device_class="running",
                icon="mdi:record-rec",
                state_topic=f"{base}/recording",
            )
            states[f"{base}/recording"] = on_off(hub.recorder.is_recording(cid))
            self._config(
                configs,
                "button",
                f"{cid}_record",
                device,
                name="Record clip",
                icon="mdi:record-rec",
                command_topic=f"{base}/record/set",
                payload_press="PRESS",
            )
            self._config(
                configs,
                "button",
                f"{cid}_stop",
                device,
                name="Stop clip",
                icon="mdi:stop",
                command_topic=f"{base}/record/set",
                payload_press="STOP",
            )

            events = camera.events_json(hub.norn_kinds(cid)) or {"kinds": [], "active": []}
            for kind in self._event_kinds(camera, events["kinds"]):
                label = LABELS.get(kind)
                self._config(
                    configs,
                    "binary_sensor",
                    f"{cid}_event_{kind}",
                    device,
                    name=label.name if label else kind,
                    device_class=EVENT_CLASSES.get(kind),
                    icon=EVENT_ICONS.get(kind),
                    state_topic=f"{base}/event/{slug(kind)}",
                )
                states[f"{base}/event/{slug(kind)}"] = on_off(kind in events["active"])

            names = preset_names(camera)
            if names:
                self._config(
                    configs,
                    "select",
                    f"{cid}_preset",
                    device,
                    cid,
                    name="Preset",
                    icon="mdi:camera-switch",
                    options=list(names.values()),
                    state_topic=f"{base}/preset",
                    command_topic=f"{base}/preset/set",
                )
                states[f"{base}/preset"] = names.get(hub.preset_of(cid) or "", NONE)

            for control in camera.controls or []:
                topic = f"{base}/control/{slug(control.id)}"
                component = COMPONENTS[control.kind]
                entity: dict[str, Any] = {
                    "name": control.label,
                    "icon": ICONS.get(control.icon or ""),
                    "command_topic": f"{topic}/set",
                }
                if component == "button":
                    entity["payload_press"] = "PRESS"
                else:
                    entity["state_topic"] = topic
                    states[topic] = control_state(control)
                if component == "select":
                    entity["options"] = [o.label for o in control.options or []]
                if component == "number":
                    entity |= {
                        "min": control.min,
                        "max": control.max,
                        "step": control.step,
                        "unit_of_measurement": control.unit,
                        "mode": "slider",
                    }
                self._config(configs, component, f"{cid}_control_{control.id}", device, cid, **entity)
        return configs | states

    def ours(self, topic: str) -> bool:
        """A retained topic Norn publishes (or did in an earlier run): a state or a discovery config."""
        parts = topic.split("/")
        if parts[0] == self.prefix:
            return parts[-1] != "set" and topic != f"{self.prefix}/status"
        return (
            bool(self.discovery)
            and len(parts) == 5
            and parts[0] == self.discovery
            and (parts[2] == self.prefix and parts[4] == "config")
        )

    def _event_kinds(self, camera: Camera, kinds: list[str]) -> list[str]:
        """The camera's kinds now, and those its driver reported while it was online before."""
        driver, known = self._kinds.get(camera.id, ("", set()))
        if driver != camera.config.driver:
            known = set()
        if camera.device and camera.device.online:
            known = known | set(camera.camera_kinds())
            self._kinds[camera.id] = (camera.config.driver, known)
        return [k for k in LABELS if k in kinds or k in known]

    def _unknown(self, topic: str) -> bool:
        """A topic of what Norn can't know (yet) about a camera: its controls, until they are read,
        and its events, until it was online. Keep it, or Home Assistant would drop the entity
        while the camera is offline."""
        for cid, camera in self.hub.cameras.items():
            if camera.controls is None and (
                f"/camera/{cid}/control/" in topic or f"/{slug(cid)}_control_" in topic
            ):
                return True
            if (
                cid not in self._kinds
                and camera.driver
                and camera.config.enabled
                and (f"/camera/{cid}/event/" in topic or f"/{cid}_event_" in topic)
            ):
                return True
        return False

    async def sync(self) -> None:
        """Publish what changed since the last sync, and clear topics Norn no longer has."""
        if self._publish is None:
            return
        want = self.desired()
        gone = [t for t in self._sent if t not in want]
        # Not while config.yaml has an error: the hub then runs without cameras, and clearing
        # their topics would make Home Assistant delete the devices.
        if self._ready and not self.hub.config_error:
            gone += [t for t in self._found if t not in want and t not in self._sent]
            self._found = set()
        for topic in gone:
            if self._unknown(topic):
                if topic not in self._sent:
                    self._found.add(topic)  # for a later sync
                continue
            await self._publish(topic, "")
            self._sent.pop(topic, None)
        for topic, payload in want.items():
            if self._sent.get(topic) != payload:
                await self._publish(topic, payload)
                self._sent[topic] = payload

    # What Norn listens to.

    async def handle(self, topic: str, payload: str) -> None:
        """A message from the broker: a command, Home Assistant starting, or an old discovery
        config. Never raises: a bad command must not drop the connection."""
        try:
            await self._handle(topic, payload.strip())
        except Exception as e:
            log.warning("%s: %s", topic, e)
            self.last_error = {
                "command": f"{topic} {payload.strip()[:100]}".strip(),
                "error": str(e) or type(e).__name__,
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            # Send the true state again: Home Assistant shows what it asked for until it hears.
            self._sent.pop(topic.removesuffix("/set"), None)
            self._dirty.set()
            self.hub.bus.publish("mqtt.changed", {"connected": self.connected})

    async def _handle(self, topic: str, payload: str) -> None:
        p, hub = self.prefix, self.hub
        if self.discovery and topic == f"{self.discovery}/status":
            if payload == "online":  # Home Assistant (re)started: tell it everything again
                self._sent.clear()
                self._dirty.set()
            return
        if self.ours(topic):
            if payload:  # retained from before: `sync` clears it if Norn no longer has it
                self._found.add(topic)
                self._dirty.set()
            return
        parts = topic.split("/")
        if parts[0] != p or parts[-1] != "set":
            return
        match parts[1:-1]:
            case ["away"]:
                if payload.upper() not in (ON, OFF):
                    raise ValueError(f"{payload!r} is not ON or OFF")
                await self._away(payload.upper() == ON)
            case ["camera", cid, "record"]:
                await self._record(cid, *self._record_args(payload))
            case ["camera", cid, "preset"]:
                await self._goto(cid, payload)
            case ["camera", cid, "control", control_id]:
                await self._set_control(cid, control_id, payload)
            case ["circle", circle_id, "record"]:
                if circle_id not in hub.config.circles:
                    raise ValueError(f"no circle {circle_id!r}")
                args = self._record_args(payload)
                errors = []
                for cid in hub.circle_members(circle_id):
                    try:
                        await self._record(cid, *args)
                    except Exception as e:
                        errors.append(f"{cid}: {e}")
                if errors:
                    raise RuntimeError("; ".join(errors))
            case _:
                raise ValueError("unknown command")
        self._dirty.set()

    def _camera(self, cid: str) -> Camera:
        camera = self.hub.cameras.get(cid)
        if camera is None or camera.driver is None or not camera.config.enabled:
            raise ValueError(f"no camera {cid!r}")
        return camera

    async def _away(self, away: bool) -> None:
        """Like the web app's button: off also ends a planned absence that is running now."""
        current = self.hub.config.away
        if away == self.hub.away:
            return
        values = current.model_dump()
        values["active"] = away
        if not away and current.start and current.now():
            values["start"] = values["end"] = None
        await self.hub.put_settings({"away": AwaySettings.model_validate(values)})

    @staticmethod
    def _record_args(payload: str) -> tuple[bool, str, int | None]:
        """A record command: (stop, trigger, seconds), checked like the API's."""
        from .api import RecordBody  # the API imports the hub, which imports this

        if payload.upper() == "STOP":
            return True, "", None
        body = json.loads(payload) if payload.startswith("{") else {}
        try:
            record = RecordBody.model_validate({"trigger": "mqtt", **body})
        except ValidationError as e:
            raise ValueError(short_error(e)) from None
        return False, record.trigger, record.seconds

    async def _record(self, cid: str, stop: bool, trigger: str, seconds: int | None) -> None:
        self._camera(cid)
        if stop:
            await self.hub.recorder.stop_clip(cid)
        else:
            await self.hub.recorder.record_clip(cid, trigger, seconds)

    async def _goto(self, cid: str, payload: str) -> None:
        camera = self._camera(cid)
        pilot = self.hub.pilots.get(cid)
        names = preset_names(camera)
        preset = next((pid for pid, name in names.items() if payload in (name, pid)), None)
        if pilot is None or preset is None:
            raise ValueError(f"no preset {payload!r}")
        await pilot.goto(preset)
        pilot.manual()  # like the web app: a patrol waits a while

    async def _set_control(self, cid: str, control_id: str, payload: str) -> None:
        camera = self._camera(cid)
        control = next((c for c in camera.controls or [] if slug(c.id) == control_id), None)
        if control is None:
            raise ValueError(f"no control {control_id!r}")
        value = control_value(control, payload)
        await camera.driver.set_control(control.id, value)
        self.hub.remember_control(cid, control.id, value)

    # The connection.

    async def start(self) -> None:
        if self.broker:
            self._task = asyncio.create_task(self._run(), name="mqtt")

    async def stop(self) -> None:
        if self._publish and self.connected:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._publish(f"{self.prefix}/status", "offline"), 2)
        tasks = [t for t in (self._task, *self._commands) if t and not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self) -> None:
        import aiomqtt

        assert self.broker is not None
        broker = self.broker
        status = f"{self.prefix}/status"
        delay = 5.0
        while True:
            try:
                async with aiomqtt.Client(
                    broker.host,
                    broker.port,
                    username=broker.username,
                    password=broker.password,
                    identifier=f"norn-{slug(self.prefix)}",
                    will=aiomqtt.Will(status, "offline", qos=1, retain=True),
                    tls_params=aiomqtt.TLSParameters() if broker.tls else None,
                ) as client:

                    async def publish(topic: str, payload: str) -> None:
                        await client.publish(topic, payload, qos=1, retain=True)

                    async def send(topic: str, payload: bytes) -> None:
                        await client.publish(topic, payload, qos=0, retain=False)

                    self._publish, self._send, self._sent = publish, send, {}
                    self._changed(True, None)
                    self._found, self._ready = set(), False
                    delay = 5.0
                    log.info("connected to the MQTT broker %s:%d", broker.host, broker.port)
                    await client.subscribe([(topic, 0) for topic in self.subscriptions()])
                    await publish(status, "online")
                    async with asyncio.TaskGroup() as group:
                        group.create_task(self._load_controls(first=True))
                        group.create_task(self._watch_hub())
                        group.create_task(self._listen(client))
                        if self.stills:
                            group.create_task(self._send_stills())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                errors = e.exceptions if isinstance(e, BaseExceptionGroup) else [e]
                error = "; ".join(str(x) or type(x).__name__ for x in errors)
                log.warning("MQTT broker %s:%d: %s; again in %.0f s", broker.host, broker.port, error, delay)
                self._publish, self._send = None, None
                self._changed(False, error)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    def subscriptions(self) -> list[str]:
        """Commands, and Norn's retained topics from before (to clear what is gone); not `#`,
        which would send every still back to Norn."""
        p, camera = self.prefix, f"{self.prefix}/camera/+"
        topics = [f"{p}/away", f"{p}/away/set", f"{p}/error", f"{p}/error/attributes"]
        topics += [f"{camera}/{state}" for state in ("available", "online", "recording", "preset")]
        topics += [f"{camera}/event/+", f"{camera}/control/+", f"{camera}/control/+/set"]
        topics += [f"{camera}/record/set", f"{camera}/preset/set", f"{p}/circle/+/record/set"]
        if self.discovery:
            topics += [f"{self.discovery}/status", f"{self.discovery}/+/{p}/+/config"]
        return topics

    async def _listen(self, client: Any) -> None:
        async for message in client.messages:
            payload = message.payload.decode(errors="replace") if isinstance(message.payload, bytes) else ""
            topic = str(message.topic)
            if topic.endswith("/set"):
                if message.retain or not payload.strip():
                    # A command someone left on the broker (not for every reconnect), or one
                    # cleared from it (an empty message): nothing to do.
                    continue
                # Commands talk to cameras, which can be slow: don't hold up the next message.
                task = asyncio.create_task(self.handle(topic, payload))
                self._commands.add(task)
                task.add_done_callback(self._commands.discard)
            elif message.retain or topic == f"{self.discovery}/status":
                await self.handle(topic, payload)

    async def _watch_hub(self) -> None:
        """Sync after anything that changes what Norn publishes; bursts are sent as one."""
        async with self.hub.bus.subscribe() as queue:
            loads: set[asyncio.Task[None]] = set()

            async def mark() -> None:
                while True:
                    event = await queue.get()
                    if event["type"] in ("camera.device", "cameras.changed"):
                        # A new or changed camera: read its controls, so they appear at once.
                        camera = self.hub.cameras.get(event["data"].get("camera", ""))
                        if camera is None or camera.controls is None:
                            task = asyncio.create_task(self._load_controls())
                            loads.add(task)
                            task.add_done_callback(loads.discard)
                    self._dirty.set()

            marker = asyncio.create_task(mark())
            try:
                self._dirty.set()
                while True:
                    await self._dirty.wait()
                    await asyncio.sleep(0.2)
                    self._dirty.clear()
                    await self.sync()
            finally:
                for task in (marker, *loads):
                    task.cancel()

    async def send_stills(self) -> None:
        """Each camera's newest still, to `.../still` (Home Assistant's MQTT camera)."""
        for cid, camera in list(self.hub.cameras.items()):
            if self._send is None:
                return
            if camera.driver is None or not camera.config.enabled:
                continue
            try:
                jpeg = await self.hub.still_jpeg(cid)
            except Exception as e:
                log.debug("%s: no still: %s", cid, e)
                continue
            if jpeg:
                await self._send(f"{self.prefix}/camera/{cid}/still", jpeg)

    async def _send_stills(self) -> None:
        while True:
            await self.send_stills()
            await asyncio.sleep(self.stills)

    async def _load_controls(self, first: bool = False) -> None:
        """Controls are read when someone looks; Home Assistant needs them from the start."""
        missing = [cid for cid, cam in self.hub.cameras.items() if cam.driver and cam.controls is None]
        await asyncio.gather(*(self.hub.refresh_controls(cid) for cid in missing), return_exceptions=True)
        if first:
            self._ready = True
        self._dirty.set()
