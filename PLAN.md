# Plan

What comes next, roughly in order. The changelog has what is done.

## Cameras, one at a time

Done: Hikvision (ISAPI), Reolink (ONVIF), supra/Foscam CGI, generic ONVIF. Next for these:

- Hikvision: motion events from `/ISAPI/Event/notification/alertStream` as recording triggers.
- Reolink: with the HTTP API on, the online firmware check and update (`CheckFirmware`,
  `UpgradeOnline`), spotlight and siren. ONVIF events (PullPoint) as triggers.
- supra/Foscam: the alarm state from `get_status.cgi` as a trigger; the IR LED.

We add support by looking at one real camera after the other: find its protocols (RTSP, ONVIF,
vendor API), what it can do, and write or extend a driver.

1. `onvif` driver: profiles and stream URLs, PTZ (continuous move, presets, home), imaging
   settings as controls, events (motion) as triggers. Discovery over WS-Discovery in the add form.
2. Vendor drivers on top of `onvif` or their own APIs, for what ONVIF lacks (spotlight, siren,
   privacy mode): Reolink, Tapo, Amcrest/Dahua, Hikvision, UniFi Protect.
3. Two-way audio (`talkback`), through go2rtc.

## Recording

- Motion and other camera events as triggers, with a pre-roll buffer.
- A timeline per camera to scrub through continuous recordings.
- Disk usage in the settings, and a size limit besides the age limit.

## Later

- Users and sign-in, so Norn can be reached from outside the home. Until then it trusts its
  network, and the API (including camera passwords in options) has no access control.
- Hide secrets in API responses.
- Notifications (web push) for triggers.
