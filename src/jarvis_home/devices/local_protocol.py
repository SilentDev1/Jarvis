import asyncio
import contextlib
import json
import secrets
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field

from ..persistence import Device, utcnow
from .arc_reactor import ArcReactorController
from .audio_stream import (
    AUDIO_MAX_STREAM_BYTES,
    AUDIO_SAMPLE_BYTES,
    AudioStreamError,
    OutboundAudioStream,
    chunk_payload,
    duration_seconds,
)
from .terminal_state import TerminalState, TerminalStateMachine

PROTOCOL_VERSION = 1
SUBPROTOCOL = "jarvis.device.v1"
MAX_CONTROL_BYTES = 4096
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TIMEOUT_SECONDS = 75
ALLOWED_CAPABILITIES = {"DISPLAY", "BUTTON", "WIFI", "LOCAL_CONNECTION", "STATUS"}


def message(message_type: str, **payload) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "type": message_type,
        "id": secrets.token_hex(8),
        **payload,
    }


def parse_message(raw: str) -> dict:
    if len(raw.encode()) > MAX_CONTROL_BYTES:
        raise ValueError("message_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("message_must_be_object")
    if value.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError("unsupported_protocol_version")
    if not isinstance(value.get("type"), str) or not value["type"]:
        raise ValueError("message_type_required")
    return value


@dataclass
class LocalDeviceHealth:
    connected: bool = False
    ready: bool = False
    device_id: str | None = None
    firmware_version: str | None = None
    capabilities: list[str] = field(default_factory=list)
    ip: str | None = None
    wifi_rssi: int | None = None
    uptime_seconds: int | None = None
    free_heap: int | None = None
    free_psram: int | None = None
    display_status: str | None = None
    button_status: str | None = None
    terminal_state: str = "JARVIS_OFFLINE"
    connected_at: float | None = None
    last_seen: float | None = None
    last_successful_heartbeat: float | None = None
    last_error: str | None = None

    def public(self) -> dict:
        result = asdict(self)
        result["connection_duration_seconds"] = (
            max(0, int(time.time() - self.connected_at))
            if self.connected and self.connected_at
            else 0
        )
        return result


class ConnectionFloodLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, address: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        bucket = self.attempts[address]
        while bucket and bucket[0] <= now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


class LocalDeviceHub:
    def __init__(self, store):
        self.store = store
        self.websocket = None
        self.health = LocalDeviceHealth()
        self._lock = asyncio.Lock()
        # Only one utterance may be in flight; a second would interleave on the
        # device and leave amplifier ownership ambiguous.
        self._audio_active = False
        # The single authoritative terminal state. Audio, display, and the arc
        # reactor all read this rather than tracking their own.
        self.terminal = TerminalStateMachine()
        # Consumes the terminal state and the outgoing audio envelope. Disabled
        # until the physical light is identified.
        self.arc = ArcReactorController()

    def mark_offline(self) -> None:
        self.health = LocalDeviceHealth()
        self._persist(False)

    def _persist(self, online: bool) -> None:
        with self.store.Session() as session:
            device = session.get(Device, "aipi-front-door")
            if device is None:
                return
            device.status = "online" if online else "offline"
            device.connection_state = "local_lan" if online else "disconnected"
            device.last_seen = utcnow() if online else device.last_seen
            device.updated_at = utcnow()
            session.commit()

    async def attach(self, websocket, device_id: str, ip: str | None) -> None:
        async with self._lock:
            if self.websocket is not None:
                await self.websocket.close(code=1013, reason="device_replaced")
            self.websocket = websocket
            if self.terminal.state is not TerminalState.IDLE:
                self.terminal.transition(TerminalState.IDLE)
            now = time.time()
            self.health = LocalDeviceHealth(
                connected=True,
                device_id=device_id,
                ip=ip,
                connected_at=now,
                last_seen=now,
                terminal_state="AUTHENTICATING",
            )

    async def detach(self, reason: str, websocket=None) -> None:
        async with self._lock:
            if websocket is not None and websocket is not self.websocket:
                return
            self.websocket = None
            self.terminal.transition(TerminalState.OFFLINE)
            self.health.connected = False
            self.health.ready = False
            self.health.terminal_state = "JARVIS_OFFLINE"
            self.health.last_error = reason
            self._persist(False)

    async def play_pcm(self, pcm: bytes, stream_id: int = 1) -> dict:
        """Stream one bounded PCM utterance to the device.

        Returns playback statistics. Any failure aborts the stream so the
        device drops the amplifier rather than waiting for chunks that will
        never arrive.
        """
        if self.websocket is None:
            raise AudioStreamError("device_not_connected")
        if not self.health.ready:
            raise AudioStreamError("device_not_ready")
        if not pcm:
            raise AudioStreamError("empty_stream")
        if len(pcm) % AUDIO_SAMPLE_BYTES:
            raise AudioStreamError("payload_not_sample_aligned")
        if len(pcm) > AUDIO_MAX_STREAM_BYTES:
            raise AudioStreamError("stream_too_large")
        if self._audio_active:
            raise AudioStreamError("stream_already_active")

        # Half-duplex: entering SPEAKING is what closes the microphone, and it
        # is done here rather than by the caller so playback can never run with
        # the microphone still open.
        self.terminal.transition(TerminalState.SPEAKING)
        stream = OutboundAudioStream(stream_id, expected_bytes=len(pcm))
        self._audio_active = True
        started = time.monotonic()
        chunks = chunk_payload(pcm)
        try:
            await self.send("AUDIO_BEGIN", **stream.begin_message())
            for payload in chunks:
                # Envelope is computed here, on the host, so the device does no
                # floating-point work between I2S writes.
                self.arc.observe_audio(payload)
                await self.websocket.send_bytes(stream.next_chunk(payload))
            summary = stream.end_message()
            await self.send("AUDIO_END", **summary)
        except Exception as error:
            # Best effort: if the socket is already gone the device aborts on
            # its own disconnect path.
            with contextlib.suppress(Exception):
                await self.send("AUDIO_ABORT", **stream.abort_message(str(error)))
            raise
        finally:
            self._audio_active = False
            # Leaving SPEAKING starts the settling delay before the microphone
            # may reopen, on the success and the failure path alike.
            self.terminal.transition(TerminalState.IDLE)
        return {
            **summary,
            "durationSeconds": round(duration_seconds(len(pcm)), 3),
            "elapsedSeconds": round(time.monotonic() - started, 3),
        }

    async def send(self, message_type: str, **payload) -> None:
        if self.websocket is None:
            raise ConnectionError("device_offline")
        await self.websocket.send_text(
            json.dumps(message(message_type, **payload), separators=(",", ":"))
        )

    async def receive(self, value: dict) -> None:
        now = time.time()
        self.health.last_seen = now
        message_type = value["type"]
        if message_type == "DEVICE_HELLO":
            if value.get("deviceId") != self.health.device_id:
                raise ValueError("device_id_mismatch")
            capabilities = value.get("capabilities")
            if not isinstance(capabilities, list) or not all(
                isinstance(item, str) and item in ALLOWED_CAPABILITIES
                for item in capabilities
            ):
                raise ValueError("invalid_capabilities")
            self.health.firmware_version = str(value.get("firmwareVersion", ""))[:40]
            self.health.capabilities = capabilities
            self.health.ready = True
            self.health.terminal_state = "JARVIS_ONLINE"
            self._persist(True)
            await self.send("DEVICE_READY", deviceId=self.health.device_id)
            await self.send("STATUS_REQUEST")
        elif message_type == "PONG":
            self.health.last_successful_heartbeat = now
        elif message_type == "PING":
            await self.send("PONG", replyTo=value.get("id"))
        elif message_type == "DEVICE_STATUS":
            self.health.uptime_seconds = _bounded_int(value.get("uptimeSeconds"), 0, 2**31)
            self.health.wifi_rssi = _bounded_int(value.get("wifiRssi"), -127, 0)
            self.health.free_heap = _bounded_int(value.get("freeHeap"), 0, 2**31)
            self.health.free_psram = _bounded_int(value.get("freePsram"), 0, 2**31)
            self.health.display_status = _bounded_text(value.get("displayStatus"), 40)
            self.health.button_status = _bounded_text(value.get("buttonStatus"), 20)
            self.health.terminal_state = _bounded_text(
                value.get("terminalState"), 30
            ) or "JARVIS_ONLINE"
            self._persist(True)
        elif message_type == "ERROR":
            self.health.last_error = _bounded_text(value.get("code"), 80)
        else:
            raise ValueError("unsupported_message_type")

    async def heartbeat_once(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if not self.websocket or not self.health.connected:
            return
        if self.health.last_seen and now - self.health.last_seen > HEARTBEAT_TIMEOUT_SECONDS:
            socket = self.websocket
            await socket.close(code=1011, reason="heartbeat_timeout")
            await self.detach("heartbeat_timeout", socket)
            return
        await self.send("PING")


def _bounded_int(value, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(minimum, min(maximum, value))


def _bounded_text(value, limit: int) -> str | None:
    return str(value)[:limit] if isinstance(value, str) else None
