"""What Norn costs the machine: CPU and memory of Norn, go2rtc and each FFmpeg, and the GPU.

CPU is measured between two calls (psutil keeps the counters per process), so the first report
after a start shows 0 for new processes. 100 % is one full core, like `top`.

Norn uses no GPU yet: it copies video and encodes MJPEG on the CPU. The report says so, and
names the GPU it could use (/dev/dri), for when hardware encoding comes.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

import psutil


def describe(process: psutil.Process) -> tuple[str, str | None]:
    """A process as (what it is, camera): 'Norn', 'go2rtc', 'Buffer', 'Continuous', 'Clip', ..."""
    try:
        cmd = process.cmdline()
    except (psutil.Error, OSError):
        return "Process", None
    if process.pid == os.getpid():
        return "Norn", None
    name = Path(cmd[0]).name if cmd else process.name()
    if "go2rtc" in name:
        return "go2rtc", None
    if "ffmpeg" not in name:
        return name, None
    camera = None
    if "-i" in cmd:
        source = cmd[cmd.index("-i") + 1]
        if source.startswith("rtsp://"):
            camera = source.rsplit("/", 1)[-1].split("_")[0] or None
    if cmd and cmd[-1].startswith("rtsp://"):
        return "Transcode", camera  # go2rtc's FFmpeg, making the low stream for a viewer
    if any("prev_selected_t" in part for part in cmd):
        return "Stills", camera
    if "mpegts" in cmd and "-segment_start_number" in cmd:
        return "Buffer", camera
    if cmd and cmd[-1].endswith("_continuous.mp4"):
        return "Continuous", camera
    if "-frames:v" in cmd:
        return "Thumbnail", None
    if source_is_file(cmd):
        return "Finishing clip", None
    return "Clip", camera


def source_is_file(cmd: list[str]) -> bool:
    return "-i" in cmd and not cmd[cmd.index("-i") + 1].startswith(("rtsp://", "http"))


def gpu() -> dict[str, Any]:
    devices = sorted(p.name for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
    nvidia = shutil.which("nvidia-smi") is not None
    return {
        "used": False,
        "available": [*(f"/dev/dri/{d}" for d in devices), *(["NVIDIA"] if nvidia else [])],
    }


class Resources:
    def __init__(self) -> None:
        # By pid and start time: a pid can be reused by a new process.
        self._processes: dict[tuple[int, float], psutil.Process] = {}
        self._me = psutil.Process()
        self._me.cpu_percent()
        psutil.cpu_percent()

    def report(self) -> dict[str, Any]:
        """Norn's processes now. Blocking (reads /proc): call it in a thread."""
        try:
            current = [self._me, *self._me.children(recursive=True)]
        except psutil.Error:
            current = [self._me]
        seen = set()
        processes = []
        for process in current:
            pid = process.pid
            try:
                key = (pid, process.create_time())
            except psutil.Error:
                continue
            seen.add(key)
            known = self._processes.setdefault(key, process)
            try:
                with known.oneshot():
                    cpu = known.cpu_percent()
                    rss = known.memory_info().rss
            except psutil.Error:
                continue
            kind, camera = describe(known)
            processes.append(
                {"pid": pid, "kind": kind, "camera": camera, "cpu": round(cpu, 1), "memory": rss}
            )
        for key in list(self._processes):
            if key not in seen:
                del self._processes[key]
        memory = psutil.virtual_memory()
        return {
            "time": time.time(),
            "cpu": round(sum(p["cpu"] for p in processes), 1),
            "memory": sum(p["memory"] for p in processes),
            "processes": sorted(processes, key=lambda p: -p["cpu"]),
            "system": {
                "cores": psutil.cpu_count() or 1,
                "cpu": psutil.cpu_percent(),  # all cores, 0-100
                "memory_total": memory.total,
                "memory_available": memory.available,
            },
            "gpu": gpu(),
        }
