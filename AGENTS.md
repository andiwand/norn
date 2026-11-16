# AGENTS.md

Orientation for agents: what this is, the layout, the build loop, and the conventions. The plan
is in [`PLAN.md`](PLAN.md), the user documentation in [`README.md`](README.md).

## What this is

Norn is a self-hosted hub for home cameras. It relays live video to browsers, exposes each
camera's controls (PTZ, settings), and records. It runs locally, without accounts, as one Docker
image or the PyPI package `norn-hub`. The name may change later.

## Architecture

- **Video never passes through Python.** go2rtc reads each camera once and repackages the stream
  (WebRTC, MSE, HLS for browsers; RTSP on localhost for the recorder). FFmpeg transcodes only when
  a source asks for it (`#video=h264` in a go2rtc source). Keep it that way: CPU cost is a goal.
- `backend/src/norn/`:
  - `hub.py` ties everything together. It builds a `Camera` (config + driver instance) for each
    entry of the config, keeps unchanged ones, and pushes the streams to go2rtc and the recorder.
  - `config.py`: `config.yaml` is the only state. `ConfigStore` edits it with ruamel.yaml's
    round-trip mode so hand-written comments survive; `_take_tail_comment` keeps a trailing
    comment block at the end when keys are added. The hub polls the file's mtime and reloads.
    There is no database, on purpose.
  - `drivers/`: one module per kind of camera, registered with `@register`. A driver declares its
    `Options` (a pydantic model: the extra keys of the camera in config.yaml, and the add-camera
    form via its JSON schema), `streams()` (go2rtc sources), `capabilities()`, `controls()`
    (widgets: toggle, select, range, button), `presets()` and `ptz()`. The web app renders
    whatever a driver declares, so a new driver needs no UI change. Drivers push state changes
    with `self.emit(...)`, which goes to the event bus.
  - Drivers also report `info()` (a `DeviceInfo`: model, firmware, details, notes). The hub
    polls it every 5 minutes, and `firmware.py` compares the firmware with a hand-kept catalogue
    of the newest versions (with the date each entry was checked). Firmware updates go through
    `firmware_upload` (a file) or `firmware_online_update`; `auto_update` in a camera's config only
    acts for drivers with `Capability.FIRMWARE_ONLINE`.
  - The hub caches each camera's controls and presets (`get_controls`), refreshes them with the
    device poll, and publishes `camera.controls` on a change; the web app also keeps them in
    localStorage, so a camera page renders complete at once.
  - `reolink.py` uses reolink_aio in Baichuan-only mode (`bc_only=True`). Keep it that way: the
    library's normal mode opens ports on the camera by itself. `tapo.py` wraps pytapo (sync) with
    `asyncio.to_thread`. Drivers marked untested in the README were written from vendor docs.
  - Driver notes: `foscam.py` must never call `get_params.cgi` (old firmware returns all
    passwords and the Wi-Fi key); `onvif.py` (the client, in `norn/`) signs with the camera's
    clock; credentials in stream URLs are always percent-encoded.
  - `go2rtc.py` runs go2rtc (`managed`) or talks to one (`external`), writes its config into
    `<config dir>/.norn/go2rtc.yaml` (block YAML: go2rtc edits that file itself), and syncs streams through its API. Stream names: the main
    stream is the camera id, others `<id>_<stream>`.
  - `recorder.py`: FFmpeg with `-c:v copy` from go2rtc's RTSP. Continuous: the segment muxer,
    into day folders made in advance (it can't make folders). Clips: one FFmpeg per clip, plus a
    thumbnail and a JSON sidecar.
    Three storage stages: a `Buffer` per camera writes ~2 s MPEG-TS pieces into `NORN_BUFFER`
    (RAM) so a clip can start before its trigger (a clip "claims" pieces so pruning keeps them);
    clips, continuous files and pictures are written into `NORN_TEMP` (a `Library` with the same
    layout) and moved into the recordings when finished (video first, then .jpg and .json).
    Pictures (`interval`) come from the buffer's newest piece, else from go2rtc.
  - Circles (`config.circles`) group cameras. `Config.setting(camera, name)` resolves
    `picture_seconds`/`prebuffer_seconds`: the camera's own, its first circle's, the global one.
    The hub computes the controls all members share (`circle_controls`) and sets them on all.
  - Events: drivers with `Capability.EVENTS` yield `Event(kind, active)` from `events()`
    (Reolink: Baichuan push; Hikvision: ISAPI alertStream; foscam: polls get_status.cgi). The
    hub runs one watcher per camera (`_watch_events`), publishes `camera.event`, and while a
    kind in the camera's `triggers` lasts, `_hold` extends a clip every few seconds.
  - `labels.py` defines the detection labels (motion, person, vehicle, ...) and maps each
    source's names onto them (Reolink AI, Hikvision events, COCO). Use it, never raw names.
  - `gop.py`: instant live video. A GopCache per stream reads go2rtc's MSE output (fMP4,
    one frame per message) and keeps the init segment and the fragments since the newest
    video keyframe. `api._pipe` answers a browser's MSE request from it (init + GOP in one
    message, then the live fragments); the player jumps to the buffered start and catches up
    (one marked change in the vendored `video-rtc.js`). WebRTC still goes to go2rtc. The
    hub keeps `ready_streams` cached all the time (default: the tile stream), others while
    watched and `GOP_LINGER` after; stills come from the newest keyframe too. Not for MJPEG
    or streams FFmpeg makes.
  - `stills.py`: one FFmpeg per camera and mode reads go2rtc's sub-stream and emits stills
    (JPEG, gray for motion, the detector's input) to subscribers; `-skip_frame nokey` in
    keyframe mode. It stops `IDLE_AFTER` seconds after the last subscriber. `detect.py`: the
    motion detector, YOLOX (`Detectors`, one inference at a time) and the `Tracker`. The hub's
    `_watch_stills` subscribes per camera when the camera's `detection_for` asks for it.
  - `pilot.py`: one Pilot per camera: Norn presets (`config.presets`: a camera slot plus
    controls; pictures in `.norn/presets/`), patrol, reactions (from `_react` in the hub) and
    following (`autotrack` control, else `nudge` from `_watch_stills`). Manual PTZ via the API
    pauses it. Camera PUTs without presets/patrol/reactions/follow keep the current ones.
  - `logs.py`: console, rotating file and an in-memory ring for `/api/logs`; the `Scrub` filter
    removes credentials from every line.
  - `resources.py`: CPU and memory of Norn and its child processes (psutil), and the GPU.
  - `recordings.py`: the folder layout is the index (`<camera>/<YYYY-MM-DD>/<HH-MM-SS>_<trigger>.mp4`).
    A `.jpg` without a video next to it is a picture. Everything but `manual` expires after
    `retention_days`; `prune` deletes per file.
    `Library.path` validates every part; never build a recordings path another way.
  - `api.py`: the API under `/api`, the WebSocket `/api/stream` that forwards to go2rtc (so the
    browser needs only port 8000 plus 8555 for WebRTC media), `/api/events`, and the web app with
    an index.html fallback.
  - `settings.py`: process settings from `NORN_*` environment variables. Camera and recording
    settings belong in config.yaml, not here.
- `frontend/`: SvelteKit 3 + Svelte 5 runes + Tailwind 4, built as a static single-page app
  (`adapter-static`, `ssr = false`). `src/lib/state.svelte.ts` holds the shared state and the
  event WebSocket; `src/lib/api.ts` the typed API. The live player is go2rtc's `video-rtc.js`
  (vendored unchanged in `src/lib/go2rtc/`, excluded from prettier) extended by `norn-video.js`.
  Imports from `src/lib` use the `#lib/...` alias; TypeScript modules need the `.js` suffix there
  (`#lib/api.js`). Colors are semantic tokens in `src/routes/layout.css` (dark default, light by
  system preference); shared classes are Tailwind `@utility` definitions there.
- `website/`: the GitHub Pages site, plain HTML and CSS, no build.
- `Dockerfile`: builds the web app, installs the Python package with the web app inside
  (`norn/web`), and adds go2rtc and a static FFmpeg. The PyPI workflow bundles the web app the
  same way.

## Build and test

```sh
cd backend && uv sync && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm ci && npm run lint && npm run check && npm test && npm run build
docker build -t norn:dev . && docker run --rm -p 8000:8000 norn:dev   # the real thing, with video
```

The backend tests run with `go2rtc_mode="off"`, so they need neither go2rtc nor FFmpeg. CI
(`.github/workflows/ci.yml`) also starts the Docker image and checks a frame of the demo camera
and a recorded clip, which covers go2rtc and FFmpeg.

For the web app with hot reload: run the backend (`uv run norn`, port 8000) and
`npm run dev` in `frontend/`; Vite proxies `/api` including WebSockets.

## Conventions

- Adding a camera: we look at one real camera at a time, research its protocols and abilities,
  and write or extend a driver. Prefer go2rtc's own sources (`onvif://`, `tapo://`, ...) for video
  and a driver for control.
- Config changes go through `ConfigStore`; keep config.yaml readable for people (defaults stay
  out of the file).
- Python: 3.13, ruff (line length 110), type hints, async I/O. Frontend: prettier (tabs, single
  quotes), svelte-check without warnings.
- Releases: bump `version` in `backend/pyproject.toml`, add a section to `CHANGELOG.md`, tag
  `vX.Y.Z`. The tag publishes the image (ghcr.io), a GitHub release, and the PyPI package.
