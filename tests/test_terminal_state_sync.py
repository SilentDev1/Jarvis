"""State synchronisation between Jarvis and the terminal.

Jarvis is authoritative for what the terminal is doing. These tests cover the
ways that authority can go wrong on a real network: reordering, silence, and
reconnection.
"""

import json

import pytest

from jarvis_home.devices.arc_reactor import ArcLightSettings, ArcLightStore
from jarvis_home.devices.local_protocol import LocalDeviceHub
from jarvis_home.devices.terminal_state import TerminalState

ROOT_MAIN = None


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


def make_hub():
    hub = LocalDeviceHub(FakeStore())
    hub.websocket = FakeSocket()
    hub.health.connected = True
    hub.health.ready = True
    hub.terminal.transition(TerminalState.IDLE)
    return hub


def states(hub):
    return [
        json.loads(m) for m in hub.websocket.text
        if json.loads(m)["type"] == "TERMINAL_STATE"
    ]


@pytest.mark.asyncio
async def test_revision_increases_monotonically():
    # Without a monotonic revision, a delayed packet can revert the terminal.
    hub = make_hub()
    await hub.sync_visual()
    await hub.set_visitor_present(True)
    await hub.set_visitor_present(False)
    revisions = [s["revision"] for s in states(hub)]
    assert revisions == sorted(revisions)
    assert len(set(revisions)) == len(revisions)


@pytest.mark.asyncio
async def test_unchanged_state_is_not_resent():
    # The link also carries audio; repeating the same state is pure noise.
    hub = make_hub()
    await hub.sync_visual()
    before = len(states(hub))
    await hub.sync_visual()
    await hub.sync_visual()
    assert len(states(hub)) == before


@pytest.mark.asyncio
async def test_forced_sync_resends_for_resync():
    hub = make_hub()
    await hub.sync_visual()
    before = len(states(hub))
    await hub.sync_visual(force=True)
    assert len(states(hub)) == before + 1


@pytest.mark.asyncio
async def test_every_push_carries_a_timestamp():
    hub = make_hub()
    await hub.sync_visual()
    assert all("timestamp" in s for s in states(hub))


@pytest.mark.asyncio
async def test_visual_reflects_the_authoritative_terminal_state():
    hub = make_hub()
    for state, expected in [
        (TerminalState.SPEAKING, "SPEAKING"),
        (TerminalState.IDLE, "IDLE"),
        (TerminalState.LISTENING, "LISTENING"),
        (TerminalState.PROCESSING, "PROCESSING"),
    ]:
        hub.terminal.transition(state)
        assert hub.visual_for_state() == expected


@pytest.mark.asyncio
async def test_update_outranks_every_other_presentation_state():
    # A half-flashed terminal showing IDLE would be actively misleading.
    hub = make_hub()
    hub.ota.begin("9.9.9", "0.0.0")
    hub.terminal.transition(TerminalState.SPEAKING)
    assert hub.visual_for_state() == "UPDATING"


@pytest.mark.asyncio
async def test_sync_failure_never_propagates():
    class Broken(FakeSocket):
        async def send_text(self, value):
            raise ConnectionResetError("gone")

    hub = make_hub()
    hub.websocket = Broken()
    await hub.sync_visual()          # must not raise
    await hub.push_arc_settings()    # must not raise


# --- owner preference persistence ------------------------------------------


def test_preference_survives_a_restart(tmp_path):
    store = ArcLightStore(tmp_path / "arc.json")
    store.save(ArcLightSettings(enabled=True, idle_brightness=20,
                                active_brightness=60))
    reloaded = ArcLightStore(tmp_path / "arc.json").load()
    assert reloaded.enabled is True
    assert reloaded.idle_brightness == 20
    assert reloaded.active_brightness == 60


def test_explicit_off_survives_a_restart(tmp_path):
    # The whole point of the override: an owner who turned the light off must
    # not find it back on after a gateway restart.
    store = ArcLightStore(tmp_path / "arc.json")
    store.save(ArcLightSettings(enabled=False, idle_brightness=20))
    assert ArcLightStore(tmp_path / "arc.json").load().enabled is False


def test_missing_or_corrupt_preference_defaults_to_off(tmp_path):
    # A corrupt file must not stop the gateway starting, and the safe default
    # for a light at a front door is off.
    assert ArcLightStore(tmp_path / "absent.json").load().enabled is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert ArcLightStore(bad).load().enabled is False
    bad.write_text('["a list"]')
    assert ArcLightStore(bad).load().enabled is False


def test_save_is_atomic(tmp_path):
    # A crash mid-write must not leave a truncated file that reads back as
    # "light off" and silently loses the owner's preference.
    from pathlib import Path
    source = Path("src/jarvis_home/devices/arc_reactor.py").read_text()
    save = source.split("def save(", 1)[1]
    assert "with_suffix" in save
    assert ".replace(self.path)" in save
