"""Guards for the authoritative terminal state machine and half-duplex."""

import pytest

from jarvis_home.devices.terminal_state import (
    TerminalState,
    TerminalStateError,
    TerminalStateMachine,
)


def machine(state=TerminalState.IDLE, settle=0.4):
    return TerminalStateMachine(state=state, settle_seconds=settle)


def test_speaking_never_transitions_straight_to_listening():
    # The settling delay between them is what prevents self-hearing; allowing
    # the direct edge would let a caller skip it.
    m = machine(TerminalState.SPEAKING)
    with pytest.raises(TerminalStateError, match="illegal_transition"):
        m.transition(TerminalState.LISTENING)


def test_microphone_is_only_allowed_while_listening():
    for state in TerminalState:
        m = machine(state)
        m.last_speaking_ended_at = None
        assert m.microphone_allowed() is (state == TerminalState.LISTENING)


def test_microphone_stays_closed_until_the_speech_tail_has_settled():
    m = machine(TerminalState.SPEAKING, settle=0.4)
    m.transition(TerminalState.IDLE, now=100.0)
    m.transition(TerminalState.LISTENING, now=100.0)
    assert m.microphone_allowed(now=100.1) is False   # tail still decaying
    assert m.microphone_allowed(now=100.2) is False
    assert m.microphone_allowed(now=100.5) is True    # settled


def test_amplifier_is_only_allowed_while_speaking():
    for state in TerminalState:
        assert machine(state).speaker_allowed() is (state == TerminalState.SPEAKING)


def test_offline_and_error_are_reachable_from_every_state():
    for state in TerminalState:
        assert machine(state).can_transition(TerminalState.OFFLINE)
        assert machine(state).can_transition(TerminalState.ERROR)


def test_idle_cannot_jump_backwards_into_boot_or_setup():
    m = machine(TerminalState.IDLE)
    with pytest.raises(TerminalStateError):
        m.transition(TerminalState.BOOTING)


def test_transition_to_same_state_is_a_no_op_and_not_recorded():
    m = machine(TerminalState.IDLE)
    m.transition(TerminalState.IDLE)
    assert m.history == []


def test_normal_conversation_path_is_legal():
    m = machine(TerminalState.BOOTING)
    for target in (
        TerminalState.IDLE,
        TerminalState.LISTENING,
        TerminalState.PROCESSING,
        TerminalState.SPEAKING,
        TerminalState.IDLE,
    ):
        m.transition(target)
    assert m.state is TerminalState.IDLE
    assert len(m.history) == 5


def test_disconnect_mid_speech_recovers_to_idle():
    m = machine(TerminalState.SPEAKING)
    m.transition(TerminalState.OFFLINE)
    m.transition(TerminalState.IDLE)
    assert m.state is TerminalState.IDLE


def test_public_snapshot_reports_gating():
    m = machine(TerminalState.SPEAKING)
    snapshot = m.public()
    assert snapshot["state"] == "SPEAKING"
    assert snapshot["speakerAllowed"] is True
    assert snapshot["microphoneAllowed"] is False
