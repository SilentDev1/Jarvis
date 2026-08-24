import json

import pytest

from jarvis_home.core.events import EventBus
from jarvis_home.core.speech import PCM16Audio, TTSProvider
from jarvis_home.devices.voice_protocol import (
    MAX_AUDIO_CHUNK_BYTES,
    AiPiLocalVoice,
    DeviceState,
    LocalVoiceHub,
    parse_control,
)


class FakeWebSocket:
    def __init__(self, hub):
        self.hub = hub
        self.text = []
        self.binary = []
        self.closed = False

    async def send_text(self, raw):
        message = json.loads(raw)
        self.text.append(message)
        self.hub.receive_control(
            {
                "version": 1,
                "type": "ACK",
                "id": "device-ack",
                "reply_to": message["id"],
            }
        )

    async def send_bytes(self, data):
        self.binary.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = True


class FakeTTS(TTSProvider):
    async def synthesize(self, text):
        return PCM16Audio(text.encode() * 5000)


def test_protocol_rejects_malformed_unknown_version_and_oversized_control():
    with pytest.raises(json.JSONDecodeError):
        parse_control("not-json")
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        parse_control('{"version":2,"type":"PING"}')
    with pytest.raises(ValueError, match="control_message_too_large"):
        parse_control("x" * 9000)


@pytest.mark.asyncio
async def test_local_provider_streams_bounded_pcm_chunks_and_listens():
    hub = LocalVoiceHub(EventBus())
    socket = FakeWebSocket(hub)
    await hub.attach(socket, "aipi-front-door", "192.0.2.2")
    hub.health.state = DeviceState.IDLE
    hub.health.mic_ready = True
    hub.health.speaker_ready = True
    provider = AiPiLocalVoice(hub, FakeTTS())
    await provider.set_session("visitor-1")

    assert provider.is_available()
    await provider.speak("hello")
    await provider.start_listening()

    assert [message["type"] for message in socket.text] == [
        "PLAY_AUDIO_START",
        "PLAY_AUDIO_END",
        "START_LISTENING",
    ]
    assert all(len(chunk) <= MAX_AUDIO_CHUNK_BYTES for chunk in socket.binary)
    assert b"".join(socket.binary) == b"hello" * 5000


def test_audio_requires_active_session_and_is_size_bounded():
    hub = LocalVoiceHub(EventBus(), max_audio_bytes=10)
    with pytest.raises(ValueError, match="audio_without_session"):
        hub.receive_audio(b"123")
    hub.receive_control(
        {"version": 1, "type": "AUDIO_START", "id": "1", "session_id": "v1"}
    )
    hub.receive_audio(b"12345")
    with pytest.raises(ValueError, match="session_audio_too_large"):
        hub.receive_audio(b"123456")


def test_completed_audio_is_audited_then_immediately_discarded():
    bus = EventBus()
    hub = LocalVoiceHub(bus)
    hub.receive_control(
        {"version": 1, "type": "AUDIO_START", "id": "1", "session_id": "v1"}
    )
    hub.receive_audio(b"private")
    hub.receive_control({"version": 1, "type": "AUDIO_END", "id": "2"})

    assert hub.audio == b""
    assert hub.audio_session_id is None
    assert bus.history[0].payload == {
        "session_id": "v1",
        "bytes": 7,
        "retained": False,
    }


@pytest.mark.asyncio
async def test_disconnect_fails_closed_and_clears_unretained_audio():
    bus = EventBus()
    hub = LocalVoiceHub(bus)
    socket = FakeWebSocket(hub)
    await hub.attach(socket, "aipi-front-door")
    hub.receive_control(
        {"version": 1, "type": "AUDIO_START", "id": "1", "session_id": "v1"}
    )
    hub.receive_audio(b"private audio")

    await hub.detach("network_lost")

    assert not hub.health.connected
    assert hub.audio == b""
    assert hub.audio_session_id is None
    assert bus.history[0].type == "voice.device_disconnected"
