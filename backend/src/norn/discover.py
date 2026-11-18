"""Finding cameras in the network: ONVIF's WS-Discovery.

A probe goes to the multicast group 239.255.255.250:3702 (UDP); ONVIF devices answer with a
ProbeMatch to the sender: their address (`XAddrs`, the URL of their device service) and scopes,
which name the device (`onvif://www.onvif.org/name/...`), its hardware and location. Norn
reads the brand from them and suggests a driver.

Multicast doesn't cross Docker's bridge network, VPNs or subnets: there `check_host` asks one
address directly, over TCP, what camera it is (ONVIF, and the brands Norn has drivers for).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import socket
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .onvif import value, values

log = logging.getLogger("norn.discover")

GROUP = ("239.255.255.250", 3702)

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header>
<w:MessageID>uuid:{id}</w:MessageID>
<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
</e:Header>
<e:Body><d:Probe>{types}</d:Probe></e:Body>
</e:Envelope>"""

# Brand words in a device's scopes -> the driver that knows it best.
BRANDS: list[tuple[tuple[str, ...], str]] = [
    (("hikvision", "hikvison", "annke", "hilook", "hiwatch"), "hikvision"),
    (("reolink",), "reolink"),
    (("dahua", "amcrest", "lorex"), "dahua"),
    (("axis",), "axis"),
    (("tapo", "tp-link", "tplink"), "tapo"),
    (("foscam",), "foscam-hd"),
]


@dataclass
class Found:
    """A device that answered."""

    host: str
    port: int
    xaddr: str  # its ONVIF device service
    name: str | None = None
    hardware: str | None = None
    location: str | None = None
    manufacturer: str | None = None
    driver: str = "onvif"  # the suggested one
    id: str | None = None  # its WS-Discovery endpoint (uuid), the same across answers
    camera: str | None = None  # the configured camera at this address, if any
    scopes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        del data["scopes"]
        return data


def probe_message(types: bool = True) -> bytes:
    """A Probe; with `types`, for video transmitters only (some cameras only answer one of the
    two, so Norn sends both)."""
    return PROBE.format(
        id=uuid.uuid4(), types="<d:Types>dn:NetworkVideoTransmitter</d:Types>" if types else ""
    ).encode()


def parse_match(xml: str, sender: str | None = None) -> Found | None:
    """A ProbeMatch answer, or None when it isn't one (or names no address)."""
    if "ProbeMatch" not in xml:
        return None
    # Printers and computers answer WS-Discovery too: only video devices (ONVIF) count.
    types = " ".join(values(xml, "Types"))
    scopes = " ".join(values(xml, "Scopes")).split()
    if "NetworkVideoTransmitter" not in types and not any("onvif.org" in s for s in scopes):
        return None
    xaddrs = " ".join(values(xml, "XAddrs")).split()
    # Prefer the address the answer came from (cameras with several interfaces list them all,
    # some an address of another network).
    xaddr = next((x for x in xaddrs if sender and urlparse(x).hostname == sender), None)
    xaddr = xaddr or next((x for x in xaddrs if urlparse(x).hostname), None)
    if xaddr is None:
        return None
    url = urlparse(xaddr)

    def scope(kind: str) -> str | None:
        found = [
            unquote(s.split(f"/{kind}/", 1)[1]).replace("_", " ").strip()
            for s in scopes
            if f"onvif://www.onvif.org/{kind}/" in s
        ]
        return next((f for f in found if f), None)

    name, hardware = scope("name"), scope("hardware")
    words = " ".join(filter(None, [name, hardware, scope("mfr"), scope("manufacturer"), *scopes])).lower()
    driver = next((d for brands, d in BRANDS if any(b in words for b in brands)), "onvif")
    manufacturer = scope("mfr") or scope("manufacturer")
    if manufacturer is None and driver != "onvif":
        manufacturer = {"hikvision": "Hikvision", "reolink": "Reolink", "dahua": "Dahua"}.get(driver)
    endpoint = value(xml, "Address")
    return Found(
        host=url.hostname or "",
        port=url.port or (443 if url.scheme == "https" else 80),
        xaddr=xaddr,
        name=name,
        hardware=hardware,
        location=scope("location"),
        manufacturer=manufacturer,
        driver=driver,
        id=endpoint,
        scopes=scopes,
    )


class _Collector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, Found] = {}

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        try:
            match = parse_match(data.decode("utf-8", "replace"), str(addr[0]))
        except Exception:  # a broken answer must not end the scan
            return
        if match:
            self.found.setdefault(match.id or match.host, match)


def interfaces() -> list[str]:
    """The IPv4 addresses of this machine's network interfaces, the loopback and link-local
    ones aside: the probe goes out on each (the default route may be a VPN's, which carries
    no multicast)."""
    import psutil

    addresses: list[str] = []
    for _name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                addresses.append(a.address)
    return addresses or ["0.0.0.0"]


async def discover(seconds: float = 3.0, hosts: list[str] | None = None) -> list[Found]:
    """Probe the network on every interface and collect the answers for `seconds`. Devices
    that answer twice (to both probes, or on two interfaces) count once. `hosts` also get the
    probe directly (unicast): that reaches cameras where multicast doesn't (another subnet, a
    VPN, a Docker bridge network)."""
    loop = asyncio.get_running_loop()
    collector = _Collector()
    transports = []
    for address in interfaces():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if address != "0.0.0.0":
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(address))
            sock.bind((address, 0))
            transport, _ = await loop.create_datagram_endpoint(lambda: collector, sock=sock)
            transports.append(transport)
        except OSError as e:  # an interface without multicast, one going away
            log.debug("discovery: can't probe on %s: %s", address, e)
    # Unicast probes from a socket of their own: routed like any packet (a VPN included).
    unicast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    unicast_sock.bind(("0.0.0.0", 0))
    unicast, _ = await loop.create_datagram_endpoint(lambda: collector, sock=unicast_sock)
    transports.append(unicast)
    try:
        # UDP may drop one: two rounds, with and without types, each followed by the wait for
        # answers (the sockets must stay open meanwhile).
        for _rounds in range(2):
            for transport in transports[:-1]:
                for types in (True, False):
                    with contextlib.suppress(OSError):
                        transport.sendto(probe_message(types), GROUP)
            for host in hosts or []:
                for types in (True, False):
                    with contextlib.suppress(OSError):
                        unicast.sendto(probe_message(types), (host, GROUP[1]))
            await asyncio.sleep(seconds / 2)
    finally:
        for transport in transports:
            transport.close()
    # One entry per address: a camera may answer with two endpoint ids.
    by_host: dict[str, Found] = {}
    for f in collector.found.values():
        by_host.setdefault(f.host, f)
    return sorted(by_host.values(), key=_address_key)


def _address_key(f: Found) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in f.host.split("."))


ONVIF_PORTS = (80, 8000, 8080, 2020, 8899)  # where cameras put their device service
TIME = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
    '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>'
)
HOST = re.compile(r"[\w.\-]+|\[[0-9a-fA-F:]+\]")


async def check_host(
    host: str, timeout: float = 2.0, transport: httpx.AsyncBaseTransport | None = None
) -> Found | None:
    """What camera is at `host`, asked directly over TCP: for where multicast doesn't reach
    (another subnet, a VPN, Docker's bridge network), and for cameras without ONVIF. Only
    questions that need no login and change nothing, all at once (an address without a camera
    answers nothing, so this takes `timeout`): a Foscam-style status page, ONVIF's clock (on its
    usual ports), Hikvision's login challenge, Reolink's app port."""
    host = host.strip()
    if not HOST.fullmatch(host):
        raise ValueError("an IP address or host name, like 192.168.1.20")
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport) as client:

        async def ask(method: str, url: str, **kwargs: Any) -> httpx.Response | None:
            try:
                return await client.request(method, url, **kwargs)
            except httpx.HTTPError:
                return None

        async def reolink_port() -> bool:
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, 9000), timeout)
            except (OSError, TimeoutError):
                return False
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return True

        soap = {"content": TIME, "headers": {"Content-Type": "application/soap+xml"}}
        # Never get_params.cgi on a Foscam-style camera: it returns every password.
        status, isapi, reolink, *clocks = await asyncio.gather(
            ask("GET", f"http://{host}/get_status.cgi"),
            ask("GET", f"http://{host}/ISAPI/System/deviceInfo"),
            reolink_port(),
            *(ask("POST", f"http://{host}:{port}/onvif/device_service", **soap) for port in ONVIF_PORTS),
        )
        # A Foscam-style CGI camera (supra, early INSTAR, Wansview): its status page is readable
        # without a login.
        if status is not None and status.status_code == 200 and "sys_ver" in status.text:
            branding = await ask("GET", f"http://{host}/branding/branding.js")
            text = branding.text if branding is not None and branding.status_code == 200 else ""
            brand = re.search(r'brand\s*:\s*"([^"]+)"', text)
            product = re.search(r'product\s*:\s*"([^"]+)"', text)
            alias = re.search(r"var alias=['\"]([^'\"]*)", status.text)
            return Found(
                host=host,
                port=80,
                xaddr=f"http://{host}/",
                name=(alias[1] if alias else None) or None,
                hardware=product[1] if product else None,
                manufacturer=brand[1] if brand else None,
                driver="foscam",
            )
    # ONVIF: its clock needs no login on any camera (the first port that answers).
    found: Found | None = None
    for port, answer in zip(ONVIF_PORTS, clocks, strict=True):
        if answer is not None and "UTCDateTime" in answer.text:
            url = f"http://{host}:{port}/onvif/device_service"
            found = Found(host=host, port=port, xaddr=url)
            break
    # Hikvision: its own API (ISAPI) answers with a login challenge.
    challenge = isapi.headers.get("www-authenticate", "").lower() if isapi is not None else ""
    if isapi is not None and isapi.status_code == 401 and "digest" in challenge:
        found = found or Found(host=host, port=80, xaddr=f"http://{host}/")
        found.driver, found.manufacturer = "hikvision", "Hikvision"
    # Reolink: its app protocol (Baichuan) listens on 9000.
    elif reolink:
        found = found or Found(host=host, port=80, xaddr=f"http://{host}/")
        found.driver, found.manufacturer = "reolink", "Reolink"
    return found


def in_container() -> bool:
    """Norn runs in a container (where multicast needs host networking)."""
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    with contextlib.suppress(OSError), open("/proc/1/cgroup") as f:
        return bool(re.search(r"docker|containerd|kubepods|podman", f.read()))
    return False


def camera_hosts(cameras: dict[str, Any]) -> dict[str, str]:
    """Configured cameras by the host they are at (their `host`, or the host of their `url`)."""
    hosts: dict[str, str] = {}
    for cid, cfg in cameras.items():
        extra = getattr(cfg, "model_extra", None) or {}
        for candidate in (extra.get("host"), urlparse(str(extra.get("url") or "")).hostname):
            if candidate:
                hosts.setdefault(str(candidate).strip().lower(), cid)
    return hosts
