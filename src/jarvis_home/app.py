import asyncio
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
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import get_settings
from .core.events import EventBus
from .core.notifications import format_visitor_notification
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
    enforce_policy,
)
from .modules.front_door.media import (
    capture_burst,
    run_ocr,
    save_jpeg,
    select_sharpest,
)
from .modules.front_door.state import VisitorStateMachine
from .modules.front_door.zones import classify, parse_polygon
from .persistence import (
    Badge,
    ConversationTurn,
    Device,
    Image,
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
metrics = {
    "frames": 0,
    "detections": 0,
    "vision_fps": 0.0,
    "detection_latency_ms": 0.0,
    "last_detection": None,
    "loop_status": "starting",
}
zone_path = Path(cfg.data_dir) / "zones.json"


def default_zones():
    return {
        "observation": parse_polygon(cfg.zone_observation),
        "approach": parse_polygon(cfg.zone_approach),
        "interaction": parse_polygon(cfg.zone_interaction),
    }


def load_zones():
    if zone_path.exists():
        try:
            data = json.loads(zone_path.read_text())
            return {
                name: [tuple(point) for point in data[name]] for name in default_zones()
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning(
                "Invalid saved zone configuration; using environment defaults"
            )
    return default_zones()


zones = load_zones()


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


class ZoneConfiguration(BaseModel):
    observation: list[tuple[float, float]] = Field(min_length=3, max_length=12)
    approach: list[tuple[float, float]] = Field(min_length=3, max_length=12)
    interaction: list[tuple[float, float]] = Field(min_length=3, max_length=12)


async def create_visitor_session(sid: str):
    if sid in sessions:
        return sessions[sid]
    state = ConversationState(sid)
    sessions[sid] = state
    greeting = "Hello. How can I help you?"
    state.turns.append({"role": "assistant", "content": greeting})
    await voice.speak(greeting)
    with store.Session() as s:
        if not s.get(VisitorSession, sid):
            s.add(VisitorSession(id=sid, arrival_time=utcnow(), status="active"))
        s.add(
            ConversationTurn(
                session_id=sid, role="assistant", text=greeting, timestamp=utcnow()
            )
        )
        s.commit()
    bus.publish("visitor.session_started", {"session_id": sid})
    bus.publish("jarvis.greeting", {"session_id": sid, "text": greeting})
    asyncio.create_task(capture_visitor_photo(sid))
    return state


async def capture_visitor_photo(sid: str):
    frame = await camera.snapshot(high_quality=True)
    if frame is None or frame.data is None:
        bus.publish(
            "system.warning",
            {"component": "visitor_photo", "reason": "snapshot unavailable"},
        )
        return None
    path = cfg.data_dir / "media" / sid / "visitor_full.jpg"
    try:
        save_jpeg(frame.data, path)
        with store.Session() as s:
            db = s.get(VisitorSession, sid)
            if db:
                db.visitor_photo = str(path.relative_to(cfg.data_dir))
            s.add(
                Image(
                    session_id=sid,
                    kind="visitor_full",
                    path=str(path.relative_to(cfg.data_dir)),
                    timestamp=utcnow(),
                )
            )
            s.commit()
        bus.publish(
            "visitor.photo_captured",
            {"session_id": sid, "path": str(path.relative_to(cfg.data_dir))},
        )
        return path
    except (OSError, ValueError):
        logger.exception("Visitor snapshot failed")
        return None


async def capture_badge(sid: str):
    frames = await capture_burst(camera, seconds=3.0)
    image, quality = select_sharpest(frames)
    if image is None:
        bus.publish(
            "system.warning",
            {"component": "badge", "reason": "no decodable main-stream frames"},
        )
        return
    path = cfg.data_dir / "media" / sid / "badge_best.jpg"
    save_jpeg(image, path)
    try:
        result = await run_ocr(image)
    except (ImportError, RuntimeError, OSError):
        logger.exception("Badge OCR failed")
        result = None
    with store.Session() as s:
        db = s.get(VisitorSession, sid)
        if db:
            db.badge_photo = str(path.relative_to(cfg.data_dir))
            db.badge_ocr = result.text if result else None
        s.add(
            Badge(
                session_id=sid,
                image_path=str(path.relative_to(cfg.data_dir)),
                ocr_text=result.text if result else None,
                confidence=result.confidence if result else 0,
                name_candidate=result.name_candidate if result else None,
                company_candidate=result.company_candidate if result else None,
                timestamp=utcnow(),
            )
        )
        s.commit()
    bus.publish(
        "visitor.badge_captured",
        {
            "session_id": sid,
            "path": str(path.relative_to(cfg.data_dir)),
            "sharpness": round(quality, 1),
            "ocr_text": result.text if result else "",
            "ocr_confidence": round(result.confidence, 1) if result else 0,
            "evidence_only": True,
        },
    )


async def live_vision_loop():
    window_started = time.monotonic()
    window_inferences = 0
    last_inference = 0.0
    previous_zone = None
    previous_present = False
    metrics["loop_status"] = "running"
    try:
        async for frame in camera.frames():
            metrics["frames"] += 1
            now = time.monotonic()
            if now - last_inference < 1 / cfg.detection_fps:
                continue
            last_inference = now
            t0 = time.perf_counter()
            detections = await vision.detect(frame)
            window_inferences += 1
            metrics["detection_latency_ms"] = round(
                (time.perf_counter() - t0) * 1000, 1
            )
            if cfg.camera_mode == "test":
                elapsed = time.monotonic() - window_started
                if elapsed >= 5:
                    metrics["vision_fps"] = round(window_inferences / elapsed, 2)
                    window_started = time.monotonic()
                    window_inferences = 0
                continue
            people = [item for item in detections if item.label == "person"]
            zone = (
                classify(max(people, key=lambda item: item.confidence).box, zones)
                if people
                else None
            )
            transition = machine.update(zone, time.monotonic())
            if people:
                metrics["detections"] += 1
                metrics["last_detection"] = time.time()
                if not previous_present:
                    bus.publish("person.detected", {"count": len(people), "zone": zone})
                if zone != previous_zone:
                    bus.publish("person.entered_zone", {"zone": zone})
            previous_present = bool(people)
            previous_zone = zone
            if transition.event:
                bus.publish(transition.event, {"session_id": transition.session_id})
                if (
                    transition.event == "visitor.session_started"
                    and transition.session_id
                ):
                    await create_visitor_session(transition.session_id)
                elif (
                    transition.event in {"visitor.departed", "session.timeout"}
                    and transition.session_id in sessions
                ):
                    await complete_session(transition.session_id)
            elapsed = time.monotonic() - window_started
            if elapsed >= 5:
                metrics["vision_fps"] = round(window_inferences / elapsed, 2)
                window_started = time.monotonic()
                window_inferences = 0
    except asyncio.CancelledError:
        raise
    except Exception:
        metrics["loop_status"] = "error"
        logger.exception("Live vision loop stopped")
        bus.publish("system.error", {"component": "vision_loop"})


async def complete_session(sid: str):
    state = sessions.pop(sid, None)
    if not state:
        return
    state.status = "complete"
    with store.Session() as s:
        db = s.get(VisitorSession, sid)
        if db:
            db.status = "complete"
            db.departure_time = utcnow()
            db.conversation_summary = (
                f"{state.visitor_type}: {state.reason or 'reason not provided'}"
            )
        badge = s.scalar(select(Badge).where(Badge.session_id == sid).limit(1))
        s.commit()
        if db:
            await notifier.send(
                "Visitor at Front Door",
                format_visitor_notification(db, bool(badge)),
                db.visitor_photo,
            )
    bus.publish("session.completed", {"session_id": sid})


@asynccontextmanager
async def lifespan(app):
    setup_logging()
    store.init()
    bus.publish("system.started", {"version": "0.1.0"})
    vision_task = asyncio.create_task(live_vision_loop())
    yield
    vision_task.cancel()
    await asyncio.gather(vision_task, return_exceptions=True)
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
    return {**camera.health(), "vision": metrics}


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
        "vision": metrics,
        "zones": zones,
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
    state = await create_visitor_session(sid)
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
    result = enforce_policy(state, text, result)
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
        asyncio.create_task(capture_badge(sid))
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
    if sid not in sessions:
        raise HTTPException(404, "No active visitor session")
    machine.complete(time.monotonic())
    await complete_session(sid)
    bus.publish("visitor.departed", {"session_id": sid})
    bus.publish("session.completed", {"session_id": sid})
    return {"status": "complete"}


@app.get("/api/front-door/preview.jpg")
async def camera_preview():
    image = getattr(camera, "last_image", None)
    if image is None:
        frame = await camera.snapshot(high_quality=False)
        image = frame.data if frame is not None else None
    if image is None:
        raise HTTPException(503, "Camera frame unavailable")
    import cv2

    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise HTTPException(500, "Frame encoding failed")
    return Response(
        encoded.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/front-door/zones")
async def get_zone_configuration():
    return zones


@app.put("/api/front-door/zones", dependencies=[Depends(auth)])
async def save_zone_configuration(item: ZoneConfiguration):
    global zones
    data = item.model_dump()
    if any(
        not 0 <= value <= 1
        for polygon in data.values()
        for point in polygon
        for value in point
    ):
        raise HTTPException(422, "Zone coordinates must be normalized from 0 to 1")
    zones = {
        name: [tuple(point) for point in polygon] for name, polygon in data.items()
    }
    zone_path.parent.mkdir(parents=True, exist_ok=True)
    zone_path.write_text(json.dumps(data, indent=2))
    bus.publish("front_door.zones_updated", {"path": str(zone_path)})
    return zones


@app.post("/api/test/zone", dependencies=[Depends(auth)])
async def zone_event(item: ZoneEvent):
    t = machine.update(
        item.zone, item.now if item.now is not None else time.monotonic()
    )
    if t.event:
        bus.publish(t.event, {"session_id": t.session_id})
    return {"phase": t.phase, "event": t.event, "session_id": t.session_id}
