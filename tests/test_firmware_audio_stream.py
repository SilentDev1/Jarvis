"""Firmware guards for bounded streamed playback and amplifier fail-safety."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "firmware" / "aipi-jarvis" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text()


def test_firmware_format_constants_match_the_python_canonical_format():
    from jarvis_home.devices import audio_stream as py

    header = read("audio_output.h")
    assert f"#define AUDIO_SAMPLE_RATE_HZ {py.AUDIO_SAMPLE_RATE}" in header
    assert f"#define AUDIO_CHANNELS {py.AUDIO_CHANNELS}" in header
    assert f"#define AUDIO_BITS_PER_SAMPLE {py.AUDIO_BITS_PER_SAMPLE}" in header
    assert f"#define AUDIO_MAX_CHUNK_BYTES {py.AUDIO_MAX_CHUNK_BYTES}" in header
    assert f"#define AUDIO_MAX_STREAM_SECONDS {py.AUDIO_MAX_STREAM_SECONDS}" in header


def test_playback_rejects_non_canonical_formats():
    source = read("audio_output.c")
    body = source.split("esp_err_t audio_playback_begin(", 1)[1].split("esp_err_t audio_playback_write(", 1)[0]
    assert "AUDIO_SAMPLE_RATE_HZ" in body
    assert "AUDIO_CHANNELS" in body
    assert "AUDIO_BITS_PER_SAMPLE" in body
    assert "ESP_ERR_INVALID_ARG" in body


def test_every_playback_failure_path_disables_the_amplifier():
    source = read("audio_output.c")
    write_body = source.split("esp_err_t audio_playback_write(", 1)[1].split(
        "esp_err_t audio_playback_end(", 1)[0]
    # Each rejection must abort rather than skip, because abort is what drops
    # GPIO9 and mutes the codec.
    for reason in (
        "empty_chunk",
        "chunk_not_sample_aligned",
        "chunk_too_large",
        "stream_too_large",
        "stream_overrun",
        "i2s_write_failed",
    ):
        assert f'audio_playback_abort("{reason}")' in write_body
    abort_body = source.split("void audio_playback_abort(", 1)[1]
    assert "stop();" in abort_body


def test_stalled_stream_is_aborted_by_timeout():
    source = read("audio_output.c")
    assert "audio_playback_poll_timeout" in source
    assert 'audio_playback_abort("stream_timeout")' in source
    assert "AUDIO_STREAM_TIMEOUT_MS" in read("audio_output.h")


def test_playback_is_bounded_and_never_buffers_a_whole_response():
    source = read("audio_output.c")
    write_body = source.split("esp_err_t audio_playback_write(", 1)[1].split(
        "esp_err_t audio_playback_end(", 1)[0]
    # Fixed-size chunking into the validated writer, no allocation.
    assert "CHUNK_SAMPLES" in write_body
    assert "malloc" not in write_body
    assert "heap_caps_malloc" not in write_body


def test_disconnect_and_reconnect_abort_in_flight_playback():
    connection = read("local_connection.c")
    assert 'audio_playback_abort("connection_lost")' in connection
    assert 'audio_playback_abort("reconnected")' in connection


def test_audio_frames_are_validated_before_reaching_the_speaker():
    connection = read("local_connection.c")
    frame = connection.split("static void process_audio_frame(", 1)[1].split(
        "static void process_control(", 1)[0]
    for reason in ("frame_bounds", "bad_magic", "stream_id_mismatch", "sequence_gap"):
        assert f'audio_playback_abort("{reason}")' in frame
    # Fragmented frames must be rejected, not reassembled blindly.
    assert "payload_offset != 0" in frame


def test_playback_requires_an_authenticated_ready_session():
    connection = read("local_connection.c")
    begin = connection.split('"AUDIO_BEGIN"', 1)[1]
    assert "if (!online)" in begin
    assert "session not ready" in begin


def test_receive_buffer_holds_a_whole_maximum_audio_frame():
    connection = read("local_connection.c")
    assert "#define WS_RX_BUFFER_BYTES 8192" in connection
    assert ".buffer_size = WS_RX_BUFFER_BYTES," in connection


def test_microphone_input_is_still_disabled():
    combined = read("audio_output.c") + read("local_connection.c") + read("es8311_codec.c")
    assert "i2s_channel_read" not in combined
    assert "MIC_BEGIN" not in combined
    # DIN stays unused; enabling capture is a separately gated phase.
    assert "AIPI_AUDIO_DIN" not in read("audio_output.c")


def test_gpio10_is_still_never_configured():
    for name in ("audio_output.c", "local_connection.c", "es8311_codec.c"):
        assert "GPIO_NUM_10" not in read(name)


def test_project_version_matches_the_reported_firmware_version():
    # The boot banner uses PROJECT_VER while the gateway sees FIRMWARE_VERSION.
    # If they drift, recorded provenance no longer identifies one image.
    cmake = (ROOT / "firmware" / "aipi-jarvis" / "CMakeLists.txt").read_text()
    connection = read("local_connection.c")
    version = connection.split('#define FIRMWARE_VERSION "', 1)[1].split('"', 1)[0]
    assert f'set(PROJECT_VER "{version}")' in cmake
