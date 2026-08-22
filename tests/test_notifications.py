from types import SimpleNamespace

from jarvis_home.core.notifications import format_visitor_notification


def test_completed_service_notification():
    session = SimpleNamespace(
        name="John Smith",
        claimed_company="Comcast",
        reason="Internet service",
        visitor_type="service",
        arrival_time="2026-08-22T11:42:00-04:00",
        status="waiting",
        recognized_name=None,
        recognition_confidence=None,
    )
    text = format_visitor_notification(session, True)
    assert "Name: John Smith" in text
    assert "Company claimed: Comcast" in text
    assert "Badge captured: Yes" in text


def test_recognized_person_is_labeled_as_identity_hint():
    session = SimpleNamespace(
        name=None,
        recognized_name="Mike",
        recognition_confidence=0.91,
        claimed_company=None,
        reason="Stopping by",
        visitor_type="friend_family",
        arrival_time="2026-08-22T11:42:00-04:00",
        status="waiting",
    )
    text = format_visitor_notification(session, False)
    assert "Recognized: Mike (91% match; identity hint only)" in text
