"""Host-side OTA authorisation, gating and state guards."""

import pytest

from jarvis_home.devices.audio_stream import AudioStreamError
from jarvis_home.devices.local_protocol import LocalDeviceHub
from jarvis_home.devices.ota import OtaState, OtaStatus
from jarvis_home.devices.terminal_state import TerminalState


class FakeSocket:
    def __init__(self):
        self.text = []

    async def send_text(self, value):
        self.text.append(value)

    async def send_bytes(self, value):
        pass


class FakeStore:
    def __init__(self):
        self.sessions = 0

    def Session(self):
        self.sessions += 1
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


RECORD = {
    "manifest": {
        "version": "0.9.0", "hardware": "aipi-lite-esp32s3",
        "sha256": "a" * 64, "size": 1_000_000, "buildId": "b1",
        "minimumBootloaderVersion": 1, "channel": "development",
        "deviceId": "aipi-front-door",
    },
    "signature": "ab" * 128,
}


def hub(state=TerminalState.IDLE, version="0.6.0-voice-turn"):
    h = LocalDeviceHub(FakeStore())
    h.websocket = FakeSocket()
    h.health.connected = True
    h.health.ready = True
    h.health.firmware_version = version
    h.terminal.transition(TerminalState.IDLE)
    if state is not TerminalState.IDLE:
        h.terminal.transition(state)
    return h


@pytest.mark.asyncio
async def test_offer_sent_when_idle_and_newer():
    h = hub()
    result = await h.offer_update(RECORD)
    assert result["offered"] == "0.9.0"
    assert h.ota.state is OtaState.OFFERED
    import json
    assert json.loads(h.websocket.text[0])["type"] == "OTA_OFFER"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [
    TerminalState.SPEAKING, TerminalState.LISTENING, TerminalState.PROCESSING,
])
async def test_update_refused_while_the_terminal_is_busy(state):
    # An update that interrupts a visitor is worse than one that waits.
    h = hub(state=state)
    with pytest.raises(AudioStreamError, match="terminal_busy"):
        await h.offer_update(RECORD)


@pytest.mark.asyncio
async def test_update_refused_while_audio_is_streaming():
    h = hub()
    h._audio_active = True
    with pytest.raises(AudioStreamError, match="audio_in_progress"):
        await h.offer_update(RECORD)


@pytest.mark.asyncio
async def test_update_refused_while_the_microphone_is_open():
    h = hub()
    h._mic_stream_id = 1
    with pytest.raises(AudioStreamError, match="audio_in_progress"):
        await h.offer_update(RECORD)


@pytest.mark.asyncio
async def test_disconnected_or_unready_device_is_refused():
    h = hub(); h.websocket = None
    with pytest.raises(AudioStreamError, match="device_not_connected"):
        await h.offer_update(RECORD)
    h = hub(); h.health.ready = False
    with pytest.raises(AudioStreamError, match="device_not_ready"):
        await h.offer_update(RECORD)


@pytest.mark.asyncio
async def test_same_or_older_version_needs_an_explicit_force():
    h = hub(version="0.9.0")
    with pytest.raises(AudioStreamError, match="not_newer"):
        await h.offer_update(RECORD)
    # Still possible, but only when asked for deliberately.
    assert (await h.offer_update(RECORD, force=True))["offered"] == "0.9.0"


@pytest.mark.asyncio
async def test_a_second_update_cannot_start_while_one_is_running():
    h = hub()
    await h.offer_update(RECORD)
    with pytest.raises(AudioStreamError, match="already_active"):
        await h.offer_update(RECORD)


@pytest.mark.asyncio
async def test_a_stalled_update_does_not_block_forever():
    # A device that dies mid-download must not pin the terminal in UPDATING.
    h = hub()
    await h.offer_update(RECORD)
    h.ota.updated_at = 0.0
    assert h.ota.is_stalled() is True
    assert (await h.offer_update(RECORD))["offered"] == "0.9.0"


def test_unknown_device_state_is_treated_as_failure_not_guessed():
    h = hub()
    h.ota.begin("0.9.0", "0.6.0")
    h._handle_ota_message({"type": "OTA_STATUS", "state": "WAT"})
    assert h.ota.state is OtaState.FAILED
    assert "unknown_state" in h.ota.detail


def test_progress_is_clamped_to_a_sane_range():
    status = OtaStatus()
    status.begin("0.9.0", "0.6.0")
    status.advance(OtaState.DOWNLOADING, progress=999)
    assert status.progress == 100
    status.advance(OtaState.DOWNLOADING, progress=-5)
    assert status.progress == 0


def test_terminal_outcomes_are_recorded_in_history():
    status = OtaStatus()
    status.begin("0.9.0", "0.6.0")
    status.advance(OtaState.FAILED, detail="sha256_mismatch")
    assert status.history[-1]["state"] == "FAILED"
    assert status.history[-1]["detail"] == "sha256_mismatch"


def test_ota_is_never_automatic():
    # Nothing may offer an update without an explicit call; there is no timer
    # or watcher that starts one.
    import inspect

    from jarvis_home.devices import local_protocol
    source = inspect.getsource(local_protocol)
    assert "offer_update" in source
    assert "auto_update" not in source
    assert "create_task(self.offer_update" not in source
