"""Guards for the voice terminal backed by the validated device gateway."""

import httpx
import pytest

from jarvis_home.devices.gateway_voice import AiPiGatewayVoice


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return self.handler(request)


def patched(monkeypatch, handler):
    transport = FakeTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return transport


def json_response(payload, status=200):
    return httpx.Response(status, json=payload)


def provider():
    return AiPiGatewayVoice("http://127.0.0.1:8767", "secret-token")


@pytest.mark.asyncio
async def test_speak_posts_text_with_the_admin_token(monkeypatch):
    transport = patched(monkeypatch, lambda r: json_response({"totalBytes": 10}))
    await provider().speak("Hi, how can I help you?")
    request = transport.requests[0]
    assert request.url.path == "/internal/speak"
    # The token gates the operator surface; sending without it would 401.
    assert request.headers["x-jarvis-admin-token"] == "secret-token"


@pytest.mark.asyncio
async def test_speak_truncates_rather_than_sending_unbounded_text(monkeypatch):
    import json

    transport = patched(monkeypatch, lambda r: json_response({"totalBytes": 10}))
    await provider().speak("x" * 5000)
    body = json.loads(transport.requests[0].content)
    assert len(body["text"]) <= 500


@pytest.mark.asyncio
async def test_listening_stores_only_accepted_transcripts(monkeypatch):
    patched(monkeypatch, lambda r: json_response(
        {"accepted": True, "transcript": "I'm here from Comcast", "reason": "ok"}))
    p = provider()
    await p.start_listening()
    assert p.last_transcript == "I'm here from Comcast"
    assert p.last_reason == "ok"


@pytest.mark.asyncio
async def test_rejected_utterance_yields_no_transcript(monkeypatch):
    # Silence and noise must not reach the conversation as empty turns.
    patched(monkeypatch, lambda r: json_response(
        {"accepted": False, "transcript": "", "reason": "silence"}))
    p = provider()
    await p.start_listening()
    assert p.last_transcript == ""
    assert p.last_reason == "silence"


@pytest.mark.asyncio
async def test_health_reports_ready_only_when_the_device_is_connected(monkeypatch):
    patched(monkeypatch, lambda r: json_response({
        "device": {"connected": True, "ready": True, "firmware_version": "0.6.0",
                   "capabilities": ["SPEAKER", "MICROPHONE"]},
        "terminal": {"state": "IDLE"},
    }))
    p = provider()
    await p.refresh_health()
    assert p.health()["status"] == "ready"
    assert p.is_available() is True


@pytest.mark.asyncio
async def test_health_reports_offline_when_the_device_is_gone(monkeypatch):
    patched(monkeypatch, lambda r: json_response({
        "device": {"connected": False, "ready": False},
        "terminal": {"state": "OFFLINE"},
    }))
    p = provider()
    await p.refresh_health()
    assert p.health()["status"] == "offline"
    assert p.is_available() is False


@pytest.mark.asyncio
async def test_health_survives_an_unreachable_gateway(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("refused")

    patched(monkeypatch, boom)
    p = provider()
    await p.refresh_health()
    # A dead gateway must degrade, not raise into the caller.
    assert p.health()["status"] == "unavailable"
    assert p.is_available() is False


def test_health_is_synchronous_matching_the_provider_contract():
    import inspect

    from jarvis_home.core.providers import VoiceTerminalProvider

    assert not inspect.iscoroutinefunction(AiPiGatewayVoice.health)
    assert not inspect.iscoroutinefunction(VoiceTerminalProvider.health)


@pytest.mark.asyncio
async def test_availability_is_false_until_health_is_refreshed():
    # is_available() is synchronous by contract and reads a cache. Without a
    # refresher the cache stays unknown and every camera-triggered greeting
    # fails closed as terminal_unavailable, which looks like a broken device.
    p = provider()
    assert p.health()["status"] == "unknown"
    assert p.is_available() is False


def test_app_refreshes_terminal_health_periodically():
    from pathlib import Path

    source = Path("src/jarvis_home/app.py").read_text()
    assert "terminal_health_loop" in source
    assert "refresh_health" in source
    # It must actually be scheduled, not merely defined.
    assert "asyncio.create_task(terminal_health_loop())" in source
