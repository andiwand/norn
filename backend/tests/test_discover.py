"""Finding cameras: WS-Discovery answers (in each brand's style, after the ONVIF spec), the driver
Norn suggests, asking one address directly, and the API."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from norn import discover
from norn.config import Config
from norn.discover import Found, camera_hosts, check_host, parse_match, probe_message


def match(xaddrs: str, scopes: str, types: str = "dn:NetworkVideoTransmitter tds:Device") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<env:Header><wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action></env:Header>
<env:Body><d:ProbeMatches><d:ProbeMatch>
<wsa:EndpointReference><wsa:Address>urn:uuid:5a1b2c3d-0000-1111-2222-333344445555</wsa:Address></wsa:EndpointReference>
<d:Types>{types}</d:Types>
<d:Scopes>{scopes}</d:Scopes>
<d:XAddrs>{xaddrs}</d:XAddrs>
<d:MetadataVersion>10</d:MetadataVersion>
</d:ProbeMatch></d:ProbeMatches></env:Body></env:Envelope>"""


HIKVISION = match(
    "http://192.168.1.64/onvif/device_service http://[fe80::1]/onvif/device_service",
    "onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/Profile/Streaming "
    "onvif://www.onvif.org/MAC/44:19:b6:00:00:01 onvif://www.onvif.org/hardware/DS-2CD2042WD-I "
    "onvif://www.onvif.org/name/HIKVISION%20DS-2CD2042WD-I onvif://www.onvif.org/location/city/hangzhou",
)
REOLINK = match(
    "http://192.168.1.80:8000/onvif/device_service",
    "onvif://www.onvif.org/Profile/Streaming onvif://www.onvif.org/hardware/E1_Pro "
    "onvif://www.onvif.org/name/Reolink onvif://www.onvif.org/location/country/china",
)
DAHUA = match(
    "http://10.0.0.5/onvif/device_service",
    "onvif://www.onvif.org/location/country/china onvif://www.onvif.org/name/Dahua "
    "onvif://www.onvif.org/hardware/IPC-HDW2431T-AS onvif://www.onvif.org/Profile/Streaming",
)
PRINTER = match("http://192.168.1.28:80/wsd/pnpx-metadata.cgi", "", types="wsdp:Device wprt:PrintDeviceType")


def test_probe_asks_for_video_transmitters() -> None:
    typed, untyped = probe_message(True).decode(), probe_message(False).decode()
    assert "dn:NetworkVideoTransmitter" in typed and "Types" not in untyped
    assert "discovery/Probe" in typed and probe_message() != probe_message()  # a new message id


@pytest.mark.parametrize(
    ("xml", "host", "port", "driver", "name", "hardware", "manufacturer"),
    [
        (
            HIKVISION,
            "192.168.1.64",
            80,
            "hikvision",
            "HIKVISION DS-2CD2042WD-I",
            "DS-2CD2042WD-I",
            "Hikvision",
        ),
        (REOLINK, "192.168.1.80", 8000, "reolink", "Reolink", "E1 Pro", "Reolink"),
        (DAHUA, "10.0.0.5", 80, "dahua", "Dahua", "IPC-HDW2431T-AS", "Dahua"),
    ],
)
def test_matches_name_the_camera_and_its_driver(
    xml: str, host: str, port: int, driver: str, name: str, hardware: str, manufacturer: str
) -> None:
    found = parse_match(xml)
    assert found is not None
    assert (found.host, found.port, found.driver) == (host, port, driver)
    assert (found.name, found.hardware, found.manufacturer) == (name, hardware, manufacturer)
    assert found.id == "urn:uuid:5a1b2c3d-0000-1111-2222-333344445555"


def test_the_address_it_answered_from_wins() -> None:
    xml = match("http://10.9.9.9/onvif/device_service http://192.168.1.70/onvif/device_service", "")
    found = parse_match(xml, sender="192.168.1.70")
    assert found is not None and found.host == "192.168.1.70" and found.driver == "onvif"


def test_printers_and_other_answers_are_not_cameras() -> None:
    assert parse_match(PRINTER) is None
    assert parse_match("<Hello/>") is None
    assert parse_match(match("", "onvif://www.onvif.org/name/x")) is None  # no address


def test_configured_cameras_by_host() -> None:
    config = Config.model_validate(
        {
            "cameras": {
                "door": {"name": "Door", "driver": "hikvision", "host": "192.168.1.64"},
                "yard": {"name": "Yard", "driver": "rtsp", "url": "rtsp://u:p@192.168.1.81:554/s"},
                "demo": {"name": "Demo", "driver": "demo"},
            }
        }
    )
    assert camera_hosts(config.cameras) == {"192.168.1.64": "door", "192.168.1.81": "yard"}


def respond(routes: dict[tuple[str, str], httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/get_params.cgi":
            raise AssertionError("never get_params.cgi: it returns every password")
        return routes.get(
            (request.method, request.url.path + f":{request.url.port or 80}"), httpx.Response(404)
        )

    return httpx.MockTransport(handler)


async def no_reolink_port(*args: object, **kwargs: object) -> None:
    raise OSError("refused")


async def test_check_host_knows_a_foscam_cgi_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.open_connection", no_reolink_port)
    transport = respond(
        {
            ("GET", "/get_status.cgi:80"): httpx.Response(
                200, text="var sys_ver='0.41.2.51';\nvar alias='cam1';"
            ),
            ("GET", "/branding/branding.js:80"): httpx.Response(
                200, text='var branding_settings={brand:"supra",product:"IPC-1A"};'
            ),
        }
    )
    found = await check_host("192.168.1.21", transport=transport)
    assert found is not None
    assert (found.driver, found.manufacturer, found.hardware, found.name) == (
        "foscam",
        "supra",
        "IPC-1A",
        "cam1",
    )


async def test_check_host_knows_onvif_hikvision_and_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.open_connection", no_reolink_port)
    clock = httpx.Response(200, text="<tt:UTCDateTime><tt:Time/></tt:UTCDateTime>")
    onvif = await check_host("10.0.0.5", transport=respond({("POST", "/onvif/device_service:8000"): clock}))
    assert onvif is not None and (onvif.driver, onvif.port) == ("onvif", 8000)
    challenge = httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="IP Camera(58649)"'})
    hik = await check_host("10.0.0.6", transport=respond({("GET", "/ISAPI/System/deviceInfo:80"): challenge}))
    assert hik is not None and hik.driver == "hikvision"
    assert await check_host("10.0.0.7", transport=respond({})) is None
    with pytest.raises(ValueError):
        await check_host("http://x/; rm", transport=respond({}))


def test_the_api_marks_cameras_already_added(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.post(
        "/api/cameras",
        json={"id": "door", "name": "Door", "driver": "hikvision", "host": "192.168.1.64", "password": "x"},
    )

    async def found(seconds: float = 3.0, hosts: object = None) -> list[Found]:
        return [
            Found(
                host="192.168.1.64",
                port=80,
                xaddr="http://192.168.1.64/onvif/device_service",
                driver="hikvision",
            ),
            Found(host="192.168.1.80", port=8000, xaddr="http://192.168.1.80:8000/onvif/device_service"),
        ]

    async def one(host: str, timeout: float = 3.0) -> Found | None:
        if not discover.HOST.fullmatch(host):
            raise ValueError("an IP address or host name")
        return (
            Found(host=host, port=80, xaddr=f"http://{host}/", driver="reolink")
            if host == "192.168.1.80"
            else None
        )

    monkeypatch.setattr(discover, "discover", found)
    monkeypatch.setattr(discover, "check_host", one)
    got = client.get("/api/discover?seconds=1").json()
    assert [(d["host"], d["camera"]) for d in got["devices"]] == [
        ("192.168.1.64", "door"),
        ("192.168.1.80", None),
    ]
    assert isinstance(got["container"], bool)
    assert client.get("/api/discover/192.168.1.80").json()["device"]["driver"] == "reolink"
    assert client.get("/api/discover/192.168.1.99").json() == {"device": None}
    assert client.get("/api/discover/a;b").status_code == 422
