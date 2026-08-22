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
    )
    text = format_visitor_notification(session, True)
    assert "Name: John Smith" in text
    assert "Company claimed: Comcast" in text
    assert "Badge captured: Yes" in text
