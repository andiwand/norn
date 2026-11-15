<p align="center"><img src="website/favicon.svg" width="72" alt=""></p>

<h1 align="center">Norn</h1>

<p align="center"><b>All your home cameras in one place.</b><br>
A lightweight, self-hosted hub that relays live video to your phone or desktop browser, gives you
the controls of the camera's own app, and records.</p>

<p align="center"><a href="https://andiwand.github.io/norn/">Website</a> ·
<a href="#quick-start">Quick start</a> · <a href="#configuration">Configuration</a> ·
<a href="#development">Development</a></p>

---

> Norn is an early preview. Support for cameras grows one real camera at a time. See
> [PLAN.md](PLAN.md).

| Driver      | Cameras                                         | Video        | Control                                                    |
| ----------- | ----------------------------------------------- | ------------ | ---------------------------------------------------------- |
| `hikvision` | Hikvision IP cameras (tested: DS-2CD2042WD-I)   | RTSP H.264   | day/night, WDR, flip, colour, motion detection, firmware   |
| `reolink`   | Reolink (tested: E1 Pro)                        | RTSP H.264   | pan/tilt, presets, day/night, image (ONVIF)                |
| `onvif`     | any ONVIF camera                                | RTSP         | PTZ, presets, day/night, image                             |
| `foscam`    | Foscam CGI: supra IPC-1A / IPC-100HD, Wansview… | MJPEG (HTTP) | pan/tilt, presets, resolution, brightness, flip            |
| `rtsp`      | anything with an RTSP URL                       | RTSP         | –                                                          |
| `demo`      | a test pattern with pretend controls            | FFmpeg       | everything, pretend                                        |

Each camera page shows what the camera reports about itself (model, firmware, uptime, …) and
whether newer firmware exists.

- **Live video** in any browser over WebRTC, with MSE and HLS as fallbacks. Installable on phones.
- **Camera controls**: pan, tilt, zoom, presets, and whatever settings the camera has. Each driver
  describes its controls; the web app builds itself from that.
- **No re-encoding.** [go2rtc](https://github.com/AlexxIT/go2rtc) reads each camera once and
  repackages the stream for every viewer and the recorder. FFmpeg transcodes only a stream a
  browser can't play.
- **Recordings** as plain MP4 files in day folders: continuous, or clips from a button or webhook.
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
  retention_days: 14 # delete recordings older than this; 0 keeps them forever
  segment_minutes: 10 # length of one file of a continuous recording
  clip_seconds: 30 # length of a triggered clip

cameras:
  front-door: # the id: the key here and the folder of its recordings
    name: Front door
    driver: rtsp
    url: rtsp://user:password@192.168.1.20:554/stream1
    substream: rtsp://user:password@192.168.1.20:554/stream2 # optional, for the grid
    record: continuous # off (default) or continuous
    enabled: true # default
    auto_update: false # install new firmware by itself, where the driver can

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
| `NORN_PORT`        | `8000`                    | The port of the web app and the API.                          |
| `NORN_WEBRTC_PORT` | `8555`                    | The port of WebRTC media, TCP and UDP.                        |
| `NORN_GO2RTC`      | `managed`                 | `managed` (Norn runs go2rtc), `external`, or `off`.           |
| `NORN_GO2RTC_API`  | `http://127.0.0.1:1984`   | The API of go2rtc; set it for an `external` go2rtc.           |
| `NORN_GO2RTC_BIN`  | `go2rtc`                  | The go2rtc binary.                                            |
| `NORN_FFMPEG`      | `ffmpeg`                  | The FFmpeg binary.                                            |
| `TZ`               |                           | The time zone of the recordings' file names.                  |

### Recordings

```
recordings/front-door/2026-11-15/14-32-07_manual.mp4   the video
                                 14-32-07_manual.json  details of a clip
                                 14-32-07_manual.jpg   its thumbnail
```

Start a clip from anything that sends HTTP, like Home Assistant or a doorbell:

```sh
curl -X POST http://norn.local:8000/api/cameras/front-door/record \
  -H 'Content-Type: application/json' -d '{"trigger": "doorbell", "seconds": 30}'
```

The whole API is documented at `/api/docs`.

> Norn has no sign-in yet. Run it in your home network only, not open to the internet.

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
