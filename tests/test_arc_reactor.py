"""Arc reactor behaviour, driven entirely by the authoritative terminal state."""

import math
from array import array

from jarvis_home.devices.arc_reactor import (
    ArcPattern,
    ArcReactorController,
    pcm_envelope,
)
from jarvis_home.devices.terminal_state import TerminalState


def tone(amplitude: int, samples: int = 1600) -> bytes:
    data = array("h", (
        int(amplitude * math.sin(2.0 * math.pi * 440 * i / 16000))
        for i in range(samples)
    ))
    return data.tobytes()


def test_disabled_by_default_because_the_hardware_is_unidentified():
    # Enabling before voltage, current, and driver requirements are known could
    # damage the board.
    assert ArcReactorController().enabled is False
    assert ArcReactorController().frame(TerminalState.IDLE, 0).enabled is False


def test_every_terminal_state_maps_to_a_pattern():
    controller = ArcReactorController()
    for state in TerminalState:
        frame = controller.frame(state, 0.0)
        assert isinstance(frame.pattern, ArcPattern)
        assert 0.0 <= frame.brightness <= 1.0


def test_speaking_is_audio_reactive_and_tracks_level():
    controller = ArcReactorController()
    quiet = controller.frame(TerminalState.SPEAKING, 0.0).brightness
    for _ in range(6):
        controller.observe_audio(tone(24000))
    loud = controller.frame(TerminalState.SPEAKING, 0.1).brightness
    assert loud > quiet
    assert controller.frame(TerminalState.SPEAKING, 0.1).pattern is ArcPattern.AUDIO_REACTIVE


def test_envelope_uses_rms_not_peak():
    # A single loud transient in otherwise quiet audio must not read as loud.
    quiet = array("h", [0] * 1600)
    quiet[0] = 32767
    assert pcm_envelope(quiet.tobytes()) < 0.05
    assert pcm_envelope(tone(32000)) > 0.5


def test_envelope_handles_empty_and_odd_length_input():
    assert pcm_envelope(b"") == 0.0
    assert pcm_envelope(b"\x00") == 0.0
    assert 0.0 <= pcm_envelope(b"\x00\x01\x02") <= 1.0


def test_envelope_attack_is_faster_than_release():
    # The light should snap to speech onsets but not flicker between syllables.
    rising = ArcReactorController()
    rising.observe_audio(tone(30000))
    attack_step = rising.level

    falling = ArcReactorController()
    falling.level = attack_step
    before = falling.level
    falling.observe_audio(tone(0))
    release_step = before - falling.level
    assert attack_step > release_step


def test_waiting_visitor_brightens_idle_but_never_overrides_error():
    controller = ArcReactorController()
    controller.set_visitor_present(True)
    assert controller.frame(TerminalState.IDLE, 0.0).pattern is ArcPattern.BRIGHT_SLOW_PULSE
    assert controller.frame(TerminalState.ERROR, 0.0).pattern is ArcPattern.ERROR_BLINK
    assert controller.frame(TerminalState.LISTENING, 0.0).pattern is ArcPattern.BREATHING


def test_boot_fades_in_rather_than_snapping_on():
    controller = ArcReactorController()
    early = controller.frame(TerminalState.BOOTING, 0.0).brightness
    later = controller.frame(TerminalState.BOOTING, 1.0).brightness
    assert early < later


def test_session_completion_fades_back_to_idle():
    controller = ArcReactorController()
    controller.frame(TerminalState.IDLE, 0.0)
    controller.begin_session_fade(now=10.0)
    assert controller.frame(TerminalState.IDLE, 10.1).pattern is ArcPattern.FADE_TO_IDLE
    bright = controller.frame(TerminalState.IDLE, 10.2).brightness
    dimmer = controller.frame(TerminalState.IDLE, 11.0).brightness
    assert dimmer < bright
    # Once the fade elapses it must fall back to the real state pattern.
    assert controller.frame(TerminalState.IDLE, 12.0).pattern is ArcPattern.DIM_STEADY


def test_offline_is_dimmer_than_idle():
    controller = ArcReactorController()
    offline = controller.frame(TerminalState.OFFLINE, 0.0).brightness
    idle = controller.frame(TerminalState.IDLE, 0.0).brightness
    assert offline < idle


def test_the_module_drives_no_gpio():
    """This Jarvis-side controller computes frames; firmware owns the pin.

    Asserted over the parsed AST rather than the raw text. The previous version
    searched the source for the string "GPIO" and exempted any file containing
    the phrase "GPIO is assigned", so accurate prose about the firmware's pin
    broke it while a comment carrying the magic phrase would have satisfied it
    even if the module really did drive a pin. Comments and docstrings cannot
    affect this check in either direction.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/jarvis_home/devices/arc_reactor.py").read_text())

    hardware_modules = {"machine", "RPi", "gpiozero", "board", "digitalio",
                        "pigpio", "periphery", "smbus", "spidev"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in hardware_modules, (
                    f"arc_reactor imports hardware module {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in hardware_modules, (
                f"arc_reactor imports from hardware module {node.module}")

    # No executable name may look like a pin assignment. Docstrings and
    # comments are not Name nodes, so they are structurally excluded.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assert "gpio" not in node.id.lower(), (
                f"arc_reactor assigns a GPIO-like name: {node.id}")
        if isinstance(node, ast.Attribute):
            assert "gpio" not in node.attr.lower(), (
                f"arc_reactor touches a GPIO-like attribute: {node.attr}")
