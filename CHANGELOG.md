# Changelog

## 0.7.3 — 2026-11-18

- MQTT is set in config.yaml (`mqtt:`) or in Settings → MQTT: on or off, broker, user, password,
  topic prefix, discovery and stills. The NORN_MQTT* environment variables are its defaults.
  Norn connects again when the settings change, without a restart.

## 0.7.2 — 2026-11-18

- Reolink: the sensitivity and the delay of the camera's AI for each kind it detects (person,
  animal, ...) are controls under Alarm. A delay of a few seconds keeps short false alarms at
  night (insects in the infrared light) from recording.
- Detection by Norn: `confirm_seconds` ("Confirm after" in Triggers): an object counts only once
  Norn has seen it that long.
- The drivers share one way of sending requests and reporting network errors and refused logins.
- CPU readings are steady: the hub measures at most every 4 s, so two pages polling at once no
  longer see tiny, jumpy windows.

## 0.7.1 — 2026-11-18

Fixes from a review of the whole code:

- config.yaml: a save from the web app no longer overwrites a hand edit made just before, or a
  file with an error (which could empty it); comments inside presets, schedules and removed
  cameras stay where they belong; error messages never show a password.
- Recording: a detection while a clip is being finished starts a new clip instead of getting
  lost; clips have a length limit with pre-recording too; a failing FFmpeg start is retried; the
  hour the clocks go back no longer overwrites recordings.
- MQTT: an error in config.yaml, or a camera that is offline at start, no longer removes devices
  and sensors from Home Assistant; a circle's record button records on every camera even if one
  fails; `NORN_MQTT_PREFIX` is checked at start.
- go2rtc: with an external go2rtc, Norn leaves streams it didn't make alone; a stream that
  failed to sync is retried.
- Cameras: ONVIF and UniFi cameras that are offline when Norn starts get their video once they
  are back; Axis day and night were swapped; Dahua diagonal moves; Reolink closes its connection
  when a camera is edited or removed; Tapo pauses after a failed login instead of locking the
  account; Hikvision person and vehicle detections can be triggers.
- Web app: the timeline keeps working after filtering by camera; turning a patrol off sticks;
  "Save this view" no longer replaces a preset of the same name; Away's home switch works when
  the server's time zone differs; players close their connection when they are gone; the pan
  and tilt pad works with the keyboard.

## 0.7.0 — 2026-11-17

- Home Assistant over MQTT: with `NORN_MQTT` set to a broker, each camera appears in Home
  Assistant by itself (MQTT discovery) with sensors for its detections, recording and whether
  it is online, buttons to record and stop a clip, its Norn presets, and its controls as
  switches, selects, numbers and buttons. Away mode is a switch both ways, and each circle has a
  record button. With `NORN_MQTT_STILLS`, each camera also sends its still every so many
  seconds, as a camera entity. Other home automation can use the same topics (`norn/...`); see
  the README.
- MQTT in Diagnostics: whether Norn is connected to the broker, why not, and the last command
  that failed. In Home Assistant a failed command shows as the Norn device's "Last error", and
  the entity returns to the real state; the controls, presets and still of a camera that doesn't
  answer are unavailable.

## 0.6.1 — 2026-11-17

- Phone: the page no longer moves sideways a little, which also made the top and bottom bars
  shift while scrolling (the Save bar on Away, Triggers and Settings was 4 px too wide). The
  Save bar sticks right below the lower top bar again.
- Away, Triggers and Settings: Save and Discard sit beside the page's headline, and the
  headline stays below the top bar while scrolling (with Settings' tabs), instead of a separate
  bar that stuck halfway down. Away's own "At home" chip is gone: the top bar's switch shows it.

## 0.6.0 — 2026-11-17

- Recordings timeline: the gaps between camera tracks point, press and drag like the tracks.
- Recordings timeline on a phone: scrolling the page over the timeline no longer changes the
  moment above. Like the mouse's pointing and dragging, a finger now does one thing at a time:
  dragging along the tracks (or a tap) picks the moment, dragging the times below the tracks
  moves the window. The time labels no longer run into each other.
- Recordings timeline: a tap or click on a trigger icon opens its clip (on a phone it no longer
  only picked the moment). On a phone the cameras at the moment show two to a row, the thumbnail
  strip is left out and the detection chips scroll sideways, so the tracks stay in view.
- Top bar: two small gauges, like a battery, for how full the recordings disk is and how busy the
  CPU is; they link to Diagnostics. Storage left the Recordings page (it is in Diagnostics).
- Install the app: a button in the top bar while Norn doesn't run as an installed app. It opens
  the browser's install dialog where there is one, else Help's new section on how to do it: for
  Safari (Share, Add to Home Screen; on a Mac File, Add to Dock), and why a browser can't when Norn
  is open over plain HTTP (browsers install apps only from HTTPS). Settings links to it on a phone.
- Top bar: Home and Away are a switch now, a house on the left and a plane on the right; the
  button that said "Home" looked like a link to the start page. The connection is just its dot.
- Less height above the content: a lower top bar, smaller page titles, and the sentence under a
  title only where there is room; the camera chips on Recordings stay on one line.

## 0.5.0 — 2026-11-16

- Triggers: a page of its own for what makes Norn record (detections and their schedule, clip
  length, pre-recording, pictures) and Norn's detection, with a list of the circles, cameras and
  presets that set their own. Settings keeps storage, continuous files and firmware.
- Cameras can set their own clip length; pan/tilt presets their own triggers, clip length and
  pre-recording, which count while the camera is at the preset
  (`PUT /api/cameras/<id>/presets/<preset>/recording`).
- Camera page: the pan/tilt pad stays beside the video; recent recordings, recording &
  triggers, controls and the device fold up below it. A camera's recording settings moved there
  from its edit page.
- Circle page: the cameras first, Record all in the title line, the settings folded below.
- A record button on every camera's video: on Live, in circles and on its page.
- Home Assistant: a Connect panel on each camera's page with its stream and picture addresses,
  the API calls to record, turn and set controls, and a `configuration.yaml` to copy.
  `NORN_RTSP_SHARE=1` serves the RTSP streams to the network.

## 0.4.0 — 2026-11-16

- Timeline: every camera at one moment, above the tracks. Move along the tracks: each tile
  shows the video frame then if a recording runs (`GET /api/recordings/<id>/frame?at=`), else
  the newest picture or thumbnail before it, with how long before. Click a tile to open it
  there.

## 0.3.1 — 2026-11-16

- Docker image: Norn's own object detection works when the container runs as a user other
  than root (the model folders weren't readable).

## 0.3.0 — 2026-11-16

- Instant live video: Norn keeps the newest keyframe of a stream, and what followed, ready.
  A new viewer's picture appears in about 0.1 s instead of waiting up to a few seconds for
  the camera's next keyframe; stills come from it at once too. By default for the stream the
  Live page shows; "Instant start" per stream in the camera's settings (`ready_streams`).
  Other streams are kept while watched and 5 minutes after.
- Replace a Norn preset with what the camera shows now (and the preset's settings as they are
  now): a button beside the star, with a second tap to confirm. Same name, same camera slot.
- A default preset whose slot the camera no longer has (deleted on the camera) isn't steered
  to any more; the log says to save the view again.
- Reolink: the camera's preset list is read anew each time; deleted or renamed presets no
  longer linger under their old names.
- config.yaml: a camera's presets or lists written by the app land in its block, not below
  the example comments at the end of the file.
- Colours: the detection badge on the video is dark glass with a teal dot, like the REC
  badge; "Update available" and the default preset's star use the accent. Orange is left
  for warnings.

## 0.2.0 — 2026-11-16

- New tabs: Cameras (the list, with rows you can click, and circles), Away, Diagnostics (version,
  go2rtc, resources, storage, log) and Help (webhook, config file, links). Settings has sub-tabs
  Recording, Detection and Firmware, with Save at the top. The list of camera drivers is gone.
- Live: Auto, HD, SD or Stills for all tiles, remembered per browser; each tile shows the
  quality that plays.
- Arrange the cameras on the Live page by dragging or with arrows; the order is saved in
  config.yaml, each camera with its comments (`PUT /api/camera-order`).
- A default Norn preset per camera (the star on a preset): the camera returns there when
  nothing else steers it: no patrol in its schedule, no hold after a hand move (at least 30 s)
  or a reaction, no following. Star and delete show on hover; on touch screens always, and
  deleting takes a second tap.
- Pan/tilt: commands are sent in order, so a quick tap can't leave the camera turning to its
  end stop; a move stops by itself after 8 s without a new command (holding renews it); the
  camera stops when the page loses focus; the arrow keys steer only over the video or the pad.
- Adaptive quality is calmer: no switching while a stream starts, a freeze must last two
  checks, and a stream that played isn't taken for one that never starts.
- No more "Exception in ASGI application" tracebacks in the log when a browser closes a video
  connection (switching quality, leaving the page).

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
