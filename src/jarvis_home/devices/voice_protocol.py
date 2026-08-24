import asyncio
import json
import secrets
import time
from dataclasses import asdict, dataclass
from enum import StrEnum

from ..core.providers import VoiceTerminalProvider
from ..core.speech import PCM16Audio, TTSProvider

PROTOCOL_VERSION = 1
SUBPROTOCOL = "jarvis.voice.v1"
MAX_CONTROL_BYTES = 8192
MAX_AUDIO_CHUNK_BYTES = 16384
MAX_SESSION_AUDIO_BYTES = 4_000_000


class DeviceState(StrEnum):
    BOOTING = "BOOTING"
    CONNECTING = "CONNECTING"
    IDLE = "IDLE"
    GREETING = "GREETING"
    LISTENING = "LISTENING"
    STREAMING = "STREAMING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    UPDATING = "UPDATING"


@dataclass
class DeviceHealth:
    connected: bool = False
    state: DeviceState = DeviceState.CONNECTING
    firmware_version: str | None = None
    ip: str | None = None
    uptime_seconds: int | None = None
    wifi_rssi: int | None = None
    mic_ready: bool | None = None
    speaker_ready: bool | None = None
    active_session: str | None = None
    last_seen: float | None = None
    last_error: str | None = None

    def public(self):
        return asdict(self)


def control_message(message_type: str, **payload) -> dict:
    return {
        "version": PROTOCOL_VERSION,
        "type": message_type,
        "id": secrets.token_hex(8),
        **payload,
    }


def parse_control(raw: str) -> dict:
    if len(raw.encode()) > MAX_CONTROL_BYTES:
        raise ValueError("control_message_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("control_message_must_be_object")
    if value.get("version") != PROTOCOL_VERSION:
        raise ValueError("unsupported_protocol_version")
    if not isinstance(value.get("type"), str) or not value.get("type"):
        raise ValueError("message_type_required")
    return value


class LocalVoiceHub:
    """Single-device connection broker; no camera or skill logic lives here."""

    def __init__(self, bus, max_audio_bytes: int = MAX_SESSION_AUDIO_BYTES):
        self.bus = bus
        self.websocket = None
        self.device_id: str | None = None
        self.health = DeviceHealth()
        self.pending: dict[str, asyncio.Future] = {}
        self.audio = bytearray()
        self.max_audio_bytes = max_audio_bytes
        self.audio_session_id: str | None = None

    async def attach(self, websocket, device_id: str, ip: str | None = None):
        if self.websocket is not None:
            await self.websocket.close(code=1013, reason="device_replaced")
        self.websocket = websocket
        self.device_id = device_id
        self.health = DeviceHealth(connected=True, ip=ip, last_seen=time.time())
        self.bus.publish("voice.device_connected", {"device_id": device_id})

    async def detach(self, reason: str = "disconnected", websocket=None):
        if websocket is not None and websocket is not self.websocket:
            return
        device_id = self.device_id
        self.websocket = None
        self.device_id = None
        self.health.connected = False
        self.health.state = DeviceState.CONNECTING
        self.health.active_session = None
        self.health.last_error = reason
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError(reason))
        self.pending.clear()
        self.audio.clear()
        self.audio_session_id = None
        if device_id:
            self.bus.publish(
                "voice.device_disconnected", {"device_id": device_id, "reason": reason}
            )

    async def command(self, message_type: str, timeout: float = 5, **payload):
        if self.websocket is None or not self.health.connected:
            raise ConnectionError("AiPi local terminal is offline")
        message = control_message(message_type, **payload)
        loop = asyncio.get_running_loop()
        acknowledged = loop.create_future()
        self.pending[message["id"]] = acknowledged
        await self.websocket.send_text(json.dumps(message, separators=(",", ":")))
        try:
            return await asyncio.wait_for(acknowledged, timeout)
        finally:
            self.pending.pop(message["id"], None)

    async def play(self, audio: PCM16Audio, session_id: str | None):
        if audio.channels != 1 or audio.sample_width != 2:
            raise ValueError("Only PCM16 mono audio is supported")
        await self.command(
            "PLAY_AUDIO_START",
            session_id=session_id,
            codec="pcm_s16le",
            sample_rate=audio.sample_rate,
            channels=1,
            byte_length=len(audio.data),
        )
        for offset in range(0, len(audio.data), MAX_AUDIO_CHUNK_BYTES):
            if self.websocket is None:
                raise ConnectionError("AiPi disconnected during playback")
            await self.websocket.send_bytes(
                audio.data[offset : offset + MAX_AUDIO_CHUNK_BYTES]
            )
        await self.command("PLAY_AUDIO_END", session_id=session_id)

    def receive_control(self, message: dict):
        self.health.last_seen = time.time()
        message_type = message["type"]
        if message_type == "ACK":
            reply_to = message.get("reply_to")
            future = self.pending.get(reply_to) if isinstance(reply_to, str) else None
            if future and not future.done():
                future.set_result(message)
            return
        if message_type == "DEVICE_HELLO":
            self.health.firmware_version = str(message.get("firmware_version", ""))[:40]
            self.health.mic_ready = bool(message.get("mic_ready"))
            self.health.speaker_ready = bool(message.get("speaker_ready"))
        elif message_type == "DEVICE_STATUS":
            try:
                self.health.state = DeviceState(message.get("state", "ERROR"))
            except ValueError:
                self.health.state = DeviceState.ERROR
                self.health.last_error = "invalid_device_state"
            self.health.uptime_seconds = message.get("uptime_seconds")
            self.health.wifi_rssi = message.get("wifi_rssi")
            self.health.active_session = message.get("session_id")
        elif message_type == "AUDIO_START":
            self.audio.clear()
            self.audio_session_id = str(message.get("session_id", ""))[:100]
        elif message_type == "AUDIO_END":
            received_bytes = len(self.audio)
            self.bus.publish(
                "voice.audio_received",
                {
                    "session_id": self.audio_session_id,
                    "bytes": received_bytes,
                    "retained": False,
                },
            )
            self.audio.clear()
            self.audio_session_id = None

    def receive_audio(self, chunk: bytes):
        if len(chunk) > MAX_AUDIO_CHUNK_BYTES:
            raise ValueError("audio_chunk_too_large")
        if self.audio_session_id is None:
            raise ValueError("audio_without_session")
        if len(self.audio) + len(chunk) > self.max_audio_bytes:
            raise ValueError("session_audio_too_large")
        self.audio.extend(chunk)
        self.health.last_seen = time.time()


class AiPiLocalVoice(VoiceTerminalProvider):
    def __init__(self, hub: LocalVoiceHub, tts: TTSProvider):
        self.hub = hub
        self.tts = tts
        self.session_id: str | None = None

    async def set_session(self, session_id: str | None):
        self.session_id = session_id

    async def speak(self, text: str):
        audio = await self.tts.synthesize(text)
        await self.hub.play(audio, self.session_id)

    async def start_listening(self):
        await self.hub.command(
            "START_LISTENING", session_id=self.session_id, timeout_seconds=15
        )

    async def stop_listening(self):
        if self.hub.health.connected:
            await self.hub.command("RETURN_IDLE", session_id=self.session_id)

    def is_available(self):
        return bool(
            self.hub.health.connected
            and self.hub.health.state == DeviceState.IDLE
            and self.hub.health.speaker_ready
            and self.hub.health.mic_ready
        )

    def health(self):
        return {
            "status": "ready" if self.is_available() else "offline",
            "provider": "aipi_local",
            **self.hub.health.public(),
        }
