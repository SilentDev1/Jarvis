import asyncio
import json
import logging
import math
import secrets
import sys
from array import array
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect

from ..config import get_settings
from ..core.speech import MacSayTTS
from ..persistence import Store
from .audio_stream import AUDIO_SAMPLE_RATE, AudioStreamError, validate_format
from .auth import authenticate_device
from .local_protocol import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_CONTROL_BYTES,
    SUBPROTOCOL,
    ConnectionFloodLimiter,
    LocalDeviceHub,
    parse_message,
)

cfg = get_settings()
store = Store(cfg.data_dir / "jarvis.db")
store.init()
hub = LocalDeviceHub(store)
limiter = ConnectionFloodLimiter()
logger = logging.getLogger("jarvis_home.device_gateway")


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


@asynccontextmanager
async def lifespan(_app):
    hub.mark_offline()
    task = asyncio.create_task(heartbeat_loop())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Jarvis Local Device Gateway", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ready", "device": hub.health.public()}


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
    if not 100 <= frequency <= 4000 or not 100 <= milliseconds <= 5000:
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
    return {**result, "text": text}


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
                raise ValueError("binary_messages_disabled")
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
