import contextvars
import json
import time
from collections import defaultdict, deque

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from sqlalchemy import select

from ..config import get_settings
from ..persistence import Device, DeviceAudit, DeviceToolPermission, Store, utcnow
from .auth import authenticate_device
from .skills import FrontDoorRecentSkill, FrontDoorStatusSkill, JarvisStatusSkill

cfg = get_settings()
store = Store(cfg.data_dir / "jarvis.db")
store.init()
current_device = contextvars.ContextVar("current_device", default=None)
status_skill = JarvisStatusSkill(cfg.jarvis_core_url)
front_door_skill = FrontDoorStatusSkill(cfg.jarvis_core_url, store)
recent_skill = FrontDoorRecentSkill(store)

mcp = MCPServer(
    "Jarvis Device Gateway",
    instructions=(
        "This is the homeowner's authoritative, narrow Jarvis interface. Always call "
        "the matching Jarvis tool for status, current front-door state, or recent "
        "front-door activity. Speak exactly the returned speech field. Never invent "
        "home state, identity, package state, access, or successful actions."
    ),
)


class StatusResponse(BaseModel):
    ok: bool
    speech: str
    status: str


class FrontDoorStatusResponse(BaseModel):
    ok: bool
    speech: str
    status: str
    cameraOnline: bool | None = None
    presence: str | None = None
    personPresent: bool | None = None
    personCount: int | None = None
    identityStatus: str | None = None
    knownPerson: str | None = None
    faceConfidence: float | None = None
    packagePresent: bool | None = None
    packageDetectionAvailable: bool = False
    lastDetectionTime: float | None = None
    observedAt: str | None = None
    ageMs: int | None = None
    source: str | None = None
    visitorType: str | None = None
    companyClaimed: str | None = None
    uniformDetected: bool | None = None
    badgeDetected: bool | None = None
    evidenceNotice: str | None = None


class RecentResponse(BaseModel):
    ok: bool
    speech: str
    status: str
    windowHours: int
    events: list[dict]
    bounded: bool


def permitted(device_id: str, tool_name: str) -> bool:
    with store.Session() as session:
        return (
            session.scalar(
                select(DeviceToolPermission).where(
                    DeviceToolPermission.device_id == device_id,
                    DeviceToolPermission.tool_name == tool_name,
                    DeviceToolPermission.enabled.is_(True),
                )
            )
            is not None
        )


def audit(device_id: str, tool_name: str, result: dict, duration_ms: float) -> None:
    passed = bool(result.get("ok"))
    now = utcnow()
    with store.Session() as session:
        session.add(
            DeviceAudit(
                device_id=device_id,
                request=tool_name,
                skill=tool_name,
                result=json.dumps(result, default=str)[:2000],
                response_status="PASS" if passed else "FAIL",
                timestamp=now,
                duration_ms=round(duration_ms, 2),
                error_code=None if passed else result.get("status", "provider_failure"),
            )
        )
        tracked = session.get(Device, device_id)
        if tracked:
            tracked.last_seen = now
            tracked.status = "online" if passed else "degraded"
            tracked.connection_state = "connected" if passed else "request_failed"
            if passed:
                tracked.last_successful_request = now
            else:
                tracked.last_failed_request = now
            tracked.updated_at = now
        session.commit()


async def invoke(tool_name: str, skill) -> dict:
    device = current_device.get()
    if device is None:
        return {
            "ok": False,
            "speech": "This device is not authorized.",
            "status": "unauthorized",
        }
    started = time.monotonic()
    if not permitted(device.id, tool_name):
        result = {
            "ok": False,
            "speech": "This device is not permitted to use that capability.",
            "status": "forbidden",
        }
    elif not duplicate_guard.allow(device.id, tool_name):
        result = {
            **duplicate_results.get((device.id, tool_name), {"ok": True}),
            "speech": "",
            "status": "duplicate_suppressed",
        }
    else:
        result = await skill.invoke()
        duplicate_results[(device.id, tool_name)] = dict(result)
    audit(device.id, tool_name, result, (time.monotonic() - started) * 1000)
    return result


@mcp.tool(
    name="jarvis.status",
    description="MUST be called for any question asking whether Jarvis is online, ready, available, or running. Return Jarvis Core's authoritative status and speak exactly speech.",
    structured_output=True,
)
async def jarvis_status() -> StatusResponse:
    return StatusResponse(**await invoke("jarvis.status", status_skill))


@mcp.tool(
    name="jarvis.frontDoor.status",
    description="MUST be called for current questions about the front door, who or how many people are there, whether someone is recognized, camera state, or a package. Never infer identity or package state beyond this result; speak exactly speech.",
    structured_output=True,
)
async def jarvis_front_door_status() -> FrontDoorStatusResponse:
    return FrontDoorStatusResponse(
        **await invoke("jarvis.frontDoor.status", front_door_skill)
    )


@mcp.tool(
    name="jarvis.frontDoor.recent",
    description="MUST be called for recent or latest front-door activity. Returns at most five sanitized events from the last 24 hours. Speak exactly speech and do not invent omitted details.",
    structured_output=True,
)
async def jarvis_front_door_recent() -> RecentResponse:
    return RecentResponse(**await invoke("jarvis.frontDoor.recent", recent_skill))


class DeviceRateLimiter:
    def __init__(self, limit=30, window_seconds=60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        bucket = self.requests[key]
        while bucket and bucket[0] <= now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


class DuplicateRequestGuard:
    def __init__(self, window_seconds=4):
        self.window_seconds = window_seconds
        self.last_request = {}

    def allow(self, device_id: str, tool_name: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        key = (device_id, tool_name)
        previous = self.last_request.get(key)
        self.last_request[key] = now
        return previous is None or now - previous >= self.window_seconds


duplicate_guard = DuplicateRequestGuard()
duplicate_results: dict[tuple[str, str], dict] = {}


class DeviceAuthMiddleware:
    def __init__(self, wrapped, device_store=store, max_body_bytes=65536, limiter=None):
        self.wrapped = wrapped
        self.device_store = device_store
        self.max_body_bytes = max_body_bytes
        self.limiter = limiter or DeviceRateLimiter()

    async def _reject(self, send, status, error):
        body = json.dumps({"error": error}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.wrapped(scope, receive, send)
            return
        headers = {
            key.decode().lower(): value.decode()
            for key, value in scope.get("headers", [])
        }
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            await self._reject(send, 400, "invalid_content_length")
            return
        if content_length > self.max_body_bytes:
            await self._reject(send, 413, "request_too_large")
            return
        buffered = []
        total = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_body_bytes:
                    await self._reject(send, 413, "request_too_large")
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        async def replay_receive():
            if buffered:
                return buffered.pop(0)
            return await receive()

        authorization = headers.get("authorization", "")
        token = (
            authorization[7:] if authorization.lower().startswith("bearer ") else None
        )
        device = authenticate_device(self.device_store, token)
        if device is None:
            await self._reject(send, 401, "unauthorized_device")
            return
        if not self.limiter.allow(device.id):
            await self._reject(send, 429, "rate_limit_exceeded")
            return
        marker = current_device.set(device)
        try:
            await self.wrapped(scope, replay_receive, send)
        finally:
            current_device.reset(marker)


allowed_hosts: list[str] = []
for configured_host in cfg.mcp_allowed_hosts.split(","):
    configured_host = configured_host.strip()
    if configured_host:
        allowed_hosts.extend(
            (configured_host, f"{configured_host}:{cfg.device_gateway_port}")
        )

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts
    ),
)
app = DeviceAuthMiddleware(mcp_app)
