from __future__ import annotations

from pathlib import Path

import pytest

from norn.config import DEFAULT_CONFIG, CameraConfig, ConfigError, ConfigStore


def test_writes_default_config(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "c" / "config.yaml")
    config = store.load()
    assert (tmp_path / "c" / "config.yaml").read_text() == DEFAULT_CONFIG
    assert list(config.cameras) == ["demo"]
    assert config.recording.retention_days == 14


def test_put_camera_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "# my cameras\ncameras:\n  porch:  # the old one\n    name: Porch\n    driver: rtsp\n"
        "    url: rtsp://a/1\n"
    )
    store = ConfigStore(path)
    store.load()
    store.put_camera(
        "porch", CameraConfig(name="Porch", driver="rtsp", url="rtsp://a/2", record="continuous")
    )
    store.put_camera("yard", CameraConfig(name="Yard", driver="demo"))
    text = path.read_text()
    assert "# my cameras" in text
    assert "# the old one" in text
    assert "url: rtsp://a/2" in text
    assert "record: continuous" in text
    assert "enabled" not in text  # defaults stay out of the file
    reloaded = ConfigStore(path).load()
    assert reloaded.cameras["porch"].options == {"url": "rtsp://a/2"}
    assert reloaded.cameras["yard"].driver == "demo"


def test_remove_camera(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    store.load()
    store.remove_camera("demo")
    assert ConfigStore(store.path).load().cameras == {}
    with pytest.raises(KeyError):
        store.remove_camera("demo")
    store.put_camera("again", CameraConfig(name="Again", driver="demo"))
    assert "  again:\n    name: Again\n" in store.path.read_text()
    assert list(ConfigStore(store.path).load().cameras) == ["again"]


@pytest.mark.parametrize(
    "text",
    [
        "cameras:\n  Bad_Id:\n    name: x\n    driver: demo\n",
        "cameras:\n  ok:\n    driver: demo\n",
        "recording:\n  retention_days: -1\n",
        "unknown: 1\n",
        "- a list\n",
        "cameras: [\n",
    ],
)
def test_invalid_config(tmp_path: Path, text: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        ConfigStore(path).load()


def test_empty_cameras(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("cameras:\n")
    assert ConfigStore(path).load().cameras == {}


def test_detects_change_on_disk(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    store.load()
    assert not store.changed_on_disk()
    store.put_camera("x", CameraConfig(name="X", driver="demo"))
    assert not store.changed_on_disk()  # our own write doesn't count
    store.path.write_text("cameras: {}\n# edited\n")
    assert store.changed_on_disk()


def test_new_keys_go_above_trailing_comments(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    store.load()  # the default config ends with a commented example camera
    store.put_camera("demo", CameraConfig(name="Demo camera", driver="demo", record="continuous"))
    store.put_camera("yard", CameraConfig(name="Yard", driver="demo"))
    text = store.path.read_text()
    assert text.index("record: continuous") < text.index("# A plain RTSP camera")
    assert text.index("yard:") < text.index("# A plain RTSP camera")
    assert text.rstrip().endswith("# off (default) or continuous")
    store.remove_camera("yard")
    text = store.path.read_text()
    assert "yard" not in text and "# A plain RTSP camera" in text
    assert list(ConfigStore(store.path).load().cameras) == ["demo"]
