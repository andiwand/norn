# Plan

What comes next, roughly in order. The changelog has what is done.

## Cameras, one at a time

Done and tested on real cameras: Hikvision (ISAPI, events), Reolink (Baichuan, events, presets),
supra/Foscam CGI, generic ONVIF. Next:

- Test the drivers written from documentation (Dahua, Axis, Foscam HD, Tapo, UniFi) on real
  cameras; cloud-only brands (Ring, Nest, Wyze, Eufy, Arlo) through go2rtc's sources.
- supra/Foscam: the alarm state from `get_status.cgi` as a trigger; the IR LED.

We add support by looking at one real camera after the other: find its protocols (RTSP, ONVIF,
vendor API), what it can do, and write or extend a driver.

1. `onvif` driver: profiles and stream URLs, PTZ (continuous move, presets, home), imaging
   settings as controls, events (motion) as triggers. Discovery over WS-Discovery in the add form.
2. Vendor drivers on top of `onvif` or their own APIs, for what ONVIF lacks (spotlight, siren,
   privacy mode): Reolink, Tapo, Amcrest/Dahua, Hikvision, UniFi Protect.
3. Two-way audio (`talkback`), through go2rtc.

## Next

- HTTPS (own certificate, or behind Caddy / `tailscale serve`) and a service worker, so Android
  installs the app; then web push notifications for detections.
- Saving presets on the supra cameras; real-camera tests of the untested drivers.
- ONVIF discovery and events in the add-camera form.

## Later

- Users and sign-in, so Norn can be reached from outside the home. Until then it trusts its
  network, and the API (including camera passwords in options) has no access control.
- Hide secrets in API responses.
- Notifications (web push) for triggers.
