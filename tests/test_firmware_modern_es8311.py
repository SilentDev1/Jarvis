from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "firmware" / "aipi-jarvis" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text()


def test_codec_uses_only_new_i2c_driver_and_one_shared_handle():
    codec = read("es8311_codec.c")
    combined = codec + read("audio_output.c") + read("es8311_codec.h")
    prohibited = (
        '"driver/i2c.h"',
        "i2c_param_config(",
        "i2c_driver_install(",
        "i2c_master_write_to_device(",
    )
    for value in prohibited:
        assert value not in combined
    assert '"driver/i2c_master.h"' in codec
    assert "i2c_master_bus_handle_t codec_bus" in codec
    assert "i2c_master_dev_handle_t codec_device" in codec
    assert codec.count("i2c_master_bus_add_device(") == 1
    assert "i2c_master_transmit(" in codec
    assert "i2c_master_transmit_receive(" in codec


def test_codec_register_sequence_is_speaker_only_and_bounded():
    codec = read("es8311_codec.c")
    assert "ES8311_ADDRESS 0x18" in codec
    assert "configure_4096khz_mclk_16khz_pcm16" in codec
    assert "value &= 0x9F" in codec
    assert "if (muted) value |= 0x60" in codec
    assert "volume <= 60" in codec
    assert 'es8311_codec_write_register(0x13, 0x18)' in codec
    assert 'es8311_codec_write_register(0x04, 0x20)' in codec
    assert "microphone" not in codec.lower().replace("microphone capture remains disabled", "")


def test_safe_amplifier_sequence_and_one_shot_tone():
    audio = read("audio_output.c")
    assert audio.index("es8311_codec_set_muted(true)") < audio.index("amplifier_set(true)")
    assert audio.index("amplifier_set(true)") < audio.index("es8311_codec_set_muted(false)")
    stop = audio.split("static void stop", 1)[1].split(
        "esp_err_t audio_output_test_tone", 1
    )[0]
    assert stop.index("es8311_codec_set_muted(true)") < stop.index("amplifier_set(false)")
    assert "TONE_DURATION_MS 400" in audio
    assert "TONE_AMPLITUDE 16000" in audio
    assert "CHUNK_SAMPLES 256" in audio
    assert "while (true)" not in audio


def test_boot_is_quiet_and_audio_failure_is_nonfatal():
    app = read("app_main.c")
    bringup = read("bringup.c")
    connection = read("local_connection.c")
    assert "audio_output_test_tone" not in app
    assert "audio_output_manual_test_enabled()" in bringup
    assert "AUDIO: ERROR" in bringup
    assert "ESP_ERROR_CHECK(audio" not in app + bringup
    assert "audio_output_set_manual_test_enabled(true)" in connection
    assert "audio_output_set_manual_test_enabled(false)" in connection


def test_audio_mapping_never_touches_gpio10():
    board = read("aipi_board.h")
    codec_audio = read("es8311_codec.c") + read("audio_output.c")
    for name, pin in {
        "AIPI_AUDIO_MCLK": 6,
        "AIPI_SPEAKER_ENABLE": 9,
        "AIPI_AUDIO_DOUT": 11,
        "AIPI_AUDIO_WS": 12,
        "AIPI_AUDIO_DIN": 13,
        "AIPI_AUDIO_BCLK": 14,
    }.items():
        assert f"#define {name} GPIO_NUM_{pin}" in board
    assert "GPIO_NUM_10" not in codec_audio
    assert "AIPI_UNVERIFIED_POWER_GPIO" not in codec_audio
