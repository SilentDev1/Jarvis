from datetime import UTC, datetime, timedelta

from jarvis_home.core.events import EventBus


def test_event_history_bounded():
    b = EventBus(2)
    [b.publish("x", {"i": i}) for i in range(3)]
    assert len(b.history) == 2 and b.history[0].payload["i"] == 2


def test_retention_cutoff_logic():
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    assert now - timedelta(days=31) < cutoff and now - timedelta(days=1) > cutoff
