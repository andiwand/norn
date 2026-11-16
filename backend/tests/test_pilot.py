"""Norn's presets, patrol and reactions, on the demo camera (it pretends to move)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

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
