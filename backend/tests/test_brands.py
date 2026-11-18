"""The brand drivers against canned answers in each vendor's documented format.

No real cameras here: these pin down parsing and the requests the drivers send.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from norn.drivers import DRIVERS
from norn.drivers.base import Capability, PtzCommand
from norn.drivers.tapo import find
from norn.drivers.unifi import go2rtc_url


def make(driver: str, **options: object):
    cls = DRIVERS[driver]
    return cls("cam", cls.Options.model_validate(options))


def mock(
    driver: Any, base_url: str, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Route the driver's HTTP client to `handler`; return the list of requests it sends."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    driver.client = httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(record))
    return seen


async def test_dahua() -> None:
    d = make("dahua", host="10.0.0.9", password="p#")
    answers = {
        "getDeviceType": "type=IPC-HDW2431T-AS\r\n",
        "getSoftwareVersion": "version=2.800.0000000.25.R,build:2021-07-02\r\n",
        "getSerialNo": "sn=ABC123\r\n",
        "getVendor": "vendor=Amcrest\r\n",
        "getMachineName": "name=Porch\r\n",
        "getStatus": "status.MoveStatus=Idle\r\n",
        "getPresets": (
            "presets[0].Index=1\r\npresets[0].Name=Gate\r\npresets[1].Index=2\r\npresets[1].Name=\r\n"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        if request.url.path.endswith("configManager.cgi"):
            if q.get("action") == "setConfig":
                return httpx.Response(200, text="OK\r\n")
            if q["name"] == "VideoInOptions":
                return httpx.Response(
                    200,
                    text="table.VideoInOptions[0].DayNightColor=1\r\n"
                    "table.VideoInOptions[0].Flip=false\r\n"
                    "table.VideoInOptions[0].Brightness=50\r\n",
                )
            return httpx.Response(200, text="table.MotionDetect[0].Enable=true\r\n")
        if q.get("action") in ("start", "stop"):
            return httpx.Response(200, text="OK\r\n")
        return httpx.Response(200, text=answers[q["action"]])

    seen = mock(d, "http://10.0.0.9/cgi-bin/", handler)
    await d.start()
    assert Capability.PTZ in d.capabilities()
    info = await d.info()
    assert (info.manufacturer, info.model, info.serial, info.name) == (
        "Amcrest",
        "IPC-HDW2431T-AS",
        "ABC123",
        "Porch",
    )
    assert info.firmware == "2.800.0000000.25.R (2021-07-02)"
    controls = {c.id: c.value for c in await d.controls()}
    assert controls == {"daynight": "1", "flip": False, "brightness": 50, "motion": True}
    assert [(p.id, p.name) for p in await d.presets()] == [("1", "Gate"), ("2", "Preset 2")]
    await d.set_control("flip", True)
    assert seen[-1].url.params["VideoInOptions[0].Flip"] == "true"
    await d.ptz(PtzCommand(action="move", pan=-0.5, tilt=0.5))
    assert [seen[-1].url.params[k] for k in ("code", "arg1", "arg2")] == ["LeftUp", "4", "4"]
    await d.ptz(PtzCommand(action="move", pan=0.5))
    assert [seen[-1].url.params[k] for k in ("code", "arg1", "arg2")] == ["Right", "0", "4"]
    assert d.streams()[1].source == "rtsp://admin:p%23@10.0.0.9:554/cam/realmonitor?channel=1&subtype=1"


async def test_axis() -> None:
    d = make("axis", host="10.0.0.8", password="pw")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("basicdeviceinfo.cgi"):
            props = {
                "Brand": "AXIS",
                "ProdNbr": "M3106-LVE Mk II",
                "Version": "10.12.199",
                "SerialNumber": "ACCC8E",
            }
            return httpx.Response(200, json={"data": {"propertyList": props}})
        if path.endswith("param.cgi"):
            if request.url.params["action"] == "update":
                return httpx.Response(200, text="OK")
            if request.url.params["group"] == "Properties.PTZ":
                return httpx.Response(200, text="root.Properties.PTZ.PTZ=yes\n")
            return httpx.Response(200, text="root.ImageSource.I0.DayNight.IrCutFilter=auto\n")
        if request.url.params.get("query") == "presetposcam":
            return httpx.Response(200, text="presetposno1=Gate\npresetposno2=Drive\n")
        return httpx.Response(200, text="")

    seen = mock(d, "http://10.0.0.8/axis-cgi/", handler)
    await d.start()
    info = await d.info()
    assert (info.manufacturer, info.model, info.firmware) == ("AXIS", "M3106-LVE Mk II", "10.12.199")
    assert [(c.id, c.value) for c in await d.controls()] == [("ircut", "auto")]
    assert [p.name for p in await d.presets()] == ["Gate", "Drive"]
    await d.ptz(PtzCommand(action="move", pan=0.5, tilt=-0.25))
    assert seen[-1].url.params["continuouspantiltmove"] == "50,-25"
    await d.set_control("ircut", "yes")
    assert seen[-1].url.params["ImageSource.I0.DayNight.IrCutFilter"] == "yes"
    ircut = (await d.controls())[0]
    assert {o.value: o.label for o in ircut.options or []}["yes"] == "Day (filter on)"
    await d.save_preset("norn-gate", "Gate")
    assert seen[-1].url.params["setserverpresetname"] == "norn-gate"


async def test_foscam_hd() -> None:
    d = make("foscam-hd", host="10.0.0.7", password="pw")
    xml = {
        "getDevInfo": "<productName>FI9826P</productName><firmwareVer>2.x.1.110</firmwareVer>"
        "<serialNo>X1</serialNo><mac>A0B1C2D3E4F5</mac><devName>Hall</devName>",
        "getInfraLedConfig": "<mode>0</mode>",
        "getMirrorAndFlipSetting": "<isMirror>0</isMirror><isFlip>1</isFlip>",
        "getPTZPresetPointList": "<cnt>2</cnt><point0>TopMost</point0><point1>Door</point1>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cmd = request.url.params["cmd"]
        if request.url.params["pwd"] != "pw":
            return httpx.Response(200, text="<CGI_Result><result>-2</result></CGI_Result>")
        return httpx.Response(200, text=f"<CGI_Result><result>0</result>{xml.get(cmd, '')}</CGI_Result>")

    seen = mock(d, "http://10.0.0.7:88/cgi-bin/", handler)
    info = await d.info()
    assert (info.model, info.firmware, info.mac, info.name) == (
        "FI9826P",
        "2.x.1.110",
        "a0:b1:c2:d3:e4:f5",
        "Hall",
    )
    assert {c.id: c.value for c in await d.controls()} == {
        "irmode": "0",
        "ir": None,
        "mirror": False,
        "flip": True,
    }
    assert [p.name for p in await d.presets()] == ["TopMost", "Door"]
    await d.ptz(PtzCommand(action="move", pan=0.6))
    assert seen[-1].url.params["cmd"] == "ptzMoveRight"
    d.options.password = "wrong"
    assert (await d.info()).error == "getDevInfo: wrong username or password"


async def test_unifi() -> None:
    cls = DRIVERS["unifi"]
    events: list[tuple[str, dict[str, Any]]] = []
    options = cls.Options.model_validate({"host": "10.0.0.1", "api_key": "k", "camera": "Garden"})
    d = cls("garden", options, lambda kind, data: events.append((kind, data)))
    offline = True
    camera = {
        "id": "abc",
        "name": "Garden",
        "state": "CONNECTED",
        "marketName": "G4 Bullet",
        "mac": "AA",
        "ledSettings": {"isEnabled": True},
        "micVolume": 80,
        "featureFlags": {"isPtz": False},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/cameras"):
            return httpx.Response(200, json=[{"id": "zzz", "name": "Door"}, camera])
        if offline:
            return httpx.Response(503)
        if path.endswith("/rtsps-stream"):
            if request.method == "GET":
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "high": "rtsps://10.0.0.1:7441/tok1?enableSrtp",
                    "low": "rtsps://10.0.0.1:7441/tok2?enableSrtp",
                },
            )
        if request.method == "PATCH":
            return httpx.Response(200, json=camera)
        return httpx.Response(200, json=camera)

    seen = mock(d, "https://10.0.0.1/proxy/protect/integration/v1", handler)
    await d.start()  # the console is offline at start: no streams yet
    assert d.streams() == []
    offline = False
    info = await d.info()
    assert (info.model, info.name) == ("G4 Bullet", "Garden")
    assert [s.source for s in d.streams()] == ["rtspx://10.0.0.1:7441/tok1", "rtspx://10.0.0.1:7441/tok2"]
    assert events == [("camera.streams", {"camera": "garden"})]
    assert {c.id: c.value for c in await d.controls()} == {"led": True, "mic": 80}
    await d.set_control("led", False)
    assert seen[-1].method == "PATCH" and b'"isEnabled":false' in seen[-1].content.replace(b" ", b"")
    await d.set_control("mic", 150)
    assert events[-1] == ("camera.control", {"camera": "garden", "control": "mic", "value": 100})
    assert go2rtc_url("rtsp://x/y") == "rtsp://x/y"


async def test_tapo(monkeypatch: pytest.MonkeyPatch) -> None:
    d = make("tapo", host="10.0.0.6", camera_username="cam", camera_password="c#p", cloud_password="cloud")

    class FakeTapo:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...]]] = []

        def __getattr__(self, name: str) -> Callable[..., Any]:
            def call(*args: Any) -> Any:
                self.calls.append((name, args))
                return {
                    "getBasicInfo": {
                        "device_info": {
                            "basic_info": {
                                "device_model": "C210",
                                "sw_version": "1.3.11",
                                "mac": "AA-BB-CC-DD-EE-FF",
                                "device_alias": "Kids",
                            }
                        }
                    },
                    "getDayNightMode": "auto",
                    "getPrivacyMode": {"enabled": "off"},
                    "getLED": {"enabled": "on"},
                    "getPresets": {"1": "Bed", "2": "Door"},
                    "isUpdateAvailable": {
                        "result": {
                            "responses": [
                                {},
                                {
                                    "result": {
                                        "cloud_config": {
                                            "upgrade_info": {"version": "1.4.2"},
                                            "need_to_upgrade": True,
                                        }
                                    }
                                },
                            ]
                        }
                    },
                }.get(name)

            return call

    fake = FakeTapo()
    monkeypatch.setattr(d, "_client", lambda: fake)
    info = await d.info()
    assert (info.model, info.firmware, info.mac, info.name) == ("C210", "1.3.11", "aa:bb:cc:dd:ee:ff", "Kids")
    assert Capability.PTZ in d.capabilities()
    controls = {c.id: c.value for c in await d.controls()}
    assert controls["daynight"] == "auto" and controls["privacy"] is False and controls["led"] is True
    assert [p.name for p in await d.presets()] == ["Bed", "Door"]
    await d.ptz(PtzCommand(action="move", pan=1))
    assert fake.calls[-1] == ("moveMotor", (30, 0))
    assert await d.firmware_online_check() == "1.4.2"
    assert d.streams()[0].source == "rtsp://cam:c%23p@10.0.0.6:554/stream1"
    assert find({"a": [{"b": {"c": 1}}]}, "c") == 1


async def test_tapo_pauses_after_a_failed_login(monkeypatch: pytest.MonkeyPatch) -> None:
    d = make("tapo", host="10.0.0.6", camera_username="cam", camera_password="pw", cloud_password="bad")
    logins = 0

    def login() -> Any:
        nonlocal logins
        logins += 1
        raise Exception("Invalid authentication data")

    monkeypatch.setattr(d, "_client", login)
    assert [c.id for c in await d.controls()] == ["alarm"]  # every getter fails
    assert logins == 1  # one login, then a pause instead of a burst that locks the account
    assert (await d.info()).error == "login failed: Invalid authentication data"
    assert logins == 1


def test_hikvision_event_kinds() -> None:
    assert make("hikvision", host="10.0.0.3", password="p").event_kinds() == ["motion", "person", "vehicle"]
