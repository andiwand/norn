from __future__ import annotations

from pathlib import Path

import pytest

from norn.settings import Settings


def test_mqtt_prefixes_are_one_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORN_MQTT_PREFIX", "/norn-2/")
    assert Settings.from_env().mqtt_prefix == "norn-2"
    for name, value in (("NORN_MQTT_PREFIX", "home/norn"), ("NORN_MQTT_DISCOVERY", "ha+")):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError, match=name):
            Settings.from_env()
        monkeypatch.delenv(name)


def test_buffer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NORN_BUFFER", str(tmp_path / "ram"))
    assert Settings.from_env().buffer_path == tmp_path / "ram"
    monkeypatch.delenv("NORN_BUFFER")
    monkeypatch.setenv("NORN_TEMP", "/")
    # In RAM if there is enough, else in the temporary storage: never beside it, in /.
    assert Settings.from_env().buffer_path in (Path("/dev/shm/norn"), Path("/.norn/buffer"))
