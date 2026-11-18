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

> Norn is an early preview. Support for cameras grows one real camera at a time. See
> [PLAN.md](PLAN.md).

| Driver      | Cameras                                             | Video        | Control                                                         | Tested on a real camera |
| ----------- | --------------------------------------------------- | ------------ | --------------------------------------------------------------- | ----------------------- |
| `reolink`   | Reolink (over Reolink's app protocol, no HTTP needed) | RTSP H.264 | pan/tilt, presets, IR, status light, siren, tracking, motion and AI events, firmware | yes (E1 Pro)            |
| `hikvision` | Hikvision and relabels (Annke, HiLook, …)           | RTSP H.264   | day/night, WDR, flip, colour, motion detection and events, firmware file | yes (DS-2CD2042WD-I)    |
| `foscam`    | Foscam CGI: supra IPC-1A / IPC-100HD, Wansview, …   | MJPEG (HTTP) | pan/tilt, presets, resolution, brightness, flip, motion alarm   | yes (supra)             |
| `dahua`     | Dahua, Amcrest, Lorex                               | RTSP         | pan/tilt/zoom, presets, day/night, flip, motion detection       | not yet                 |
| `axis`      | Axis                                                | RTSP H.264   | pan/tilt/zoom, presets, day/night, firmware file                | not yet                 |
| `foscam-hd` | Foscam HD (since about 2014)                        | RTSP H.264   | pan/tilt/zoom, presets, IR, mirror, flip                        | not yet                 |
| `tapo`      | TP-Link Tapo                                        | RTSP H.264   | pan/tilt, presets, night vision, privacy, siren, firmware       | not yet                 |
| `unifi`     | UniFi Protect cameras (through the console's API)   | RTSPS        | status light, microphone, PTZ presets                           | not yet                 |
| `onvif`     | any ONVIF camera                                    | RTSP         | PTZ, presets, day/night, image                                  | yes (Reolink, ONVIF)    |
| `rtsp`      | anything with an RTSP URL                           | RTSP         | –                                                               |                         |
| `demo`      | a test pattern with pretend controls                | FFmpeg       | everything, pretend                                             |                         |

Drivers marked "not yet" follow the vendor's documented API and have tests with its answers, but
nobody has run them against the real camera yet. Reports and fixes are welcome.

Each camera page shows what the camera reports about itself (model, firmware, uptime, …) and
whether newer firmware exists.

- **Live video** in any browser over WebRTC, with MSE and HLS as fallbacks. It starts in about
  a tenth of a second (Norn keeps the newest keyframe ready), the quality adapts to the
  connection, and a stills view watches many cameras on little bandwidth.
- **Camera controls**: pan, tilt, zoom, presets, and whatever settings the camera has. Each driver
  describes its controls; the web app builds itself from that. Norn tests each camera's streams
  (also third and fourth ones) and whether they work at the same time.
- **Detection**: the cameras' own motion and AI events, and Norn's own on stills (motion; people,
  vehicles and animals with a small AI model). Triggers on a schedule, and an away mode. What
  records can be set for all cameras, and per circle, camera or pan/tilt preset.
- **Pan/tilt**: Norn presets with a picture and their own settings, a default preset to return
  to, patrol, reactions to detections, following people. A preset can record its own way
  (`triggers`, `clip_seconds`, `prebuffer_seconds` under the preset) while the camera is there.
- **No re-encoding.** [go2rtc](https://github.com/AlexxIT/go2rtc) reads each camera once and
  repackages the stream for every viewer and the recorder. FFmpeg transcodes only a stream a
  browser can't play.
- **Recordings** as plain MP4 and JPEG files in day folders: continuous, clips from a button or
  webhook that start a few seconds *before* the trigger, and pictures on a timer. A timeline
  shows them all, with what triggered each, and every camera at the moment you point at.
  Automatic recordings expire by age, size or free space; clips you record by hand, or pin,
  stay.
- **Circles**: groups of cameras with one trigger, shared settings, and controls set on all at
  once.
- **Home Assistant**: over MQTT, each camera appears in Home Assistant by itself, with its
  detections, recording, controls and presets, and away mode as a switch. Each camera's page
  also has its streams to copy. See [Home Assistant](#home-assistant).
- **An app on your phone**: install the web app to the home screen (see
  [Install as an app](#install-as-an-app)).
- **A YAML file, no database.** Edit `config.yaml` by hand or in the app; both keep the other's
  changes, comments included.
- **Local.** No account, no cloud, no telemetry.

## Quick start

With Docker (Linux host; amd64 or arm64):

```yaml
# compose.yaml
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

Open `http://<host>:8000`. A demo camera shows a test pattern, so you can try everything before
you add a real camera.

Host networking lets WebRTC reach the browser directly. On Docker Desktop (macOS, Windows), map
the ports instead: `8000:8000`, `8555:8555/tcp`, `8555:8555/udp`. Video then falls back to MSE.

Without Docker, with `go2rtc` and `ffmpeg` on the PATH:

```sh
uvx --from norn-hub norn
```

## Configuration

`config.yaml` (in `/config` in the container):

```yaml
recording:
  retention_days: 14 # automatic recordings expire after this; 0 keeps them forever
  max_gb: 500 # also keep them under this size (oldest automatic ones go first); 0: no limit
  min_free_gb: 20 # and keep this much free on the disk; 0: no limit
  segment_minutes: 10 # length of one file of a continuous recording
  clip_seconds: 30 # length of a triggered clip
  prebuffer_seconds: 10 # a clip starts this long before its trigger; 0 turns it off
  picture_seconds: 0 # a picture of every camera this often; 0 turns it off
  triggers: [motion] # what the cameras detect that starts a clip: motion, person, vehicle, ...
  schedule: # when detections record; none: always
    - { days: [mon, tue, wed, thu, fri], from: "20:00", to: "07:00" } # weeknights
    - { days: [sat, sun], from: "00:00", to: "23:59" }

away: # holiday mode: detections record at any time; also a switch in the header
  start: 2026-12-20T15:00 # planned; or `active: true` for now
  end: 2027-01-03T12:00
  triggers: [motion, person]
  picture_seconds: 60 # pictures while away; 0: as usual

firmware:
  check_hours: 24 # how often to ask the vendors for new firmware; 0 never

detection: # Norn's own detection, on a still of each camera every few seconds
  motion: true # compare stills (no extra packages)
  objects: true # people, vehicles, animals: pip install 'norn-hub[detect]' (in the Docker image)
  every_seconds: 2
  min_score: 0.5 # how sure the AI must be about an object
  confirm_seconds: 0 # an object counts once seen this long (less noise at night); 0: at once
  stills: auto # keyframe (nearly free), live (every frame, exact), auto

circles: # groups of cameras
  outside:
    name: Outside
    cameras: [front-door, garden]
    picture_seconds: 300 # settings for these cameras; a camera's own setting wins
    together: true # when one camera here detects a trigger, all of them record

cameras:
  front-door: # the id: the key here and the folder of its recordings
    name: Front door
    driver: rtsp
    url: rtsp://user:password@192.168.1.20:554/stream1
    substream: rtsp://user:password@192.168.1.20:554/stream2 # optional, for the grid
    record: continuous # off (default) or continuous
    enabled: true # default
    auto_update: false # install new firmware by itself, where the driver can
    picture_seconds: 60 # this camera's own (also clip_seconds, prebuffer_seconds, triggers, schedule)
    ready_streams: [sub] # streams kept ready, so live video starts at once; default: the small one

  garden:
    name: Garden
    driver: hikvision
    host: 192.168.1.64
    username: admin
    password: secret # quote it if it starts with a special character
```

The settings of the process come from environment variables:

| Variable           | Default                   | What                                                          |
| ------------------ | ------------------------- | ------------------------------------------------------------- |
| `NORN_CONFIG`      | `data/config/config.yaml` | The config file (`/config/config.yaml` in the image).         |
| `NORN_RECORDINGS`  | `data/recordings`         | The recordings folder (`/recordings` in the image).           |
| `NORN_TEMP`        | `data/tmp`                | What is being recorded (`/temp`); best a local disk.          |
| `NORN_BUFFER`      | `/dev/shm/norn`           | The pre-recording buffer; RAM if /dev/shm has 128 MB or more, else `<temp>/.norn/buffer`. |
| `NORN_PORT`        | `8000`                    | The port of the web app and the API.                          |
| `NORN_WEBRTC_PORT` | `8555`                    | The port of WebRTC media, TCP and UDP.                        |
| `NORN_LOG_FILE`    | `<config>/.norn/logs/norn.log` | The log file (rotated, 5 × 5 MB); `off` for none.   |
| `NORN_LOG_LEVEL`   | `info`                    | `debug`, `info`, `warning` or `error`.                        |
| `NORN_GO2RTC`      | `managed`                 | `managed` (Norn runs go2rtc), `external`, or `off`.           |
| `NORN_GO2RTC_API`  | `http://127.0.0.1:1984`   | The API of go2rtc; set it for an `external` go2rtc.           |
| `NORN_RTSP_SHARE`  | `0`                       | `1`: serve the RTSP streams to the network (Home Assistant).  |
| `NORN_MQTT`        |                           | An MQTT broker, `mqtt://user:password@host:1883` (`mqtts://` for TLS). |
| `NORN_MQTT_PREFIX` | `norn`                    | The first level of Norn's MQTT topics (letters, digits, `_`, `-`). |
| `NORN_MQTT_DISCOVERY` | `homeassistant`        | Home Assistant's discovery prefix (one level, like the prefix); `off` for none. |
| `NORN_MQTT_STILLS` | `0`                       | Send each camera's still over MQTT every so many seconds (at least 5); `0` for none. |
| `NORN_GO2RTC_BIN`  | `go2rtc`                  | The go2rtc binary.                                            |
| `NORN_FFMPEG`      | `ffmpeg`                  | The FFmpeg binary.                                            |
| `TZ`               |                           | The time zone of the recordings' file names.                  |

### Recordings

```
recordings/front-door/2026-11-15/14-32-07_manual.mp4     the video
                                 14-32-07_manual.json    details of a clip
                                 14-32-07_manual.jpg     its thumbnail
                                 14-35-00_interval.jpg   a picture on the timer
```

Recordings go through three stages: each camera's last seconds wait in RAM (`NORN_BUFFER`), what
is being recorded is written to `NORN_TEMP`, and finished files move to `NORN_RECORDINGS`, which
can be a NAS. Diagnostics shows what each stage holds, a forecast per trigger (measured from the
last week, or estimated from the settings and each camera's bitrate), and what Norn costs in CPU
and memory; the top bar shows how full the disk is and how busy the CPU is.

Start a clip from anything that sends HTTP, like Home Assistant or a doorbell:

```sh
curl -X POST http://norn.local:8000/api/cameras/front-door/record \
  -H 'Content-Type: application/json' -d '{"trigger": "doorbell", "seconds": 30}'
```

A circle has its own webhook, `POST /api/circles/<id>/record`, which records all its cameras.
The whole API is documented at `/api/docs`.

### Home Assistant

Home Assistant can use the cameras through Norn instead of directly: each camera keeps one
connection, to Norn, and its password stays in Norn. A camera's page has a **Connect** panel
with its addresses and a `configuration.yaml` to copy (buttons to record and turn to presets,
sensors for recording and detections).

- Video: start Norn with `NORN_RTSP_SHARE=1`, then add a **Generic Camera** with the stream
  `rtsp://<norn>:<rtsp port>/<camera id>` (`<camera id>_sub` for the small stream) and the
  still image `http://<norn>/api/cameras/<camera id>/still.jpg`.
- Without RTSP: an **MJPEG IP Camera** with `http://<norn>/api/cameras/<camera id>/stills`.

#### MQTT

With a broker (in Home Assistant, the Mosquitto add-on), Norn publishes what it knows and takes
commands, and Home Assistant's MQTT discovery adds everything by itself: no YAML to copy.
Start Norn with the broker's address:

```yaml
environment:
  NORN_MQTT: mqtt://norn:secret@homeassistant.local
```

Home Assistant then shows a **Norn** device with an **Away mode** switch and a record button for
each circle, and one device per camera with:

- a sensor for each kind of detection (motion, person, vehicle, ...), on while it lasts;
- **Recording** and **Online** sensors;
- **Record clip** and **Stop clip** buttons;
- **Preset**, to turn a pan/tilt camera to one of its Norn presets;
- the camera's controls, as Norn shows them: switches, selects, numbers and buttons.

Away mode goes both ways: an automation can turn it on when everyone has left, and others can
follow it when it changes in Norn (by hand or as planned).

While a camera doesn't answer, its controls, presets and still show as unavailable in Home
Assistant; its sensors and record buttons stay. While config.yaml has an error, Norn leaves the
devices it had in Home Assistant alone. A command that fails shows as the Norn device's
**Last error**, and the entity goes back to the camera's real state. Diagnostics shows whether
Norn is connected to the broker, and the last failed command.

MQTT carries no video: for that, add a Generic Camera (above). It can carry still pictures:
with `NORN_MQTT_STILLS=10`, each camera also gets a **Still** camera entity with a new picture
every 10 seconds. That is off by default, since each picture is a whole JPEG through the broker.

The topics, for other home automation (states are retained; `ON`/`OFF` for on and off):

| Topic                                  | What                                                       |
| -------------------------------------- | ---------------------------------------------------------- |
| `norn/status`                          | `online` or `offline`.                                     |
| `norn/error`, `norn/error/attributes`  | The last command that failed: why, and the command and time. |
| `norn/camera/<id>/available`           | `online` or `offline`: whether the camera answers Norn.    |
| `norn/away`, `norn/away/set`           | Away mode.                                                 |
| `norn/camera/<id>/event/<kind>`        | A detection (`motion`, `person`, ...).                     |
| `norn/camera/<id>/recording`           | Whether the camera records.                                |
| `norn/camera/<id>/online`              | Whether the camera answers.                                |
| `norn/camera/<id>/record/set`          | `PRESS` starts a clip, `STOP` ends it; or `{"trigger": "doorbell", "seconds": 30}` (5 to 3600 seconds). |
| `norn/camera/<id>/preset`, `.../set`   | The Norn preset, by name.                                  |
| `norn/camera/<id>/control/<id>`, `.../set` | A control: `ON`/`OFF`, an option's label, or a number. |
| `norn/circle/<id>/record/set`          | Like a camera's: all the circle's cameras.                 |
| `norn/camera/<id>/still`               | A JPEG, with `NORN_MQTT_STILLS` (not retained).            |

Anyone who can publish to the broker can control the cameras through these topics, so give the
broker passwords.

### Install as an app

Norn installs like an app, with its own icon and without the browser's bars. The button with
the arrow in the top bar does it, or explains how:

- **iPhone, iPad**: in Safari, Share, then Add to Home Screen. **Mac**: in Safari, File, then
  Add to Dock.
- **Android, desktop Chrome and Edge**: the browser's Install app. These browsers install only
  from an HTTPS address, so over `http://<host>:8000` they offer just a shortcut. Put Norn behind
  HTTPS with a certificate the phone trusts, for example with
  [Tailscale Serve](https://tailscale.com/kb/1312/serve) (`tailscale serve --bg 8000`) or a
  reverse proxy such as Caddy. A proxy must pass WebSockets (`/api/stream`, `/api/events`).

> Norn has no sign-in yet. Run it in your home network only, not open to the internet. The same
> goes for the shared RTSP streams.

## Development

The repository: `backend/` (Python, FastAPI), `frontend/` (SvelteKit, Tailwind), `website/` (the
GitHub Pages site). [AGENTS.md](AGENTS.md) explains the architecture.

```sh
# Backend, on http://localhost:8000 (needs go2rtc and ffmpeg for video; NORN_GO2RTC=off without)
cd backend && uv run norn

# Web app with hot reload, on http://localhost:5173, using the backend above
cd frontend && npm install && npm run dev

# Checks
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run lint && npm run check && npm test

# Everything in Docker
docker build -t norn . && docker run --rm -p 8000:8000 norn
```

## License

MIT. Norn bundles [go2rtc](https://github.com/AlexxIT/go2rtc) (MIT) and FFmpeg (GPL build from
[static-ffmpeg](https://github.com/wader/static-ffmpeg)) in its Docker image.
