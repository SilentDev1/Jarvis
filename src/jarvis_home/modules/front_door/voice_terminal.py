import time
from dataclasses import asdict, dataclass
from enum import StrEnum

from ...core.providers import VoiceTerminalProvider


class VoiceConversationPhase(StrEnum):
    STANDBY = "standby"
    GREETING = "greeting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class VoiceConversationSession:
    visitor_session_id: str
    phase: VoiceConversationPhase = VoiceConversationPhase.STANDBY
    started_at: float = 0
    last_activity_at: float = 0
    turns: int = 0
    greeting: str = ""
    end_reason: str | None = None

    def public(self) -> dict:
        return asdict(self)


class VisitorGreetingPolicy:
    def __init__(self, personalize_known_visitors: bool = False):
        self.personalize_known_visitors = personalize_known_visitors

    def greeting(self, known_person_name: str | None = None) -> str:
        if self.personalize_known_visitors and known_person_name:
            return f"Hi {known_person_name}, how can I help you?"
        return "Hi, how can I help you?"


class VoiceTerminalService:
    """Owns bounded event-initiated voice state, independent of camera code."""

    def __init__(
        self,
        provider: VoiceTerminalProvider,
        event_bus,
        no_speech_timeout: float = 15,
        max_duration: float = 120,
        max_turns: int = 8,
    ):
        self.provider = provider
        self.bus = event_bus
        self.no_speech_timeout = no_speech_timeout
        self.max_duration = max_duration
        self.max_turns = max_turns
        self.active: VoiceConversationSession | None = None

    async def begin(self, session_id: str, greeting: str, now: float | None = None):
        now = time.monotonic() if now is None else now
        if self.active and self.active.phase not in {
            VoiceConversationPhase.COMPLETE,
            VoiceConversationPhase.ERROR,
        }:
            return False
        session = VoiceConversationSession(
            visitor_session_id=session_id,
            phase=VoiceConversationPhase.GREETING,
            started_at=now,
            last_activity_at=now,
            greeting=greeting,
        )
        self.active = session
        self.bus.publish(
            "voice.greeting_requested", {"session_id": session_id, "text": greeting}
        )
        if not self.provider.is_available():
            session.phase = VoiceConversationPhase.ERROR
            session.end_reason = "terminal_unavailable"
            self.bus.publish(
                "voice.terminal_unavailable",
                {"session_id": session_id, "safe_failure": True},
            )
            return False
        try:
            await self.provider.set_session(session_id)
            await self.provider.speak(greeting)
            await self.provider.start_listening()
        except Exception as error:  # noqa: BLE001 - provider boundary fails closed
            session.phase = VoiceConversationPhase.ERROR
            session.end_reason = "provider_error"
            self.bus.publish(
                "voice.terminal_error",
                {"session_id": session_id, "error": type(error).__name__},
            )
            await self.provider.stop_listening()
            return False
        session.phase = VoiceConversationPhase.LISTENING
        session.last_activity_at = now
        self.bus.publish("voice.listening_started", {"session_id": session_id})
        return True

    def begin_processing(self, session_id: str, now: float | None = None) -> bool:
        if not self.active or self.active.visitor_session_id != session_id:
            return False
        self.active.phase = VoiceConversationPhase.PROCESSING
        self.active.last_activity_at = time.monotonic() if now is None else now
        return True

    async def respond(self, session_id: str, text: str, now: float | None = None):
        if not self.active or self.active.visitor_session_id != session_id:
            return False
        now = time.monotonic() if now is None else now
        self.active.turns += 1
        if self.active.turns >= self.max_turns:
            await self.end(session_id, "maximum_turns")
            return False
        self.active.phase = VoiceConversationPhase.SPEAKING
        try:
            await self.provider.speak(text)
            await self.provider.start_listening()
        except Exception as error:  # noqa: BLE001 - provider boundary fails closed
            self.bus.publish(
                "voice.terminal_error",
                {"session_id": session_id, "error": type(error).__name__},
            )
            await self.end(session_id, "provider_error")
            return False
        self.active.phase = VoiceConversationPhase.LISTENING
        self.active.last_activity_at = now
        return True

    async def expire(self, now: float | None = None) -> str | None:
        if not self.active or self.active.phase in {
            VoiceConversationPhase.COMPLETE,
            VoiceConversationPhase.ERROR,
        }:
            return None
        now = time.monotonic() if now is None else now
        if now - self.active.started_at >= self.max_duration:
            reason = "maximum_duration"
        elif (
            self.active.phase == VoiceConversationPhase.LISTENING
            and now - self.active.last_activity_at >= self.no_speech_timeout
        ):
            reason = "no_speech_timeout"
        else:
            return None
        await self.end(self.active.visitor_session_id, reason)
        return reason

    async def end(self, session_id: str, reason: str) -> bool:
        if not self.active or self.active.visitor_session_id != session_id:
            return False
        try:
            await self.provider.stop_listening()
        except Exception as error:  # noqa: BLE001 - cleanup remains fail closed
            self.bus.publish(
                "voice.terminal_error",
                {"session_id": session_id, "error": type(error).__name__},
            )
        finally:
            await self.provider.set_session(None)
        self.active.phase = VoiceConversationPhase.COMPLETE
        self.active.end_reason = reason
        self.bus.publish(
            "voice.session_completed", {"session_id": session_id, "reason": reason}
        )
        return True
