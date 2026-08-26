"""Local speech recognition and the filters that guard it.

Two separable concerns live here. `FasterWhisperSTT` turns canonical PCM into
text locally. `UtteranceFilter` decides whether audio and its transcript are
worth acting on at all.

The filter matters more than it looks. A door terminal listens in a room with
HVAC, traffic, televisions, and its own loudspeaker. Without a gate, silence
and noise become AI calls, tool calls, and spoken answers to nobody, and the
terminal talks to itself. Everything here fails closed: when in doubt, the
utterance is rejected rather than acted on.
"""

from __future__ import annotations

import asyncio
import math
import re
from array import array
from dataclasses import dataclass

from .speech import PCM16Audio, STTProvider

FULL_SCALE = 32767.0

# Below this RMS the room is effectively silent. Set from measured noise
# floors, not guessed: normal speech at the door sits far above it.
SILENCE_RMS = 0.006

# Shorter than this cannot carry a real request; it is a door slam or a cough.
MIN_SPEECH_SECONDS = 0.35

# Fraction of frames that must exceed the silence floor. Steady noise like a
# fan is loud but uniform; speech is bursty, so a clip that is uniformly "loud"
# with no quiet gaps is more likely machinery than a person.
MIN_VOICED_FRACTION = 0.06
MAX_VOICED_FRACTION = 0.995

FRAME_SAMPLES = 400  # 25 ms at 16 kHz

# Transcripts that Whisper commonly emits for silence or noise. These are
# hallucinations of its training data, not speech in the room.
# Stored in already-normalized form, because that is what they are compared
# against: normalization strips punctuation and underscores, so a literal like
# "[BLANK_AUDIO]" arrives here as "blank audio".
_NOISE_TRANSCRIPTS = {
    "thank you", "thanks for watching", "thank you for watching",
    "you", "bye", "okay", "ok", "uh", "um", "hmm", "mm", "ah", "oh",
    "blank audio", "silence", "music", "subscribe", "please subscribe",
    "applause", "laughter", "inaudible", "background noise",
}

_WORD = re.compile(r"[a-z0-9']+")


def rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    total = 0.0
    for value in samples:
        total += float(value) * float(value)
    return math.sqrt(total / len(samples)) / FULL_SCALE


def voiced_fraction(pcm: bytes, threshold: float = SILENCE_RMS) -> float:
    """Fraction of short frames whose level exceeds the silence floor."""
    frame_bytes = FRAME_SAMPLES * 2
    if len(pcm) < frame_bytes:
        return 1.0 if rms(pcm) > threshold else 0.0
    frames = len(pcm) // frame_bytes
    voiced = sum(
        1
        for index in range(frames)
        if rms(pcm[index * frame_bytes : (index + 1) * frame_bytes]) > threshold
    )
    return voiced / frames


def normalize_transcript(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


@dataclass(frozen=True)
class UtteranceDecision:
    accepted: bool
    reason: str
    transcript: str = ""


class UtteranceFilter:
    """Rejects audio and transcripts that must not reach the AI.

    Keeps a short memory of what Jarvis last said so the terminal does not act
    on an echo of its own voice, and of what the visitor last said so a
    repeated recognition does not produce two answers to one question.
    """

    def __init__(self, echo_memory: int = 3):
        self.echo_memory = echo_memory
        self._spoken: list[str] = []
        self._heard: list[str] = []

    def remember_spoken(self, text: str) -> None:
        """Record something Jarvis said, so its echo can be recognised."""
        normalized = normalize_transcript(text)
        if normalized:
            self._spoken.append(normalized)
            del self._spoken[: -self.echo_memory]

    def reset(self) -> None:
        self._heard.clear()

    def check_audio(self, audio: PCM16Audio) -> UtteranceDecision:
        seconds = len(audio.data) / (
            audio.sample_rate * audio.channels * audio.sample_width
        )
        if not audio.data:
            return UtteranceDecision(False, "empty_audio")
        if seconds < MIN_SPEECH_SECONDS:
            return UtteranceDecision(False, "too_short")
        if rms(audio.data) <= SILENCE_RMS:
            return UtteranceDecision(False, "silence")
        fraction = voiced_fraction(audio.data)
        if fraction < MIN_VOICED_FRACTION:
            return UtteranceDecision(False, "mostly_silence")
        if fraction > MAX_VOICED_FRACTION:
            # Uniformly loud with no gaps: machinery, not a person talking.
            return UtteranceDecision(False, "steady_noise")
        return UtteranceDecision(True, "ok")

    def check_transcript(self, text: str) -> UtteranceDecision:
        normalized = normalize_transcript(text)
        if not normalized:
            return UtteranceDecision(False, "empty_transcript")
        if normalized in _NOISE_TRANSCRIPTS:
            return UtteranceDecision(False, "noise_transcript", normalized)
        if len(normalized.split()) < 2 and len(normalized) < 4:
            return UtteranceDecision(False, "too_few_words", normalized)
        if normalized in self._spoken:
            # This is Jarvis hearing itself.
            return UtteranceDecision(False, "echo_of_jarvis", normalized)
        if normalized in self._heard:
            return UtteranceDecision(False, "duplicate_utterance", normalized)
        self._heard.append(normalized)
        del self._heard[: -self.echo_memory]
        return UtteranceDecision(True, "ok", text.strip())


class FasterWhisperSTT(STTProvider):
    """Local speech recognition. Nothing leaves the machine.

    The model is loaded lazily and reused: loading costs seconds, and a door
    terminal cannot pay that on every utterance.
    """

    def __init__(self, model_size: str = "base.en", compute_type: str = "int8",
                 download_root: str | None = None):
        self.model_size = model_size
        self.compute_type = compute_type
        self.download_root = download_root
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type=self.compute_type,
                download_root=self.download_root,
            )
        return self._model

    def _transcribe_sync(self, audio: PCM16Audio) -> str:
        import numpy as np

        model = self._load()
        samples = np.frombuffer(audio.data, dtype="<i2").astype("float32") / FULL_SCALE
        segments, _ = model.transcribe(
            samples,
            language="en",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, audio: PCM16Audio) -> str:
        if not audio.data:
            raise RuntimeError("Cannot transcribe empty audio")
        # Recognition is CPU-bound; keep it off the event loop so the gateway
        # stays responsive to the device while a phrase is being decoded.
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, audio)
