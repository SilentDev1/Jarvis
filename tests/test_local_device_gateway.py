import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import jarvis_home.devices.local_gateway as gateway
from jarvis_home.devices.auth import issue_device_token, revoke_device_tokens
from jarvis_home.devices.local_protocol import (
    ConnectionFloodLimiter,
    LocalDeviceHub,
    parse_message,
)
from jarvis_home.persistence import Device, Store


def configured(tmp_path, monkeypatch):
    store = Store(tmp_path / "local-device.db")
    store.init()
    token = issue_device_token(store, "aipi-front-door")
    monkeypatch.setattr(gateway, "store", store)
    monkeypatch.setattr(gateway, "hub", LocalDeviceHub(store))
    monkeypatch.setattr(gateway, "limiter", ConnectionFloodLimiter())
    return TestClient(gateway.app), store, token


def hello():
    return {
        "protocolVersion": 1,
        "type": "DEVICE_HELLO",
        "id": "hello-1",
        "deviceId": "aipi-front-door",
        "firmwareVersion": "0.2.0-local",
        "capabilities": ["DISPLAY", "BUTTON", "WIFI", "LOCAL_CONNECTION", "STATUS"],
    }


def test_valid_auth_hello_status_and_database_health(tmp_path, monkeypatch):
    client, store, token = configured(tmp_path, monkeypatch)
    with client.websocket_connect(
        "/ws/device",
        headers={"Authorization": f"DevicePassword {token}"},
        subprotocols=["jarvis.device.v1"],
    ) as socket:
        socket.send_json(hello())
        assert socket.receive_json()["type"] == "DEVICE_READY"
        assert socket.receive_json()["type"] == "STATUS_REQUEST"
        socket.send_json({
            "protocolVersion": 1, "type": "DEVICE_STATUS", "id": "status-1",
            "uptimeSeconds": 10, "wifiRssi": -44, "freeHeap": 1000,
            "freePsram": 2000, "displayStatus": "ONLINE", "buttonStatus": "READY",
            "terminalState": "JARVIS_ONLINE",
        })
        assert gateway.hub.health.ready
    with store.Session() as session:
        device = session.get(Device, "aipi-front-door")
        assert device is not None and device.last_seen is not None


@pytest.mark.parametrize("authorization", [None, "DevicePassword wrong", "Malformed"])
def test_missing_wrong_and_malformed_auth_are_rejected(
    tmp_path, monkeypatch, authorization
):
    client, _store, _token = configured(tmp_path, monkeypatch)
    headers = {"Authorization": authorization} if authorization else {}
    with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
        "/ws/device", headers=headers, subprotocols=["jarvis.device.v1"]
    ):
        pass
    assert rejected.value.code == 4401


def test_revoked_token_and_unknown_device_are_rejected(tmp_path, monkeypatch):
    client, store, token = configured(tmp_path, monkeypatch)
    revoke_device_tokens(store, "aipi-front-door")
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            "/ws/device", headers={"Authorization": f"DevicePassword {token}"},
        subprotocols=["jarvis.device.v1"]
    ):
        pass
    with pytest.raises(ValueError, match="Unknown device"):
        issue_device_token(store, "missing-device")


def test_protocol_rejects_malformed_version_oversize_and_unknown_type():
    with pytest.raises(json.JSONDecodeError):
        parse_message("bad-json")
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        parse_message('{"protocolVersion":2,"type":"PING"}')
    with pytest.raises(ValueError, match="message_too_large"):
        parse_message("x" * 5000)


def test_connection_flood_limiter_recovers():
    limiter = ConnectionFloodLimiter(limit=2, window_seconds=10)
    assert limiter.allow("host", 0)
    assert limiter.allow("host", 1)
    assert not limiter.allow("host", 2)
    assert limiter.allow("host", 11)


@pytest.mark.asyncio
async def test_heartbeat_timeout_marks_device_offline(tmp_path):
    store = Store(tmp_path / "heartbeat.db")
    store.init()
    hub = LocalDeviceHub(store)

    class Socket:
        closed = False

        async def close(self, **_kwargs):
            self.closed = True

        async def send_text(self, _raw):
            pass

    socket = Socket()
    await hub.attach(socket, "aipi-front-door", "192.0.2.1")
    hub.health.last_seen = 1
    await hub.heartbeat_once(now=100)
    assert socket.closed and not hub.health.connected


def test_health_never_contains_device_token(tmp_path, monkeypatch):
    client, _store, token = configured(tmp_path, monkeypatch)
    body = client.get("/health").text
    assert token not in body
    assert "token" not in body.lower()
