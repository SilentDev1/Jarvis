import pytest

from jarvis_home.integrations.providers import TapoCamera, TestCamera


@pytest.mark.asyncio
async def test_test_camera_health_snapshot():
    c = TestCamera()
    assert c.health()["connected"]
    assert (await c.snapshot()).width == 1920


def test_tapo_initial_reconnect_health():
    c = TapoCamera("rtsp://sub", "rtsp://main")
    assert not c.health()["connected"] and c.health()["reconnects"] == 0
