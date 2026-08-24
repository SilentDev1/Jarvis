import contextvars
import json

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from ..config import get_settings
from ..persistence import DeviceAudit, Store, utcnow
from .auth import authenticate_device
from .skills import JarvisStatusSkill

cfg = get_settings()
store = Store(cfg.data_dir / "jarvis.db")
store.init()
current_device = contextvars.ContextVar("current_device", default=None)
status_skill = JarvisStatusSkill(cfg.jarvis_core_url)

mcp = MCPServer(
    "Jarvis Device Gateway",
    instructions=(
        "A narrow physical-device interface to Jarvis Core. Tool results are "
        "authoritative device responses; never invent home or device state."
    ),
)


class StatusResponse(BaseModel):
    ok: bool
    speech: str
    status: str


def audit(device_id: str, request: str, result: dict) -> None:
    with store.Session() as session:
        session.add(
            DeviceAudit(
                device_id=device_id,
                request=request,
                skill="jarvis.status",
                result=json.dumps(result)[:2000],
                response_status="PASS" if result.get("ok") else "FAIL",
                timestamp=utcnow(),
            )
        )
        session.commit()


@mcp.tool(
    name="jarvis.status",
    description="Return the authoritative availability status of Jarvis Core.",
    structured_output=True,
)
async def jarvis_status() -> StatusResponse:
    device = current_device.get()
    if device is None:
        return StatusResponse(
            ok=False,
            speech="This device is not authorized.",
            status="unauthorized",
        )
    result = await status_skill.invoke()
    with store.Session() as session:
        tracked = session.get(type(device), device.id)
        if tracked:
            tracked.last_seen = utcnow()
            tracked.status = "online"
            tracked.updated_at = utcnow()
            session.commit()
    audit(device.id, "status", result)
    return StatusResponse(**result)


class DeviceAuthMiddleware:
    def __init__(self, wrapped, device_store=store):
        self.wrapped = wrapped
        self.device_store = device_store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.wrapped(scope, receive, send)
            return
        headers = {
            key.decode().lower(): value.decode()
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get("authorization", "")
        token = authorization[7:] if authorization.lower().startswith("bearer ") else None
        device = authenticate_device(self.device_store, token)
        if device is None:
            body = b'{"error":"unauthorized_device"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        marker = current_device.set(device)
        try:
            await self.wrapped(scope, receive, send)
        finally:
            current_device.reset(marker)


allowed_hosts = []
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
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
    ),
)
app = DeviceAuthMiddleware(mcp_app)
