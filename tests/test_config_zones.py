import pytest

from jarvis_home.config import ROOT, Settings
from jarvis_home.modules.front_door.zones import classify, contains, parse_polygon


def test_portable_default_paths():
    assert Settings().data_dir == ROOT / "data"


def test_invalid_camera_mode():
    with pytest.raises(ValueError):
        Settings(camera_mode="other")


def test_zone_classification():
    zones = {
        "observation": parse_polygon("0,0;1,0;1,1;0,1"),
        "approach": parse_polygon(".2,.2;.8,.2;.8,.8;.2,.8"),
        "interaction": parse_polygon(".4,.4;.6,.4;.6,1;.4,1"),
    }
    assert classify((0.45, 0.3, 0.55, 0.8), zones) == "interaction"
    assert contains((0.5, 0.5), zones["observation"])


def test_rtsp_credential_encoding_and_masking():
    s = Settings(camera_host="camera", camera_username="a@b", camera_password="p/x")
    assert "a%40b:p%2Fx" in s.rtsp_url()
    assert s.public()["camera_password"] == "***"
    assert s.public()["camera_host"] == "***"
    assert s.public()["camera_username"] == "***"
