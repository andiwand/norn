<p align="center"><img src="website/favicon.svg" width="72" alt=""></p>

<h1 align="center">Norn</h1>

<p align="center"><b>All your home cameras in one place.</b><br>
A lightweight, self-hosted hub that relays live video to your phone or desktop browser, gives you
the controls of the camera's own app, and records.</p>

<p align="center">
<a href="https://github.com/andiwand/norn/actions/workflows/ci.yml"><img src="https://github.com/andiwand/norn/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="https://pypi.org/project/norn-hub/"><img src="https://img.shields.io/pypi/v/norn-hub.svg" alt="PyPI"></a>
<a href="https://pypi.org/project/norn-hub/"><img src="https://img.shields.io/pypi/pyversions/norn-hub.svg" alt="Python"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-brightgreen.svg" alt="License: MIT"></a>
</p>

<p align="center"><a href="https://andiwand.github.io/norn/">Website</a> ·
<a href="#quick-start">Quick start</a> · <a href="#configuration">Configuration</a> ·
<a href="#development">Development</a></p>

---

> Norn is an early preview. Camera support grows one real camera at a time; see [PLAN.md](PLAN.md).

| Driver      | Cameras                                         | Video        | Control                                                              | Tested      |
| ----------- | ----------------------------------------------- | ------------ | -------------------------------------------------------------------- | ----------- |
| `reolink`   | Reolink (app protocol, no HTTP needed)          | RTSP H.264   | pan/tilt, presets, IR, status light, siren, tracking, motion and AI events, firmware | E1 Pro |
| `hikvision` | Hikvision and relabels (Annke, HiLook, …)       | RTSP H.264   | day/night, WDR, flip, colour, motion events, firmware file           | DS-2CD2042WD-I |
| `foscam`    | Foscam CGI: supra IPC-1A / IPC-100HD, Wansview, … | MJPEG (HTTP) | pan/tilt, presets, resolution, brightness, flip, motion alarm      | supra       |
| `onvif`     | any ONVIF camera                                | RTSP         | PTZ, presets, day/night, image                                       | Reolink     |
| `dahua`     | Dahua, Amcrest, Lorex                           | RTSP         | pan/tilt/zoom, presets, day/night, flip, motion detection            | not yet     |
| `axis`      | Axis                                            | RTSP H.264   | pan/tilt/zoom, presets, day/night, firmware file                     | not yet     |
| `foscam-hd` | Foscam HD (since about 2014)                    | RTSP H.264   | pan/tilt/zoom, presets, IR, mirror, flip                             | not yet     |
| `tapo`      | TP-Link Tapo                                    | RTSP H.264   | pan/tilt, presets, night vision, privacy, siren, firmware            | not yet     |
| `unifi`     | UniFi Protect (through the console's API)       | RTSPS        | status light, microphone, PTZ presets                                | not yet     |
| `rtsp`      | anything with an RTSP URL                       | RTSP         | –                                                                    |             |
| `demo`      | a test pattern with pretend controls            | FFmpeg       | everything, pretend                                                  |             |

"Not yet" drivers follow the vendor's documented API and are tested against its answers, not a
real camera. Reports and fixes are welcome.

- **Live video** in any browser over WebRTC (MSE and HLS as fallbacks). It starts in about a
  tenth of a second, adapts to the connection, and a stills view watches many cameras cheaply.
- **Camera controls**: pan, tilt, zoom, presets and whatever settings the camera has, plus its
  device info and firmware updates. The web app builds itself from what each driver declares.
- **Detection**: the cameras' own motion and AI events, and Norn's own on stills (motion; people,
  vehicles and animals with a small AI model). Triggers on a schedule, and an away mode.
- **Pan/tilt**: Norn presets with a picture and their own recording settings, patrol, reactions
  to detections, following people.
- **No re-encoding**: [go2rtc](https://github.com/AlexxIT/go2rtc) reads each camera once and
  repackages the stream; FFmpeg transcodes only what a browser can't play.
- **Recordings** as plain MP4 and JPEG files: continuous, clips that start seconds *before* their
  trigger, and pictures on a timer, on one timeline. Automatic ones expire by age, size or free
  space; manual and pinned ones stay.
- **Circles**: groups of cameras with one trigger, shared settings and shared controls.
- **Home Assistant** over MQTT discovery, or with streams to copy. See
  [Home Assistant](#home-assistant).
- **An app on your phone**: see [Install as an app](#install-as-an-app).
- **A YAML file, no database**: edit `config.yaml` by hand or in the app; both keep the other's
  changes, comments included.
- **Local**: no account, no cloud, no telemetry.

## Quick start

With Docker (Linux; amd64 or arm64), using [compose.yaml](compose.yaml):

```yaml
services:
  norn:
    image: ghcr.io/andiwand/norn:latest
    restart: unless-stopped
    network_mode: host
    environment:
      TZ: Etc/UTC
    volumes:
      - ./config:/config
      - ./recordings:/recordings
      - ./temp:/temp
    shm_size: 256m # the pre-recording buffer, in RAM
```

```sh
docker compose up -d
```

Open `http://<host>:8000`. A demo camera lets you try everything before adding a real one.

Host networking lets WebRTC reach the browser directly, and lets *Add camera* find cameras in
the network (ONVIF's discovery is multicast, which Docker's bridge network doesn't pass). On
Docker Desktop (macOS, Windows), map `8000:8000`, `8555:8555/tcp` and `8555:8555/udp` instead;
*Add camera* can still check a camera's address.

Without Docker, with `go2rtc` and `ffmpeg` on the PATH: `uvx --from norn-hub norn`.

## Configuration

Everything is in `config.yaml` (`/config` in the container), editable in the app too. Settings
left out keep their defaults:

```yaml
recording:
  retention_days: 14 # automatic recordings expire after this; 0: never
  max_gb: 500 # and are kept under this size, oldest first; 0: no limit
  min_free_gb: 20 # and leave this much free on the disk; 0: no limit
  segment_minutes: 10 # length of one file of a continuous recording
  clip_seconds: 30 # length of a triggered clip
  prebuffer_seconds: 10 # a clip starts this long before its trigger
  picture_seconds: 0 # a picture of every camera this often; 0: off
  triggers: [motion] # what starts a clip: motion, person, vehicle, ...
  schedule: # when detections record; none: always
    - { days: [mon, tue, wed, thu, fri], from: "20:00", to: "07:00" }

away: # holiday mode: detections record at any time; also a switch in the header
  start: 2026-12-20T15:00 # planned; or `active: true` for now
  end: 2027-01-03T12:00
  triggers: [motion, person]
  picture_seconds: 60 # 0: as usual

firmware:
  check_hours: 24 # 0: never

detection: # Norn's own, on a still of each camera
  motion: true
  objects: true # people, vehicles, animals: needs norn-hub[detect] (in the Docker image)
  every_seconds: 2
  min_score: 0.5 # how sure the AI must be
  confirm_seconds: 0 # an object counts once seen this long; 0: at once
  stills: auto # keyframe (nearly free), live (every frame), auto

mqtt: # see Home Assistant below
  enabled: true
  host: homeassistant.local
  username: norn
  password: secret

circles:
  outside:
    name: Outside
    cameras: [front-door, garden]
    picture_seconds: 300 # settings for these cameras; a camera's own wins
    together: true # one camera's trigger records all of them

cameras:
  front-door: # the id: the key here and the folder of its recordings
    name: Front door
    driver: rtsp
    url: rtsp://user:password@192.168.1.20:554/stream1
    substream: rtsp://user:password@192.168.1.20:554/stream2 # optional, for the grid
    record: continuous # default: off
    picture_seconds: 60 # its own (also clip_seconds, prebuffer_seconds, triggers, schedule)

  garden:
    name: Garden
    driver: hikvision
    host: 192.168.1.64
    username: admin
    password: secret # quote it if it starts with a special character
```

The process itself is set with environment variables:

| Variable              | Default                        | What                                                       |
| --------------------- | ------------------------------ | ---------------------------------------------------------- |
| `NORN_CONFIG`         | `data/config/config.yaml`      | The config file (`/config/config.yaml` in the image).      |
| `NORN_RECORDINGS`     | `data/recordings`              | Finished recordings (`/recordings`); can be a NAS.         |
| `NORN_TEMP`           | `data/tmp`                     | What is being recorded (`/temp`); best a local disk.       |
| `NORN_BUFFER`         | `/dev/shm/norn`                | The pre-recording buffer: RAM if /dev/shm has 128 MB, else `<temp>/.norn/buffer`. |
| `NORN_PORT`           | `8000`                         | The web app and the API.                                   |
| `NORN_WEBRTC_PORT`    | `8555`                         | WebRTC media, TCP and UDP.                                 |
| `NORN_RTSP_SHARE`     | `0`                            | `1`: serve the RTSP streams (port 8554) to the network.    |
| `NORN_LOG_FILE`       | `<config>/.norn/logs/norn.log` | Rotated, 5 × 5 MB; `off` for none.                         |
| `NORN_LOG_LEVEL`      | `info`                         | `debug`, `info`, `warning` or `error`.                     |
| `NORN_GO2RTC`         | `managed`                      | `managed` (Norn runs go2rtc), `external`, or `off`.        |
| `NORN_GO2RTC_API`     | `http://127.0.0.1:1984`        | go2rtc's API, for an `external` one.                       |
| `NORN_GO2RTC_BIN`, `NORN_FFMPEG` | `go2rtc`, `ffmpeg`  | The binaries.                                              |
| `NORN_MQTT`           |                                | Initial broker, `mqtt://user:password@host:1883` (`mqtts://` for TLS). |
| `NORN_MQTT_PREFIX`, `NORN_MQTT_DISCOVERY`, `NORN_MQTT_STILLS` | `norn`, `homeassistant`, `0` | Initial values of the MQTT settings below. |
| `TZ`                  |                                | The time zone of file names, schedules and away times.     |

### Recordings

```
recordings/front-door/2026-11-15/14-32-07_manual.mp4     the video
                                 14-32-07_manual.json    details of a clip
                                 14-32-07_manual.jpg     its thumbnail
                                 14-35-00_interval.jpg   a picture on the timer
```

The last seconds of each camera wait in RAM (`NORN_BUFFER`), recordings are written to
`NORN_TEMP` and moved to `NORN_RECORDINGS` when finished. Diagnostics shows each stage, a
storage forecast, and Norn's CPU and memory.

Start a clip from anything that sends HTTP (`POST /api/circles/<id>/record` for a circle; the
whole API is at `/api/docs`):

```sh
curl -X POST http://norn.local:8000/api/cameras/front-door/record \
  -H 'Content-Type: application/json' -d '{"trigger": "doorbell", "seconds": 30}'
```

### Home Assistant

Through Norn, each camera keeps one connection, and its password stays in Norn.

**MQTT** (in Home Assistant, the Mosquitto add-on): turn it on in **Settings → MQTT** or in
`config.yaml`, and Home Assistant's discovery adds everything by itself:

```yaml
mqtt:
  enabled: true
  host: homeassistant.local
  port: 0 # 0: 1883, or 8883 with TLS
  tls: false
  username: norn
  password: secret
  prefix: norn # Norn's topics start with it
  discovery: true # Home Assistant's MQTT discovery
  discovery_prefix: homeassistant
  stills_seconds: 0 # each camera's still this often (at least 5), as a camera entity; 0: none
```

`NORN_MQTT` and the other `NORN_MQTT_*` variables only give the initial values: when config.yaml
has no `mqtt` section, Norn writes them into it on start. From then on the file alone counts, so
change the settings there or in Settings → MQTT. Norn connects again when they change.

Home Assistant then shows a **Norn** device (**Away mode** switch, a record button per circle,
**Last error**) and one device per camera with a sensor per kind of detection, **Recording** and
**Online** sensors, **Record clip** and **Stop clip** buttons, a **Preset** select, and the
camera's controls as switches, selects, numbers and buttons. While a camera doesn't answer, its
controls, presets and still are unavailable. A failed command shows as **Last error** and the
entity returns to the camera's real state.

The topics, for other home automation (retained; `ON`/`OFF`):

| Topic                                      | What                                                   |
| ------------------------------------------ | ------------------------------------------------------ |
| `norn/status`                              | `online` or `offline`.                                 |
| `norn/error`, `norn/error/attributes`      | The last failed command: why, what and when.           |
| `norn/away`, `norn/away/set`               | Away mode.                                             |
| `norn/camera/<id>/available`               | `online` or `offline`: whether the camera answers Norn. |
| `norn/camera/<id>/online`, `.../recording` | Whether the camera answers, and records.               |
| `norn/camera/<id>/event/<kind>`            | A detection (`motion`, `person`, ...).                 |
| `norn/camera/<id>/record/set`              | `PRESS`, `STOP`, or `{"trigger": "doorbell", "seconds": 30}` (5 to 3600). |
| `norn/camera/<id>/preset`, `.../set`       | The Norn preset, by name.                              |
| `norn/camera/<id>/control/<id>`, `.../set` | A control: `ON`/`OFF`, an option's label, or a number. |
| `norn/circle/<id>/record/set`              | Like a camera's, for all the circle's cameras.         |
| `norn/camera/<id>/still`                   | A JPEG, with `stills_seconds` (not retained).          |

Anyone who can publish to the broker controls the cameras: give it passwords.

**Video**: MQTT carries none. Start Norn with `NORN_RTSP_SHARE=1` and add a **Generic Camera**
with `rtsp://<norn>:8554/<camera id>` (`<camera id>_sub` for the small stream) and the still
`http://<norn>:8000/api/cameras/<camera id>/still.jpg`; or, without RTSP, an **MJPEG IP Camera**
with `http://<norn>:8000/api/cameras/<camera id>/stills`. A camera's **Connect** panel has these
addresses and a `configuration.yaml` to copy.

### Install as an app

The arrow button in the top bar installs Norn, or explains how:

- **iPhone, iPad**: Safari, Share, Add to Home Screen. **Mac**: Safari, File, Add to Dock.
- **Android, Chrome, Edge**: the browser's Install app, which needs HTTPS (over plain HTTP you get
  a shortcut). For example [Tailscale Serve](https://tailscale.com/kb/1312/serve)
  (`tailscale serve --bg 8000`) or a reverse proxy like Caddy that passes WebSockets.

### Sign-in

Off until you add the first user in **Settings → Users**: then everyone signs in, at home too.
Turn it on before you open Norn to the internet, behind a reverse proxy with HTTPS (Norn doesn't
serve HTTPS itself). Two roles:

- **Admin**: changes everything, adds and removes users.
- **Viewer**: watches live and recorded video, steers pan/tilt cameras, records a clip, keeps
  recordings, switches away mode.

Users are in `config.yaml` (`users:`, with a password hash). Each device stays signed in while
it's used at least once a month; **Settings → Account** lists them and signs them out. Webhooks
and scripts use an API token from there: `Authorization: Bearer <token>`. Shared RTSP streams
(`NORN_RTSP_SHARE`) have no sign-in: keep them inside your home network.

## Development

`backend/` (Python, FastAPI), `frontend/` (SvelteKit, Tailwind), `website/` (GitHub Pages).
[AGENTS.md](AGENTS.md) explains the architecture.

```sh
cd backend && uv run norn                          # http://localhost:8000; NORN_GO2RTC=off without go2rtc
cd frontend && npm install && npm run dev          # http://localhost:5173, with hot reload

cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run lint && npm run check && npm test

docker build -t norn . && docker run --rm -p 8000:8000 norn
```

## License

MIT. The Docker image bundles [go2rtc](https://github.com/AlexxIT/go2rtc) (MIT) and FFmpeg (GPL
build from [static-ffmpeg](https://github.com/wader/static-ffmpeg)).
