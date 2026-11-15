# Changelog

## Unreleased

The first version.

- Live video in the browser through go2rtc: WebRTC, with MSE and HLS as fallbacks.
- Camera drivers with capabilities and controls; the web app builds its controls from them.
  Drivers: `demo` (a test pattern with pretend controls) and `rtsp`.
- Pan, tilt, zoom and presets, hold to move, also with the arrow keys.
- Recording without re-encoding: continuous files and triggered clips, with thumbnails, in day
  folders. A webhook starts clips.
- Cameras in `config.yaml`, edited by hand or in the app, with comments kept.
- One Docker image with go2rtc and FFmpeg, for amd64 and arm64; the PyPI package `norn-hub`.
- Drivers `foscam` (the CGI interface of supra, early INSTAR, Wansview: MJPEG, pan/tilt,
  presets, image settings), `hikvision` (ISAPI: day/night, WDR, flip, colour, motion detection,
  firmware upload), `onvif` (any ONVIF camera: PTZ, presets, imaging) and `reolink` (on ONVIF).
- MJPEG cameras: the player shows MJPEG frames, the recorder encodes them to H.264.
- Device status: Norn reads each camera every 5 minutes (model, firmware, uptime, ...), shows
  offline cameras, and compares the firmware with a catalogue of the latest versions.
- Firmware updates from a file (Hikvision, Axis), one click where the driver finds firmware
  online (Reolink, Tapo), an `auto_update` setting per camera, and a daily check.
- `reolink` uses Reolink's app protocol (Baichuan, port 9000) through reolink_aio, so it works
  with the camera's HTTP API off: IR, status light, siren, day/night, auto-tracking, motion
  sensitivity, HTTP/HTTPS switches, and firmware download and upload.
- New drivers `dahua` (Amcrest, Lorex), `axis`, `foscam-hd`, `tapo` and `unifi`, written from
  the vendors' APIs and not yet tested on real cameras.
- Controls are cached: the server keeps them warm, the browser remembers them, so a camera page
  opens complete.
