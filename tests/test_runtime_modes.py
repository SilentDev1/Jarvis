from jarvis_home.config import Settings


def test_simulator_mode_is_explicit():
    settings = Settings(camera_mode="test", voice_satellite="simulator")
    assert settings.camera_mode == "test"
    assert settings.voice_satellite == "simulator"
