"""Listening must end when the visitor stops, not on a fixed timer.

A fixed window is the worst of both worlds: too short and it truncates someone
mid-sentence, too long and everyone waits out dead air. Both were reported from
the doorstep.
"""

import math
from array import array

from jarvis_home.devices.local_protocol import (
    ENDPOINT_MIN_SPEECH_SECONDS,
    ENDPOINT_NO_SPEECH_SECONDS,
    ENDPOINT_SILENCE_SECONDS,
    LocalDeviceHub,
)


class FakeStore:
    def Session(self):
        return _Null()


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return None

    def commit(self):
        return None


def hub():
    return LocalDeviceHub(FakeStore())


def voiced(seconds: float, rate: int = 16000) -> bytes:
    data = array("h", (
        int(9000 * math.sin(2 * math.pi * 220 * i / rate))
        for i in range(int(rate * seconds))
    ))
    return data.tobytes()


def silence(seconds: float, rate: int = 16000) -> bytes:
    return bytes(int(rate * seconds) * 2)


def feed(h, payload: bytes) -> None:
    """Mirrors what receive_binary tracks, without the framing."""
    from jarvis_home.core.speech_input import rms
    from jarvis_home.devices.audio_stream import AUDIO_SAMPLE_BYTES, AUDIO_SAMPLE_RATE
    seconds = len(payload) / (AUDIO_SAMPLE_RATE * AUDIO_SAMPLE_BYTES)
    h._mic_bytes += len(payload)
    h._mic_levels.append((seconds, rms(payload)))


def test_turn_ends_after_the_speaker_stops():
    h = hub()
    feed(h, voiced(1.5))
    assert h._endpoint_reason() is None, "must not end while they are talking"
    feed(h, silence(ENDPOINT_SILENCE_SECONDS + 0.2))
    assert h._endpoint_reason() == "endpoint_silence"


def test_a_pause_mid_sentence_does_not_end_the_turn():
    # The reported failure: cut off while still speaking.
    h = hub()
    feed(h, voiced(1.0))
    feed(h, silence(ENDPOINT_SILENCE_SECONDS / 2))
    assert h._endpoint_reason() is None
    feed(h, voiced(1.0))          # they carry on
    assert h._endpoint_reason() is None


def test_silence_before_any_speech_does_not_end_the_turn_immediately():
    # Someone gathering their thoughts must not be cut off before they start.
    h = hub()
    feed(h, silence(ENDPOINT_SILENCE_SECONDS + 0.5))
    assert h._endpoint_reason() is None


def test_a_completely_silent_turn_gives_up():
    h = hub()
    feed(h, silence(ENDPOINT_NO_SPEECH_SECONDS + 0.5))
    assert h._endpoint_reason() == "no_speech"


def test_a_cough_is_not_enough_speech_to_endpoint_on():
    h = hub()
    feed(h, voiced(ENDPOINT_MIN_SPEECH_SECONDS / 3))
    feed(h, silence(ENDPOINT_SILENCE_SECONDS + 0.3))
    # Too little real speech to treat the silence as the end of a sentence;
    # it falls through to the no-speech path instead.
    assert h._endpoint_reason() != "endpoint_silence"


def test_maximum_window_is_generous_because_endpointing_governs():
    from jarvis_home.devices.voice_loop import DEFAULT_LISTEN_MS
    # A long ceiling costs nothing once the turn ends on silence, and stops a
    # visitor being truncated.
    assert DEFAULT_LISTEN_MS >= 12000


def test_recognition_is_warmed_at_startup():
    from pathlib import Path
    source = Path("src/jarvis_home/devices/local_gateway.py").read_text()
    # Cold loading costs ~1.6s and the visitor paying it is the first real one.
    assert "_warm_recognition" in source
    assert "asyncio.create_task(_warm_recognition())" in source
    # Failure must not be fatal. Slice to the next top-level definition; a
    # blank-line split would stop inside the docstring.
    warm = source.split("async def _warm_recognition(", 1)[1].split("\n@", 1)[0]
    assert "except Exception" in warm


def test_threshold_adapts_to_a_noisy_room():
    # A fixed absolute threshold could not work: the measured floor at this
    # door was 0.041, seven times the nominal silence level, so nothing ever
    # counted as silence and the turn ran to its full ceiling every time.
    from jarvis_home.core.speech_input import rms
    from jarvis_home.devices.local_protocol import LocalDeviceHub

    def hum(seconds, amplitude, rate=16000):
        data = array("h", (
            int(amplitude * math.sin(2 * math.pi * 60 * i / rate))
            for i in range(int(rate * seconds))
        ))
        return data.tobytes()

    h = LocalDeviceHub(FakeStore())
    noisy_room = hum(0.5, 1400)          # well above the old fixed threshold
    assert rms(noisy_room) > 0.02, "sanity: this is a noisy room"
    feed(h, noisy_room)
    # Room tone must not be mistaken for speech.
    assert h._speech_profile()[0] == 0.0

    speech = hum(1.0, 14000)
    feed(h, speech)
    assert h._speech_profile()[0] > 0.0, "real speech must be recognised"
    feed(h, noisy_room)
    feed(h, noisy_room)
    assert h._endpoint_reason() == "endpoint_silence"


def test_endpointing_is_logged_for_diagnosis():
    from pathlib import Path
    source = Path("src/jarvis_home/devices/local_protocol.py").read_text()
    assert "listen ended:" in source
    assert "peak" in source.split("listen ended:", 1)[1][:200]
