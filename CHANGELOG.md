# Changelog

## Unreleased

- New tabs: Cameras (the list, with rows you can click, and circles), Away, Diagnostics (version,
  go2rtc, resources, storage, log) and Help (webhook, config file, links). Settings has sub-tabs
  Recording, Detection and Firmware, with Save at the top. The list of camera drivers is gone.
- Live: Auto, HD, SD or Stills for all tiles, remembered per browser; each tile shows the
  quality that plays.
- Arrange the cameras on the Live page by dragging or with arrows; the order is saved in
  config.yaml (`PUT /api/cameras/order`).
- A default Norn preset per camera (the star on a preset): the camera returns there when
  nothing else steers it: no patrol in its schedule, no hold after a hand move or a reaction,
  no following. Star and delete show on hover; on touch screens always, and deleting takes
  a second tap. The Edit toggle is gone.
- No more "Exception in ASGI application" tracebacks in the log when a browser closes a video
  connection (switching quality, leaving the page).

## 0.1.1 — 2026-11-16

- Pan/tilt: commands are sent in order, so a quick tap can't leave the camera turning to its
  end stop; a move stops by itself after 8 s without a new command (holding renews it); the
  camera stops when the page loses focus; the arrow keys steer only over the video or the pad.
- Adaptive quality is calmer: no switching while a stream starts, a freeze must last two
  checks, and a stream that played isn't taken for one that never starts.

## 0.1.0 — 2026-11-16

The first version, an early preview.

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
- Norn presets for pan/tilt cameras: a camera preset slot plus settings to apply there, with a
  picture; saved from the camera page. Patrol through them (in turn or at random, a dwell
  time, a schedule), reactions (a detection somewhere turns a camera to a preset for a while),
  and following people (the camera's own tracking, else Norn's person detection).
- Logging to the console, a rotating file and the Settings page; credentials are scrubbed.
- The timeline shows what started each clip as an icon, and finds the clips that saw a
  person, a vehicle, ...
- Camera passwords never leave Norn through the API: secret options are left out of responses,
  passwords in addresses show as •••, and a save without them keeps the stored ones.
- Storage limits besides the age: a size limit and a minimum of free disk space; the oldest
  automatic recordings go first. The forecast says when a limit is reached.
- Recordings can be pinned (kept whatever the limits) and downloaded, from the tile or the
  big view.
- Adaptive quality: the player steps down (HD, SD, Low) when the connection struggles and up
  again after a calm. Norn probes each camera's streams (also third and fourth ones) and
  whether they work at the same time; each stream can be switched on or off (one at a time
  where the camera can't do more). A transcoded low stream exists only when a camera has no
  small one, and go2rtc runs it only while someone watches.
- A button to the camera's own web page, when it has one that answers.
- Norn's own detection on stills: motion (comparing stills, no extra packages) and people,
  vehicles and animals (YOLOX on ONNX Runtime, the optional extra `norn-hub[detect]`, in the
  Docker image). Things that stand still stop counting. Labels are defined once (labels.py);
  every source's own names map onto them.
- Still streams: a camera as a slow stream of stills (keyframes only, or every frame), shared
  by detection and the web app, idle when nobody watches. The Live page can show stills
  instead of video; the player shows the newest still at once while the video starts.
- Schedules for triggers (time windows per day, also past midnight), globally, per circle or
  per camera; and away mode for holidays, switched in the header or planned, with its own
  triggers and pictures.
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
