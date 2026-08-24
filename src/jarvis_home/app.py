import asyncio
import base64
import hashlib
import hmac
import json
import logging
import logging.handlers
import platform
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import psutil
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import get_settings
from .core.events import EventBus
from .core.notifications import format_visitor_notification
from .core.security import sanitize
from .devices.auth import issue_device_token, revoke_device_tokens
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
from .modules.front_door.recognition import OpenCVFaceRecognition
from .modules.front_door.state import VisitorStateMachine
from .modules.front_door.tracking import CentroidTracker
from .modules.front_door.zones import classify, parse_polygon
from .persistence import (
    Badge,
    ConversationTurn,
    Device,
    DeviceAudit,
    DeviceCredential,
    DeviceToolPermission,
    FrontDoorEvent,
    Image,
    KnownPerson,
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
try:
    face_recognition = (
        OpenCVFaceRecognition(
            cfg.face_detection_model,
            cfg.face_recognition_model,
            cfg.face_recognition_threshold,
            cfg.face_possible_threshold,
        )
        if cfg.face_recognition
        else None
    )
except (FileNotFoundError, ImportError, AttributeError):
    face_recognition = None
sessions: dict[str, ConversationState] = {}
tracker = CentroidTracker(
    max_missed=max(3, round(cfg.disappear_grace_seconds * cfg.detection_fps))
)
started = time.time()
metrics = {
    "frames": 0,
    "detections": 0,
    "vision_fps": 0.0,
    "detection_latency_ms": 0.0,
    "last_detection": None,
    "loop_status": "starting",
    "tracks": [],
    "face_recognition_latency_ms": None,
}
zone_path = Path(cfg.data_dir) / "zones.json"
zones_configured = zone_path.exists()


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


FRONT_DOOR_EVENT_TYPES = {
    "person.detected": "PERSON_DETECTED",
    "visitor.face_recognized": "KNOWN_PERSON",
    "visitor.face_unknown": "UNKNOWN_PERSON",
    "visitor.face_insufficient": "UNKNOWN_PERSON",
    "visitor.session_started": "VISITOR_SESSION_STARTED",
    "visitor.departed": "VISITOR_DEPARTED",
    "visitor.badge_captured": "BADGE_CAPTURED",
    "package.detected": "PACKAGE_DETECTED",
    "package.removed": "PACKAGE_REMOVED",
}


def persist_front_door_event(event):
    event_type = FRONT_DOOR_EVENT_TYPES.get(event.type)
    if not event_type:
        return
    payload = event.payload
    safe_metadata = {
        key: payload[key]
        for key in ("zone", "track_id", "face_match_status", "recognized_name")
        if key in payload
    }
    with store.Session() as session:
        session.add(
            FrontDoorEvent(
                event_type=event_type,
                camera_id="tapo-front-door",
                session_id=payload.get("session_id"),
                confidence=payload.get("confidence"),
                known_person_id=payload.get("known_person_id"),
                metadata_json=json.dumps(safe_metadata)[:1000],
                timestamp=event.timestamp,
            )
        )
        session.commit()


bus.subscribe(persist_front_door_event)


def create_session_cookie(expires_at: int) -> str:
    payload = f"{cfg.jarvis_admin_username}:{expires_at}"
    signature = hmac.new(
        cfg.jarvis_admin_token.encode(), payload.encode(), hashlib.sha256
    ).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{expires_at}.{encoded}"


def valid_session_cookie(value: str | None, now: int | None = None) -> bool:
    if not value:
        return False
    try:
        expires_text, supplied = value.split(".", 1)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        return False
    if expires_at < (now if now is not None else int(time.time())):
        return False
    expected = create_session_cookie(expires_at).split(".", 1)[1]
    return secrets.compare_digest(supplied, expected)


async def auth(
    x_jarvis_token: str | None = Header(None),
    jarvis_session: str | None = Cookie(None),
):
    token_ok = secrets.compare_digest(x_jarvis_token or "", cfg.jarvis_admin_token)
    if not token_ok and not valid_session_cookie(jarvis_session):
        raise HTTPException(401, "Admin login required")


class VisitorInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ZoneEvent(BaseModel):
    zone: str | None = None
    now: float | None = None


class ZoneConfiguration(BaseModel):
    observation: list[tuple[float, float]] = Field(min_length=3, max_length=12)
    approach: list[tuple[float, float]] = Field(min_length=3, max_length=12)
    interaction: list[tuple[float, float]] = Field(min_length=3, max_length=12)


class KnownPersonEnrollment(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    session_id: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=40)


class KnownPersonUpdate(BaseModel):
    enabled: bool


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None


def media_path(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    root = cfg.data_dir.resolve()
    candidate = (root / relative_path).resolve()
    return candidate if candidate.is_relative_to(root) else None


async def recognize_visitor(sid: str, image) -> None:
    if face_recognition is None:
        return
    with store.Session() as s:
        people = s.scalars(
            select(KnownPerson).where(KnownPerson.enabled.is_(True))
        ).all()
        candidates = []
        for person in people:
            path = media_path(person.face_data_path)
            if path:
                candidates.append((person.id, person.display_name, path))
    if not candidates:
        return
    started_at = time.perf_counter()
    embedding = await asyncio.to_thread(face_recognition.embedding, image)
    metrics["face_recognition_latency_ms"] = round(
        (time.perf_counter() - started_at) * 1000, 1
    )
    if embedding is None:
        bus.publish(
            "visitor.face_insufficient",
            {
                "session_id": sid,
                "status": "INSUFFICIENT_FACE",
                "face_count": face_recognition.last_face_count,
            },
        )
        return
    match = await asyncio.to_thread(face_recognition.match, embedding, candidates)
    if match is None:
        with store.Session() as s:
            visit = s.get(VisitorSession, sid)
            if visit:
                visit.face_match_status = "UNKNOWN"
                s.commit()
        bus.publish("visitor.face_unknown", {"session_id": sid})
        return
    if match.status == "POSSIBLE_MATCH":
        with store.Session() as s:
            visit = s.get(VisitorSession, sid)
            if visit:
                visit.face_match_status = match.status
                visit.recognition_confidence = match.confidence
                s.commit()
        bus.publish(
            "visitor.face_possible_match",
            {
                "session_id": sid,
                "confidence": round(match.confidence, 3),
                "identity_hint_only": True,
            },
        )
        return
    with store.Session() as s:
        visit = s.get(VisitorSession, sid)
        person = s.get(KnownPerson, match.known_person_id)
        if not visit or not person or not person.enabled:
            return
        visit.known_person_id = person.id
        visit.recognized_name = person.display_name
        visit.recognition_confidence = match.confidence
        visit.face_match_status = match.status
        person.last_seen = utcnow()
        person.match_count = (person.match_count or 0) + 1
        s.commit()
    bus.publish(
        "visitor.face_recognized",
        {
            "session_id": sid,
            "known_person_id": match.known_person_id,
            "display_name": match.display_name,
            "confidence": round(match.confidence, 3),
            "identity_hint_only": True,
        },
    )


async def create_visitor_session(sid: str):
    if sid in sessions:
        return sessions[sid]
    state = ConversationState(sid)
    sessions[sid] = state
    with store.Session() as s:
        if not s.get(VisitorSession, sid):
            s.add(VisitorSession(id=sid, arrival_time=utcnow(), status="active"))
        s.commit()
    await capture_visitor_photo(sid)
    with store.Session() as s:
        visit = s.get(VisitorSession, sid)
        recognized_name = (
            visit.recognized_name
            if visit and visit.face_match_status == "KNOWN_HIGH_CONFIDENCE"
            else None
        )
        if recognized_name:
            state.known_person_name = recognized_name
            state.face_match_status = "KNOWN_HIGH_CONFIDENCE"
    greeting = (
        f"Hi {recognized_name}. How can I help you?"
        if recognized_name
        else "Hello. How can I help you?"
    )
    state.turns.append({"role": "assistant", "content": greeting})
    await voice.speak(greeting)
    with store.Session() as s:
        s.add(
            ConversationTurn(
                session_id=sid, role="assistant", text=greeting, timestamp=utcnow()
            )
        )
        s.commit()
    bus.publish("visitor.session_started", {"session_id": sid})
    bus.publish("jarvis.greeting", {"session_id": sid, "text": greeting})
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
        crop_path = None
        tracks = metrics.get("tracks") or []
        if tracks:
            x1, y1, x2, y2 = tracks[0]["box"]
            height, width = frame.data.shape[:2]
            crop = frame.data[
                max(0, int(y1 * height)) : min(height, int(y2 * height)),
                max(0, int(x1 * width)) : min(width, int(x2 * width)),
            ]
            if crop.size:
                crop_path = cfg.data_dir / "media" / sid / "visitor_crop.jpg"
                save_jpeg(crop, crop_path)
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
            if crop_path:
                s.add(
                    Image(
                        session_id=sid,
                        kind="visitor_crop",
                        path=str(crop_path.relative_to(cfg.data_dir)),
                        timestamp=utcnow(),
                    )
                )
            s.commit()
        bus.publish(
            "visitor.photo_captured",
            {"session_id": sid, "path": str(path.relative_to(cfg.data_dir))},
        )
        await recognize_visitor(sid, frame.data)
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
            detections = tracker.update(detections)
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
            metrics["tracks"] = [
                {
                    "id": item.track_id,
                    "box": item.box,
                    "confidence": round(item.confidence, 3),
                }
                for item in people
            ]
            zone = (
                classify(max(people, key=lambda item: item.confidence).box, zones)
                if people
                else None
            )
            transition = machine.update(
                zone if zones_configured else None, time.monotonic()
            )
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


@app.post("/api/auth/login")
async def login(item: LoginInput):
    username_ok = secrets.compare_digest(item.username, cfg.jarvis_admin_username)
    password_ok = secrets.compare_digest(item.password, cfg.jarvis_admin_password)
    if not username_ok or not password_ok:
        raise HTTPException(401, "Incorrect username or password")
    max_age = cfg.admin_session_days * 24 * 60 * 60
    expires_at = int(time.time()) + max_age
    response = JSONResponse(
        {"status": "authenticated", "username": cfg.jarvis_admin_username}
    )
    response.set_cookie(
        "jarvis_session",
        create_session_cookie(expires_at),
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return response


@app.post("/api/auth/logout")
async def logout():
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie("jarvis_session", path="/", samesite="strict")
    return response


@app.get("/api/auth/session")
async def auth_session(jarvis_session: str | None = Cookie(None)):
    return {
        "authenticated": valid_session_cookie(jarvis_session),
        "username": cfg.jarvis_admin_username
        if valid_session_cookie(jarvis_session)
        else None,
    }


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
        "face_recognition": {
            "enabled": cfg.face_recognition,
            "ready": face_recognition is not None,
            "mode": "local_identity_hint",
        },
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


@app.get("/api/devices", dependencies=[Depends(auth)])
async def devices():
    with store.Session() as s:
        result = []
        for device in s.scalars(select(Device)).all():
            item = {c.name: getattr(device, c.name) for c in Device.__table__.columns}
            item["capabilities"] = json.loads(device.capabilities or "[]")
            item["tools"] = [
                p.tool_name
                for p in s.scalars(
                    select(DeviceToolPermission).where(
                        DeviceToolPermission.device_id == device.id,
                        DeviceToolPermission.enabled.is_(True),
                    )
                ).all()
            ]
            item["credential_count"] = len(
                s.scalars(
                    select(DeviceCredential).where(
                        DeviceCredential.device_id == device.id,
                        DeviceCredential.enabled.is_(True),
                    )
                ).all()
            )
            item["recent_requests"] = [
                {
                    "tool": row.skill,
                    "status": row.response_status,
                    "timestamp": row.timestamp,
                    "duration_ms": row.duration_ms,
                    "error_code": row.error_code,
                }
                for row in s.scalars(
                    select(DeviceAudit)
                    .where(DeviceAudit.device_id == device.id)
                    .order_by(DeviceAudit.timestamp.desc())
                    .limit(5)
                ).all()
            ]
            result.append(item)
        return result


@app.patch("/api/devices/{device_id}", dependencies=[Depends(auth)])
async def update_device(device_id: str, item: DeviceUpdate):
    with store.Session() as session:
        device = session.get(Device, device_id)
        if not device:
            raise HTTPException(404, "Device not found")
        if item.name is not None:
            device.name = sanitize(item.name, 80).strip()
        if item.enabled is not None:
            device.enabled = item.enabled
            device.connection_state = "disabled" if not item.enabled else "unknown"
        device.updated_at = utcnow()
        session.commit()
    if item.enabled is False:
        revoke_device_tokens(store, device_id)
    return {"status": "updated", "device_id": device_id}


@app.post("/api/devices/{device_id}/rotate-token", dependencies=[Depends(auth)])
async def rotate_device_token(device_id: str):
    with store.Session() as session:
        device = session.get(Device, device_id)
        if not device or not device.enabled:
            raise HTTPException(404, "Enabled device not found")
    revoke_device_tokens(store, device_id)
    token = issue_device_token(store, device_id)
    return {
        "status": "rotated",
        "device_id": device_id,
        "token": token,
        "notice": "Shown once. Update the device provider now; Jarvis stores only its hash.",
    }


@app.get("/api/devices/{device_id}/gateway-test", dependencies=[Depends(auth)])
async def device_gateway_test(device_id: str):
    with store.Session() as session:
        device = session.get(Device, device_id)
        if not device:
            raise HTTPException(404, "Device not found")
        credentials = session.scalars(
            select(DeviceCredential).where(
                DeviceCredential.device_id == device_id,
                DeviceCredential.enabled.is_(True),
            )
        ).all()
        tools = session.scalars(
            select(DeviceToolPermission).where(
                DeviceToolPermission.device_id == device_id,
                DeviceToolPermission.enabled.is_(True),
            )
        ).all()
    checks = {
        "registered": True,
        "enabled": device.enabled,
        "credentialConfigured": bool(credentials),
        "toolRegistryConfigured": bool(tools),
        "gatewayProcessReachable": False,
        "physicalRoundTripVerified": False,
    }
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(cfg.device_gateway_host, cfg.device_gateway_port),
            timeout=1,
        )
        checks["gatewayProcessReachable"] = True
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        pass
    software_checks = {
        k: v for k, v in checks.items() if k != "physicalRoundTripVerified"
    }
    return {
        "status": "pass" if all(software_checks.values()) else "partial",
        "checks": checks,
        "notice": "This is a gateway configuration test, not a physical speaker round trip.",
    }


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


@app.get("/api/known-people", dependencies=[Depends(auth)])
async def known_people():
    with store.Session() as s:
        return [
            {
                "id": person.id,
                "display_name": person.display_name,
                "category": person.category,
                "enabled": person.enabled,
                "source_session_id": person.source_session_id,
                "created_at": person.created_at,
                "last_seen": person.last_seen,
                "match_count": person.match_count,
            }
            for person in s.scalars(
                select(KnownPerson).order_by(KnownPerson.display_name)
            ).all()
        ]


@app.post("/api/known-people", dependencies=[Depends(auth)])
async def enroll_known_person(item: KnownPersonEnrollment):
    if face_recognition is None:
        raise HTTPException(503, "Local face recognition is not ready")
    display_name = sanitize(item.display_name, 80).strip()
    if not display_name:
        raise HTTPException(422, "Display name is required")
    with store.Session() as s:
        visit = s.get(VisitorSession, item.session_id)
        photo = media_path(visit.visitor_photo if visit else None)
    if photo is None or not photo.is_file():
        raise HTTPException(404, "Visitor photo not found")
    import cv2

    image = await asyncio.to_thread(cv2.imread, str(photo))
    if image is None:
        raise HTTPException(422, "Visitor photo could not be decoded")
    embedding = await asyncio.to_thread(face_recognition.embedding, image)
    if embedding is None:
        raise HTTPException(422, "No clear face found in this visitor photo")
    with store.Session() as s:
        person = KnownPerson(
            display_name=display_name,
            category=sanitize(item.category, 40) if item.category else None,
            enabled=True,
            source_session_id=item.session_id,
            created_at=utcnow(),
            match_count=0,
        )
        s.add(person)
        s.flush()
        relative = Path("faces") / f"person_{person.id}.npy"
        await asyncio.to_thread(
            face_recognition.save_embedding, embedding, cfg.data_dir / relative
        )
        person.face_data_path = str(relative)
        s.commit()
        person_id = person.id
    bus.publish(
        "known_person.enrolled",
        {"known_person_id": person_id, "display_name": display_name},
    )
    return {"id": person_id, "display_name": display_name, "status": "enrolled"}


@app.patch("/api/known-people/{person_id}", dependencies=[Depends(auth)])
async def update_known_person(person_id: int, item: KnownPersonUpdate):
    with store.Session() as s:
        person = s.get(KnownPerson, person_id)
        if person is None:
            raise HTTPException(404, "Known person not found")
        person.enabled = item.enabled
        s.commit()
    bus.publish(
        "known_person.updated",
        {"known_person_id": person_id, "enabled": item.enabled},
    )
    return {"id": person_id, "enabled": item.enabled}


@app.post("/api/face-recognition/test-current", dependencies=[Depends(auth)])
async def test_current_face():
    """Test the current frame without enrolling or retaining a new biometric."""
    if face_recognition is None:
        raise HTTPException(503, "Local face recognition is not ready")
    frame = await camera.snapshot(high_quality=True)
    if frame is None or frame.data is None:
        raise HTTPException(503, "Camera frame unavailable")
    started_at = time.perf_counter()
    embedding = await asyncio.to_thread(face_recognition.embedding, frame.data)
    detect_ms = round((time.perf_counter() - started_at) * 1000, 1)
    if embedding is None:
        return {
            "face_detected": False,
            "face_count": face_recognition.last_face_count,
            "decision": "INSUFFICIENT_FACE",
            "latency_ms": detect_ms,
            "retained": False,
        }
    with store.Session() as s:
        people = s.scalars(
            select(KnownPerson).where(KnownPerson.enabled.is_(True))
        ).all()
        candidates = [
            (person.id, person.display_name, path)
            for person in people
            if (path := media_path(person.face_data_path)) is not None
        ]
    match = await asyncio.to_thread(face_recognition.match, embedding, candidates)
    return {
        "face_detected": True,
        "face_count": face_recognition.last_face_count,
        "best_match": match.display_name if match else None,
        "confidence": round(match.confidence, 3) if match else None,
        "decision": match.status if match else "UNKNOWN",
        "latency_ms": detect_ms,
        "retained": False,
    }


@app.delete("/api/known-people/{person_id}", dependencies=[Depends(auth)])
async def delete_known_person(person_id: int):
    with store.Session() as s:
        person = s.get(KnownPerson, person_id)
        if person is None:
            raise HTTPException(404, "Known person not found")
        embedding_path = media_path(person.face_data_path)
        for visit in s.scalars(
            select(VisitorSession).where(VisitorSession.known_person_id == person_id)
        ).all():
            visit.known_person_id = None
            visit.recognized_name = None
            visit.recognition_confidence = None
        name = person.display_name
        s.delete(person)
        s.commit()
    if embedding_path and embedding_path.is_file():
        embedding_path.unlink()
    bus.publish("known_person.deleted", {"known_person_id": person_id})
    return {"id": person_id, "display_name": name, "status": "deleted"}


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
        "zones_configured": zones_configured,
        "face_recognition": {
            "enabled": cfg.face_recognition,
            "ready": face_recognition is not None,
            "mode": "local_identity_hint",
        },
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

    image = image.copy()
    height, width = image.shape[:2]
    colors = {
        "observation": (255, 200, 92),
        "approach": (97, 191, 245),
        "interaction": (170, 230, 101),
    }
    for name, polygon in zones.items():
        points = np.array([(round(x * width), round(y * height)) for x, y in polygon])
        cv2.polylines(image, [points], True, colors[name], 2)
        if len(points):
            cv2.putText(
                image,
                name,
                tuple(points[0]),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                colors[name],
                2,
            )
    for track in metrics.get("tracks", []):
        x1, y1, x2, y2 = track["box"]
        start = (round(x1 * width), round(y1 * height))
        end = (round(x2 * width), round(y2 * height))
        cv2.rectangle(image, start, end, (101, 230, 170), 2)
        cv2.putText(
            image,
            f"person #{track['id']} {track['confidence']:.0%}",
            (start[0], max(20, start[1] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (101, 230, 170),
            2,
        )
    cv2.putText(
        image,
        f"state: {machine.phase}",
        (18, height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )
    if not zones_configured:
        cv2.putText(
            image,
            "ZONES NOT SAVED - SESSION TRIGGERS DISABLED",
            (18, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 190, 255),
            2,
        )
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
    global zones, zones_configured
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
    zones_configured = True
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
