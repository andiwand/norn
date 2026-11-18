"""MQTT: what Norn publishes for Home Assistant, and the commands it takes. Without a broker: the
publisher is a dict, and messages go to `handle` directly."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from norn.drivers.base import DeviceInfo, Event
from norn.hub import Hub
from norn.mqtt import Broker, Mqtt
from norn.settings import Settings

CONFIG = (
    "cameras:\n"
    "  yard:\n"
    "    name: Yard\n"
    "    driver: demo\n"
    "    presets: {gate: {name: Gate, slot: drive}}\n"
    "circles:\n"
    "  outside: {name: Outside, cameras: [yard]}\n"
)


@pytest.fixture
async def hub(settings: Settings) -> AsyncIterator[Hub]:
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text(CONFIG)
    hub = Hub(replace(settings, mqtt_url="mqtt://norn:p%40ss@broker.local"))
    await hub.start()
    if hub.mqtt._task:
        hub.mqtt._task.cancel()
    await hub.refresh_controls("yard")
    try:
        yield hub
    finally:
        await hub.stop()


@pytest.fixture
def broker(hub: Hub) -> dict[str, str]:
    """What the broker keeps (retained topics), as the hub's MQTT publisher fills it."""
    retained: dict[str, str] = {}

    async def publish(topic: str, payload: str) -> None:
        if payload:
            retained[topic] = payload
        else:
            retained.pop(topic, None)

    hub.mqtt._publish = publish
    hub.mqtt._ready = True
    return retained


def config(broker: dict[str, str], component: str, object_id: str) -> dict:
    return json.loads(broker[f"homeassistant/{component}/norn/{object_id}/config"])


def test_broker_url() -> None:
    b = Broker.parse("mqtt://norn:p%40ss@broker.local")
    assert (b.host, b.port, b.tls, b.username, b.password) == ("broker.local", 1883, False, "norn", "p@ss")
    assert Broker.parse("mqtts://broker.local").port == 8883
    assert Broker.parse("broker.local:1884").port == 1884
    with pytest.raises(ValueError):
        Broker.parse("http://broker.local")


async def test_discovery(hub: Hub, broker: dict[str, str]) -> None:
    await hub.mqtt.sync()
    away = config(broker, "switch", "away")
    assert away["command_topic"] == "norn/away/set" and away["device"]["name"] == "Norn"
    assert broker["norn/away"] == "OFF"

    record = config(broker, "button", "yard_record")
    assert record["device"]["identifiers"] == ["norn_yard"] and record["device"]["via_device"] == "norn"
    assert record["availability_topic"] == "norn/status"
    assert broker["norn/camera/yard/recording"] == "OFF"
    assert config(broker, "button", "circle_outside_record")["name"] == "Outside: record"

    # The driver's controls, by kind.
    ir = config(broker, "select", "yard_control_ir")
    assert ir["options"] == ["Auto", "On", "Off"] and ir["icon"] == "mdi:weather-night"
    assert broker["norn/camera/yard/control/ir"] in ir["options"]
    brightness = config(broker, "number", "yard_control_brightness")
    assert (brightness["min"], brightness["max"], brightness["unit_of_measurement"]) == (0, 100, "%")
    assert config(broker, "switch", "yard_control_spotlight")["state_topic"] == (
        "norn/camera/yard/control/spotlight"
    )
    assert "state_topic" not in config(broker, "button", "yard_control_siren")

    preset = config(broker, "select", "yard_preset")
    assert preset["options"] == ["Gate"] and broker["norn/camera/yard/preset"] == "None"


async def test_events(hub: Hub, broker: dict[str, str]) -> None:
    await hub.mqtt.sync()
    kinds = [t.rsplit("/", 1)[1] for t in broker if t.startswith("norn/camera/yard/event/")]
    assert "motion" in kinds
    hub.on_event("yard", Event(kind="motion", active=True))
    await hub.mqtt.sync()
    assert broker["norn/camera/yard/event/motion"] == "ON"
    assert config(broker, "binary_sensor", "yard_event_motion")["device_class"] == "motion"


async def test_commands(hub: Hub, broker: dict[str, str]) -> None:
    mqtt = hub.mqtt
    await mqtt.handle("norn/camera/yard/control/spotlight/set", "ON")
    await mqtt.handle("norn/camera/yard/control/ir/set", "Off")
    await mqtt.handle("norn/camera/yard/control/brightness/set", "30.0")
    state = hub.get_driver("yard").state  # type: ignore[attr-defined]
    assert (state["spotlight"], state["ir"], state["brightness"]) == (True, "off", 30)

    await mqtt.handle("norn/camera/yard/preset/set", "Gate")
    assert hub.preset_of("yard") == "gate"
    await mqtt.sync()
    assert broker["norn/camera/yard/preset"] == "Gate"
    assert broker["norn/camera/yard/control/ir"] == "Off"

    await mqtt.handle("norn/away/set", "ON")
    assert hub.away and hub.config.away.active
    await mqtt.sync()
    assert broker["norn/away"] == "ON"
    await mqtt.handle("norn/away/set", "OFF")
    assert not hub.away

    # Bad commands are logged, never raised.
    await mqtt.handle("norn/camera/yard/control/ir/set", "Sometimes")
    await mqtt.handle("norn/camera/nope/record/set", "PRESS")
    await mqtt.handle("norn/camera/yard/record/set", '{"trigger": "Bad Trigger!"}')
    await mqtt.handle("norn/away/set", "maybe")
    assert state["ir"] == "off"


async def test_removed_entities_are_cleared(hub: Hub, broker: dict[str, str]) -> None:
    # Left on the broker by an earlier run, for a camera that is gone.
    old = "homeassistant/button/norn/porch_record/config"
    broker[old] = "{}"
    await hub.mqtt.handle(old, "{}")
    await hub.mqtt.handle("homeassistant/button/other/porch_record/config", "{}")  # not Norn's
    await hub.mqtt.sync()
    assert old not in broker
    assert "homeassistant/button/norn/yard_record/config" in broker

    await hub.remove_circle("outside")
    await hub.mqtt.sync()
    assert "homeassistant/button/norn/circle_outside_record/config" not in broker


async def test_stills(hub: Hub, broker: dict[str, str], settings: Settings) -> None:
    # Off unless asked for: no camera entity.
    await hub.mqtt.sync()
    assert not any(t.startswith("homeassistant/camera/") for t in broker)

    mqtt = Mqtt(replace(settings, mqtt_url="mqtt://broker.local", mqtt_stills=2), hub)
    assert mqtt.stills == 5  # at least 5 s
    camera = json.loads(mqtt.desired()["homeassistant/camera/norn/yard_still/config"])
    assert camera["topic"] == "norn/camera/yard/still"

    sent: dict[str, bytes] = {}

    async def send(topic: str, payload: bytes) -> None:
        sent[topic] = payload

    async def still_jpeg(camera_id: str) -> bytes:
        return b"\xff\xd8 " + camera_id.encode()

    mqtt._send = send
    hub.still_jpeg = still_jpeg  # type: ignore[method-assign]
    await mqtt.send_stills()
    assert sent == {"norn/camera/yard/still": b"\xff\xd8 yard"}


async def test_failed_command(hub: Hub, broker: dict[str, str]) -> None:
    await hub.mqtt.sync()
    assert (
        broker["norn/error"] == "None"
        and config(broker, "sensor", "error")["entity_category"] == "diagnostic"
    )
    hub.mqtt._sent["norn/camera/yard/control/ir"] = "stale"  # Home Assistant thinks it changed

    await hub.mqtt.handle("norn/camera/yard/control/ir/set", "Sometimes")
    await hub.mqtt.sync()
    assert "not an option" in broker["norn/error"]
    attributes = json.loads(broker["norn/error/attributes"])
    assert attributes["command"] == "norn/camera/yard/control/ir/set Sometimes" and attributes["time"]
    assert broker["norn/camera/yard/control/ir"] == "Auto"  # the true state, again
    assert hub.mqtt.status()["last_error"]["error"] == broker["norn/error"]


async def test_offline_camera(hub: Hub, broker: dict[str, str]) -> None:
    await hub.mqtt.sync()
    assert broker["norn/camera/yard/available"] == "online"
    spotlight = config(broker, "switch", "yard_control_spotlight")
    assert spotlight["availability_mode"] == "all"
    assert [a["topic"] for a in spotlight["availability"]] == ["norn/status", "norn/camera/yard/available"]
    assert "yard/available" in str(config(broker, "select", "yard_preset")["availability"])
    # What doesn't talk to the camera's controls depends on Norn only.
    assert config(broker, "button", "yard_record")["availability_topic"] == "norn/status"
    assert config(broker, "binary_sensor", "yard_online")["availability_topic"] == "norn/status"

    hub.cameras["yard"].device = DeviceInfo(online=False, error="no answer")
    await hub.mqtt.sync()
    assert broker["norn/camera/yard/available"] == "offline"
    assert broker["norn/camera/yard/online"] == "OFF"


async def test_status(hub: Hub, settings: Settings) -> None:
    assert Mqtt(settings, hub).status() == {"enabled": False}
    status = hub.mqtt.status()
    assert status["enabled"] and status["broker"] == "broker.local:1883" and not status["connected"]
    assert "p@ss" not in json.dumps(status)


async def test_listen_skips_left_and_cleared_commands(hub: Hub, broker: dict[str, str]) -> None:
    class Message:
        def __init__(self, topic: str, payload: bytes, retain: bool) -> None:
            self.topic, self.payload, self.retain = topic, payload, retain

    class Client:
        async def _messages(self):  # type: ignore[no-untyped-def]
            yield Message("norn/camera/yard/control/brightness/set", b"7", True)  # left retained
            yield Message("norn/camera/yard/control/brightness/set", b"", False)  # cleared
            yield Message("norn/camera/yard/control/spotlight/set", b"ON", False)  # a real one

        @property
        def messages(self):  # type: ignore[no-untyped-def]
            return self._messages()

    state = hub.get_driver("yard").state  # type: ignore[attr-defined]
    brightness = state["brightness"]
    await hub.mqtt._listen(Client())
    await asyncio.gather(*hub.mqtt._commands)
    assert state["brightness"] == brightness and state["spotlight"] is True
    assert hub.mqtt.last_error is None


async def test_nothing_is_cleared_while_the_config_has_an_error(hub: Hub, broker: dict[str, str]) -> None:
    old = "homeassistant/button/norn/porch_record/config"
    broker[old] = "{}"
    await hub.mqtt.handle(old, "{}")
    hub.config_error = "a typo"  # the hub then runs without the cameras of the file
    await hub.mqtt.sync()
    assert old in broker
    hub.config_error = None
    await hub.mqtt.sync()
    assert old not in broker


async def test_offline_cameras_keep_their_entities(hub: Hub, broker: dict[str, str]) -> None:
    mqtt, camera = hub.mqtt, hub.cameras["yard"]
    # Before the camera answered: its controls and events from an earlier run stay.
    camera.controls, camera.device = None, None
    mqtt._kinds.clear()
    found = [
        "homeassistant/switch/norn/yard_control_old/config",
        "norn/camera/yard/control/old",
        "homeassistant/binary_sensor/norn/yard_event_animal/config",
        "norn/camera/yard/event/animal",
    ]
    for topic in found:
        broker[topic] = "x"
        await mqtt.handle(topic, "x")
    await mqtt.sync()
    assert all(t in broker for t in found)

    # Online: what it reports now counts, and the rest goes.
    camera.device = DeviceInfo(online=True)
    await hub.refresh_controls("yard")
    await mqtt.sync()
    assert not any(t in broker for t in found)

    # A kind the camera knows only while connected (Reolink's AI) stays while it is offline.
    driver = hub.get_driver("yard")
    assert "homeassistant/binary_sensor/norn/yard_event_person/config" in broker
    driver.event_kinds = lambda: ["motion"]  # type: ignore[method-assign]
    camera.device = DeviceInfo(online=False)
    await mqtt.sync()
    assert "homeassistant/binary_sensor/norn/yard_event_person/config" in broker


async def test_record_commands(hub: Hub, broker: dict[str, str]) -> None:
    clips: list[tuple[str, str, int | None]] = []

    async def record_clip(camera: str, trigger: str = "manual", seconds: int | None = None) -> None:
        clips.append((camera, trigger, seconds))

    hub.recorder.record_clip = record_clip  # type: ignore[method-assign]
    mqtt = hub.mqtt
    await mqtt.handle("norn/camera/yard/record/set", "PRESS")
    await mqtt.handle("norn/camera/yard/record/set", '{"trigger": "doorbell", "seconds": 30}')
    assert clips == [("yard", "mqtt", None), ("yard", "doorbell", 30)]
    for bad in ('{"seconds": -1}', '{"seconds": 100000}', '{"trigger": "continuous"}', '{"seconds": "x"}'):
        await mqtt.handle("norn/camera/yard/record/set", bad)
        assert mqtt.last_error and bad in mqtt.last_error["command"]
    assert len(clips) == 2

    # A circle records every camera it can, and says which failed.
    hub.circle_members = lambda circle_id: ["gone", "yard"]  # type: ignore[method-assign]
    await mqtt.handle("norn/circle/outside/record/set", "PRESS")
    assert clips[-1] == ("yard", "mqtt", None)
    assert "gone" in mqtt.last_error["error"]


def test_subscriptions(hub: Hub) -> None:
    from paho.mqtt.client import topic_matches_sub

    topics = hub.mqtt.subscriptions()
    for wanted in ("norn/camera/yard/control/ir/set", "norn/camera/yard/event/person", "norn/away"):
        assert any(topic_matches_sub(t, wanted) for t in topics)
    assert not any(topic_matches_sub(t, "norn/camera/yard/still") for t in topics)  # Norn's own JPEGs
