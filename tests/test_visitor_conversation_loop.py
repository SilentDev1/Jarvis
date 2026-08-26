"""The spoken visitor conversation must actually advance.

The terminal greeted, listened, stored what it heard, and nothing read it. From
the doorstep that looked like Jarvis ignoring you. These tests pin the loop
that closes it.
"""

from pathlib import Path

from jarvis_home.core.providers import VoiceTerminalProvider

ROOT = Path(__file__).parents[1]
APP = (ROOT / "src" / "jarvis_home" / "app.py").read_text()


def test_recognised_speech_reaches_the_conversation():
    # last_transcript was written by start_listening and read by nobody.
    assert "voice.last_transcript" in APP
    loop = APP.split("async def visitor_conversation_loop(", 1)[1]
    assert "handle_visitor_utterance(sid, transcript)" in loop


def test_the_loop_is_actually_started_after_a_greeting():
    # Defining it is not enough; the greeting path must drive it.
    assert "asyncio.create_task(visitor_conversation_loop(sid))" in APP
    window = APP.split("delivered = await voice_service.begin(", 1)[1][:400]
    assert "visitor_conversation_loop" in window


def test_transcript_is_cleared_before_answering():
    # respond() listens again and overwrites it; a stale transcript left in
    # place would be answered twice.
    loop = APP.split("async def visitor_conversation_loop(", 1)[1]
    assert 'voice.last_transcript = ""' in loop
    assert loop.index('voice.last_transcript = ""') < loop.index("handle_visitor_utterance")


def test_silence_ends_the_session_rather_than_looping():
    loop = APP.split("async def visitor_conversation_loop(", 1)[1]
    assert "if not transcript:" in loop
    assert "no_speech_timeout" in loop


def test_loop_is_bounded():
    # A conversation that cannot end would hold the microphone open forever.
    loop = APP.split("async def visitor_conversation_loop(", 1)[1]
    assert "visitor_conversation_max_turns" in loop
    assert "for _ in range(" in loop


def test_loop_stops_when_the_session_changes_or_ends():
    loop = APP.split("async def visitor_conversation_loop(", 1)[1]
    assert "if sid not in sessions" in loop
    assert "visitor_session_id != sid" in loop


def test_spoken_and_typed_visitors_take_the_same_path():
    # Otherwise policy, persistence and notification could diverge between a
    # real visitor and the simulator.
    assert "async def handle_visitor_utterance(" in APP
    sim = APP.split("async def sim_say(", 1)[1].split("\n\n", 1)[0]
    assert "handle_visitor_utterance(sid, item.text)" in sim


def test_turn_handler_still_enforces_meaningfulness():
    handler = APP.split("async def handle_visitor_utterance(", 1)[1]
    assert "is_meaningful_utterance(text)" in handler
    assert "empty_or_noise_only" in handler


def test_transcript_is_part_of_the_provider_contract():
    # Reading it with getattr would hide a provider that never sets it.
    assert hasattr(VoiceTerminalProvider, "last_transcript")
    assert hasattr(VoiceTerminalProvider, "last_reason")
    assert VoiceTerminalProvider.last_transcript == ""


def loop_body() -> str:
    """The loop's code, with its docstring stripped.

    The docstring names the functions it deliberately does not call, so
    searching the whole block would match the explanation rather than the code.
    """
    block = APP.split("async def visitor_conversation_loop(", 1)[1]
    _, _, after = block.partition('"""')
    _, _, body = after.partition('"""')
    return body.split("\n@app.post", 1)[0]


def test_greeting_deduplication_is_untouched():
    # The loop answers utterances; it must never start a visitor session.
    body = loop_body()
    for trigger in ("voice_service.begin(", "greeting_policy", "session_started"):
        assert trigger not in body
