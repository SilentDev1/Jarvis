from datetime import datetime


def format_visitor_notification(session, badge_captured: bool) -> str:
    try:
        arrival = (
            datetime.fromisoformat(session.arrival_time)
            .astimezone()
            .strftime("%I:%M %p")
            .lstrip("0")
        )
    except (TypeError, ValueError):
        arrival = session.arrival_time or "Unknown"
    return "\n".join(
        (
            f"Name: {session.name or 'Not provided'}",
            f"Company claimed: {session.claimed_company or 'Not provided'}",
            f"Reason: {session.reason or session.visitor_type}",
            f"Badge captured: {'Yes' if badge_captured else 'No'}",
            f"Arrival: {arrival}",
            f"Status: {session.status.title()}",
        )
    )
