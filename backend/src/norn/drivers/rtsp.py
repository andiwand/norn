"""Any camera with an RTSP stream. Live view and recording, no controls."""

from __future__ import annotations

from pydantic import Field

from . import register
from .base import Driver, DriverOptions, Stream


class RtspOptions(DriverOptions):
    url: str = Field(
        title="Stream URL",
        description="The main stream, like rtsp://user:password@192.168.1.20:554/stream1",
        pattern=r"^(rtsps?|rtmp|http|https)://",
    )
    substream: str | None = Field(
        None,
        title="Substream URL",
        description="A smaller stream for the grid. Optional; the grid uses the main stream without it.",
        pattern=r"^(rtsps?|rtmp|http|https)://",
    )


@register
class RtspDriver(Driver):
    name = "rtsp"
    label = "RTSP camera"
    description = "Any camera that offers an RTSP stream. Live view and recording."
    Options = RtspOptions
    options: RtspOptions

    def streams(self) -> list[Stream]:
        streams = [Stream(id="main", label="Main", source=self.options.url)]
        if self.options.substream:
            streams.append(Stream(id="sub", label="Sub", source=self.options.substream))
        return streams
