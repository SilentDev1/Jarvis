"""One bounded voice turn on the physical terminal.

Sequences the terminal through LISTENING, PROCESSING and SPEAKING, and
guarantees it lands back in IDLE on every path. A turn that ends anywhere else
leaves the microphone or amplifier gated wrongly for the next visitor.

The loop is deliberately half-duplex and single-turn. It listens, thinks, then
speaks, and never overlaps them, so the terminal cannot hear itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..core.speech import PCM16Audio, TTSProvider
from ..core.speech_input import STTProvider, UtteranceFilter
from .audio_stream import AudioStreamError, validate_format
from .terminal_state import TerminalState

logger = logging.getLogger("jarvis_home.voice_loop")

# Upper bound only. Endpointing ends the turn as soon as the speaker stops, so
# a generous ceiling costs nothing and stops a visitor being cut off when they
# pause mid-sentence.
DEFAULT_LISTEN_MS = 15000

# Kept short on purpose: this is spoken aloud at a front door, not read.
# The shared AIProvider requests JSON from the model, so the reply must be
# asked for in that shape or parsing fails and the terminal falls back to an
# apology instead of answering.
SYSTEM_PROMPT = (
    "You are Jarvis, a home terminal at the front door. Reply with JSON of the "
    'form {"reply": "..."} and nothing else. The reply must be one short '
    "spoken sentence, with no lists, markdown, or emoji. If you do not know, "
    "say so plainly."
)

# Answered locally so the basic terminal keeps working when no AI is reachable.
# The door terminal must not depend on a model being up.
#
# Matched on keyword sets rather than exact phrases. Recognition of the same
# spoken sentence varies run to run ("is Jarvis online" came back as "it's
# Jarvis Online"), so exact matching made the local answers nearly unreachable
# in practice.
_LOCAL_ANSWERS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"jarvis", "online"}), "Jarvis is online."),
    (frozenset({"you", "online"}), "Jarvis is online."),
    (frozenset({"you", "there"}), "Jarvis is online."),
    (frozenset({"microphone", "test"}), "Microphone test received."),
    (frozenset({"you", "hear"}), "Yes, I can hear you."),
)


@dataclass
class VoiceTurn:
    heard: str = ""
    reply: str = ""
    accepted: bool = False
    reason: str = ""
    source: str = ""
    stats: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "heard": self.heard,
            "reply": self.reply,
            "accepted": self.accepted,
            "reason": self.reason,
            "source": self.source,
            **self.stats,
        }


class VoiceLoop:
    def __init__(self, hub, stt: STTProvider, tts: TTSProvider,
                 utterance_filter: UtteranceFilter, ai=None):
        self.hub = hub
        self.stt = stt
        self.tts = tts
        self.filter = utterance_filter
        self.ai = ai

    async def _answer(self, heard: str) -> tuple[str, str]:
        words = {word.strip("?.,!'\"") for word in heard.lower().split()}
        for keywords, answer in _LOCAL_ANSWERS:
            if keywords <= words:
                return answer, "local"
        if self.ai is None:
            return "I heard you, but no assistant is configured.", "unavailable"
        try:
            result = await self.ai.respond(
                SYSTEM_PROMPT, [{"role": "user", "content": heard}], {}
            )
        except Exception as error:  # noqa: BLE001 - any AI failure must still speak
            logger.warning("voice turn AI failed: %s", type(error).__name__)
            return "Sorry, I could not reach my assistant.", "error"
        reply = str(result.get("reply") or result.get("content") or "").strip()
        if not reply:
            return "Sorry, I did not have an answer for that.", "empty"
        # Spoken aloud, so keep it to something a person will actually listen to.
        return reply[:300], "ai"

    async def speak(self, text: str) -> dict:
        audio = await self.tts.synthesize(text)
        if not audio.data:
            raise AudioStreamError("tts_produced_no_audio")
        validate_format(audio.sample_rate, audio.channels, audio.sample_width * 8)
        result = await self.hub.play_pcm(audio.data)
        # Remember it so the microphone cannot act on its own echo next turn.
        self.filter.remember_spoken(text)
        return result

    async def run_turn(self, listen_milliseconds: int = DEFAULT_LISTEN_MS) -> VoiceTurn:
        turn = VoiceTurn()
        try:
            self.hub.terminal.transition(TerminalState.LISTENING)
            pcm = await self.hub.listen(max_milliseconds=listen_milliseconds)
            audio = PCM16Audio(data=pcm)
            turn.stats = {"bytes": len(pcm)}

            gate = self.filter.check_audio(audio)
            if not gate.accepted:
                # Silence must produce no AI call, no tool call, and no speech.
                turn.reason = gate.reason
                return turn

            self.hub.terminal.transition(TerminalState.PROCESSING)
            heard = await self.stt.transcribe(audio)
            decision = self.filter.check_transcript(heard)
            if not decision.accepted:
                turn.heard = heard
                turn.reason = decision.reason
                return turn

            turn.heard = decision.transcript
            turn.accepted = True
            turn.reply, turn.source = await self._answer(decision.transcript)
            turn.reason = "ok"
        finally:
            # Whatever happened, the terminal must not be left mid-turn.
            if self.hub.terminal.state in (
                TerminalState.LISTENING,
                TerminalState.PROCESSING,
            ):
                self.hub.terminal.transition(TerminalState.IDLE)

        if turn.reply:
            await self.speak(turn.reply)
        return turn
