import asyncio
import json
import logging
import math
import os
import secrets
import sys
import time
from array import array
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse
from fastapi.websockets import WebSocketDisconnect

from ..config import get_settings
from ..core.speech import MacSayTTS, PCM16Audio
from ..core.speech_input import (
    FasterWhisperSTT,
    UtteranceFilter,
    rms,
    voiced_fraction,
)
from ..integrations.providers import OllamaAI
from ..persistence import Store
from .arc_reactor import ArcLightSettings, ArcLightStore
from .audio_stream import (
    AUDIO_MAX_BINARY_FRAME_BYTES,
    AUDIO_MAX_STREAM_SECONDS,
    AUDIO_SAMPLE_RATE,
    AudioStreamError,
    validate_format,
)
from .auth import authenticate_device
from .discovery import start_discovery_responder
from .firmware_release import (
    DEVICE_ID,
    FirmwareError,
    FirmwareStore,
    is_newer,
)
from .local_protocol import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_CONTROL_BYTES,
    SUBPROTOCOL,
    ConnectionFloodLimiter,
    LocalDeviceHub,
    parse_message,
)
from .terminal_state import TerminalState
from .voice_loop import VoiceLoop

cfg = get_settings()
store = Store(cfg.data_dir / "jarvis.db")
store.init()
hub = LocalDeviceHub(store)
limiter = ConnectionFloodLimiter()
# uvicorn configures only its own loggers, so application records were being
# dropped. A door terminal needs its voice turns visible in the log, otherwise
# a wrong answer or a rejected utterance leaves no trace to diagnose.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logging.getLogger("jarvis_home").setLevel(logging.INFO)
logger = logging.getLogger("jarvis_home.device_gateway")

# One shared recogniser and filter: the model costs seconds to load and the
# filter's echo memory must persist across turns to catch Jarvis hearing itself.
firmware_store = FirmwareStore(cfg.data_dir / "firmware")
# Owner light preference, loaded at startup so an explicit "off" survives a
# gateway restart rather than quietly coming back on.
arc_store = ArcLightStore(cfg.data_dir / "arc_light.json")
stt = FasterWhisperSTT()
utterance_filter = UtteranceFilter()
# Local reasoning by default. A door terminal must keep working when no model
# is reachable, so the loop answers basic status questions itself.
ai = OllamaAI(cfg.ollama_url, cfg.ollama_model)
voice_loop = VoiceLoop(hub, stt, MacSayTTS(), utterance_filter, ai=ai)


def peak_level(pcm: bytes) -> int:
    if len(pcm) < 2:
        return 0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    return max((abs(value) for value in samples), default=0)


def generate_tone(frequency: int, milliseconds: int, amplitude: int = 12000) -> bytes:
    """Deterministic mono PCM16 at the canonical sample rate."""
    total = AUDIO_SAMPLE_RATE * milliseconds // 1000
    samples = array("h", (
        int(amplitude * math.sin(2.0 * math.pi * frequency * index / AUDIO_SAMPLE_RATE))
        for index in range(total)
    ))
    # The canonical format is little-endian; normalise on big-endian hosts.
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


async def heartbeat_loop():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            await hub.heartbeat_once()
        except Exception:
            logger.exception("Local device heartbeat failed")


async def _button_voice_turn():
    """A physical press starts one voice turn. Failures are logged, never raised
    into the device receive loop."""
    try:
        turn = await voice_loop.run_turn()
        logger.info(
            "button voice turn: accepted=%s reason=%s source=%s heard=%r reply=%r",
            turn.accepted, turn.reason, turn.source, turn.heard, turn.reply,
        )
    except Exception:
        logger.exception("button voice turn failed")


async def _warm_recognition() -> None:
    """Loads the speech model before anyone needs it.

    Cold-loading costs about 1.6 seconds more than a warm pass, and the visitor
    who would pay it is the first real one to speak. Done in the background so
    it never delays startup, and failure is not fatal: the model would simply
    load lazily as before.
    """
    try:
        await asyncio.to_thread(stt._load)
        logger.info("speech recognition model warmed")
    except Exception:  # noqa: BLE001 - warm-up is best effort, never fatal
        logger.warning("speech model warm-up failed; it will load on first use")


@asynccontextmanager
async def lifespan(_app):
    hub.on_button_pressed = _button_voice_turn
    hub.arc_settings = arc_store.load()
    logger.info("arc light preference loaded: enabled=%s", hub.arc_settings.enabled)
    hub.mark_offline()
    task = asyncio.create_task(heartbeat_loop())
    warm = asyncio.create_task(_warm_recognition())
    # Broadcast discovery, so the terminal can find Jarvis without multicast.
    discovery = await start_discovery_responder(
        int(os.environ.get("LOCAL_DEVICE_GATEWAY_PORT", "8767"))
    )
    yield
    if discovery is not None:
        discovery.close()
    task.cancel()
    warm.cancel()
    await asyncio.gather(task, warm, return_exceptions=True)


app = FastAPI(title="Jarvis Local Device Gateway", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ready",
        "device": hub.health.public(),
        # The authoritative terminal state machine. `device.terminal_state` is
        # what the board reports about itself; this is what Jarvis has decided,
        # and it is the one audio, display, and the arc reactor consume.
        "terminal": hub.terminal.public(),
        "arc": hub.arc.frame(hub.terminal.state, time.monotonic()).public(),
    }


LOOPBACK_ADDRESSES = {"127.0.0.1", "::1", "localhost"}


def _authorize_loopback_admin(request: Request) -> None:
    """Gate the playback controls.

    These are operator controls, not part of the device surface. They require
    the admin token and are additionally restricted to loopback, so that
    exposing the gateway on the LAN for the terminal never exposes the ability
    to make the house speak.
    """
    client = request.client.host if request.client else ""
    if client not in LOOPBACK_ADDRESSES:
        raise HTTPException(status_code=404)
    supplied = request.headers.get("x-jarvis-admin-token", "")
    if not supplied or not secrets.compare_digest(supplied, cfg.jarvis_admin_token):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/internal/play-test-tone")
async def play_test_tone(request: Request):
    """Stream a deterministic PCM tone. Proves network + protocol + speaker
    independently of speech synthesis."""
    _authorize_loopback_admin(request)
    payload = await request.json() if await request.body() else {}
    frequency = int(payload.get("frequency", 440))
    milliseconds = int(payload.get("milliseconds", 1000))
    # Bounded by the protocol's own stream limit rather than a second, stricter
    # number, so the tone can exercise the real boundary.
    if not 100 <= frequency <= 4000:
        raise HTTPException(status_code=400, detail="out_of_range")
    if not 100 <= milliseconds <= AUDIO_MAX_STREAM_SECONDS * 1000:
        raise HTTPException(status_code=400, detail="out_of_range")
    pcm = generate_tone(frequency, milliseconds)
    try:
        return await hub.play_pcm(pcm)
    except AudioStreamError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/internal/speak")
async def speak(request: Request):
    """Synthesize text locally and stream it to the physical speaker."""
    _authorize_loopback_admin(request)
    payload = await request.json()
    text = str(payload.get("text", "")).strip()
    if not text or len(text) > 500:
        raise HTTPException(status_code=400, detail="invalid_text")
    audio = await MacSayTTS().synthesize(text)
    # Reject empty synthesis rather than silently "succeeding" with no sound.
    if not audio.data:
        raise HTTPException(status_code=502, detail="tts_produced_no_audio")
    validate_format(audio.sample_rate, audio.channels, audio.sample_width * 8)
    try:
        result = await hub.play_pcm(audio.data)
    except AudioStreamError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    # Remember what was said so the microphone does not act on its own echo.
    utterance_filter.remember_spoken(text)
    return {**result, "text": text}


@app.post("/internal/listen")
async def listen(request: Request):
    """Capture one bounded utterance and transcribe it locally.

    Runs the full input path: half-duplex gating, bounded capture, the noise
    and echo filters, then local recognition. Returns why an utterance was
    rejected rather than silently producing nothing, so a failed listen is
    diagnosable.
    """
    _authorize_loopback_admin(request)
    payload = await request.json() if await request.body() else {}
    milliseconds = int(payload.get("milliseconds", 15000))
    if not 500 <= milliseconds <= 20000:
        raise HTTPException(status_code=400, detail="out_of_range")

    hub.terminal.transition(TerminalState.LISTENING)
    try:
        pcm = await hub.listen(max_milliseconds=milliseconds)
    except AudioStreamError as error:
        hub.terminal.transition(TerminalState.IDLE)
        raise HTTPException(status_code=409, detail=str(error)) from error
    hub.terminal.transition(TerminalState.IDLE)

    audio = PCM16Audio(data=pcm)
    stats = {
        "bytes": len(pcm),
        "durationSeconds": round(
            len(pcm) / (AUDIO_SAMPLE_RATE * 2), 3
        ),
        "rms": round(rms(pcm), 5),
        "voicedFraction": round(voiced_fraction(pcm), 3),
        "peak": peak_level(pcm),
    }
    gate = utterance_filter.check_audio(audio)
    if not gate.accepted:
        return {**stats, "accepted": False, "reason": gate.reason, "transcript": ""}
    text = await stt.transcribe(audio)
    decision = utterance_filter.check_transcript(text)
    return {
        **stats,
        "accepted": decision.accepted,
        "reason": decision.reason,
        "transcript": decision.transcript if decision.accepted else "",
        "rawTranscript": text,
    }


@app.post("/internal/voice-turn")
async def voice_turn(request: Request):
    """Run one complete voice turn: listen, recognise, answer, speak."""
    _authorize_loopback_admin(request)
    payload = await request.json() if await request.body() else {}
    milliseconds = int(payload.get("milliseconds", 6000))
    if not 500 <= milliseconds <= 20000:
        raise HTTPException(status_code=400, detail="out_of_range")
    try:
        turn = await voice_loop.run_turn(listen_milliseconds=milliseconds)
    except AudioStreamError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return turn.public()


@app.get("/firmware/{version}/image")
async def firmware_image(version: str, request: Request):
    """Serve one approved firmware image to the authenticated device.

    Only artifacts that were explicitly published are reachable, and only by a
    device presenting its own credential. The build directory and the wider
    filesystem are never exposed.
    """
    supplied = request.headers.get("authorization", "")
    password = (
        supplied[15:] if supplied.lower().startswith("devicepassword ") else None
    )
    device = authenticate_device(store, password)
    if device is None or device.id != DEVICE_ID:
        logger.warning("Firmware download rejected: unauthorized device")
        raise HTTPException(status_code=401, detail="unauthorized_device")
    try:
        path = firmware_store.image_path(version)
    except FirmwareError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/internal/firmware/releases")
async def firmware_releases(request: Request):
    """List published releases and what the device is currently running."""
    _authorize_loopback_admin(request)
    latest = firmware_store.latest("development")
    current = hub.health.firmware_version
    update_available = bool(
        latest and current and is_newer(latest["manifest"]["version"], current)
    )
    return {
        "current": current,
        "latest": (latest or {}).get("manifest"),
        "updateAvailable": update_available,
        "releases": [r["manifest"] for r in firmware_store.available()],
        "state": hub.ota.public(),
    }


@app.post("/internal/firmware/update")
async def firmware_update(request: Request):
    """Offer an update to the device. Owner-approved, never automatic."""
    _authorize_loopback_admin(request)
    payload = await request.json() if await request.body() else {}
    version = str(payload.get("version", "")).strip()
    force = bool(payload.get("force", False))
    if not version:
        latest = firmware_store.latest("development")
        if latest is None:
            raise HTTPException(status_code=404, detail="no_releases_published")
        version = latest["manifest"]["version"]
    try:
        record = firmware_store.record(version)
    except FirmwareError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    try:
        return await hub.offer_update(record, force=force)
    except AudioStreamError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/internal/visitor")
async def visitor_presence(request: Request):
    """Marks a visitor session open or closed, for the display only.

    Purely visual. Greeting and session deduplication remain owned by the
    front-door state machine; nothing here can cause Jarvis to speak.
    """
    _authorize_loopback_admin(request)
    payload = await request.json() if await request.body() else {}
    await hub.set_visitor_present(bool(payload.get("present", False)))
    return {"visitorPresent": hub.visitor_present, "visual": hub.visual_for_state()}


@app.post("/internal/arc-light")
async def arc_light_settings(request: Request):
    """Owner settings for the physical arc light.

    Brightness and quiet hours live here rather than in firmware constants, so
    adjusting them never needs a rebuild or a reflash.
    """
    _authorize_loopback_admin(request)
    payload = await request.json() if await request.body() else {}
    # Start from the stored preference so a partial request (for example just
    # {"enabled": false}) does not silently reset brightness to defaults.
    current = hub.arc_settings or arc_store.load()
    settings = ArcLightSettings(
        enabled=bool(payload.get("enabled", current.enabled)),
        idle_brightness=int(payload.get("idleBrightness", current.idle_brightness)),
        active_brightness=int(
            payload.get("activeBrightness", current.active_brightness)
        ),
        audio_reactive=bool(payload.get("audioReactive", current.audio_reactive)),
        quiet_hours_start=int(payload.get("quietHoursStart", current.quiet_hours_start)),
        quiet_hours_end=int(payload.get("quietHoursEnd", current.quiet_hours_end)),
    )
    hub.arc_settings = settings
    arc_store.save(settings)
    # Quiet hours are a wall-clock policy, so local time is what the owner
    # means; the timezone is made explicit rather than left naive.
    hour = (int(payload["hour"]) if "hour" in payload
            else datetime.now(UTC).astimezone().hour)
    message = settings.device_message(hour=hour)
    await hub.send("ARC_SETTINGS", **message)
    return {"applied": message, "hour": hour}


@app.websocket("/ws/device")
async def device_gateway(websocket: WebSocket):
    client_ip = websocket.client.host if websocket.client else "unknown"
    if not limiter.allow(client_ip):
        await websocket.close(code=4429, reason="connection_rate_limited")
        return
    authorization = websocket.headers.get("authorization", "")
    password = (
        authorization[15:]
        if authorization.lower().startswith("devicepassword ")
        else None
    )
    device = authenticate_device(store, password)
    if device is None or device.id != "aipi-front-door":
        logger.warning(
            "Device handshake rejected: authorization_present=%s device_password_format=%s length=%d valid=NO",
            "YES" if authorization else "NO",
            "YES" if password is not None else "NO",
            len(password) if password is not None else 0,
        )
        await websocket.close(code=4401, reason="unauthorized_device")
        return
    requested = {
        item.strip()
        for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    }
    if SUBPROTOCOL not in requested:
        logger.warning("Device handshake rejected: subprotocol_present=NO")
        await websocket.close(code=4406, reason="subprotocol_required")
        return
    await websocket.accept(subprotocol=SUBPROTOCOL)
    await hub.attach(websocket, device.id, client_ip)
    reason = "disconnected"
    try:
        while True:
            packet = await websocket.receive()
            if packet.get("type") == "websocket.disconnect":
                break
            raw = packet.get("text")
            if raw is None:
                # Binary frames are microphone audio and are accepted only
                # while a capture the gateway itself requested is open. Outside
                # that window the device has no reason to send bytes, so they
                # are refused rather than parsed.
                payload = packet.get("bytes")
                if payload is None:
                    raise ValueError("empty_frame")
                if len(payload) > AUDIO_MAX_BINARY_FRAME_BYTES:
                    raise ValueError("binary_frame_too_large")
                await hub.receive_binary(payload)
                continue
            if len(raw.encode()) > MAX_CONTROL_BYTES:
                raise ValueError("message_too_large")
            await hub.receive(parse_message(raw))
    except WebSocketDisconnect:
        pass
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        reason = str(error)[:80]
        await websocket.close(code=1008, reason=reason)
    finally:
        await hub.detach(reason, websocket)
