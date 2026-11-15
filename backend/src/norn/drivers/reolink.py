"""Reolink cameras, through ONVIF and RTSP.

Reolink's own HTTP API (with spotlight, siren, and its firmware check) needs the camera's HTTP
port, which is off by default on newer firmware; ONVIF (port 8000) and RTSP (554) are on. So this
driver builds on the ONVIF driver and uses Reolink's fixed RTSP paths, which work even when the
ONVIF profile returns a bare address like rtsp://host:554/.
"""

from __future__ import annotations

from urllib.parse import quote

from pydantic import Field

from . import register
from .base import DeviceInfo, Stream
from .onvif import OnvifDriver, OnvifOptions


class ReolinkOptions(OnvifOptions):
    port: int = Field(8000, title="ONVIF port", ge=1, le=65535)
    rtsp_port: int = Field(554, title="RTSP port", ge=1, le=65535)


@register
class ReolinkDriver(OnvifDriver):
    name = "reolink"
    label = "Reolink"
    description = "Reolink cameras: video, pan/tilt, presets and image settings (ONVIF and RTSP)."
    Options = ReolinkOptions
    options: ReolinkOptions
    manufacturer = "Reolink"

    def streams(self) -> list[Stream]:
        o = self.options
        auth = f"{quote(o.username, safe='')}:{quote(o.password, safe='')}@"
        base = f"rtsp://{auth}{o.host}:{o.rtsp_port}/h264Preview_01_"
        return [
            Stream(id="main", label="Main", source=f"{base}main", codec="h264"),
            Stream(id="sub", label="Sub", source=f"{base}sub", codec="h264"),
        ]

    async def info(self) -> DeviceInfo:
        info = await super().info()
        if info.online:
            info.notes.append(
                "The HTTP API is off, so spotlight, siren and the online firmware check aren't "
                "available. Turn on HTTP in the Reolink app (Settings > Network > Advanced > Server "
                "settings) to enable them later."
            )
        return info
