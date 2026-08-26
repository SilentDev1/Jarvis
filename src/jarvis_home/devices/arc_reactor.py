"""Arc reactor light behaviour.

This is the software half only. No GPIO is assigned and the controller is
disabled by default, because the physical light has not been identified: its
voltage, current draw, connector, and whether it is simple PWM, RGB, or
addressable are all unknown, and an ESP32 GPIO must never source the current a
decorative light typically wants. Selecting a pin before that is known risks
the board.

The controller derives everything from the authoritative terminal state rather
than keeping its own idea of what the terminal is doing, so the light can never
contradict the speaker or the display.

Brightness is computed here on the host from the outgoing PCM envelope, not on
the device. Doing envelope maths on the ESP32 during playback would put
floating-point work between I2S writes, and the audio path is already
physically validated; nothing is worth risking it for a light.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from enum import StrEnum

from .terminal_state import TerminalState


class ArcPattern(StrEnum):
    FADE_IN = "FADE_IN"
    DOUBLE_PULSE = "DOUBLE_PULSE"
    DIM_SLOW_PULSE = "DIM_SLOW_PULSE"
    DIM_STEADY = "DIM_STEADY"
    BRIGHT_SLOW_PULSE = "BRIGHT_SLOW_PULSE"
    BREATHING = "BREATHING"
    FAST_PULSE = "FAST_PULSE"
    AUDIO_REACTIVE = "AUDIO_REACTIVE"
    ERROR_BLINK = "ERROR_BLINK"
    FADE_TO_IDLE = "FADE_TO_IDLE"


_STATE_PATTERNS: dict[TerminalState, ArcPattern] = {
    TerminalState.BOOTING: ArcPattern.FADE_IN,
    TerminalState.SETUP: ArcPattern.DOUBLE_PULSE,
    TerminalState.OFFLINE: ArcPattern.DIM_SLOW_PULSE,
    TerminalState.IDLE: ArcPattern.DIM_STEADY,
    TerminalState.LISTENING: ArcPattern.BREATHING,
    TerminalState.PROCESSING: ArcPattern.FAST_PULSE,
    TerminalState.SPEAKING: ArcPattern.AUDIO_REACTIVE,
    TerminalState.ERROR: ArcPattern.ERROR_BLINK,
}

# Pattern shape: (base brightness, oscillation depth, cycles per second).
_PATTERN_SHAPE: dict[ArcPattern, tuple[float, float, float]] = {
    ArcPattern.FADE_IN: (0.0, 0.0, 0.0),
    ArcPattern.DOUBLE_PULSE: (0.25, 0.45, 1.6),
    ArcPattern.DIM_SLOW_PULSE: (0.06, 0.05, 0.25),
    ArcPattern.DIM_STEADY: (0.18, 0.0, 0.0),
    ArcPattern.BRIGHT_SLOW_PULSE: (0.55, 0.25, 0.4),
    ArcPattern.BREATHING: (0.45, 0.30, 0.28),
    ArcPattern.FAST_PULSE: (0.50, 0.28, 1.8),
    ArcPattern.AUDIO_REACTIVE: (0.25, 0.0, 0.0),
    ArcPattern.ERROR_BLINK: (0.30, 0.55, 3.0),
    ArcPattern.FADE_TO_IDLE: (0.18, 0.0, 0.0),
}

FULL_SCALE = 32767.0
# Attack faster than release, so the light snaps to speech onsets but does not
# flicker between syllables.
ENVELOPE_ATTACK = 0.55
ENVELOPE_RELEASE = 0.15
BOOT_FADE_SECONDS = 1.5
SESSION_FADE_SECONDS = 1.2


@dataclass(frozen=True)
class ArcFrame:
    brightness: float
    pattern: ArcPattern
    enabled: bool

    def public(self) -> dict:
        return {
            "brightness": round(self.brightness, 3),
            "pattern": str(self.pattern),
            "enabled": self.enabled,
        }


def pcm_envelope(pcm: bytes) -> float:
    """RMS level of a PCM16 chunk, normalised to 0..1.

    RMS rather than peak: peak tracks single-sample transients and makes the
    light stutter, while RMS follows perceived loudness.
    """
    if len(pcm) < 2:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    total = 0.0
    for value in samples:
        total += float(value) * float(value)
    rms = math.sqrt(total / len(samples)) / FULL_SCALE
    return max(0.0, min(1.0, rms))


class ArcReactorController:
    """Maps terminal state and audio level to a light frame.

    Disabled by default. While disabled it still computes frames so the
    behaviour is testable and observable, but reports `enabled=False` and must
    not be driven onto hardware.
    """

    def __init__(self, enabled: bool = False, gain: float = 3.2):
        self.enabled = enabled
        self.gain = gain
        self.level = 0.0
        self.pattern = ArcPattern.FADE_IN
        self.pattern_started_at = 0.0
        self._visitor_present = False
        self._session_closing_until: float | None = None

    def observe_audio(self, pcm: bytes) -> float:
        """Feed outgoing audio so SPEAKING can be audio-reactive."""
        target = min(1.0, pcm_envelope(pcm) * self.gain)
        smoothing = ENVELOPE_ATTACK if target > self.level else ENVELOPE_RELEASE
        self.level += (target - self.level) * smoothing
        return self.level

    def set_visitor_present(self, present: bool) -> None:
        self._visitor_present = present

    def begin_session_fade(self, now: float) -> None:
        self._session_closing_until = now + SESSION_FADE_SECONDS

    def pattern_for(self, state: TerminalState, now: float) -> ArcPattern:
        if self._session_closing_until is not None:
            if now < self._session_closing_until:
                return ArcPattern.FADE_TO_IDLE
            self._session_closing_until = None
        # A waiting visitor outranks plain IDLE so the terminal visibly wakes
        # before it speaks, but never overrides an error or a live conversation.
        if state is TerminalState.IDLE and self._visitor_present:
            return ArcPattern.BRIGHT_SLOW_PULSE
        return _STATE_PATTERNS[state]

    def frame(self, state: TerminalState, now: float) -> ArcFrame:
        pattern = self.pattern_for(state, now)
        if pattern is not self.pattern:
            self.pattern = pattern
            self.pattern_started_at = now
        elapsed = now - self.pattern_started_at

        if pattern is ArcPattern.AUDIO_REACTIVE:
            base, _, _ = _PATTERN_SHAPE[pattern]
            brightness = base + (1.0 - base) * self.level
        elif pattern is ArcPattern.FADE_IN:
            brightness = min(1.0, elapsed / BOOT_FADE_SECONDS) * 0.6
        elif pattern is ArcPattern.FADE_TO_IDLE:
            remaining = 1.0
            if self._session_closing_until is not None:
                remaining = max(
                    0.0,
                    (self._session_closing_until - now) / SESSION_FADE_SECONDS,
                )
            idle_base = _PATTERN_SHAPE[ArcPattern.DIM_STEADY][0]
            brightness = idle_base + (0.55 - idle_base) * remaining
        else:
            base, depth, hz = _PATTERN_SHAPE[pattern]
            brightness = base
            if depth and hz:
                brightness += depth * 0.5 * (1.0 + math.sin(2.0 * math.pi * hz * elapsed))
        return ArcFrame(
            brightness=max(0.0, min(1.0, brightness)),
            pattern=pattern,
            enabled=self.enabled,
        )
