import pytest

from jarvis_home.core.events import EventBus
from jarvis_home.integrations.providers import SimulatorVoice, StockAiPiVoice
from jarvis_home.modules.front_door.voice_terminal import (
    VisitorGreetingPolicy,
    VoiceConversationPhase,
    VoiceTerminalService,
)


@pytest.mark.asyncio
async def test_camera_triggered_greeting_starts_bounded_listening_once():
    bus = EventBus()
    provider = SimulatorVoice()
    service = VoiceTerminalService(provider, bus, no_speech_timeout=5)

    assert await service.begin("visit-1", "Hi, how can I help you?", now=10)
    assert not await service.begin("visit-2", "Hi, how can I help you?", now=11)
    assert provider.last_spoken == "Hi, how can I help you?"
    assert provider.health()["state"] == "listening"
    assert service.active.phase == VoiceConversationPhase.LISTENING
    assert [event.type for event in bus.history] == [
        "voice.listening_started",
        "voice.greeting_requested",
    ]


@pytest.mark.asyncio
async def test_stock_aipi_unavailable_fails_closed_and_audits():
    bus = EventBus()
    provider = StockAiPiVoice()
    service = VoiceTerminalService(provider, bus)

    assert not await service.begin("visit-1", "Hi, how can I help you?", now=0)
    assert service.active.phase == VoiceConversationPhase.ERROR
    assert service.active.end_reason == "terminal_unavailable"
    assert bus.history[0].type == "voice.terminal_unavailable"
    assert bus.history[0].payload == {"session_id": "visit-1", "safe_failure": True}


@pytest.mark.asyncio
async def test_no_speech_timeout_returns_terminal_to_standby():
    bus = EventBus()
    provider = SimulatorVoice()
    service = VoiceTerminalService(provider, bus, no_speech_timeout=5)
    await service.begin("visit-1", "Hi, how can I help you?", now=10)

    assert await service.expire(now=14.9) is None
    assert await service.expire(now=15) == "no_speech_timeout"
    assert provider.health()["state"] == "standby"
    assert service.active.phase == VoiceConversationPhase.COMPLETE


@pytest.mark.asyncio
async def test_person_leaving_ends_conversation_cleanly():
    bus = EventBus()
    provider = SimulatorVoice()
    service = VoiceTerminalService(provider, bus)
    await service.begin("visit-1", "Hi, how can I help you?", now=10)

    assert await service.end("visit-1", "visitor_departed")
    assert provider.health()["state"] == "standby"
    assert service.active.end_reason == "visitor_departed"


@pytest.mark.asyncio
async def test_multi_turn_response_reopens_listening_and_is_bounded():
    bus = EventBus()
    provider = SimulatorVoice()
    service = VoiceTerminalService(provider, bus, max_turns=2)
    await service.begin("visit-1", "Hi, how can I help you?", now=0)

    assert service.begin_processing("visit-1", now=1)
    assert await service.respond("visit-1", "May I have your name?", now=2)
    assert service.active.phase == VoiceConversationPhase.LISTENING
    assert not await service.respond("visit-1", "Thank you.", now=3)
    assert service.active.end_reason == "maximum_turns"
    assert provider.health()["state"] == "standby"


def test_known_person_greeting_is_opt_in_and_never_guessed():
    generic = VisitorGreetingPolicy()
    personalized = VisitorGreetingPolicy(personalize_known_visitors=True)

    assert generic.greeting("John") == "Hi, how can I help you?"
    assert personalized.greeting(None) == "Hi, how can I help you?"
    assert personalized.greeting("John") == "Hi John, how can I help you?"
