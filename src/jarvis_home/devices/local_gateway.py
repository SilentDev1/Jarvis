import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect

from ..config import get_settings
from ..persistence import Store
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
