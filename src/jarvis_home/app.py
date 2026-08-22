import json
import logging
import logging.handlers
import platform
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import get_settings
from .core.events import EventBus
from .core.security import sanitize
from .integrations.providers import (
    LogNotification,
    MockVision,
    OllamaAI,
    SimulatorVoice,
    TapoCamera,
    TestCamera,
    YoloVision,
)
from .modules.front_door.conversation import (
    SYSTEM,
    ConversationState,
    apply_result,
    deterministic_reply,
)
from .modules.front_door.state import VisitorStateMachine
from .persistence import (
    ConversationTurn,
    Device,
    Store,
    VisitorSession,
    utcnow,
)

cfg = get_settings()
bus = EventBus()
store = Store(cfg.data_dir / "jarvis.db")
logger = logging.getLogger("jarvis_home")
machine = VisitorStateMachine(
    cfg.dwell_seconds,
    cfg.disappear_grace_seconds,
    cfg.greeting_cooldown_seconds,
    cfg.session_timeout_seconds,
)
camera = (
    TestCamera()
    if cfg.camera_mode == "test"
    else TapoCamera(cfg.rtsp_url(), cfg.rtsp_url(True))
)
try:
    vision = (
        YoloVision(cfg.vision_model, cfg.detection_confidence)
        if cfg.vision_provider == "yolo"
        else MockVision()
    )
except Exception:  # noqa: BLE001 - optional provider import/model failures must degrade safely
    vision = MockVision()
ai = OllamaAI(cfg.ollama_url, cfg.ollama_model)
voice = SimulatorVoice()
notifier = LogNotification(bus)
sessions: dict[str, ConversationState] = {}
started = time.time()


def setup_logging():
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(
        cfg.log_dir / "jarvis.log", maxBytes=5_000_000, backupCount=5
    )
    h.setFormatter(
        logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","message":%(message)r}'
        )
    )
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)


def persist_event(event):
    try:
        store.event(event.type, json.dumps(event.payload)[:2000])
    except Exception:
        logger.exception("event persistence failed")


bus.subscribe(persist_event)


async def auth(x_jarvis_token: str | None = Header(None)):
    if not secrets.compare_digest(x_jarvis_token or "", cfg.jarvis_admin_token):
        raise HTTPException(401, "Valid X-Jarvis-Token required")


class VisitorInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ZoneEvent(BaseModel):
    zone: str | None = None
    now: float | None = None


@asynccontextmanager
async def lifespan(app):
    setup_logging()
    store.init()
    bus.publish("system.started", {"version": "0.1.0"})
    yield
    bus.publish("system.stopped")


app = FastAPI(title="Jarvis Home", version="0.1.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return (Path(__file__).parent / "static" / "index.html").read_text()


@app.get("/health")
async def health():
    return {
        "status": "ready",
        "core": "ready",
        "uptime_seconds": round(time.time() - started),
        "host": platform.node(),
        "front_door": "active",
    }


@app.get("/health/camera")
async def health_camera():
    return camera.health()


@app.get("/health/ai")
async def health_ai():
    return await ai.health()


@app.get("/health/database")
async def health_db():
    try:
        with store.Session() as s:
            s.execute(select(1))
        return {
            "status": "ready",
            "engine": "sqlite",
            "path": str(cfg.data_dir / "jarvis.db"),
        }
    except Exception as e:  # noqa: BLE001 - health endpoints report, rather than raise, failures
        return {"status": "error", "detail": type(e).__name__}


@app.get("/health/devices")
async def health_devices():
    return {
        "status": "ready",
        "camera": camera.health(),
        "voice": voice.health(),
        "aipi": "waiting_for_hardware",
    }


@app.get("/api/system")
async def system():
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(cfg.data_dir)
    return {
        "current_host": platform.node(),
        "host_role": "current compute host (portable)",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_percent": psutil.cpu_percent(),
        "ram_total": vm.total,
        "ram_percent": vm.percent,
        "disk_total": du.total,
        "disk_free": du.free,
        "uptime_seconds": round(time.time() - started),
        "config": cfg.public(),
    }


@app.get("/api/devices")
async def devices():
    with store.Session() as s:
        return [
            {c.name: getattr(d, c.name) for c in Device.__table__.columns}
            for d in s.scalars(select(Device)).all()
        ]


@app.get("/api/events")
async def events(limit: int = 50):
    return [e.dict() for e in list(bus.history)[: min(limit, 200)]]


@app.get("/api/visitors")
async def visitors():
    with store.Session() as s:
        return [
            {c.name: getattr(v, c.name) for c in VisitorSession.__table__.columns}
            for v in s.scalars(
                select(VisitorSession)
                .order_by(VisitorSession.arrival_time.desc())
                .limit(100)
            ).all()
        ]


@app.get("/api/front-door")
async def front_door():
    return {
        "phase": machine.phase,
        "session_id": machine.session_id,
        "camera": camera.health(),
        "vision_provider": type(vision).__name__,
        "voice": voice.health(),
        "active_session": sessions.get(machine.session_id).public()
        if machine.session_id in sessions
        else None,
    }


@app.post("/api/simulator/start", dependencies=[Depends(auth)])
async def sim_start():
    now = time.monotonic()
    machine.update("interaction", now)
    t = machine.update("interaction", now + cfg.dwell_seconds + 0.01)
    sid = t.session_id or machine.session_id
    if not sid:
        raise HTTPException(409, "Cooldown active")
    state = ConversationState(sid)
    sessions[sid] = state
    state.turns.append({"role": "assistant", "content": "Hello. How can I help you?"})
    await voice.speak(state.turns[-1]["content"])
    with store.Session() as s:
        s.add(VisitorSession(id=sid, arrival_time=utcnow(), status="active"))
        s.add(
            ConversationTurn(
                session_id=sid,
                role="assistant",
                text=state.turns[-1]["content"],
                timestamp=utcnow(),
            )
        )
        s.commit()
    bus.publish("visitor.session_started", {"session_id": sid})
    bus.publish("jarvis.greeting", {"session_id": sid})
    return {
        "session_id": sid,
        "reply": state.turns[-1]["content"],
        "state": state.public(),
    }


@app.post("/api/simulator/{sid}/say", dependencies=[Depends(auth)])
async def sim_say(sid: str, item: VisitorInput):
    state = sessions.get(sid)
    if not state:
        raise HTTPException(404, "No active visitor session")
    text = sanitize(item.text)
    state.turns.append({"role": "user", "content": text})
    bus.publish("visitor.spoke", {"session_id": sid, "text": text})
    t0 = time.perf_counter()
    try:
        result = await ai.respond(SYSTEM, state.turns, state.public())
        provider = "ollama"
    except Exception:  # noqa: BLE001 - deterministic fallback is the resilience boundary
        result = deterministic_reply(state, text)
        provider = "safe_fallback"
    result = apply_result(state, result)
    reply = sanitize(
        result.get(
            "reply", "I'm having trouble right now. I've notified the homeowner."
        ),
        300,
    )
    state.turns.append({"role": "assistant", "content": reply})
    await voice.speak(reply)
    if result["action"] == "request_badge":
        machine.request_badge()
        bus.publish("visitor.badge_requested", {"session_id": sid})
    if result["action"] in {"notify_homeowner", "mark_delivery"}:
        await notifier.send(
            "Visitor at Front Door",
            f"Name: {state.visitor_name or 'Not provided'}\nCompany claimed: {state.claimed_company or 'Not provided'}\nReason: {state.reason or state.visitor_type}",
        )
    with store.Session() as s:
        db = s.get(VisitorSession, sid)
        db.name = state.visitor_name
        db.claimed_company = state.claimed_company
        db.reason = state.reason
        db.visitor_type = state.visitor_type
        s.add(
            ConversationTurn(session_id=sid, role="user", text=text, timestamp=utcnow())
        )
        s.add(
            ConversationTurn(
                session_id=sid, role="assistant", text=reply, timestamp=utcnow()
            )
        )
        s.commit()
    bus.publish(
        "jarvis.spoke", {"session_id": sid, "reply": reply, "provider": provider}
    )
    return {
        "reply": reply,
        "action": result["action"],
        "provider": provider,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "state": state.public(),
    }


@app.post("/api/simulator/{sid}/end", dependencies=[Depends(auth)])
async def sim_end(sid: str):
    state = sessions.pop(sid, None)
    if not state:
        raise HTTPException(404, "No active visitor session")
    machine.complete(time.monotonic())
    state.status = "complete"
    with store.Session() as s:
        db = s.get(VisitorSession, sid)
        db.status = "complete"
        db.departure_time = utcnow()
        db.conversation_summary = (
            f"{state.visitor_type}: {state.reason or 'reason not provided'}"
        )
        s.commit()
    bus.publish("visitor.departed", {"session_id": sid})
    bus.publish("session.completed", {"session_id": sid})
    return {"status": "complete"}


@app.post("/api/test/zone", dependencies=[Depends(auth)])
async def zone_event(item: ZoneEvent):
    t = machine.update(
        item.zone, item.now if item.now is not None else time.monotonic()
    )
    if t.event:
        bus.publish(t.event, {"session_id": t.session_id})
    return {"phase": t.phase, "event": t.event, "session_id": t.session_id}
