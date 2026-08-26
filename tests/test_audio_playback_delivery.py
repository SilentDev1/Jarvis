"""Delivery guards for streamed playback and the operator playback controls."""

import pytest

from jarvis_home.devices.audio_stream import (
    AUDIO_MAX_STREAM_BYTES,
    AudioStreamError,
    decode_chunk,
)
from jarvis_home.devices.local_protocol import LocalDeviceHub


class FakeSocket:
    def __init__(self, fail_on_bytes=False):
        self.text = []
        self.binary = []
        self.fail_on_bytes = fail_on_bytes

    async def send_text(self, value):
        self.text.append(value)

    async def send_bytes(self, value):
        if self.fail_on_bytes:
            raise ConnectionResetError("socket gone")
        self.binary.append(value)


class FakeStore:
    class Session:
        def __enter__(self):
            raise AssertionError("persistence must not be touched by playback")

        def __exit__(self, *args):
            return False


def make_hub(ready=True, socket=None):
    hub = LocalDeviceHub(FakeStore())
    hub.websocket = socket if socket is not None else FakeSocket()
    hub.health.connected = True
    hub.health.ready = ready
    return hub


def types_sent(socket):
    import json

    return [json.loads(item)["type"] for item in socket.text]


@pytest.mark.asyncio
async def test_playback_sends_begin_chunks_and_end_in_order():
    socket = FakeSocket()
    hub = make_hub(socket=socket)
    pcm = b"\x01\x02" * 3000
    result = await hub.play_pcm(pcm)
    assert types_sent(socket) == ["AUDIO_BEGIN", "AUDIO_END"]
    assert result["totalBytes"] == len(pcm)
    assert result["totalChunks"] == len(socket.binary)
    # Sequence numbers must be gapless: the device aborts on any gap.
    sequences = [decode_chunk(frame).sequence for frame in socket.binary]
    assert sequences == list(range(len(socket.binary)))
    assert b"".join(decode_chunk(f).payload for f in socket.binary) == pcm


@pytest.mark.asyncio
async def test_playback_requires_a_ready_authenticated_device():
    with pytest.raises(AudioStreamError, match="device_not_ready"):
        await make_hub(ready=False).play_pcm(b"\x00\x00")
    hub = make_hub()
    hub.websocket = None
    with pytest.raises(AudioStreamError, match="device_not_connected"):
        await hub.play_pcm(b"\x00\x00")


@pytest.mark.asyncio
async def test_playback_rejects_empty_misaligned_and_oversized_audio():
    hub = make_hub()
    with pytest.raises(AudioStreamError, match="empty_stream"):
        await hub.play_pcm(b"")
    with pytest.raises(AudioStreamError, match="sample_aligned"):
        await hub.play_pcm(b"\x00\x00\x00")
    with pytest.raises(AudioStreamError, match="stream_too_large"):
        await hub.play_pcm(b"\x00" * (AUDIO_MAX_STREAM_BYTES + 2))


@pytest.mark.asyncio
async def test_failed_send_aborts_so_the_device_drops_the_amplifier():
    socket = FakeSocket(fail_on_bytes=True)
    hub = make_hub(socket=socket)
    with pytest.raises(ConnectionResetError):
        await hub.play_pcm(b"\x01\x02" * 100)
    assert types_sent(socket) == ["AUDIO_BEGIN", "AUDIO_ABORT"]
    # The stream slot must be released, otherwise playback wedges permanently.
    assert hub._audio_active is False


@pytest.mark.asyncio
async def test_only_one_stream_may_be_active():
    hub = make_hub()
    hub._audio_active = True
    with pytest.raises(AudioStreamError, match="stream_already_active"):
        await hub.play_pcm(b"\x00\x00")
