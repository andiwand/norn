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
- Settings are editable in the app: recording, pre-recording, pictures, firmware check interval.
- Three storage stages: a RAM buffer per camera, so clips start before their trigger; temporary
  storage for what is being recorded; the recordings folder for finished files. Settings shows
  what each holds, and the CPU and memory of Norn, go2rtc and each FFmpeg.
- Camera detections as triggers: motion and AI events pushed by Reolink cameras (person,
  animal, ...), the Hikvision alert stream, and the alarm of supra/Foscam cameras. A clip runs
  while the detection lasts; a circle can record all its cameras together. A live badge shows
  what each camera detects.
- A storage forecast per trigger and camera: bytes per day, the size it levels off at, and when
  the disk is full; measured from recordings, estimated from the bitrate before.
- Pictures on a timer (trigger `interval`), globally, per circle or per camera.
- Automatic recordings expire after the retention time, shown as a ring on each; clips recorded
  by hand stay. Recordings have a delete button.
- A timeline of all recordings with thumbnails, at 1 hour, 6 hours, a day or a week.
- Circles: groups of cameras with one trigger (and webhook), shared settings, and the controls
  they have in common set on all at once.
- Camera pages fold their panels; long choices become dropdowns.
- Controls are cached: the server keeps them warm, the browser remembers them, so a camera page
  opens complete.
