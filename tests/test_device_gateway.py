import json

import httpx
import pytest
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from jarvis_home.devices.auth import (
    authenticate_device,
    issue_device_token,
    revoke_device_tokens,
)
from jarvis_home.devices.mcp_gateway import (
    DeviceAuthMiddleware,
    DeviceRateLimiter,
    DuplicateRequestGuard,
)
from jarvis_home.devices.skills import (
    FrontDoorRecentSkill,
    FrontDoorStatusSkill,
    JarvisStatusSkill,
)
from jarvis_home.persistence import (
    Device,
    DeviceToolPermission,
    FrontDoorEvent,
    Store,
    VisitorSession,
    utcnow,
)


@pytest.fixture
def device_store(tmp_path):
    store = Store(tmp_path / "jarvis.db")
    store.init()
    return store


def test_device_token_authentication_and_revocation(device_store):
    token = issue_device_token(device_store, "aipi-front-door")
    device = authenticate_device(device_store, token)
    assert device.id == "aipi-front-door"
    assert authenticate_device(device_store, "wrong") is None
    assert revoke_device_tokens(device_store, device.id) == 1
    assert authenticate_device(device_store, token) is None


def test_disabled_device_is_blocked(device_store):
    token = issue_device_token(device_store, "aipi-front-door")
    with device_store.Session() as session:
        device = session.get(Device, "aipi-front-door")
        device.enabled = False
        session.commit()
    assert authenticate_device(device_store, token) is None


def test_gateway_requires_device_authorization(device_store):
    async def endpoint(_request):
        return JSONResponse({"ok": True})

    wrapped = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    app = DeviceAuthMiddleware(wrapped, device_store)
    token = issue_device_token(device_store, "aipi-front-door")
    with TestClient(app) as client:
        assert client.post("/mcp").status_code == 401
        response = client.post("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_gateway_rejects_oversized_requests(device_store):
    async def endpoint(_request):
        return JSONResponse({"ok": True})

    wrapped = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    app = DeviceAuthMiddleware(wrapped, device_store, max_body_bytes=4)
    token = issue_device_token(device_store, "aipi-front-door")
    with TestClient(app) as client:
        response = client.post(
            "/mcp", content="12345", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 413


def test_rate_limiter_is_bounded_and_recovers():
    limiter = DeviceRateLimiter(limit=2, window_seconds=10)
    assert limiter.allow("device", now=0)
    assert limiter.allow("device", now=1)
    assert not limiter.allow("device", now=2)
    assert limiter.allow("device", now=11)


def test_duplicate_tool_request_is_suppressed_but_other_tool_is_allowed():
    guard = DuplicateRequestGuard(window_seconds=4)
    assert guard.allow("device", "jarvis.status", now=10)
    assert not guard.allow("device", "jarvis.status", now=12)
    assert guard.allow("device", "jarvis.frontDoor.status", now=12)
    assert guard.allow("device", "jarvis.status", now=17)


@pytest.mark.asyncio
async def test_status_skill_reports_core_state():
    def handler(request):
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ready"})

    skill = JarvisStatusSkill(
        "http://jarvis.test", transport=httpx.MockTransport(handler)
    )
    result = await skill.invoke()
    assert result["speech"] == "Jarvis is online."


@pytest.mark.asyncio
async def test_status_skill_handles_provider_failure():
    def handler(_request):
        raise httpx.ConnectError("offline")

    skill = JarvisStatusSkill(
        "http://jarvis.test", transport=httpx.MockTransport(handler)
    )
    result = await skill.invoke()
    assert result == {
        "ok": False,
        "speech": "Jarvis Core is temporarily unavailable.",
        "status": "provider_failure",
    }


@pytest.mark.asyncio
async def test_front_door_status_does_not_invent_identity_or_package(device_store):
    def handler(request):
        assert request.url.path == "/api/front-door"
        return httpx.Response(
            200,
            json={
                "camera": {"connected": True},
                "vision": {"tracks": [{"id": 1}], "last_detection": 123.0},
                "presence": {
                    "state": "PRESENT",
                    "person_count": 1,
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "age_ms": 200,
                    "source": "live_detection",
                },
                "session_id": None,
            },
        )

    result = await FrontDoorStatusSkill(
        "http://jarvis.test", device_store, transport=httpx.MockTransport(handler)
    ).invoke()
    assert result["identityStatus"] == "UNKNOWN"
    assert result["knownPerson"] is None
    assert result["packageDetectionAvailable"] is False
    assert result["packagePresent"] is None


@pytest.mark.asyncio
async def test_front_door_status_reports_camera_offline(device_store):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "camera": {"connected": False},
                "vision": {"tracks": []},
                "presence": {"state": "UNKNOWN", "source": "camera_offline"},
            },
        )

    result = await FrontDoorStatusSkill(
        "http://jarvis.test", device_store, transport=httpx.MockTransport(handler)
    ).invoke()
    assert result["status"] == "presence_unknown"
    assert result["personPresent"] is None


@pytest.mark.asyncio
async def test_front_door_status_uses_only_high_confidence_known_name(device_store):
    with device_store.Session() as session:
        session.add(
            VisitorSession(
                id="visit-1",
                arrival_time=utcnow(),
                visitor_type="known_person",
                status="active",
                confidence=0.9,
                face_match_status="KNOWN_HIGH_CONFIDENCE",
                recognized_name="Morgan",
                recognition_confidence=0.82,
            )
        )
        session.commit()

    def handler(_request):
        return httpx.Response(
            200,
            json={
                "camera": {"connected": True},
                "vision": {"tracks": [{"id": 1}]},
                "presence": {
                    "state": "PRESENT",
                    "person_count": 1,
                    "age_ms": 100,
                    "source": "live_detection",
                },
                "session_id": "visit-1",
            },
        )

    result = await FrontDoorStatusSkill(
        "http://jarvis.test", device_store, transport=httpx.MockTransport(handler)
    ).invoke()
    assert result["identityStatus"] == "KNOWN"
    assert result["speech"] == "Morgan is at the front door."


@pytest.mark.asyncio
async def test_front_door_stale_or_unknown_never_becomes_absent(device_store):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "camera": {"connected": True},
                "vision": {"tracks": []},
                "presence": {
                    "state": "UNKNOWN",
                    "person_count": None,
                    "observed_at": None,
                    "age_ms": None,
                    "source": "snapshot_unavailable",
                },
            },
        )

    result = await FrontDoorStatusSkill(
        "http://jarvis.test", device_store, transport=httpx.MockTransport(handler)
    ).invoke()
    assert result["presence"] == "UNKNOWN"
    assert result["personPresent"] is None
    assert "can't reliably tell" in result["speech"]


@pytest.mark.asyncio
async def test_front_door_fresh_empty_is_absent(device_store):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "camera": {"connected": True},
                "vision": {"tracks": []},
                "presence": {
                    "state": "ABSENT",
                    "person_count": 0,
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "age_ms": 100,
                    "source": "live_detection",
                },
            },
        )

    result = await FrontDoorStatusSkill(
        "http://jarvis.test", device_store, transport=httpx.MockTransport(handler)
    ).invoke()
    assert result["presence"] == "ABSENT"
    assert result["personPresent"] is False
    assert result["speech"] == "No, I don't see anyone at the front door."


@pytest.mark.asyncio
async def test_recent_activity_is_bounded(device_store):
    with device_store.Session() as session:
        for _index in range(8):
            session.add(
                FrontDoorEvent(
                    event_type="PERSON_DETECTED",
                    timestamp=utcnow(),
                    metadata_json='{"private_path":"must-not-leak"}',
                )
            )
        session.commit()
    result = await FrontDoorRecentSkill(device_store).invoke()
    assert len(result["events"]) == 5
    assert result["bounded"] is True
    assert all("metadata" not in event for event in result["events"])


def test_registered_aipi_is_workspace_scoped(device_store):
    with device_store.Session() as session:
        device = session.get(Device, "aipi-front-door")
        assert device.workspace_id == "home"
        assert "VOICE_INPUT" in json.loads(device.capabilities)
        tools = {
            row.tool_name
            for row in session.scalars(
                select(DeviceToolPermission).where(
                    DeviceToolPermission.device_id == device.id
                )
            ).all()
        }
        assert tools == {
            "jarvis.status",
            "jarvis.frontDoor.status",
            "jarvis.frontDoor.recent",
        }
