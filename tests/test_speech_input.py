"""Guards for local STT and the filters that stop noise becoming AI calls."""

import math
from array import array

import pytest

from jarvis_home.core.speech import PCM16Audio
from jarvis_home.core.speech_input import (
    MIN_SPEECH_SECONDS,
    UtteranceFilter,
    normalize_transcript,
    rms,
    voiced_fraction,
)


def pcm(seconds=1.0, amplitude=8000, rate=16000, speechlike=True):
    total = int(rate * seconds)
    data = array("h")
    for i in range(total):
        value = amplitude * math.sin(2.0 * math.pi * 200 * i / rate)
        if speechlike:
            # Bursty envelope with quiet gaps, like syllables.
            envelope = 1.0 if (i // 1600) % 2 == 0 else 0.02
            value *= envelope
        data.append(int(value))
    return PCM16Audio(data=data.tobytes(), sample_rate=rate)


def audio_filter():
    return UtteranceFilter()


def test_silence_is_rejected_and_never_reaches_the_ai():
    decision = audio_filter().check_audio(pcm(amplitude=0))
    assert decision.accepted is False
    assert decision.reason in ("silence", "mostly_silence")


def test_empty_audio_is_rejected():
    assert audio_filter().check_audio(PCM16Audio(data=b"")).accepted is False


def test_very_short_audio_is_rejected():
    short = pcm(seconds=MIN_SPEECH_SECONDS / 2)
    assert audio_filter().check_audio(short).reason == "too_short"


def test_steady_noise_is_rejected_but_bursty_speech_is_accepted():
    # A fan is loud and uniform; speech has gaps between syllables.
    steady = pcm(amplitude=9000, speechlike=False)
    assert audio_filter().check_audio(steady).accepted is False
    assert audio_filter().check_audio(pcm(amplitude=9000)).accepted is True


def test_empty_transcript_is_rejected():
    assert audio_filter().check_transcript("").reason == "empty_transcript"
    assert audio_filter().check_transcript("   ").reason == "empty_transcript"


def test_whisper_silence_hallucinations_are_rejected():
    # Whisper emits these for silence; they are training-data artefacts.
    for text in ("Thank you.", "thanks for watching", "[BLANK_AUDIO]", "you", "..."):
        assert audio_filter().check_transcript(text).accepted is False


def test_echo_of_jarvis_own_speech_is_rejected():
    f = audio_filter()
    f.remember_spoken("Hi, how can I help you?")
    decision = f.check_transcript("hi how can i help you")
    assert decision.accepted is False
    assert decision.reason == "echo_of_jarvis"


def test_duplicate_utterance_is_rejected_so_one_question_gets_one_answer():
    f = audio_filter()
    assert f.check_transcript("is jarvis online").accepted is True
    assert f.check_transcript("is jarvis online").reason == "duplicate_utterance"


def test_reset_clears_heard_history_between_sessions():
    f = audio_filter()
    f.check_transcript("is jarvis online")
    f.reset()
    assert f.check_transcript("is jarvis online").accepted is True


def test_real_request_is_accepted():
    f = audio_filter()
    assert f.check_audio(pcm()).accepted is True
    decision = f.check_transcript("I'm here from Comcast")
    assert decision.accepted is True
    assert decision.transcript == "I'm here from Comcast"


def test_normalisation_ignores_case_and_punctuation():
    assert normalize_transcript("Hi, How Can I Help You?") == "hi how can i help you"


def test_rms_and_voiced_fraction_handle_degenerate_input():
    assert rms(b"") == 0.0
    assert rms(b"\x00") == 0.0
    assert 0.0 <= voiced_fraction(b"\x00\x00") <= 1.0


@pytest.mark.asyncio
async def test_stt_refuses_empty_audio_without_loading_a_model():
    from jarvis_home.core.speech_input import FasterWhisperSTT

    provider = FasterWhisperSTT()
    with pytest.raises(RuntimeError, match="empty"):
        await provider.transcribe(PCM16Audio(data=b""))
    assert provider._model is None
