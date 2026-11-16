# Norn

All your home cameras in one place: a lightweight, self-hosted hub that relays live video to your
phone or desktop browser, gives you the camera's controls, and records.

```sh
uvx --from norn-hub norn            # needs go2rtc and ffmpeg on the PATH
uvx --from 'norn-hub[detect]' norn  # with Norn's own detection of people, vehicles, animals
```

Then open http://localhost:8000. The Docker image comes with everything included:
`ghcr.io/andiwand/norn`.

Documentation: https://andiwand.github.io/norn/ · Source: https://github.com/andiwand/norn
