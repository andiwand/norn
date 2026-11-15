from __future__ import annotations

import pytest

from norn.drivers import DRIVERS
from norn.drivers.foscam import _mac, parse_vars
from norn.drivers.hikvision import duration, xml_replace, xml_value
from norn.drivers.onvif import with_credentials
from norn.firmware import check, version_key
from norn.onvif import _namespaces, attributes, value


def make(driver: str, **options: object):
    cls = DRIVERS[driver]
    return cls("cam", cls.Options.model_validate(options))


def test_parse_vars_both_quote_styles() -> None:
    text = "var id='00AABBCCDDEE';\nvar alias=\"garden\";\nvar now=1700000000;\nvar empty='';"
    assert parse_vars(text) == {"id": "00AABBCCDDEE", "alias": "garden", "now": "1700000000", "empty": ""}
    assert _mac("00AABBCCDDEE") == "00:aa:bb:cc:dd:ee"
    assert _mac("nope") is None


def test_passwords_are_encoded_in_stream_urls() -> None:
    foscam = make("foscam", host="10.0.0.2", password="a#b@c")
    [main] = foscam.streams()
    assert main.source == "http://admin:a%23b%40c@10.0.0.2:80/videostream.cgi"
    assert main.codec == "mjpeg"
    hik = make("hikvision", host="10.0.0.3", password="p#1")
    assert [s.source for s in hik.streams()] == [
        "rtsp://admin:p%231@10.0.0.3:554/Streaming/Channels/101",
        "rtsp://admin:p%231@10.0.0.3:554/Streaming/Channels/102",
    ]
    reolink = make("reolink", host="10.0.0.4", password="x#y")
    assert reolink.streams()[1].source == "rtsp://admin:x%23y@10.0.0.4:554/h264Preview_01_sub"
    assert with_credentials("rtsp://10.0.0.5:554/s0", "u", "p#") == "rtsp://u:p%23@10.0.0.5:554/s0"


def test_hikvision_xml() -> None:
    xml = '<IrcutFilter version="2.0" xmlns="x"><IrcutFilterType>auto</IrcutFilterType><x>1</x></IrcutFilter>'
    assert xml_value(xml, "IrcutFilterType") == "auto"
    assert "<IrcutFilterType>night</IrcutFilterType><x>1</x>" in xml_replace(xml, "IrcutFilterType", "night")
    assert duration(3246275) == "37 d 13 h"


def test_onvif_helpers() -> None:
    xml = '<tt:Profiles token="000" fixed="true"><tt:Name>main</tt:Name></tt:Profiles>'
    assert attributes(xml, "Profiles", "token") == ["000"]
    assert value(xml, "Name") == "main"
    assert _namespaces("<a xmlns='{ptz}'>{x}</a>") == "<a xmlns='http://www.onvif.org/ver20/ptz/wsdl'>{x}</a>"


@pytest.mark.parametrize(
    ("manufacturer", "model", "firmware", "status"),
    [
        ("Hikvision", "DS-2CD2042WD-I", "V5.3.8 build 151224", "update"),
        ("Hikvision", "DS-2CD2042WD-I", "V5.5.82 build 190909", "current"),
        ("Reolink", "E1 Pro", "v3.1.0.1414_22101301", "update"),
        ("Reolink", "E1 Pro", "v3.1.0.5112_2507081475", "current"),
        ("supra", "IPC-1A", "0.41.2.51", "end-of-life"),
        ("Acme", "X1", "1.0", "unknown"),
    ],
)
def test_firmware_check(manufacturer: str, model: str, firmware: str, status: str) -> None:
    assert check(manufacturer, model, firmware).status == status


def test_firmware_notes_for_current_version_skip_old_warnings() -> None:
    notes = check("Hikvision", "DS-2CD2042WD-I", "V5.5.82 build 190909").notes
    assert not any("CVE" in n for n in notes)
    assert version_key("V5.3.8 build 151224") == (5, 3, 8, 151224)
