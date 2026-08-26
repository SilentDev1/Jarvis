"""Arc light settings, quiet hours and the firmware driver's safety envelope."""

from pathlib import Path

from jarvis_home.devices.arc_reactor import (
    MAX_BRIGHTNESS,
    QUIET_SCALE_PERCENT,
    ArcLightSettings,
)

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "firmware" / "aipi-jarvis" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text()


def test_light_is_off_by_default():
    # A light at a front door that switches itself on is the owner's decision.
    assert ArcLightSettings().enabled is False
    assert ArcLightSettings().effective_brightness(active=True) == 0


def test_brightness_is_clamped_rather_than_rejected():
    # A settings mistake should dim the light, not stop the terminal starting.
    s = ArcLightSettings(enabled=True, idle_brightness=999, active_brightness=-40)
    assert s.idle_brightness == MAX_BRIGHTNESS
    assert s.active_brightness == 0


def test_quiet_hours_wrap_past_midnight():
    # The naive start <= hour < end comparison silently fails for 22:00-07:00,
    # which is the case that actually matters.
    s = ArcLightSettings(enabled=True, quiet_hours_start=22, quiet_hours_end=7)
    for hour in (22, 23, 0, 3, 6):
        assert s.is_quiet(hour), hour
    for hour in (7, 12, 18, 21):
        assert not s.is_quiet(hour), hour


def test_quiet_hours_within_one_day():
    s = ArcLightSettings(enabled=True, quiet_hours_start=1, quiet_hours_end=5)
    assert s.is_quiet(3)
    assert not s.is_quiet(6)
    assert not s.is_quiet(0)


def test_equal_quiet_bounds_mean_never_quiet():
    # Rather than "always quiet", which would silently disable the light.
    s = ArcLightSettings(enabled=True, quiet_hours_start=9, quiet_hours_end=9)
    assert not s.is_quiet(9)
    assert not s.is_quiet(3)


def test_quiet_hours_dim_rather_than_extinguish():
    s = ArcLightSettings(enabled=True, idle_brightness=40, active_brightness=60,
                         quiet_hours_start=22, quiet_hours_end=7)
    night = s.effective_brightness(active=False, hour=23)
    day = s.effective_brightness(active=False, hour=12)
    assert 0 < night < day
    assert night == 40 * QUIET_SCALE_PERCENT // 100


def test_device_message_shape():
    s = ArcLightSettings(enabled=True, idle_brightness=10, active_brightness=50,
                         quiet_hours_start=22, quiet_hours_end=7)
    message = s.device_message(hour=23)
    assert message == {"enabled": True, "idleBrightness": 10,
                       "activeBrightness": 50, "quietHours": True}
    assert s.device_message(hour=12)["quietHours"] is False


def test_hours_outside_range_do_not_raise():
    s = ArcLightSettings(enabled=True, quiet_hours_start=30, quiet_hours_end=-2)
    assert 0 <= s.quiet_hours_start < 24
    assert 0 <= s.quiet_hours_end < 24
    assert isinstance(s.is_quiet(99), bool)


# --- firmware driver guards -------------------------------------------------


def test_firmware_light_starts_dark_and_disabled():
    source = read("arc_light.c")
    init = source.split("esp_err_t arc_light_init(", 1)[1]
    assert "led_strip_clear(strip)" in init
    assert "disabled until enabled" in init
    app = read("app_main.c")
    # Initialised, never enabled, by firmware itself.
    assert "arc_light_init(ARC_BACKEND_ONBOARD)" in app
    assert "arc_light_set_enabled(true)" not in app


def test_firmware_clamps_brightness_independently_of_the_host():
    source = read("arc_light.c")
    assert "ARC_MAX_BRIGHTNESS" in source
    apply_body = source.split("static void apply(", 1)[1].split("\n}", 1)[0]
    assert "clamp(percent, 0, ARC_MAX_BRIGHTNESS)" in apply_body
    # A host that sends nonsense must not be able to drive the light hard.
    setter = source.split("void arc_light_set_brightness(", 1)[1].split("\n}", 1)[0]
    assert setter.count("clamp(") == 2


def test_no_external_backend_is_assumed():
    header = read("arc_light.h")
    # Adding an external backend before the light is identified would mean
    # guessing a voltage, a current and a pin.
    assert "ARC_BACKEND_EXTERNAL is intentionally absent" in header
    source = read("arc_light.c")
    # Only the onboard pin is referenced; no external GPIO is chosen.
    assert "ARC_ONBOARD_GPIO 46" in source
    assert "GPIO_NUM_10" not in source


def test_light_and_display_share_one_state_source():
    controller = read("display_controller.c")
    # Routed through the display setter so the two cannot drift apart.
    assert "arc_light_set_state(visual)" in controller
    assert "arc_light_set_level(level)" in controller
    # No separate audio analysis for the light.
    light = read("arc_light.c")
    assert "rms" not in light.lower()
    assert "i2s" not in light.lower()


def test_error_and_offline_patterns_are_not_strobes():
    source = read("arc_light.c")
    assert "not a strobe" in source
    # Offline stays visible rather than going dark, so an offline terminal
    # looks offline rather than dead.
    assert "looking dead" in source


def test_light_failure_never_stops_the_device():
    source = read("arc_light.c")
    init = source.split("esp_err_t arc_light_init(", 1)[1]
    assert "ESP_ERROR_CHECK" not in init
    assert "onboard LED unavailable" in init
    app = read("app_main.c")
    start = app.split("arc_light_init(", 1)[1][:120]
    assert "ESP_ERROR_CHECK" not in start


def test_settings_change_reports_status_immediately():
    # DEVICE_STATUS is otherwise only sent on connect, so the owner's view
    # would show the light off while it is actually lit.
    connection = read("local_connection.c")
    window = connection.split('"ARC_SETTINGS"', 1)[1].split("else if", 1)[0]
    assert "send_status()" in window
