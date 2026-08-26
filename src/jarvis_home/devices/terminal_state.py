"""The authoritative terminal state machine.

There is exactly one state machine for the physical terminal. Audio, display,
and the arc reactor consume it; none of them keeps its own parallel notion of
what the terminal is doing. Competing state machines were how the amplifier and
the display could previously disagree about whether the device was speaking.

Half-duplex is enforced here rather than in the audio layer, so that "the
microphone is off while Jarvis speaks" is a property of the state machine and
cannot be bypassed by a caller that forgets to check.
"""

from __future__ import annotations

import time
from enum import StrEnum


class TerminalState(StrEnum):
    BOOTING = "BOOTING"
    SETUP = "SETUP"
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class TerminalStateError(RuntimeError):
    """Raised on an illegal terminal state transition."""


# Losing the connection or hitting an error can happen from anywhere, so those
# targets are allowed universally and are not repeated in every row.
_ALWAYS_ALLOWED = {TerminalState.OFFLINE, TerminalState.ERROR}

_TRANSITIONS: dict[TerminalState, set[TerminalState]] = {
    TerminalState.BOOTING: {TerminalState.SETUP, TerminalState.IDLE},
    TerminalState.SETUP: {TerminalState.IDLE, TerminalState.BOOTING},
    TerminalState.OFFLINE: {TerminalState.IDLE, TerminalState.SETUP, TerminalState.BOOTING},
    TerminalState.IDLE: {TerminalState.LISTENING, TerminalState.SPEAKING,
                         TerminalState.PROCESSING},
    TerminalState.LISTENING: {TerminalState.PROCESSING, TerminalState.IDLE},
    TerminalState.PROCESSING: {TerminalState.SPEAKING, TerminalState.IDLE,
                               TerminalState.LISTENING},
    # SPEAKING never returns straight to LISTENING. The settling delay between
    # them is what stops the microphone hearing the tail of Jarvis's own voice.
    TerminalState.SPEAKING: {TerminalState.IDLE},
    TerminalState.ERROR: {TerminalState.IDLE, TerminalState.OFFLINE,
                          TerminalState.BOOTING},
}

# States in which the terminal may capture microphone audio. Deliberately a
# single-element set: barge-in is not supported, so Jarvis never listens while
# it speaks or thinks.
_MICROPHONE_STATES = {TerminalState.LISTENING}

# States in which the amplifier may be enabled.
_SPEAKER_STATES = {TerminalState.SPEAKING}

# Time the amplifier tail needs to decay before the microphone may open, so the
# terminal does not transcribe its own trailing audio.
SETTLE_SECONDS = 0.4


class TerminalStateMachine:
    def __init__(self, state: TerminalState = TerminalState.BOOTING,
                 settle_seconds: float = SETTLE_SECONDS):
        self.state = state
        self.settle_seconds = settle_seconds
        self.changed_at = time.monotonic()
        self.last_speaking_ended_at: float | None = None
        self.history: list[tuple[TerminalState, TerminalState]] = []

    def can_transition(self, target: TerminalState) -> bool:
        if target == self.state:
            return True
        if target in _ALWAYS_ALLOWED:
            return True
        return target in _TRANSITIONS.get(self.state, set())

    def transition(self, target: TerminalState, now: float | None = None) -> TerminalState:
        if not self.can_transition(target):
            raise TerminalStateError(f"illegal_transition:{self.state}->{target}")
        now = time.monotonic() if now is None else now
        if self.state == TerminalState.SPEAKING and target != TerminalState.SPEAKING:
            self.last_speaking_ended_at = now
        if target != self.state:
            self.history.append((self.state, target))
            self.state = target
            self.changed_at = now
        return self.state

    def settled(self, now: float | None = None) -> bool:
        """True once the post-speech settling delay has elapsed."""
        if self.last_speaking_ended_at is None:
            return True
        now = time.monotonic() if now is None else now
        return (now - self.last_speaking_ended_at) >= self.settle_seconds

    def microphone_allowed(self, now: float | None = None) -> bool:
        return self.state in _MICROPHONE_STATES and self.settled(now)

    def speaker_allowed(self) -> bool:
        return self.state in _SPEAKER_STATES

    def public(self) -> dict:
        return {
            "state": str(self.state),
            "microphoneAllowed": self.microphone_allowed(),
            "speakerAllowed": self.speaker_allowed(),
        }
