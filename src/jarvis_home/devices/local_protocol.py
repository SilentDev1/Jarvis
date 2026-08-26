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
    decode_chunk,
    duration_seconds,
    validate_format,
)
from .firmware_release import is_newer
from .ota import UPDATABLE_STATES, OtaState, OtaStatus
from .terminal_state import TerminalState, TerminalStateMachine

PROTOCOL_VERSION = 1
SUBPROTOCOL = "jarvis.device.v1"
MAX_CONTROL_BYTES = 4096
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TIMEOUT_SECONDS = 75
ALLOWED_CAPABILITIES = {
    "DISPLAY", "BUTTON", "WIFI", "LOCAL_CONNECTION", "STATUS",
    # Advertised once the physical speaker and microphone were validated. The
    # gateway gates audio on these rather than assuming every device has them.
    "SPEAKER", "MICROPHONE",
}


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
        # In-flight microphone stream. Bounded: capture is capped by duration
        # on the device and by byte count here, so a wedged or hostile device
        # cannot grow host memory.
        self._mic_stream_id: int | None = None
        self._mic_sequence = 0
        self._mic_chunks: list[bytes] = []
        self._mic_bytes = 0
        self._mic_done: asyncio.Event | None = None
        self._mic_reason: str | None = None
        # Signalled when the device reports playback actually finished. The
        # host finishes sending long before the device finishes playing.
        self._playback_done: asyncio.Event | None = None
        # Set by the gateway so a physical button press can start a voice turn
        # without the protocol layer depending on the voice loop.
        self.on_button_pressed = None
        # OTA is owner-initiated only; nothing here starts an update by itself.
        self.ota = OtaStatus()
        # Whether a visitor session is open. The terminal state machine does
        # not model this, but the display distinguishes waking for a visitor
        # from plain idle.
        self.visitor_present = False

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
        await self.sync_visual()
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
            self._playback_done = asyncio.Event()
            await self.send("AUDIO_END", **summary)
            # Wait for the device to report real end-of-playback. Leaving
            # SPEAKING when the last byte was merely *sent* would reopen the
            # microphone while the speaker is still running, and the terminal
            # would transcribe its own voice. Fall back to the audio's own
            # duration if the device never reports.
            expected = duration_seconds(len(pcm))
            try:
                await asyncio.wait_for(
                    self._playback_done.wait(), timeout=expected + 5
                )
            except TimeoutError:
                pass
        except Exception as error:
            # Best effort: if the socket is already gone the device aborts on
            # its own disconnect path.
            with contextlib.suppress(Exception):
                await self.send("AUDIO_ABORT", **stream.abort_message(str(error)))
            raise
        finally:
            self._audio_active = False
            self._playback_done = None
            # Leaving SPEAKING starts the settling delay before the microphone
            # may reopen, on the success and the failure path alike.
            self.terminal.transition(TerminalState.IDLE)
            await self.sync_visual()
        return {
            **summary,
            "durationSeconds": round(duration_seconds(len(pcm)), 3),
            "elapsedSeconds": round(time.monotonic() - started, 3),
        }

    def _reset_microphone(self) -> None:
        self._mic_stream_id = None
        self._mic_sequence = 0
        self._mic_chunks = []
        self._mic_bytes = 0

    async def receive_binary(self, frame: bytes) -> None:
        """Accept one microphone chunk from the device."""
        if self._mic_stream_id is None:
            raise AudioStreamError("unexpected_binary_frame")
        chunk = decode_chunk(frame)
        if chunk.stream_id != self._mic_stream_id:
            raise AudioStreamError("mic_stream_id_mismatch")
        if chunk.sequence != self._mic_sequence:
            raise AudioStreamError("mic_sequence_gap")
        if self._mic_bytes + len(chunk.payload) > AUDIO_MAX_STREAM_BYTES:
            raise AudioStreamError("mic_stream_too_large")
        self._mic_sequence += 1
        self._mic_bytes += len(chunk.payload)
        self._mic_chunks.append(chunk.payload)

    async def listen(self, max_milliseconds: int = 5000,
                     stream_id: int = 1) -> bytes:
        """Capture one bounded utterance and return raw canonical PCM.

        Refuses unless the terminal is in LISTENING, so half-duplex is enforced
        by state rather than by callers remembering to check.
        """
        if self.websocket is None:
            raise AudioStreamError("device_not_connected")
        if not self.health.ready:
            raise AudioStreamError("device_not_ready")
        if self.terminal.state is not TerminalState.LISTENING:
            raise AudioStreamError("not_listening")
        if not self.terminal.microphone_allowed():
            # The speech tail has not decayed yet. Wait it out rather than
            # failing: in the normal conversational flow listening always
            # follows speaking, so the delay is expected, not an error. The
            # safety property is that the microphone does not open early, and
            # waiting satisfies it. Bounded so a stuck clock cannot hang here.
            remaining = self.terminal.settle_seconds
            if self.terminal.last_speaking_ended_at is not None:
                remaining = self.terminal.settle_seconds - (
                    time.monotonic() - self.terminal.last_speaking_ended_at
                )
            await asyncio.sleep(max(0.0, min(remaining, self.terminal.settle_seconds)))
            if not self.terminal.microphone_allowed():
                raise AudioStreamError("microphone_not_settled")
        if self._mic_stream_id is not None:
            raise AudioStreamError("mic_stream_already_active")

        self._reset_microphone()
        self._mic_stream_id = stream_id
        self._mic_reason = None
        self._mic_done = asyncio.Event()
        await self.sync_visual()
        await self.send("LISTEN_START", streamId=stream_id,
                        maxMilliseconds=max_milliseconds)
        try:
            # Allow the device its full budget plus slack for teardown, then
            # give up rather than waiting forever on a silent device.
            await asyncio.wait_for(
                self._mic_done.wait(), timeout=(max_milliseconds / 1000) + 5
            )
        except TimeoutError:
            self._mic_reason = "host_timeout"
            with contextlib.suppress(Exception):
                await self.send("LISTEN_STOP", streamId=stream_id)
        finally:
            audio = b"".join(self._mic_chunks)
            self._reset_microphone()
            self._mic_done = None
        return audio

    async def send(self, message_type: str, **payload) -> None:
        if self.websocket is None:
            raise ConnectionError("device_offline")
        await self.websocket.send_text(
            json.dumps(message(message_type, **payload), separators=(",", ":"))
        )

    def visual_for_state(self) -> str:
        """Maps the authoritative terminal state to a display state.

        The device renders what Jarvis has decided rather than inferring it,
        so the screen cannot disagree with the speaker or the connection.
        """
        state = self.terminal.state
        if self.ota.is_active():
            return "UPDATING"
        if state is TerminalState.OFFLINE:
            return "OFFLINE"
        if state is TerminalState.ERROR:
            return "ERROR"
        if state is TerminalState.SPEAKING:
            return "SPEAKING"
        if state is TerminalState.LISTENING:
            return "LISTENING"
        if state is TerminalState.PROCESSING:
            return "PROCESSING"
        if state in (TerminalState.BOOTING, TerminalState.SETUP):
            return "CONNECTING"
        return "VISITOR" if self.visitor_present else "IDLE"

    async def sync_visual(self) -> None:
        """Pushes the current display state to the device.

        Best effort: a display update must never break audio or the
        connection, so send failures are swallowed.
        """
        if self.websocket is None:
            return
        with contextlib.suppress(Exception):
            await self.send("TERMINAL_STATE", visual=self.visual_for_state())

    async def set_visitor_present(self, present: bool) -> None:
        if self.visitor_present == present:
            return
        self.visitor_present = present
        self.arc.set_visitor_present(present)
        await self.sync_visual()

    async def offer_update(self, record: dict, force: bool = False) -> dict:
        """Offer a published release to the device.

        Refused unless the terminal is genuinely idle: an update that
        interrupts a visitor conversation, or that starts while the amplifier
        is live, is worse than one that waits.
        """
        manifest = record["manifest"]
        if self.websocket is None:
            raise AudioStreamError("device_not_connected")
        if not self.health.ready:
            raise AudioStreamError("device_not_ready")
        if self.terminal.state not in UPDATABLE_STATES:
            raise AudioStreamError(f"terminal_busy:{self.terminal.state}")
        if self._audio_active or self._mic_stream_id is not None:
            raise AudioStreamError("audio_in_progress")
        if self.ota.is_active() and not self.ota.is_stalled():
            raise AudioStreamError(f"update_already_active:{self.ota.state}")

        current = self.health.firmware_version
        if not force and current and not is_newer(manifest["version"], current):
            # Re-installing the same or an older build is almost always a
            # mistake; it stays possible but must be asked for explicitly.
            raise AudioStreamError("not_newer_than_installed")

        self.ota.begin(manifest["version"], current)
        await self.send(
            "OTA_OFFER",
            manifest=manifest,
            signature=record["signature"],
            url=f"/firmware/{manifest['version']}/image",
        )
        return {"offered": manifest["version"], "previous": current,
                "state": self.ota.public()}

    def _handle_ota_message(self, value: dict) -> bool:
        kind = value.get("type")
        if kind == "OTA_PROGRESS":
            self.ota.advance(
                OtaState.DOWNLOADING,
                progress=int(value.get("percent", 0)),
                detail=str(value.get("detail", ""))[:120] or None,
            )
            return True
        if kind == "OTA_STATUS":
            raw = str(value.get("state", ""))
            try:
                state = OtaState(raw)
            except ValueError:
                # An unknown state from the device is a protocol violation, not
                # something to guess at.
                self.ota.advance(OtaState.FAILED, detail=f"unknown_state:{raw[:40]}")
                return True
            self.ota.advance(
                state,
                progress=int(value.get("percent", self.ota.progress)),
                detail=str(value.get("detail", ""))[:120] or None,
            )
            return True
        return False

    def _handle_microphone_message(self, value: dict) -> bool:
        kind = value.get("type")
        if kind == "BUTTON_PRESSED":
            if self.on_button_pressed is not None:
                # Run detached: the turn takes seconds and must not block the
                # receive loop that the same device depends on.
                asyncio.create_task(self.on_button_pressed())
            return True
        if kind == "AUDIO_DONE":
            if self._playback_done is not None:
                self._playback_done.set()
            return True
        if kind == "MIC_BEGIN":
            # Format is validated even though the device generated it; a device
            # reporting an unexpected format must not silently corrupt STT.
            validate_format(
                int(value.get("sampleRate", 0)),
                int(value.get("channels", 0)),
                int(value.get("bitsPerSample", 0)),
            )
            return True
        if kind in ("MIC_END", "MIC_ABORT"):
            self._mic_reason = str(value.get("reason", kind))
            if self._mic_done is not None:
                self._mic_done.set()
            return True
        return False

    async def receive(self, value: dict) -> None:
        now = time.time()
        self.health.last_seen = now
        message_type = value["type"]
        if self._handle_ota_message(value):
            return
        if self._handle_microphone_message(value):
            return
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
