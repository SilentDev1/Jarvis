import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from jarvis_home.devices.auth import (
    authenticate_device,
    issue_device_token,
    revoke_device_tokens,
)
from jarvis_home.devices.mcp_gateway import DeviceAuthMiddleware
from jarvis_home.devices.skills import JarvisStatusSkill
from jarvis_home.persistence import Device, Store


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
        response = client.post(
            "/mcp", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200


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


def test_registered_aipi_is_workspace_scoped(device_store):
    with device_store.Session() as session:
        device = session.get(Device, "aipi-front-door")
        assert device.workspace_id == "home"
        assert "VOICE_INPUT" in json.loads(device.capabilities)
