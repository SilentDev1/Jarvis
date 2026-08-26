"""Bounds and framing guards for the local audio streaming protocol."""

import pytest

from jarvis_home.devices.audio_stream import (
    AUDIO_BITS_PER_SAMPLE,
    AUDIO_CHANNELS,
    AUDIO_CHUNK_BYTES,
    AUDIO_HEADER_BYTES,
    AUDIO_MAX_CHUNK_BYTES,
    AUDIO_MAX_STREAM_BYTES,
    AUDIO_SAMPLE_RATE,
    AudioStreamError,
    OutboundAudioStream,
    chunk_payload,
    decode_chunk,
    duration_seconds,
    encode_chunk,
    validate_format,
)


def test_canonical_format_matches_validated_codec_configuration():
    # The ES8311 was physically validated at exactly this configuration.
    assert AUDIO_SAMPLE_RATE == 16000
    assert AUDIO_CHANNELS == 1
    assert AUDIO_BITS_PER_SAMPLE == 16
    assert AUDIO_HEADER_BYTES == 8
    assert AUDIO_CHUNK_BYTES <= AUDIO_MAX_CHUNK_BYTES


def test_round_trip_preserves_stream_identity_and_payload():
    payload = b"\x01\x02" * 512
    chunk = decode_chunk(encode_chunk(7, 3, payload))
    assert chunk.stream_id == 7
    assert chunk.sequence == 3
    assert chunk.payload == payload


def test_rejects_unsupported_formats():
    validate_format(16000, 1, 16)
    with pytest.raises(AudioStreamError, match="sample_rate"):
        validate_format(44100, 1, 16)
    with pytest.raises(AudioStreamError, match="channel"):
        validate_format(16000, 2, 16)
    with pytest.raises(AudioStreamError, match="bit_depth"):
        validate_format(16000, 1, 24)


def test_rejects_oversized_and_misaligned_chunks():
    with pytest.raises(AudioStreamError, match="chunk_too_large"):
        encode_chunk(1, 0, b"\x00" * (AUDIO_MAX_CHUNK_BYTES + 2))
    with pytest.raises(AudioStreamError, match="sample_aligned"):
        encode_chunk(1, 0, b"\x00" * 101)
    with pytest.raises(AudioStreamError, match="empty_chunk"):
        encode_chunk(1, 0, b"")


def test_rejects_malformed_frames():
    with pytest.raises(AudioStreamError, match="truncated"):
        decode_chunk(b"JA\x01\x00\x00\x00\x00\x00")
    with pytest.raises(AudioStreamError, match="bad_magic"):
        decode_chunk(b"XX\x01\x00\x00\x00\x00\x00" + b"\x00\x02")
    with pytest.raises(AudioStreamError, match="invalid_stream_id"):
        decode_chunk(encode_chunk(1, 0, b"\x00\x02").replace(b"\x01\x00", b"\x00\x00", 1))


def test_stream_id_zero_is_reserved():
    with pytest.raises(AudioStreamError, match="invalid_stream_id"):
        OutboundAudioStream(0)


def test_chunking_is_sample_aligned_and_covers_all_data():
    data = b"\x01\x02" * 3000
    chunks = chunk_payload(data)
    assert b"".join(chunks) == data
    assert all(len(c) % 2 == 0 for c in chunks)
    assert all(len(c) <= AUDIO_CHUNK_BYTES for c in chunks)


def test_stream_rejects_oversized_total():
    with pytest.raises(AudioStreamError, match="stream_too_large"):
        OutboundAudioStream(1, expected_bytes=AUDIO_MAX_STREAM_BYTES + 2)


def test_stream_rejects_empty_total():
    with pytest.raises(AudioStreamError, match="empty_stream"):
        OutboundAudioStream(1, expected_bytes=0)


def test_stream_sequence_increments_and_end_reports_totals():
    data = b"\x01\x02" * 2048
    stream = OutboundAudioStream(9, expected_bytes=len(data))
    chunks = chunk_payload(data)
    for index, payload in enumerate(chunks):
        assert decode_chunk(stream.next_chunk(payload)).sequence == index
    end = stream.end_message()
    assert end["totalChunks"] == len(chunks)
    assert end["totalBytes"] == len(data)


def test_stream_detects_overrun_and_underrun():
    stream = OutboundAudioStream(2, expected_bytes=4)
    stream.next_chunk(b"\x00\x00")
    with pytest.raises(AudioStreamError, match="underrun"):
        stream.end_message()
    stream.next_chunk(b"\x00\x00")
    over = OutboundAudioStream(3, expected_bytes=2)
    over.next_chunk(b"\x00\x00")
    with pytest.raises(AudioStreamError, match="overrun"):
        over.next_chunk(b"\x00\x00")


def test_closed_stream_refuses_further_writes():
    stream = OutboundAudioStream(4)
    stream.next_chunk(b"\x00\x00")
    stream.end_message()
    with pytest.raises(AudioStreamError, match="stream_closed"):
        stream.next_chunk(b"\x00\x00")


def test_abort_closes_stream_and_truncates_reason():
    stream = OutboundAudioStream(5)
    payload = stream.abort_message("x" * 200)
    assert payload["streamId"] == 5
    assert len(payload["reason"]) <= 64
    with pytest.raises(AudioStreamError, match="stream_closed"):
        stream.next_chunk(b"\x00\x00")


def test_begin_message_advertises_canonical_format():
    begin = OutboundAudioStream(6, expected_bytes=32000).begin_message()
    assert begin["sampleRate"] == AUDIO_SAMPLE_RATE
    assert begin["channels"] == AUDIO_CHANNELS
    assert begin["bitsPerSample"] == AUDIO_BITS_PER_SAMPLE
    assert begin["maxChunkBytes"] == AUDIO_MAX_CHUNK_BYTES


def test_duration_matches_canonical_rate():
    assert duration_seconds(32000) == pytest.approx(1.0)
    assert duration_seconds(AUDIO_MAX_STREAM_BYTES) == pytest.approx(30.0)
