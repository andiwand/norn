"""Norn's presets, patrol and reactions, on the demo camera (it pretends to move)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from norn.config import ConfigError
from norn.drivers.base import Event
from norn.hub import Hub
from norn.settings import Settings


def test_presets_api(client: TestClient, settings: Settings) -> None:
    hub: Hub = client.app.state.hub  # type: ignore[attr-defined]
    client.post("/api/cameras/demo/ptz", json={"action": "goto", "preset": "drive"})
    client.post("/api/cameras/demo/controls/ir", json={"value": "on"})
    body = {"name": "Driveway at night", "controls": ["ir"]}
    saved = client.put("/api/cameras/demo/presets/drive-night", json=body).json()
    assert saved["controls"] == {"ir": "on"} and saved["slot"]
    assert "drive-night:" in settings.config_path.read_text()
    camera = client.get("/api/cameras/demo").json()
    assert camera["presets_norn"]["drive-night"]["name"] == "Driveway at night"

    client.post("/api/cameras/demo/ptz", json={"action": "home"})
    client.post("/api/cameras/demo/controls/ir", json={"value": "off"})
    assert client.post("/api/cameras/demo/presets/drive-night/goto").status_code == 200
    driver = hub.get_driver("demo")
    assert driver.position == [0.5, -0.2, 0.3]  # type: ignore[attr-defined]
    controls = {c["id"]: c.get("value") for c in client.get("/api/cameras/demo/controls").json()["controls"]}
    assert controls["ir"] == "on"

    # A camera form that doesn't know about presets keeps them.
    form = {"name": "Demo camera", "driver": "demo", "presets": None}
    assert client.put("/api/cameras/demo", json=form).status_code == 200
    assert client.delete("/api/cameras/demo/presets/drive-night").status_code == 204
    assert client.post("/api/cameras/demo/presets/drive-night/goto").status_code == 404


async def test_reaction_turns_another_camera(settings: Settings) -> None:
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text(
        "cameras:\n"
        "  door: {name: Door, driver: demo}\n"
        "  yard:\n"
        "    name: Yard\n"
        "    driver: demo\n"
        "    presets: {gate: {name: Gate, slot: drive}}\n"
        "    reactions: [{kinds: [person], cameras: [door], presets: [gate], hold_seconds: 30}]\n"
    )
    hub = Hub(settings)
    await hub.start()
    try:
        hub.on_event("door", Event(kind="person", active=True))
        await asyncio.sleep(0.1)
        assert hub.get_driver("yard").position == [0.5, -0.2, 0.3]  # type: ignore[attr-defined]
        assert hub.pilots["yard"].paused_until > 0  # held: no patrol meanwhile
    finally:
        await hub.stop()


async def test_a_move_without_a_stop_stops(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("norn.pilot.MOVE_TIMEOUT", 0.2)
    hub = Hub(settings)
    await hub.start()
    try:
        from norn.drivers.base import PtzCommand

        driver = hub.get_driver("demo")
        move = PtzCommand(action="move", pan=1)
        await driver.ptz(move)
        hub.pilots["demo"].moved(move)
        await asyncio.sleep(0.4)
        assert driver._move is None  # type: ignore[attr-defined]  # stopped by itself
    finally:
        await hub.stop()


async def test_default_preset_after_a_hand_move(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text(
        "cameras:\n"
        "  yard:\n"
        "    name: Yard\n"
        "    driver: demo\n"
        "    presets:\n"
        "      gate: {name: Gate, slot: drive, controls: {ir: 'on'}}\n"
        "      door: {name: Door, slot: door}\n"
        "    default_preset: gate\n"
    )
    hub = Hub(settings)
    await hub.start()
    try:
        pilot, driver = hub.pilots["yard"], hub.get_driver("yard")
        for _ in range(50):  # it goes to the default at the start
            if pilot.at_preset == "gate":
                break
            await asyncio.sleep(0.1)
        assert driver.position == [0.5, -0.2, 0.3]  # type: ignore[attr-defined]

        # Someone steers it by hand: it waits, then returns.
        await pilot.goto("door")
        pilot.manual()
        assert pilot.at_preset == "door"
        pilot.paused_until = 0  # the wait is over
        pilot.last_manual -= 60
        for _ in range(80):
            if pilot.at_preset == "gate":
                break
            await asyncio.sleep(0.1)
        assert driver.position == [0.5, -0.2, 0.3]  # type: ignore[attr-defined]
    finally:
        await hub.stop()


def test_default_preset_api(client: TestClient) -> None:
    client.post("/api/cameras/demo/ptz", json={"action": "goto", "preset": "door"})
    client.put("/api/cameras/demo/presets/porch", json={"name": "Porch"})
    assert client.put("/api/cameras/demo/default-preset", json={"preset": "nope"}).status_code == 404
    camera = client.put("/api/cameras/demo/default-preset", json={"preset": "porch"}).json()
    assert camera["default_preset"] == "porch"
    # A form that doesn't send it keeps it; deleting the preset clears it.
    assert client.put("/api/cameras/demo", json={"name": "Demo camera", "driver": "demo"}).status_code == 200
    assert client.get("/api/cameras/demo").json()["default_preset"] == "porch"
    client.delete("/api/cameras/demo/presets/porch")
    assert client.get("/api/cameras/demo").json()["default_preset"] is None


async def test_default_preset_changes_and_races(settings: Settings) -> None:
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text(
        "cameras:\n"
        "  yard:\n"
        "    name: Yard\n"
        "    driver: demo\n"
        "    presets:\n"
        "      gate: {name: Gate, slot: drive, controls: {ir: 'on'}}\n"
        "      door: {name: Door, slot: door}\n"
        "    default_preset: gate\n"
    )
    hub = Hub(settings)
    await hub.start()
    try:
        pilot, driver = hub.pilots["yard"], hub.get_driver("yard")
        await pilot.goto("gate")
        assert pilot.at_preset == "gate"
        # Another default while it sits at the old one: it goes there.
        await hub.set_default_preset("yard", "door")
        await pilot._to_default()
        assert driver.position == [-0.4, 0.0, 0.0]  # type: ignore[attr-defined]

        # A move while a goto is on its way: the goto doesn't claim the preset.
        real = driver.ptz

        async def slow(command):  # type: ignore[no-untyped-def]
            if command.action == "goto":
                await asyncio.sleep(0.2)
            await real(command)

        driver.ptz = slow  # type: ignore[method-assign]
        from norn.drivers.base import PtzCommand

        going = asyncio.create_task(pilot.goto("gate"))
        await asyncio.sleep(0.05)
        pilot.moved(PtzCommand(action="move", pan=1))
        driver.state["ir"] = "off"  # type: ignore[attr-defined]
        await going
        assert pilot.at_preset is None
        assert driver.state["ir"] == "off"  # type: ignore[attr-defined]  # nor sets its controls
        assert pilot.moving()  # and while the move runs, nothing takes over
        pilot.moved(PtzCommand(action="stop"))
    finally:
        await hub.stop()


async def test_no_default_preset_in_a_slot_the_camera_lost(settings: Settings) -> None:
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text(
        "cameras:\n"
        "  yard:\n"
        "    name: Yard\n"
        "    driver: demo\n"
        "    presets: {gone: {name: Gone, slot: deleted-on-the-camera}}\n"
        "    default_preset: gone\n"
    )
    hub = Hub(settings)
    await hub.start()
    try:
        await hub.refresh_controls("yard")
        pilot, driver = hub.pilots["yard"], hub.get_driver("yard")
        before = list(driver.position)  # type: ignore[attr-defined]
        await pilot._to_default()
        assert driver.position == before and pilot.at_preset is None  # type: ignore[attr-defined]
    finally:
        await hub.stop()


async def test_presets_saved_at_once_take_different_slots(settings: Settings) -> None:
    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text("cameras:\n  yard:\n    name: Yard\n    driver: demo\n")
    hub = Hub(settings)
    await hub.start()
    try:
        driver = hub.get_driver("yard")
        real = driver.save_preset

        async def slow(slot: str, name: str) -> None:
            await asyncio.sleep(0.05)
            await real(slot, name)

        driver.save_preset = slow  # type: ignore[method-assign]
        driver.preset_slots = lambda: ["1", "2", "3"]  # type: ignore[method-assign]
        saved = await asyncio.gather(
            hub.save_preset("yard", "gate", "Gate", None, []),
            hub.save_preset("yard", "door", "Door", None, []),
        )
        assert {p.slot for p in saved} == {"2", "3"}
        assert {p.slot for p in hub.config.cameras["yard"].presets.values()} == {"2", "3"}
        with pytest.raises(ConfigError):
            await hub.save_preset("yard", "../x", "X", None, [])
    finally:
        await hub.stop()


async def test_cancelled_nudge_stops_the_camera(settings: Settings) -> None:
    from norn.detect import Detection

    settings.config_path.parent.mkdir(parents=True)
    settings.config_path.write_text("cameras:\n  yard:\n    name: Yard\n    driver: demo\n")
    hub = Hub(settings)
    await hub.start()
    try:
        pilot, driver = hub.pilots["yard"], hub.get_driver("yard")
        commands: list[str] = []
        real = driver.ptz

        async def ptz(command):  # type: ignore[no-untyped-def]
            commands.append(command.action)
            await real(command)

        driver.ptz = ptz  # type: ignore[method-assign]
        person = [Detection("person", 0.9, (0, 0, 40, 40))]
        task = asyncio.create_task(pilot.nudge(person, 16 / 9))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert commands == ["move", "stop"]
        # Someone steering by hand: following leaves the camera alone.
        pilot.manual()
        await pilot.nudge(person, 16 / 9)
        assert commands == ["move", "stop"]
    finally:
        await hub.stop()
