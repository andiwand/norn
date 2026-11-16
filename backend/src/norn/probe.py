"""Which of a camera's streams work, what they are, and whether they work at the same time.

Cameras offer a main stream, often a sub-stream, sometimes a third or fourth. Some serve them
all at once, some only one at a time. Norn opens all RTSP streams at once with ffprobe; those
that fail are tried again one by one. One that works alone but not with the others means the
camera serves one stream at a time.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass

URL = re.compile(r"rtsps?://\S+")


@dataclass
class StreamProbe:
    ok: bool
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    fps: float | None = None
    error: str | None = None

    @property
    def pixels(self) -> int:
        return (self.width or 0) * (self.height or 0)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def probeable(source: str) -> bool:
    return source.startswith(("rtsp://", "rtsps://"))


async def probe_one(ffprobe: str, source: str, timeout: float = 15) -> StreamProbe:
    cmd = [
        ffprobe, "-v", "error", "-rtsp_transport", "tcp", "-timeout", str(int(timeout * 1e6)),
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate", "-of", "json", source,
    ]  # fmt: skip
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as e:
        return StreamProbe(ok=False, error=str(e))
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout + 5)
    except (TimeoutError, asyncio.CancelledError) as e:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(e, asyncio.CancelledError):
            raise
        return StreamProbe(ok=False, error="no answer")
    if process.returncode != 0:
        # The message names the URL, with the password in it: leave the URL out.
        lines = err.decode(errors="replace").strip().splitlines()
        # "rtsp://user:password@host/path: Server returned 404" -> "Server returned 404"
        message = URL.sub("the stream", re.sub(r"rtsps?://\S+?:\s+", "", lines[-1])) if lines else "failed"
        return StreamProbe(ok=False, error=message[:120])
    video = [s for s in json.loads(out or b"{}").get("streams", []) if s.get("width")]
    if not video:
        return StreamProbe(ok=False, error="no video")
    v = video[0]
    num, _, den = str(v.get("avg_frame_rate", "0/1")).partition("/")
    try:
        fps = round(float(num) / float(den or 1), 1) if float(den or 1) else None
    except ValueError:
        fps = None
    return StreamProbe(
        ok=True, width=v.get("width"), height=v.get("height"), codec=v.get("codec_name"), fps=fps
    )


async def probe_all(ffprobe: str, sources: dict[str, str]) -> tuple[dict[str, StreamProbe], bool | None]:
    """Probe the streams at once, the failed ones again alone. Returns the probes and whether the
    camera serves its working streams at the same time (None: fewer than two work)."""
    ids = [i for i, s in sources.items() if probeable(s)]
    together = await asyncio.gather(*(probe_one(ffprobe, sources[i]) for i in ids))
    probes = dict(zip(ids, together, strict=True))
    alone_ok = False
    for stream_id in ids:
        if not probes[stream_id].ok and probes[stream_id].error != "no video":
            single = await probe_one(ffprobe, sources[stream_id])
            if single.ok:
                probes[stream_id] = single
                alone_ok = True
    working = sum(p.ok for p in probes.values())
    if working < 2:
        return probes, None
    return probes, not alone_ok
