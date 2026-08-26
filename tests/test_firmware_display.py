"""Guards for the Jarvis visual interface.

The display is the least important subsystem on this device: voice, network,
OTA and power all outrank it. These tests mostly assert that it stays in its
lane and degrades instead of interfering.
"""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "firmware" / "aipi-jarvis" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text()


def test_display_failure_never_stops_the_device():
    controller = read("display_controller.c")
    renderer = read("display_render.c")
    # Allocation failure and task-creation failure must both degrade, not abort.
    assert "return ESP_ERR_NO_MEM" in controller
    assert "animation disabled" in renderer or "animation disabled" in controller
    for fatal in ("ESP_ERROR_CHECK(", "abort()", "esp_restart()"):
        assert fatal not in controller
    app = read("app_main.c")
    start = app.split("display_controller_start()", 1)[1][:200]
    assert "ESP_ERROR_CHECK" not in start


def test_renderer_owns_no_state_machine():
    # There is one authoritative terminal state; the display renders it.
    controller = read("display_controller.c")
    for competing in ("terminal_state_t state", "transition(", "TERMINAL_BOOTING"):
        assert competing not in controller
    connection = read("local_connection.c")
    assert '"TERMINAL_STATE"' in connection


def test_no_float_trigonometry_or_sqrt_in_the_render_path():
    # 16k pixels a frame at 20 FPS; sqrt or atan2 per pixel would cost far more
    # than the animation is worth.
    renderer = read("display_render.c")
    for expensive in ("sqrtf(", "sqrt(", "atan2", "sinf(", "cosf(", "powf("):
        assert expensive not in renderer
    assert "SIN_TABLE" in renderer


def test_framebuffer_is_bounded_and_allocation_is_checked():
    renderer = read("display_render.c")
    assert "heap_caps_malloc" in renderer
    assert "if (!framebuffer)" in renderer
    # One buffer, allocated once, not per frame.
    assert renderer.count("heap_caps_malloc") == 1
    assert "if (framebuffer) return true;" in renderer


def test_pixel_writes_are_bounds_checked():
    renderer = read("display_render.c")
    assert renderer.count("(unsigned)x >= DISPLAY_W") >= 2
    assert renderer.count("(unsigned)y >= DISPLAY_H") >= 2


def test_audio_envelope_is_cheap_and_does_not_block_the_audio_path():
    audio = read("audio_output.c")
    envelope = audio.split("static void feed_display_envelope(", 1)[1].split("\n}", 1)[0]
    # Decimated peak, integer only, no allocation, no logging, no delays.
    assert "i += 8" in envelope
    for forbidden in ("malloc", "ESP_LOG", "vTaskDelay", "float", "double"):
        assert forbidden not in envelope


def test_speaking_visual_is_released_on_every_stop_path():
    audio = read("audio_output.c")
    stop = audio.split("static void stop(void) {", 1)[1].split("\n}", 1)[0]
    # A failed utterance must not leave the core stuck animating speech.
    assert "JARVIS_VISUAL_IDLE" in stop
    assert "display_controller_set_level(0)" in stop


def test_legacy_text_screens_do_not_fight_the_animation():
    bringup = read("bringup.c")
    # Two writers to the same panel would tear.
    assert bringup.count("if (display_controller_active()) return;") >= 2


def test_power_latch_is_untouched_by_the_display():
    # GPIO10 holds the board's own power; nothing visual may claim it.
    for name in ("display_render.c", "display_controller.c"):
        source = read(name)
        assert "GPIO_NUM_10" not in source
        assert "AIPI_POWER_LATCH" not in source
    # And the latch assertion still runs first.
    app = read("app_main.c")
    body = app.split("void app_main(void) {", 1)[1]
    assert body.index("hold_board_power()") < body.index("display_controller_start")


def test_ota_display_states_are_preserved():
    connection = read("local_connection.c")
    report = connection.split("static void ota_report(", 1)[1].split("\n}", 1)[0]
    assert "JARVIS_VISUAL_UPDATING" in report
    assert "VERIFYING" in report
    assert "RESTARTING" in report
    # A failed update must not leave the ring implying progress.
    assert "JARVIS_VISUAL_ERROR" in report


def test_render_task_is_low_priority_and_bounded_rate():
    controller = read("display_controller.c")
    # Below the audio, capture and OTA tasks, which all run at 4-5.
    assert '"jarvis_visual", 4096, NULL, 2' in controller
    assert "FRAME_INTERVAL_MS 50" in controller
    assert "vTaskDelayUntil" in controller


def test_no_bundled_video_or_large_asset():
    cmake = (ROOT / "firmware" / "aipi-jarvis" / "main" / "CMakeLists.txt").read_text()
    # The interface is procedural; the only embedded file is the OTA key.
    embedded = cmake.split("EMBED_TXTFILES", 1)[1] if "EMBED_TXTFILES" in cmake else ""
    assert "ota_public_key.pem" in embedded
    for asset in (".gif", ".mp4", ".jpg", ".png", ".raw"):
        assert asset not in cmake


def test_reconnect_loop_is_supervisory_not_purely_edge_triggered():
    # Waiting forever on a disconnect notification wedges the device:
    # stop()+start() can return ESP_OK without the client attempting anything,
    # so no event fires and the task blocks for good while the device stays
    # pingable. Observed in practice on 0.9.1.
    connection = read("local_connection.c")
    task = connection.split("static void reconnect_task(", 1)[1].split("\n}", 1)[0]
    assert "portMAX_DELAY" not in task
    assert "RECONNECT_SUPERVISE_MS" in task
    assert "esp_websocket_client_is_connected" in task


def test_gateway_hostname_resolution_has_a_cached_fallback():
    # mDNS resolution of the .local name fails intermittently on this
    # hardware. When it does the terminal sits on Wi-Fi, pingable, unable to
    # find Jarvis, and needs a power cycle. Observed in practice.
    connection = read("local_connection.c")
    assert "getaddrinfo(provisioned.host" in connection
    assert "wifi_provision_cached_gateway_ip" in connection
    assert "wifi_provision_store_gateway_ip" in connection
    assert "using last known gateway" in connection
    # The resolved address must be what the socket actually uses.
    assert 'snprintf(uri, sizeof(uri), "ws://%s:%u/ws/device", target' in connection


def test_cached_gateway_address_is_not_rewritten_every_connection():
    # NVS has finite erase cycles and this runs on every successful connect.
    provision = read("wifi_provision.c")
    store = provision.split("void wifi_provision_store_gateway_ip(", 1)[1]
    assert "strcmp(existing, ip) == 0" in store


def test_pixel_stream_raises_the_data_line_before_sending():
    # lcd_window ends on RAMWR with no payload, so lcd_tx returns with DC still
    # low. Without raising it the whole framebuffer is clocked in as commands
    # and the panel shows a blank screen with no error anywhere.
    bringup = read("bringup.c")
    flush = bringup.split("static void lcd_flush(", 1)[1].split("\n}", 1)[0]
    assert "gpio_set_level(AIPI_LCD_DC, 1)" in flush
    assert flush.index("lcd_window(") < flush.index("gpio_set_level(AIPI_LCD_DC, 1)")
    assert flush.index("gpio_set_level(AIPI_LCD_DC, 1)") < flush.index("spi_device_polling_transmit")
