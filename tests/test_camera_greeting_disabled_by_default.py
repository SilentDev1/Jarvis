"""The unprompted greeting must be off until its zones are confirmed.

Camera-triggered greeting makes the house speak to strangers with no human in
the loop. Wrong zones greet passers-by on the street, or household members
crossing a room, which is worse than not greeting at all. So it is opt-in.
"""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_greeting_is_disabled_by_default():
    from jarvis_home.config import Settings

    # Read the declared default rather than the live environment, so a local
    # .env that enables it cannot mask a bad default for everyone else.
    assert Settings.model_fields["camera_greeting_enabled"].default is False


def test_the_trigger_actually_checks_the_flag():
    source = (ROOT / "src" / "jarvis_home" / "app.py").read_text()
    assert "if not cfg.camera_greeting_enabled:" in source
    # It must short-circuit before speaking, not merely log.
    gate = source.split("if not cfg.camera_greeting_enabled:", 1)[1].split(
        "delivered = await voice_service.begin", 1)[0]
    assert "return state" in gate
    assert "greeting_suppressed" in gate


def test_suppression_still_records_the_visitor():
    # Only the speech is withheld. Detection, the session, the snapshot and
    # recognition must keep working, or disabling the greeting would blind the
    # front door entirely.
    source = (ROOT / "src" / "jarvis_home" / "app.py").read_text()
    trigger = source.split("greeting = greeting_policy.greeting(", 1)[0]
    assert "capture_visitor_photo" in trigger
    assert "VisitorSession" in trigger
