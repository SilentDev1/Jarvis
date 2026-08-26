"""Guards for one bounded voice turn on the physical terminal."""

import pytest

from jarvis_home.core.speech import PCM16Audio
from jarvis_home.core.speech_input import UtteranceFilter
from jarvis_home.devices.terminal_state import TerminalState, TerminalStateMachine
from jarvis_home.devices.voice_loop import VoiceLoop


class FakeHub:
    def __init__(self, pcm=b"", fail_listen=None):
        self.terminal = TerminalStateMachine(state=TerminalState.IDLE,
                                             settle_seconds=0)
        self.pcm = pcm
        self.fail_listen = fail_listen
        self.played = []

    async def listen(self, max_milliseconds=6000):
        if self.fail_listen:
            raise self.fail_listen
        return self.pcm

    async def play_pcm(self, pcm, stream_id=1):
        self.played.append(pcm)
        self.terminal.transition(TerminalState.SPEAKING)
        self.terminal.transition(TerminalState.IDLE)
        return {"totalBytes": len(pcm)}


class FakeSTT:
    def __init__(self, text=""):
        self.text = text
        self.calls = 0

    async def transcribe(self, audio):
        self.calls += 1
        return self.text


class FakeTTS:
    def __init__(self, data=b"\x01\x02" * 100):
        self.data = data
        self.spoken = []

    async def synthesize(self, text):
        self.spoken.append(text)
        return PCM16Audio(data=self.data)


class FakeAI:
    def __init__(self, reply="Yes.", error=None):
        self.reply = reply
        self.error = error
        self.calls = 0

    async def respond(self, system, messages, state):
        self.calls += 1
        if self.error:
            raise self.error
        return {"reply": self.reply}


def speech(seconds=1.0, amplitude=9000, rate=16000):
    import math
    from array import array

    data = array("h")
    for i in range(int(rate * seconds)):
        envelope = 1.0 if (i // 1600) % 2 == 0 else 0.02
        data.append(int(amplitude * envelope * math.sin(2 * math.pi * 200 * i / rate)))
    return data.tobytes()


def build(pcm=None, text="is jarvis online", ai=None):
    hub = FakeHub(pcm if pcm is not None else speech())
    stt = FakeSTT(text)
    tts = FakeTTS()
    loop = VoiceLoop(hub, stt, tts, UtteranceFilter(), ai=ai)
    return loop, hub, stt, tts


@pytest.mark.asyncio
async def test_a_normal_turn_listens_thinks_speaks_and_returns_to_idle():
    loop, hub, _stt, tts = build()
    turn = await loop.run_turn()
    assert turn.accepted is True
    assert turn.reply == "Jarvis is online."
    assert tts.spoken == ["Jarvis is online."]
    assert hub.terminal.state is TerminalState.IDLE


@pytest.mark.asyncio
async def test_silence_produces_no_ai_call_and_no_speech():
    ai = FakeAI()
    loop, hub, stt, tts = build(pcm=b"\x00\x00" * 16000, ai=ai)
    turn = await loop.run_turn()
    assert turn.accepted is False
    assert turn.reply == ""
    assert tts.spoken == []
    assert ai.calls == 0
    assert stt.calls == 0, "silence must not even reach recognition"
    assert hub.terminal.state is TerminalState.IDLE


@pytest.mark.asyncio
async def test_noise_transcript_produces_no_answer():
    ai = FakeAI()
    loop, _hub, _stt, tts = build(text="Thank you.", ai=ai)
    turn = await loop.run_turn()
    assert turn.accepted is False
    assert turn.reason == "noise_transcript"
    assert ai.calls == 0
    assert tts.spoken == []


@pytest.mark.asyncio
async def test_terminal_returns_to_idle_even_when_listening_fails():
    loop, hub, _stt, _tts = build()
    hub.fail_listen = RuntimeError("device gone")
    with pytest.raises(RuntimeError):
        await loop.run_turn()
    # A turn stuck in LISTENING would gate the next visitor's microphone.
    assert hub.terminal.state is TerminalState.IDLE


@pytest.mark.asyncio
async def test_local_answers_work_without_any_ai_configured():
    # The door terminal must not depend on a model being reachable.
    loop, _hub, _stt, tts = build(text="is jarvis online", ai=None)
    turn = await loop.run_turn()
    assert turn.source == "local"
    assert tts.spoken == ["Jarvis is online."]


@pytest.mark.asyncio
async def test_ai_failure_still_speaks_rather_than_going_silent():
    ai = FakeAI(error=TimeoutError())
    loop, _hub, _stt, tts = build(text="what is the weather like", ai=ai)
    turn = await loop.run_turn()
    assert turn.source == "error"
    assert tts.spoken, "a failed turn must still say something aloud"


@pytest.mark.asyncio
async def test_reply_is_remembered_so_the_next_turn_ignores_its_echo():
    loop, _hub, _stt, _tts = build()
    await loop.run_turn()
    decision = loop.filter.check_transcript("Jarvis is online")
    assert decision.accepted is False
    assert decision.reason == "echo_of_jarvis"


@pytest.mark.asyncio
async def test_turn_passes_through_processing_before_speaking():
    loop, hub, _stt, _tts = build()
    await loop.run_turn()
    states = [target for _, target in hub.terminal.history]
    assert states.index(TerminalState.PROCESSING) < states.index(TerminalState.SPEAKING)


@pytest.mark.asyncio
async def test_local_answers_tolerate_recognition_variance():
    # The same spoken sentence comes back differently run to run; exact phrase
    # matching made the local answers nearly unreachable in practice.
    for heard in (
        "Is Jarvis online?",
        "It's Jarvis Online.",
        "jarvis, are you online",
        "Hey Jarvis are you online?",
    ):
        loop, _hub, _stt, tts = build(text=heard, ai=None)
        turn = await loop.run_turn()
        assert turn.source == "local", heard
        assert turn.reply == "Jarvis is online."
        assert tts.spoken == ["Jarvis is online."]


@pytest.mark.asyncio
async def test_ai_prompt_requests_the_json_shape_the_provider_parses():
    # The shared AIProvider requests format=json and parses the content as
    # JSON, so a prompt asking for prose makes every real answer fail.
    from jarvis_home.devices.voice_loop import SYSTEM_PROMPT

    assert '{"reply"' in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT
