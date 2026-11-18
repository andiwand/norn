"""The hub: config errors at start, drivers whose streams come late, resource readings."""

from __future__ import annotations

import asyncio

import pytest

from norn.config import CameraConfig, ConfigError
from norn.hub import Hub, reachable
from norn.settings import Settings


async def test_a_broken_config_at_start_is_never_overwritten(settings: Settings) -> None:
    settings.config_path.parent.mkdir(parents=True)
    broken = "# my notes\ncameras:\n  a: {name: A, driver: demo, record: sometimes}\n"
    settings.config_path.write_text(broken)
    hub = Hub(settings)
    await hub.start()
    try:
        assert hub.config_error
        with pytest.raises(ConfigError):
            await hub.put_camera("c", CameraConfig(name="C", driver="demo"))
        assert settings.config_path.read_text() == broken and hub.config_error
        # Fixed by hand: the next change builds on the fix.
        settings.config_path.write_text(broken.replace("sometimes", "continuous"))
        await hub.put_camera("c", CameraConfig(name="C", driver="demo"))
        assert list(hub.cameras) == ["a", "c"] and hub.config_error is None
        assert "# my notes" in settings.config_path.read_text()
    finally:
        await hub.stop()


async def test_streams_from_a_driver_go_out_again(settings: Settings) -> None:
    hub = Hub(settings)
    await hub.start()
    try:
        async with hub.bus.subscribe() as queue:
            hub.get_driver("demo").emit("camera.streams", {})
            types = set()
            while "cameras.changed" not in types:
                types.add((await asyncio.wait_for(queue.get(), 2))["type"])
            assert "camera.streams" in types
    finally:
        await hub.stop()


async def test_reachable_takes_odd_addresses() -> None:
    assert await reachable("http://fe80::1:80/") is None


async def test_resources_measure_at_most_every_few_seconds(settings: Settings) -> None:
    hub = Hub(settings)
    first = await hub.resources()
    assert await hub.resources() is first  # a second page asking at once gets the same window


async def test_objects_go_out_in_fractions_of_the_picture(settings: Settings) -> None:
    """The camera page draws Norn's boxes over the video: in fractions of the picture (the
    detector's square input holds the still from the top left), only when they change, and one
    empty message after the last box clears them."""
    from norn.detect import OBJECT_SIZE, Detection

    hub = Hub(settings)
    await hub.start()
    try:
        await hub.put_camera("c", CameraConfig(name="C", driver="demo"))
        camera = hub.cameras["c"]
        hub.still_aspect = lambda camera: 16 / 9  # type: ignore[method-assign]
        tall = OBJECT_SIZE * 9 / 16  # the still's height in the square
        sheet = Detection("person", 0.671, (OBJECT_SIZE / 2, tall / 4, OBJECT_SIZE, tall))
        async with hub.bus.subscribe() as queue:
            hub._publish_objects(camera, [(sheet, "still")])
            wobbled = Detection("person", 0.69, (OBJECT_SIZE / 2 + 1, tall / 4, OBJECT_SIZE, tall))
            hub._publish_objects(camera, [(wobbled, "still")])  # no visible change: quiet
            hub._publish_objects(camera, [])
            hub._publish_objects(camera, [])  # nothing new: quiet
            hub.bus.publish("end", {})
            got = []
            while (event := await asyncio.wait_for(queue.get(), 2))["type"] != "end":
                if event["type"] == "camera.objects":
                    got.append(event["data"]["objects"])
        assert got == [
            [{"kind": "person", "score": 0.67, "box": [0.5, 0.25, 1.0, 1.0], "status": "still"}],
            [],
        ]
    finally:
        await hub.stop()
