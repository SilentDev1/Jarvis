import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

import jarvis_home.app as app_module
from jarvis_home.devices.auth import issue_device_token, revoke_device_tokens
from jarvis_home.persistence import Device, Store


def configured_store(tmp_path):
    store = Store(tmp_path / "voice-gateway.db")
    store.init()
    with store.Session() as session:
        device = session.get(Device, "aipi-front-door")
        assert device is not None
        device.enabled = True
        session.commit()
    return store


def test_voice_websocket_requires_valid_revocable_device_token(tmp_path, monkeypatch):
    store = configured_store(tmp_path)
    monkeypatch.setattr(app_module, "store", store)
    client = TestClient(app_module.app)

    with pytest.raises(WebSocketDisconnect) as missing, client.websocket_connect(
        "/ws/devices/voice", subprotocols=["jarvis.voice.v1"]
    ):
        pass
    assert missing.value.code == 4401

    token = issue_device_token(store, "aipi-front-door")
    headers = {"Authorization": f"Bearer {token}"}
    with client.websocket_connect(
        "/ws/devices/voice",
        headers=headers,
        subprotocols=["jarvis.voice.v1"],
    ) as socket:
        socket.send_json(
            {
                "version": 1,
                "type": "DEVICE_HELLO",
                "id": "hello-1",
                "firmware_version": "simulator-test",
                "mic_ready": True,
                "speaker_ready": True,
            }
        )
        assert app_module.local_voice_hub.health.connected

    assert revoke_device_tokens(store, "aipi-front-door") == 1
    with pytest.raises(WebSocketDisconnect) as revoked, client.websocket_connect(
        "/ws/devices/voice",
        headers=headers,
        subprotocols=["jarvis.voice.v1"],
    ):
        pass
    assert revoked.value.code == 4401

    with store.Session() as session:
        credentials = session.scalars(select(app_module.DeviceCredential)).all()
        assert credentials and all(not row.enabled for row in credentials)


def test_voice_websocket_rejects_missing_protocol(tmp_path, monkeypatch):
    store = configured_store(tmp_path)
    monkeypatch.setattr(app_module, "store", store)
    token = issue_device_token(store, "aipi-front-door")
    client = TestClient(app_module.app)
    with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
        "/ws/devices/voice",
        headers={"Authorization": f"Bearer {token}"},
    ):
        pass
    assert rejected.value.code == 4406
