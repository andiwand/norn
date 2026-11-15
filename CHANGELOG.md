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
