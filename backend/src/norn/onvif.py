"""A small async ONVIF client: just the calls Norn's drivers use.

SOAP 1.2 over HTTP with WS-Security UsernameToken (password digest). The digest includes a
timestamp, and cameras reject one that is far off their clock, so the client reads the camera's
time first (that call needs no login) and signs with the camera's time.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import re
from dataclasses import dataclass, field

import httpx

NS = {
    "device": "http://www.onvif.org/ver10/device/wsdl",
    "media": "http://www.onvif.org/ver10/media/wsdl",
    "ptz": "http://www.onvif.org/ver20/ptz/wsdl",
    "imaging": "http://www.onvif.org/ver20/imaging/wsdl",
    "schema": "http://www.onvif.org/ver10/schema",
}
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
NONCE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"


class OnvifError(Exception):
    pass


def values(xml: str, tag: str) -> list[str]:
    """The text of every element with this local name, whatever its namespace prefix."""
    return [
        v.strip() for v in re.findall(rf"<(?:[\w-]+:)?{tag}(?:\s[^>]*)?>([^<]*)</(?:[\w-]+:)?{tag}>", xml)
    ]


def value(xml: str, tag: str) -> str | None:
    found = values(xml, tag)
    return found[0] if found else None


def attributes(xml: str, tag: str, attribute: str) -> list[str]:
    return re.findall(rf"<(?:[\w-]+:)?{tag}\s[^>]*?\b{attribute}=\"([^\"]*)\"", xml)


@dataclass
class Profile:
    token: str
    name: str
    encoding: str | None
    width: int | None
    height: int | None
    source_token: str | None
    has_ptz: bool


@dataclass
class OnvifClient:
    host: str
    port: int
    username: str
    password: str
    timeout: float = 8
    services: dict[str, str] = field(default_factory=dict)
    _offset: dt.timedelta = dt.timedelta(0)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.timeout)
        self.services.setdefault("device", f"http://{self.host}:{self.port}/onvif/device_service")

    async def close(self) -> None:
        await self._client.aclose()

    async def connect(self) -> None:
        """Sync the clock and find the service addresses."""
        xml = await self.call("device", "<GetSystemDateAndTime xmlns='{device}'/>", auth=False)
        utc = re.search(r"<(?:\w+:)?UTCDateTime>(.*?)</(?:\w+:)?UTCDateTime>", xml, re.S)
        if utc:
            part = utc[1]
            try:
                stamp = dt.datetime(
                    *(int(value(part, t) or 0) for t in ("Year", "Month", "Day", "Hour", "Minute", "Second")),
                    tzinfo=dt.UTC,
                )
                self._offset = stamp - dt.datetime.now(dt.UTC)
            except ValueError:
                pass  # a clock Norn can't read: sign with its own
        caps = await self.call(
            "device", "<GetCapabilities xmlns='{device}'><Category>All</Category></GetCapabilities>"
        )
        for name in ("Media", "PTZ", "Imaging", "Events"):
            section = re.search(rf"<(?:\w+:)?{name}>(.*?)</(?:\w+:)?{name}>", caps, re.S)
            if section and (address := value(section[1], "XAddr")):
                # Some cameras answer with an address the client can't reach (another interface);
                # keep the path, use the host we know works.
                path = re.sub(r"^https?://[^/]+", "", address)
                self.services[name.lower()] = f"http://{self.host}:{self.port}{path}"

    def _security(self) -> str:
        nonce = os.urandom(16)
        created = (dt.datetime.now(dt.UTC) + self._offset).strftime("%Y-%m-%dT%H:%M:%SZ")
        digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.password.encode()).digest())
        return (
            f"<s:Header><Security xmlns='{WSSE}'><UsernameToken><Username>{_escape(self.username)}</Username>"
            f"<Password Type='{DIGEST}'>{digest.decode()}</Password>"
            f"<Nonce EncodingType='{NONCE}'>{base64.b64encode(nonce).decode()}</Nonce>"
            f"<Created xmlns='{WSU}'>{created}</Created></UsernameToken></Security></s:Header>"
        )

    async def call(self, service: str, body: str, auth: bool = True) -> str:
        url = self.services.get(service)
        if url is None:
            raise OnvifError(f"the camera has no {service} service")
        envelope = (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope'>"
            f"{self._security() if auth else ''}<s:Body>{_namespaces(body)}</s:Body></s:Envelope>"
        )
        try:
            response = await self._client.post(
                url, content=envelope, headers={"Content-Type": "application/soap+xml; charset=utf-8"}
            )
        except httpx.HTTPError as e:
            raise OnvifError(f"{self.host}: {e}") from e
        if response.status_code >= 400:
            reason = (
                value(response.text, "Text")
                or value(response.text, "Value")
                or f"HTTP {response.status_code}"
            )
            if response.status_code in (400, 401) and "NotAuthorized" in response.text + reason:
                reason = "wrong username or password"
            raise OnvifError(reason)
        return response.text

    # Device
    async def device_information(self) -> dict[str, str | None]:
        xml = await self.call("device", "<GetDeviceInformation xmlns='{device}'/>")
        return {
            t: value(xml, t)
            for t in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber", "HardwareId")
        }

    # Media
    async def profiles(self) -> list[Profile]:
        xml = await self.call("media", "<GetProfiles xmlns='{media}'/>")
        found = []
        for block in re.findall(r"<(?:\w+:)?Profiles\s.*?</(?:\w+:)?Profiles>", xml, re.S):
            token = attributes(block, "Profiles", "token")
            video = re.search(
                r"<(?:\w+:)?VideoEncoderConfiguration\b.*?</(?:\w+:)?VideoEncoderConfiguration>", block, re.S
            )
            v = video[0] if video else ""
            found.append(
                Profile(
                    token=token[0] if token else "",
                    name=value(block, "Name") or "",
                    encoding=value(v, "Encoding"),
                    width=int(value(v, "Width") or 0) or None,
                    height=int(value(v, "Height") or 0) or None,
                    source_token=value(block, "SourceToken"),
                    has_ptz="PTZConfiguration" in block,
                )
            )
        return found

    async def stream_uri(self, profile: str) -> str | None:
        xml = await self.call(
            "media",
            "<GetStreamUri xmlns='{media}'><StreamSetup><Stream xmlns='{schema}'>RTP-Unicast</Stream>"
            "<Transport xmlns='{schema}'><Protocol>RTSP</Protocol></Transport></StreamSetup>"
            f"<ProfileToken>{_escape(profile)}</ProfileToken></GetStreamUri>",
        )
        return value(xml, "Uri")

    # PTZ
    async def continuous_move(self, profile: str, pan: float, tilt: float, zoom: float) -> None:
        zoom_xml = f"<Zoom xmlns='{{schema}}' x='{zoom:.2f}'/>" if zoom else ""
        await self.call(
            "ptz",
            f"<ContinuousMove xmlns='{{ptz}}'><ProfileToken>{_escape(profile)}</ProfileToken><Velocity>"
            f"<PanTilt xmlns='{{schema}}' x='{pan:.2f}' y='{tilt:.2f}'/>{zoom_xml}</Velocity></ContinuousMove>",
        )

    async def stop(self, profile: str) -> None:
        await self.call(
            "ptz",
            f"<Stop xmlns='{{ptz}}'><ProfileToken>{_escape(profile)}</ProfileToken>"
            "<PanTilt>true</PanTilt><Zoom>true</Zoom></Stop>",
        )

    async def presets(self, profile: str) -> list[tuple[str, str]]:
        xml = await self.call(
            "ptz", f"<GetPresets xmlns='{{ptz}}'><ProfileToken>{_escape(profile)}</ProfileToken></GetPresets>"
        )
        result = []
        for block in re.findall(r"<(?:\w+:)?Preset\s.*?(?:/>|</(?:\w+:)?Preset>)", xml, re.S):
            token = attributes(block, "Preset", "token")
            if token:
                result.append((token[0], value(block, "Name") or token[0]))
        return result

    async def set_preset(self, profile: str, preset: str | None, name: str) -> str:
        """Store the current position; `preset` None makes a new one. Returns its token."""
        token = f"<PresetToken>{_escape(preset)}</PresetToken>" if preset else ""
        xml = await self.call(
            "ptz",
            f"<SetPreset xmlns='{{ptz}}'><ProfileToken>{_escape(profile)}</ProfileToken>"
            f"<PresetName>{_escape(name)}</PresetName>{token}</SetPreset>",
        )
        return value(xml, "PresetToken") or preset or ""

    async def goto_preset(self, profile: str, preset: str) -> None:
        await self.call(
            "ptz",
            f"<GotoPreset xmlns='{{ptz}}'><ProfileToken>{_escape(profile)}</ProfileToken>"
            f"<PresetToken>{_escape(preset)}</PresetToken></GotoPreset>",
        )

    async def goto_home(self, profile: str) -> None:
        await self.call(
            "ptz",
            f"<GotoHomePosition xmlns='{{ptz}}'><ProfileToken>{_escape(profile)}</ProfileToken></GotoHomePosition>",
        )

    # Imaging
    async def imaging_settings(self, source: str) -> str:
        return await self.call(
            "imaging",
            f"<GetImagingSettings xmlns='{{imaging}}'><VideoSourceToken>{_escape(source)}</VideoSourceToken></GetImagingSettings>",
        )

    async def set_imaging(self, source: str, settings_xml: str) -> None:
        await self.call(
            "imaging",
            f"<SetImagingSettings xmlns='{{imaging}}'><VideoSourceToken>{_escape(source)}</VideoSourceToken>"
            f"<ImagingSettings>{settings_xml}</ImagingSettings></SetImagingSettings>",
        )


def _namespaces(body: str) -> str:
    """Fill in {device}, {media}, ... (not str.format: values in the body may contain braces)."""
    for key, uri in NS.items():
        body = body.replace("{" + key + "}", uri)
    return body


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;")
