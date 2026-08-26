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
    for reason in ("frame_bounds", "bad_magic", "stream_id_mismatch", "sequence_gap",
                   "frame_desync"):
        assert f'audio_frame_fail("{reason}")' in frame
    # Every failure path must clear reassembly state as well as abort, or the
    # next stream would resume onto a stale partial frame.
    helper = connection.split("static void audio_frame_fail(", 1)[1].split("}", 1)[0]
    assert "audio_playback_abort(reason)" in helper
    assert "active_stream_id = 0" in helper
    assert "audio_frame_filled = 0" in helper


def test_playback_requires_an_authenticated_ready_session():
    connection = read("local_connection.c")
    begin = connection.split('"AUDIO_BEGIN"', 1)[1]
    assert "if (!online)" in begin
    assert "session not ready" in begin


def test_receive_buffer_holds_a_whole_maximum_audio_frame():
    connection = read("local_connection.c")
    assert "#define WS_RX_BUFFER_BYTES 8192" in connection
    assert ".buffer_size = WS_RX_BUFFER_BYTES," in connection


def test_microphone_capture_cannot_run_while_the_speaker_does():
    audio = read("audio_output.c")
    begin = audio.split("esp_err_t audio_input_begin(", 1)[1].split(
        "esp_err_t audio_input_read(", 1)[0]
    # Capture takes the same lock playback holds, so the microphone can never
    # be open while the amplifier drives the speaker. This is the hardware half
    # of half-duplex; the terminal state machine is the host half.
    assert "xSemaphoreTake(playback_lock, 0)" in begin
    assert "speaker busy" in begin
    connection = read("local_connection.c")
    listen = connection.split('"LISTEN_START"', 1)[1].split('"LISTEN_STOP"', 1)[0]
    assert "audio_playback_active()" in listen
    assert "speaker active" in listen


def test_microphone_capture_is_bounded_and_never_stored():
    audio = read("audio_output.c")
    header = read("audio_output.h")
    assert "AUDIO_MIC_MAX_MS" in header
    connection = read("local_connection.c")
    capture = connection.split("static void capture_task(", 1)[1].split(
        "static void process_control(", 1)[0]
    # Bounded by both an explicit stop and a duration cap, so a wedged session
    # cannot stream indefinitely.
    assert "capture_stop_requested" in capture
    assert "duration_limit" in capture
    assert "AUDIO_MIC_MAX_MS" in connection
    # Audio is never written to flash or accumulated on the device.
    for forbidden in ("fopen", "nvs_set", "malloc", "heap_caps_malloc"):
        assert forbidden not in capture
    # The microphone is torn down on every exit path, not only success.
    assert capture.count("audio_input_end()") >= 1
    assert "audio_input_end" in audio


def test_connection_loss_closes_the_microphone():
    connection = read("local_connection.c")
    # A dead socket must not leave the ADC live.
    disconnect = connection.split('audio_playback_abort("connection_lost")', 1)[1]
    assert "capture_stop_requested = true" in disconnect[:400]


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


def test_stall_watchdog_is_actually_invoked():
    # Defining the watchdog is not enough: without a caller it is dead code and
    # a wedged sender could hold the amplifier open indefinitely.
    callers = [
        name for name in ("bringup.c", "local_connection.c", "app_main.c")
        if "audio_playback_poll_timeout()" in read(name)
    ]
    assert callers, "audio_playback_poll_timeout() is never called"


def test_audio_frame_reassembly_is_bounded_and_static():
    connection = read("local_connection.c")
    # Fragments must be reassembled, not rejected: rejecting them truncated
    # every utterance longer than a few seconds.
    assert "static uint8_t audio_frame[MAX_AUDIO_FRAME_BYTES];" in connection
    assert "payload_offset == 0" in connection
    assert "frame_desync" in connection
    frame = connection.split("static void process_audio_frame(", 1)[1].split(
        "static void process_control(", 1)[0]
    assert "malloc" not in frame
    assert "audio_frame_filled + event->data_len > MAX_AUDIO_FRAME_BYTES" in frame


def test_capture_buffers_are_static_not_on_the_task_stack():
    # These buffers total about 2 KB and overflowed a 4 KB task stack, which
    # rebooted the device the first time capture ran.
    connection = read("local_connection.c")
    assert "static uint8_t capture_chunk[" in connection
    assert "static uint8_t capture_frame[" in connection
    capture = connection.split("static void capture_task(", 1)[1].split(
        "static void process_control(", 1)[0]
    assert "uint8_t chunk[" not in capture
    assert "uint8_t frame[" not in capture
    assert '"aipi_capture", 6144' in connection
    # The stereo de-interleave buffer is on the same path.
    assert "static int16_t stereo[CHUNK_SAMPLES * 2];" in read("audio_output.c")


def test_capture_read_size_is_a_constant_not_sizeof_a_pointer():
    # capture_chunk is reached through a pointer, so sizeof() on it yields the
    # pointer width, not the buffer size. That silently reduced every read to
    # 4 bytes and captured about 6% of the audio.
    connection = read("local_connection.c")
    capture = connection.split("static void capture_task(", 1)[1].split(
        "static void process_control(", 1)[0]
    assert "sizeof(chunk)" not in capture
    assert "audio_input_read(chunk, AUDIO_MIC_CHUNK_BYTES" in capture
