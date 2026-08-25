from pathlib import Path

ROOT = Path(__file__).parents[1]
FIRMWARE = ROOT / "firmware" / "aipi-jarvis"


def test_wifi_credentials_are_runtime_provisioned_only():
    source = (FIRMWARE / "main" / "wifi_provision.c").read_text()
    defaults = (FIRMWARE / "sdkconfig.defaults").read_text()
    assert "WIFI_SSID" not in source
    assert "WIFI_PASSWORD" not in source
    assert "CONFIG_ESP_WIFI_SSID" not in defaults
    assert "CONFIG_ESP_WIFI_PASSWORD" not in defaults
    assert 'type=password' in source
    assert 'secrets omitted' in source


def test_portal_is_minimal_and_bounded():
    source = (FIRMWARE / "main" / "wifi_provision.c").read_text()
    assert 'maxlength=32' in source
    assert 'maxlength=63' in source
    assert 'request->content_len > 512' in source
    defaults = (FIRMWARE / "sdkconfig.defaults").read_text()
    assert "CONFIG_HTTPD_MAX_REQ_HDR_LEN=2048" in defaults
    assert '.uri = "/"' in source
    assert '.uri = "/provision"' in source
    for forbidden in ("firmware upload", "shell", "filesystem", "camera"):
        assert forbidden not in source.lower()


def test_local_gateway_configuration_is_runtime_only_and_redacted():
    source = (FIRMWARE / "main" / "wifi_provision.c").read_text()
    connection = (FIRMWARE / "main" / "local_connection.c").read_text()
    assert 'name=host maxlength=80' in source
    assert 'name=device_password type=password' in source
    assert 'WIFI_KEY_DEVICE_PASSWORD "device_password"' in source
    assert "credential omitted" in connection
    assert all("token" not in line.lower() for line in connection.splitlines() if "ESP_LOG" in line)


def test_local_firmware_protocol_has_no_audio_messages():
    connection = (FIRMWARE / "main" / "local_connection.c").read_text()
    for message_type in (
        "DEVICE_HELLO", "PONG", "DEVICE_STATUS", "DEVICE_READY",
        "PING", "STATUS_REQUEST",
    ):
        assert message_type in connection
    for forbidden in ("PLAY_AUDIO", "AUDIO_START", "START_LISTENING", "microphone"):
        assert forbidden not in connection


def test_custom_nvs_does_not_overlap_factory_nvs():
    partitions = (FIRMWARE / "partitions.csv").read_text()
    source = (FIRMWARE / "main" / "wifi_provision.c").read_text()
    assert "0x0d000" in partitions
    assert "0x09000" not in partitions
    assert 'WIFI_NAMESPACE "jarvis_wifi"' in source


def test_reconfiguration_requires_long_boot_hold():
    board = (FIRMWARE / "main" / "aipi_board.h").read_text()
    source = (FIRMWARE / "main" / "wifi_provision.c").read_text()
    assert "AIPI_WIFI_RESET_HOLD_MS 8000" in board
    assert "wifi_provision_boot_reset_requested" in source
    assert "nvs_erase_all" in source
    assert "nvs_flash_erase" not in source


def test_reconnect_is_bounded_and_physically_self_tested_once():
    source = (FIRMWARE / "main" / "wifi_provision.c").read_text()
    assert "if (delay_seconds < 30)" in source
    assert "one-time reconnect self-test: PASS" in source
    assert 'WIFI_KEY_RECONNECT_TEST "reconnect_ok"' in source
    assert 'esp_log_level_set("wifi", ESP_LOG_WARN)' in source
