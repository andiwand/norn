from __future__ import annotations

from pathlib import Path

import pytest

from norn.config import DEFAULT_CONFIG, CameraConfig, ConfigError, ConfigStore, Patrol


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


def test_order_cameras_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "cameras:\n"
        "  a: {name: A, driver: demo}\n"
        "  b:  # the garden\n"
        "    name: B\n"
        "    driver: demo\n"
        "  c: {name: C, driver: demo}\n"
        "\n"
        "  # a camera to add later\n"
    )
    store = ConfigStore(path)
    store.load()
    config = store.order_cameras(["c", "b"])
    assert list(config.cameras) == ["c", "b", "a"]
    text = path.read_text()
    assert "b:  # the garden" in text and text.rstrip().endswith("# a camera to add later")
    with pytest.raises(ConfigError):
        store.order_cameras(["nope"])


def test_order_cameras_moves_comments_above_cameras_with_them(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "cameras:\n"
        "  # Front door, the doorbell\n"
        "  front:\n"
        "    name: Front\n"
        "    driver: demo  # eol\n"
        "  # Garden, on the shed\n"
        "  garden: {name: Garden, driver: demo}\n"
        "  # Garage\n"
        "  garage:\n"
        "    name: Garage\n"
        "    driver: demo\n"
        "\n"
        "# Recording settings\n"
        "recording:\n"
        "  clip_seconds: 30\n"
    )
    store = ConfigStore(path)
    store.load()
    for order in (["garage", "garden", "front"], ["garden", "front", "garage"]):
        assert list(store.order_cameras(order).cameras) == order
        lines = path.read_text().splitlines()
        for label, camera in (("# Front door", "front:"), ("# Garden", "garden:"), ("# Garage", "garage:")):
            i = next(n for n, line in enumerate(lines) if line.strip().startswith(label))
            assert lines[i + 1].strip().startswith(camera), path.read_text()
            assert lines[i].startswith("  #")
        assert "driver: demo  # eol" in path.read_text()
        i = lines.index("# Recording settings")
        assert lines[i + 1] == "recording:" and lines[i - 1] == ""


def test_nested_values_stay_above_the_comments_at_the_end(tmp_path: Path) -> None:
    from norn.config import NornPreset

    path = tmp_path / "config.yaml"
    path.write_text(DEFAULT_CONFIG)
    store = ConfigStore(path)
    demo = store.load().cameras["demo"]
    for update in (
        {"triggers": ["motion", "person"]},
        {"presets": {"porch": NornPreset(name="Porch", slot="norn-porch")}},
    ):
        store.put_camera("demo", demo.model_copy(update=update))
        text = path.read_text()
        last = "      - person" if "triggers" in update else "        slot: norn-porch"
        assert last in text
        assert text.index(last) < text.index("# A plain RTSP camera"), text


def _store(tmp_path: Path, text: str) -> ConfigStore:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    store = ConfigStore(path)
    store.load()
    return store


def test_changes_keep_a_hand_edit_and_never_overwrite_a_broken_file(tmp_path: Path) -> None:
    store = _store(tmp_path, "cameras:\n  a: {name: A, driver: demo}\n")
    store.path.write_text("cameras:\n  a: {name: A by hand, driver: demo}\n")
    config = store.put_camera("b", CameraConfig(name="B", driver="demo"))
    assert config.cameras["a"].name == "A by hand" and "A by hand" in store.path.read_text()
    broken = "cameras:\n  a: {name: A, driver: demo, record: sometimes, password: hunter2}\n"
    store.path.write_text(broken)
    with pytest.raises(ConfigError) as error:
        store.put_camera("c", CameraConfig(name="C", driver="demo"))
    assert store.path.read_text() == broken
    assert "hunter2" not in str(error.value)  # the message never quotes values
    # A file that never loaded (Norn started with it broken) isn't overwritten either.
    with pytest.raises(ConfigError):
        ConfigStore(store.path).put_camera("c", CameraConfig(name="C", driver="demo"))
    assert store.path.read_text() == broken


def test_a_failed_change_is_forgotten(tmp_path: Path) -> None:
    from norn.config import RecordingSettings

    store = _store(tmp_path, "cameras:\n  a: {name: A, driver: demo}\n")
    with pytest.raises(ConfigError):  # a default preset it doesn't have
        store.put_camera(
            "x", CameraConfig(name="X", driver="demo").model_copy(update={"default_preset": "no"})
        )
    store.put_section("recording", RecordingSettings(retention_days=3))
    assert "x:" not in store.path.read_text()


def test_invalid_utf8_and_yaml_errors(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"cameras:\n  a:\n    name: \xff\n")
    with pytest.raises(ConfigError):
        ConfigStore(path).load()
    path.write_text("cameras:\n  a: [\n    password: hunter2\n  b: c\n")
    with pytest.raises(ConfigError) as error:
        ConfigStore(path).load()
    assert "hunter2" not in str(error.value) and "line" in str(error.value)


def test_nested_changes_and_deletions_keep_comments(tmp_path: Path) -> None:
    from norn.config import NornPreset

    store = _store(
        tmp_path,
        "cameras:\n"
        "  a:\n"
        "    name: A\n"
        "    driver: rtsp\n"
        "    enabled: true\n"
        "    # main stream\n"
        "    url: rtsp://x/1\n"
        "    presets:\n"
        "      # porch view\n"
        "      porch:\n"
        "        name: Porch   # the good one\n"
        "        slot: '1'\n",
    )
    a = store.config.cameras["a"]
    presets = {**a.presets, "gate": NornPreset(name="Gate", slot="2")}
    store.put_camera("a", a.model_copy(update={"name": "A2", "presets": presets}))
    text = store.path.read_text()
    assert "enabled" not in text
    assert "    driver: rtsp\n    # main stream\n    url: rtsp://x/1\n" in text
    assert "      # porch view\n      porch:\n        name: Porch   # the good one\n" in text
    assert "      gate:\n        name: Gate\n" in text


@pytest.mark.parametrize("removed", ["a", "b", "c"])
def test_remove_keeps_the_others_comments(tmp_path: Path, removed: str) -> None:
    store = _store(
        tmp_path,
        "cameras:\n"
        "  # A at the door\n"
        "  a:\n"
        "    name: A\n"
        "    driver: demo\n"
        "  # B in the garage\n"
        "  b: {name: B, driver: demo}\n"
        "  # C at the gate\n"
        "  c:\n"
        "    name: C\n"
        "    driver: demo\n"
        "# the end\n",
    )
    store.remove_camera(removed)
    lines = store.path.read_text().splitlines()
    assert f"# {removed.upper()} " not in store.path.read_text()
    for camera in {"a", "b", "c"} - {removed}:
        i = next(n for n, line in enumerate(lines) if line.startswith(f"  # {camera.upper()} "))
        assert lines[i + 1].startswith(f"  {camera}:"), lines
    assert lines[-1] == "# the end"
    assert list(ConfigStore(store.path).load().cameras) == sorted({"a", "b", "c"} - {removed})


def test_a_setting_back_at_its_default_leaves_the_file(tmp_path: Path) -> None:
    from norn.config import RecordingSettings

    store = _store(tmp_path, "recording:\n  retention_days: 14  # two weeks\n  clip_seconds: 60\n")
    store.put_section("recording", RecordingSettings(retention_days=14, clip_seconds=30))
    assert store.path.read_text() == "recording:\n  retention_days: 14  # two weeks\n"


def test_ids_and_detection_layers(tmp_path: Path) -> None:
    from norn.config import Config

    for bad in (
        'cameras: {"a\\n": {name: A, driver: demo}}\n',
        "cameras: {a: {name: A, driver: demo, presets: {'../x': {name: X, slot: '1'}}}}\n",
    ):
        with pytest.raises(ConfigError):
            _store(tmp_path, bad)
    with pytest.raises(ConfigError):
        _store(tmp_path, "cameras: {}\n").put_camera("a\n", CameraConfig(name="A", driver="demo"))
    config = Config.model_validate(
        {
            "circles": {
                "first": {"name": "F", "cameras": ["a"]},
                "second": {"name": "S", "cameras": ["a"], "detection": {"motion": True}},
            },
            "cameras": {"a": {"name": "A", "driver": "demo"}},
        }
    )
    assert config.detection_for("a").motion  # the first circle that sets any


def test_default_patrol_stays_out(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    store.load()
    store.put_camera("a", CameraConfig(name="A", driver="demo", patrol=Patrol()))
    assert "patrol" not in store.dump()
