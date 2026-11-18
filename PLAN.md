# Plan

What comes next, roughly in order. The changelog has what is done.

## Cameras, one at a time

Done and tested on real cameras: Hikvision (ISAPI, events), Reolink (Baichuan, events, presets,
AI sensitivity), supra/Foscam CGI (alarm, IR, presets), generic ONVIF. Finding cameras in the
add form: ONVIF's WS-Discovery, and "check an address" (ONVIF, Foscam CGI, Hikvision, Reolink
fingerprints) for networks multicast doesn't cross.

Waiting for real testers (written from the vendors' documentation, tested against their
documented answers only):

- Dahua / Amcrest / Lorex, Axis, Foscam HD, TP-Link Tapo, UniFi Protect.
- Cloud-only brands (Ring, Nest, Wyze, Eufy, Arlo) through go2rtc's sources.

We add support by looking at one real camera after the other: find its protocols (RTSP, ONVIF,
vendor API), what it can do, and write or extend a driver. Still to do there:

1. `onvif`: events (motion) as triggers, over PullPoint.
2. Two-way audio (`talkback`), through go2rtc.

## Next

- HTTPS (own certificate, or behind Caddy / `tailscale serve`) and a service worker, so Android
  installs the app; then web push notifications for detections.
- Real-camera tests of the untested drivers (see above).

## Later

- Users and sign-in, so Norn can be reached from outside the home. Until then it trusts its
  network, and the API (including camera passwords in options) has no access control.
- Hide secrets in API responses.
- Notifications (web push) for triggers.
