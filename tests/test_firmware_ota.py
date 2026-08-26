"""Firmware-side OTA guards.

OTA replaces the code running on a device at the front door, so these assert
what the firmware refuses, not what it accepts.
"""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "firmware" / "aipi-jarvis" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text()


def test_partition_table_has_two_app_slots_and_otadata():
    table = (ROOT / "firmware" / "aipi-jarvis" / "partitions.csv").read_text()
    assert "otadata" in table
    assert "ota_0" in table
    assert "ota_1" in table
    # Factory NVS must stay where it is; OTA must not disturb provisioning.
    assert "0x9000" not in table.replace("# Jarvis layout; factory NVS at 0x9000 is intentionally untouched.", "")


def test_rollback_is_enabled_in_the_build():
    config = (ROOT / "firmware" / "aipi-jarvis" / "sdkconfig").read_text()
    assert "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y" in config
    assert "CONFIG_APP_ROLLBACK_ENABLE=y" in config


def test_manifest_signature_is_actually_verified():
    source = read("ota_update.c")
    # Real verification against an embedded key, not a token comparison.
    assert "mbedtls_pk_verify" in source
    assert "mbedtls_pk_parse_public_key" in source
    assert "_binary_ota_public_key_pem_start" in source
    # The transfer must be abandoned when verification fails. This happens on
    # the OTA task rather than the websocket handler; see the stack test below.
    task = source.split("static void ota_task(", 1)[1].split(
        "esp_err_t ota_update_handle_offer(", 1)[0]
    assert "if (!signature_valid(offer))" in task
    assert 'report("FAILED", 0, "bad_signature")' in task
    assert "vTaskDelete(NULL)" in task


def test_no_private_key_material_is_embedded():
    embedded = (MAIN / "ota_public_key.pem").read_text()
    assert "BEGIN PUBLIC KEY" in embedded
    assert "PRIVATE" not in embedded
    for name in ("ota_update.c", "ota_update.h"):
        assert "PRIVATE KEY" not in read(name)


def test_image_is_rejected_when_the_hash_does_not_match():
    source = read("ota_update.c")
    assert "sha256_mismatch" in source
    # The hash is computed over what was actually written, then compared.
    assert "mbedtls_sha256_update" in source
    assert 'strcmp(actual, offer->sha256)' in source


def test_wrong_hardware_or_device_is_refused_before_download():
    offer = read("ota_update.c").split("esp_err_t ota_update_handle_offer(", 1)[1]
    assert "wrong hardware" in offer
    assert "wrong device" in offer
    # Both checks must precede starting the transfer task.
    assert offer.index("wrong hardware") < offer.index("xTaskCreate")
    assert offer.index("wrong device") < offer.index("xTaskCreate")


def test_implausible_image_sizes_are_refused():
    source = read("ota_update.c")
    assert "OTA_MAX_IMAGE_BYTES" in source
    assert "OTA_MIN_IMAGE_BYTES" in source
    assert "image_exceeds_slot" in source


def test_update_is_refused_while_audio_is_live():
    source = read("ota_update.c")
    offer = source.split("esp_err_t ota_update_handle_offer(", 1)[1]
    assert "audio_playback_active() || audio_input_active()" in offer
    # The protocol layer refuses too; both sides must agree.
    connection = read("local_connection.c")
    window = connection.split('"OTA_OFFER"', 1)[1].split("static void websocket_event", 1)[0]
    assert "if (!online)" in window
    assert "audio_playback_active()" in window


def test_new_image_must_pass_a_health_window_before_being_confirmed():
    connection = read("local_connection.c")
    assert "ota_update_pending_verify()" in connection
    assert "OTA_HEALTH_WINDOW_MS" in connection
    confirm = connection.split("static void ota_confirm_task(", 1)[1]
    # Losing the connection during the window must leave the image unconfirmed,
    # so the bootloader rolls back rather than keeping a broken build.
    assert "if (!online)" in confirm
    assert "leaving image unconfirmed" in confirm
    assert "ota_update_mark_valid()" in confirm


def test_the_active_slot_is_never_written():
    source = read("ota_update.c")
    # esp_ota_get_next_update_partition returns the inactive slot; writing the
    # running one would make a power cut unrecoverable.
    assert "esp_ota_get_next_update_partition" in source
    assert "esp_ota_get_running_partition" in source
    task = source.split("static void ota_task(", 1)[1]
    assert "esp_ota_get_running_partition" not in task


def test_failed_transfer_aborts_rather_than_leaving_a_half_written_slot():
    task = read("ota_update.c").split("static void ota_task(", 1)[1]
    assert "esp_ota_abort" in task
    for failure in ("truncated_download", "oversized_stream", "flash_write",
                    "read_error", "sha256_mismatch"):
        assert failure in task


def test_display_never_shows_credentials_or_paths():
    report = read("local_connection.c").split("static void ota_report(", 1)[1].split("\n}", 1)[0]
    for leak in ("url", "credential", "password", "signature", "http"):
        assert leak not in report.lower().replace("percent", "")


def test_signature_verification_runs_off_the_websocket_task():
    # RSA-2048 verification needs several KB of stack. Doing it in the
    # websocket event handler overflowed websocket_task and rebooted the
    # device before the download began.
    source = read("ota_update.c")
    offer = source.split("esp_err_t ota_update_handle_offer(", 1)[1]
    assert "signature_valid" not in offer, "verification must not run in the handler"
    task = source.split("static void ota_task(", 1)[1].split("esp_err_t ota_update_handle_offer(", 1)[0]
    assert "signature_valid(offer)" in task
    # Large buffers stay off the stack; only one OTA runs at a time.
    assert "static char canonical[" in source
    assert "static uint8_t signature[" in source
    assert '"aipi_ota", 12288' in source


def test_rollback_test_path_is_opt_in_and_uses_the_supported_mechanism():
    source = read("local_connection.c")
    assert "JARVIS_OTA_ROLLBACK_TEST" in source
    # Must be compile-time gated so a normal build can never refuse to confirm.
    assert "#if defined(JARVIS_OTA_ROLLBACK_TEST)" in source
    # Rollback via the ESP-IDF call, not by crashing into a boot loop.
    assert "esp_ota_mark_app_invalid_rollback_and_reboot()" in source
    for crash in ("abort()", "assert(0)", "while (1);"):
        assert crash not in source


def test_boot_banner_cannot_drift_from_the_reported_version():
    # The banner was a hardcoded literal and had drifted six versions behind
    # the firmware version, which misleads anyone reading a serial log.
    source = (MAIN / "app_main.c").read_text()
    assert "local_connection_firmware_version()" in source
    import re
    assert not re.search(r'"Jarvis AiPi \d+\.\d+\.\d+', source)
