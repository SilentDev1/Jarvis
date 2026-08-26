"""Bounded audio streaming for the local AiPi terminal.

One canonical format is supported deliberately. The ES8311 codec is already
physically validated at this format, macOS `say` produces it natively, and
Whisper-family speech recognition expects it, so no resampling is needed
anywhere in the local path. Supporting a second format would add conversion
code with no current caller.

Canonical format:

    sample rate     16000 Hz
    channels        1 (mono)
    bit depth       16-bit signed
    endianness      little-endian
    chunk payload   2048 bytes (1024 samples, 64 ms)

Control messages (AUDIO_BEGIN, AUDIO_END, AUDIO_ABORT) travel as JSON on the
existing authenticated channel. Chunk payloads travel as WebSocket binary
frames carrying a compact 8-byte header, because base64 in JSON would inflate
every chunk by a third and the control channel is capped at 4 KiB.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_BITS_PER_SAMPLE = 16
AUDIO_SAMPLE_BYTES = AUDIO_BITS_PER_SAMPLE // 8

# 1024 samples per chunk: 64 ms of audio, small enough to bound device memory
# and large enough that per-chunk overhead stays negligible.
AUDIO_CHUNK_BYTES = 2048
AUDIO_MAX_CHUNK_BYTES = 4096

# A single utterance may not exceed 30 seconds. This bounds device memory and
# stops a malformed or hostile stream from holding the speaker open.
AUDIO_MAX_STREAM_SECONDS = 30
AUDIO_MAX_STREAM_BYTES = (
    AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_SAMPLE_BYTES * AUDIO_MAX_STREAM_SECONDS
)

# A stream that stalls mid-flight must not leave the amplifier enabled.
AUDIO_STREAM_TIMEOUT_SECONDS = 10

AUDIO_MAGIC = b"JA"
AUDIO_HEADER_FORMAT = "<2sHI"
AUDIO_HEADER_BYTES = struct.calcsize(AUDIO_HEADER_FORMAT)

MAX_STREAM_ID = 0xFFFF
MAX_SEQUENCE = 0xFFFFFFFF


class AudioStreamError(ValueError):
    """Raised when an audio stream violates the protocol contract."""


@dataclass(frozen=True)
class AudioChunk:
    stream_id: int
    sequence: int
    payload: bytes


def duration_seconds(byte_count: int) -> float:
    return byte_count / (AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_SAMPLE_BYTES)


def validate_format(sample_rate: int, channels: int, bits_per_sample: int) -> None:
    if sample_rate != AUDIO_SAMPLE_RATE:
        raise AudioStreamError("unsupported_sample_rate")
    if channels != AUDIO_CHANNELS:
        raise AudioStreamError("unsupported_channel_count")
    if bits_per_sample != AUDIO_BITS_PER_SAMPLE:
        raise AudioStreamError("unsupported_bit_depth")


def validate_stream_id(stream_id: int) -> None:
    if not isinstance(stream_id, int) or isinstance(stream_id, bool):
        raise AudioStreamError("invalid_stream_id")
    if not 1 <= stream_id <= MAX_STREAM_ID:
        raise AudioStreamError("invalid_stream_id")


def encode_chunk(stream_id: int, sequence: int, payload: bytes) -> bytes:
    validate_stream_id(stream_id)
    if not 0 <= sequence <= MAX_SEQUENCE:
        raise AudioStreamError("invalid_sequence")
    if not payload:
        raise AudioStreamError("empty_chunk")
    if len(payload) > AUDIO_MAX_CHUNK_BYTES:
        raise AudioStreamError("chunk_too_large")
    # A partial sample would desynchronise every following frame.
    if len(payload) % AUDIO_SAMPLE_BYTES:
        raise AudioStreamError("chunk_not_sample_aligned")
    header = struct.pack(AUDIO_HEADER_FORMAT, AUDIO_MAGIC, stream_id, sequence)
    return header + payload


def decode_chunk(frame: bytes) -> AudioChunk:
    if len(frame) <= AUDIO_HEADER_BYTES:
        raise AudioStreamError("chunk_truncated")
    magic, stream_id, sequence = struct.unpack(
        AUDIO_HEADER_FORMAT, frame[:AUDIO_HEADER_BYTES]
    )
    if magic != AUDIO_MAGIC:
        raise AudioStreamError("bad_magic")
    payload = frame[AUDIO_HEADER_BYTES:]
    if len(payload) > AUDIO_MAX_CHUNK_BYTES:
        raise AudioStreamError("chunk_too_large")
    if len(payload) % AUDIO_SAMPLE_BYTES:
        raise AudioStreamError("chunk_not_sample_aligned")
    validate_stream_id(stream_id)
    return AudioChunk(stream_id=stream_id, sequence=sequence, payload=payload)


def chunk_payload(data: bytes, size: int = AUDIO_CHUNK_BYTES) -> list[bytes]:
    """Split PCM into sample-aligned chunks no larger than the protocol cap."""
    if size <= 0 or size > AUDIO_MAX_CHUNK_BYTES:
        raise AudioStreamError("invalid_chunk_size")
    if size % AUDIO_SAMPLE_BYTES:
        raise AudioStreamError("invalid_chunk_size")
    if len(data) % AUDIO_SAMPLE_BYTES:
        raise AudioStreamError("payload_not_sample_aligned")
    return [data[start : start + size] for start in range(0, len(data), size)]


class OutboundAudioStream:
    """Tracks one in-flight playback stream and enforces its bounds.

    Only one stream may be active at a time. A second concurrent stream would
    interleave on the device and leave amplifier ownership ambiguous.
    """

    def __init__(self, stream_id: int, expected_bytes: int | None = None):
        validate_stream_id(stream_id)
        if expected_bytes is not None:
            if expected_bytes <= 0:
                raise AudioStreamError("empty_stream")
            if expected_bytes > AUDIO_MAX_STREAM_BYTES:
                raise AudioStreamError("stream_too_large")
            if expected_bytes % AUDIO_SAMPLE_BYTES:
                raise AudioStreamError("payload_not_sample_aligned")
        self.stream_id = stream_id
        self.expected_bytes = expected_bytes
        self.sequence = 0
        self.sent_bytes = 0
        self.closed = False

    def begin_message(self) -> dict:
        return {
            "streamId": self.stream_id,
            "sampleRate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
            "bitsPerSample": AUDIO_BITS_PER_SAMPLE,
            "expectedBytes": self.expected_bytes,
            "maxChunkBytes": AUDIO_MAX_CHUNK_BYTES,
        }

    def next_chunk(self, payload: bytes) -> bytes:
        if self.closed:
            raise AudioStreamError("stream_closed")
        self.sent_bytes += len(payload)
        if self.sent_bytes > AUDIO_MAX_STREAM_BYTES:
            raise AudioStreamError("stream_too_large")
        if self.expected_bytes is not None and self.sent_bytes > self.expected_bytes:
            raise AudioStreamError("stream_overrun")
        frame = encode_chunk(self.stream_id, self.sequence, payload)
        self.sequence += 1
        return frame

    def end_message(self) -> dict:
        if self.closed:
            raise AudioStreamError("stream_closed")
        if self.expected_bytes is not None and self.sent_bytes != self.expected_bytes:
            raise AudioStreamError("stream_underrun")
        self.closed = True
        return {
            "streamId": self.stream_id,
            "totalChunks": self.sequence,
            "totalBytes": self.sent_bytes,
        }

    def abort_message(self, reason: str) -> dict:
        self.closed = True
        return {"streamId": self.stream_id, "reason": reason[:64]}
