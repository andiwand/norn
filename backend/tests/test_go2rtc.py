"""Syncing streams with go2rtc's API, against a fake go2rtc."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from norn.events import EventBus
from norn.go2rtc import Go2rtc, Go2rtcUnavailableError
from norn.settings import Settings


def fake(settings: Settings, streams: dict[str, str], failing: set[str]) -> tuple[Go2rtc, list[str]]:
    """An external go2rtc with `streams`; requests for a name in `failing` fail."""
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("name") or request.url.params.get("src", "")
        if request.method == "GET":
            return httpx.Response(200, json={k: {} for k in streams})
        requests.append(f"{request.method} {name}")
        if name in failing:
            return httpx.Response(500, text="no")
        if request.method == "PUT":
            streams[name] = request.url.params["src"]
        else:
            streams.pop(name, None)
        return httpx.Response(200)

    go2rtc = Go2rtc(replace(settings, go2rtc_mode="external"), EventBus())
    go2rtc._client = httpx.AsyncClient(base_url="http://go2rtc", transport=httpx.MockTransport(handle))

    async def up(timeout: float = 15) -> bool:
        return True

    go2rtc._wait_api = up  # type: ignore[method-assign]
    return go2rtc, requests


async def test_leaves_others_streams_alone(settings: Settings) -> None:
    streams = {"frigate_door": "rtsp://frigate", "yard": "rtsp://old"}
    go2rtc, _ = fake(settings, streams, set())
    go2rtc._wanted = {"yard": "rtsp://yard", "yard_sub": "rtsp://yard/sub"}
    await go2rtc._sync_when_ready()
    assert streams == {"frigate_door": "rtsp://frigate", "yard": "rtsp://yard", "yard_sub": "rtsp://yard/sub"}
    await go2rtc.apply({"yard": "rtsp://yard"})  # a stream Norn put there goes
    assert streams == {"frigate_door": "rtsp://frigate", "yard": "rtsp://yard"}


async def test_a_failed_request_is_tried_again(settings: Settings) -> None:
    streams: dict[str, str] = {}
    failing = {"a"}
    go2rtc, requests = fake(settings, streams, failing)
    go2rtc.ready.set()
    with pytest.raises(Go2rtcUnavailableError):
        await go2rtc.apply({"a": "rtsp://a", "b": "rtsp://b"})
    assert streams == {"b": "rtsp://b"}  # the rest went ahead
    failing.clear()
    requests.clear()
    await go2rtc.apply({"a": "rtsp://a", "b": "rtsp://b"})
    assert streams == {"a": "rtsp://a", "b": "rtsp://b"} and requests == ["PUT a"]
