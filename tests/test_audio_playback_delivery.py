import asyncio

"""Delivery guards for streamed playback and the operator playback controls."""

import json

import pytest

from jarvis_home.devices.audio_stream import (
    AUDIO_MAX_STREAM_BYTES,
    AudioStreamError,
    decode_chunk,
)
from jarvis_home.devices.local_protocol import LocalDeviceHub
from jarvis_home.devices.terminal_state import TerminalState


class FakeSocket:
    """Stands in for the device, including reporting end-of-playback.

    A real device answers AUDIO_END with AUDIO_DONE once the speaker has
    actually finished. Without that the hub correctly waits out its timeout, so
    the fake must complete too or every test pays the full wait.
    """

    def __init__(self, fail_on_bytes=False, report_done=True):
        self.text = []
        self.binary = []
        self.fail_on_bytes = fail_on_bytes
        self.report_done = report_done
        self.hub = None

    async def send_text(self, value):
        self.text.append(value)
        if (self.report_done and self.hub is not None
                and json.loads(value)["type"] == "AUDIO_END"):
            self.hub._playback_done.set()

    async def send_bytes(self, value):
        if self.fail_on_bytes:
            raise ConnectionResetError("socket gone")
        self.binary.append(value)


class FakeStore:
    """Counts session use so tests can assert playback stays off the database."""

    def __init__(self):
        self.sessions = 0

    def Session(self):
        self.sessions += 1
        return _NullSession()


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        return None

    def add(self, *args, **kwargs):
        return None

    def commit(self):
        return None


def make_hub(ready=True, socket=None):
    hub = LocalDeviceHub(FakeStore())
    hub.websocket = socket if socket is not None else FakeSocket()
    hub.health.connected = True
    hub.health.ready = ready
    # attach() puts a real connected device in IDLE; these tests set the socket
    # directly, so mirror that rather than leaving the hub in BOOTING.
    hub.terminal.transition(TerminalState.IDLE)
    if isinstance(hub.websocket, FakeSocket):
        hub.websocket.hub = hub
    return hub


def types_sent(socket):
    """Audio protocol messages only.

    Display state sync is orthogonal traffic and interleaves freely; including
    it here would make the audio ordering assertions brittle for no benefit.
    """
    return [
        json.loads(item)["type"]
        for item in socket.text
        if json.loads(item)["type"] != "TERMINAL_STATE"
    ]


def all_types_sent(socket):
    return [json.loads(item)["type"] for item in socket.text]


@pytest.mark.asyncio
async def test_playback_sends_begin_chunks_and_end_in_order():
    socket = FakeSocket()
    hub = make_hub(socket=socket)
    pcm = b"\x01\x02" * 3000
    result = await hub.play_pcm(pcm)
    assert types_sent(socket) == ["AUDIO_BEGIN", "AUDIO_END"]
    assert result["totalBytes"] == len(pcm)
    assert result["totalChunks"] == len(socket.binary)
    # Sequence numbers must be gapless: the device aborts on any gap.
    sequences = [decode_chunk(frame).sequence for frame in socket.binary]
    assert sequences == list(range(len(socket.binary)))
    assert b"".join(decode_chunk(f).payload for f in socket.binary) == pcm


@pytest.mark.asyncio
async def test_playback_requires_a_ready_authenticated_device():
    with pytest.raises(AudioStreamError, match="device_not_ready"):
        await make_hub(ready=False).play_pcm(b"\x00\x00")
    hub = make_hub()
    hub.websocket = None
    with pytest.raises(AudioStreamError, match="device_not_connected"):
        await hub.play_pcm(b"\x00\x00")


@pytest.mark.asyncio
async def test_playback_rejects_empty_misaligned_and_oversized_audio():
    hub = make_hub()
    with pytest.raises(AudioStreamError, match="empty_stream"):
        await hub.play_pcm(b"")
    with pytest.raises(AudioStreamError, match="sample_aligned"):
        await hub.play_pcm(b"\x00\x00\x00")
    with pytest.raises(AudioStreamError, match="stream_too_large"):
        await hub.play_pcm(b"\x00" * (AUDIO_MAX_STREAM_BYTES + 2))


@pytest.mark.asyncio
async def test_failed_send_aborts_so_the_device_drops_the_amplifier():
    socket = FakeSocket(fail_on_bytes=True)
    hub = make_hub(socket=socket)
    with pytest.raises(ConnectionResetError):
        await hub.play_pcm(b"\x01\x02" * 100)
    assert types_sent(socket) == ["AUDIO_BEGIN", "AUDIO_ABORT"]
    # The stream slot must be released, otherwise playback wedges permanently.
    assert hub._audio_active is False


@pytest.mark.asyncio
async def test_only_one_stream_may_be_active():
    hub = make_hub()
    hub._audio_active = True
    with pytest.raises(AudioStreamError, match="stream_already_active"):
        await hub.play_pcm(b"\x00\x00")


@pytest.mark.asyncio
async def test_playback_drives_the_terminal_into_speaking_and_back():
    hub = make_hub()
    assert hub.terminal.state is TerminalState.IDLE
    await hub.play_pcm(b"\x01\x02" * 100)
    # Must return to IDLE so the settling delay starts and the mic can reopen.
    assert hub.terminal.state is TerminalState.IDLE
    assert (TerminalState.IDLE, TerminalState.SPEAKING) in hub.terminal.history


@pytest.mark.asyncio
async def test_microphone_is_closed_for_the_whole_utterance():
    seen = []

    class Watching(FakeSocket):
        async def send_bytes(self, value):
            seen.append(hub.terminal.microphone_allowed())
            await super().send_bytes(value)

    hub = make_hub(socket=Watching())
    await hub.play_pcm(b"\x01\x02" * 2000)
    assert seen and not any(seen), "microphone was open while speaking"


@pytest.mark.asyncio
async def test_failed_playback_still_leaves_speaking_state():
    hub = make_hub(socket=FakeSocket(fail_on_bytes=True))
    with pytest.raises(ConnectionResetError):
        await hub.play_pcm(b"\x01\x02" * 100)
    # A stuck SPEAKING state would keep the microphone closed forever.
    assert hub.terminal.state is TerminalState.IDLE


@pytest.mark.asyncio
async def test_disconnect_moves_the_terminal_offline():
    hub = make_hub()
    await hub.detach("test", hub.websocket)
    assert hub.terminal.state is TerminalState.OFFLINE


@pytest.mark.asyncio
async def test_playback_never_touches_persistence():
    # Streaming audio is a hot path; writing to the database per utterance
    # would put disk IO between chunks.
    hub = make_hub()
    before = hub.store.sessions
    await hub.play_pcm(b"\x01\x02" * 500)
    assert hub.store.sessions == before


@pytest.mark.asyncio
async def test_playback_waits_for_the_device_to_finish_not_just_for_sending():
    # The host finishes sending in milliseconds while the device plays for
    # seconds. Leaving SPEAKING early would reopen the microphone into Jarvis's
    # own voice.
    socket = FakeSocket(report_done=False)
    hub = make_hub(socket=socket)
    hub.terminal.settle_seconds = 0

    async def complete_later():
        await asyncio.sleep(0.05)
        assert hub.terminal.state is TerminalState.SPEAKING, (
            "left SPEAKING before the device reported completion"
        )
        hub._playback_done.set()

    waiter = asyncio.create_task(complete_later())
    await hub.play_pcm(b"\x01\x02" * 100)
    await waiter
    assert hub.terminal.state is TerminalState.IDLE


@pytest.mark.asyncio
async def test_playback_falls_back_if_the_device_never_reports_completion():
    # A device that dies mid-utterance must not wedge SPEAKING forever.
    socket = FakeSocket(report_done=False)
    hub = make_hub(socket=socket)
    audio = b"\x01\x02" * 100
    import jarvis_home.devices.local_protocol as protocol

    original = protocol.duration_seconds
    protocol.duration_seconds = lambda _b: -4.9  # forces an immediate timeout
    try:
        await hub.play_pcm(audio)
    finally:
        protocol.duration_seconds = original
    assert hub.terminal.state is TerminalState.IDLE


@pytest.mark.asyncio
async def test_listen_waits_out_the_settle_delay_instead_of_failing():
    # Listening always follows speaking in a conversation, so the settle delay
    # is expected rather than an error; the microphone still must not open early.
    hub = make_hub()
    hub.terminal.settle_seconds = 0.05
    await hub.play_pcm(b"\x01\x02" * 50)
    hub.terminal.transition(TerminalState.LISTENING)
    assert hub.terminal.microphone_allowed() is False

    async def finish():
        await asyncio.sleep(0.01)
        hub._mic_done.set()

    asyncio.create_task(finish())
    await hub.listen(max_milliseconds=500)
    assert hub.terminal.microphone_allowed() is True


@pytest.mark.asyncio
async def test_display_state_is_pushed_around_playback():
    # The device renders what Jarvis decided rather than inferring it, so the
    # screen cannot disagree with the speaker.
    socket = FakeSocket()
    hub = make_hub(socket=socket)
    await hub.play_pcm(b"\x01\x02" * 100)
    assert "TERMINAL_STATE" in all_types_sent(socket)
    visuals = [
        json.loads(item)["visual"]
        for item in socket.text
        if json.loads(item)["type"] == "TERMINAL_STATE"
    ]
    assert "SPEAKING" in visuals
    assert visuals[-1] == "IDLE"


@pytest.mark.asyncio
async def test_visitor_presence_changes_the_display_state():
    hub = make_hub()
    assert hub.visual_for_state() == "IDLE"
    await hub.set_visitor_present(True)
    assert hub.visual_for_state() == "VISITOR"
    await hub.set_visitor_present(False)
    assert hub.visual_for_state() == "IDLE"


@pytest.mark.asyncio
async def test_an_update_in_progress_outranks_other_display_states():
    # A half-flashed device showing IDLE would be actively misleading.
    hub = make_hub()
    hub.ota.begin("9.9.9", "0.0.0")
    assert hub.visual_for_state() == "UPDATING"


@pytest.mark.asyncio
async def test_display_sync_failure_never_breaks_audio():
    class Broken(FakeSocket):
        async def send_text(self, value):
            if json.loads(value)["type"] == "TERMINAL_STATE":
                raise ConnectionResetError("display sync failed")
            await super().send_text(value)

    hub = make_hub(socket=Broken())
    # Playback must still complete even though every display push fails.
    result = await hub.play_pcm(b"\x01\x02" * 100)
    assert result["totalBytes"] == 200
