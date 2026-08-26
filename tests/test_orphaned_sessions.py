"""Visitor sessions must not survive a restart as permanently open."""

from jarvis_home.persistence import Store, VisitorSession, utcnow


def make_store(tmp_path):
    store = Store(tmp_path / "t.db")
    store.init()
    return store


def add(store, sid, status, departure=None):
    with store.Session() as s:
        s.add(VisitorSession(id=sid, arrival_time=utcnow(), status=status,
                             departure_time=departure))
        s.commit()


def statuses(store):
    with store.Session() as s:
        return {v.id: (v.status, v.departure_time) for v in s.query(VisitorSession)}


def close_orphans(store):
    """Mirrors app.close_orphaned_sessions against an isolated store."""
    closed = 0
    with store.Session() as session:
        for visit in session.query(VisitorSession).filter(
            VisitorSession.status == "active"
        ):
            visit.status = "complete"
            visit.departure_time = visit.departure_time or utcnow()
            closed += 1
        if closed:
            session.commit()
    return closed


def test_active_sessions_are_closed_on_startup(tmp_path):
    # The state machine is in memory, so a restart mid-session leaves the row
    # active with nothing tracking it. One such session stayed open four days.
    store = make_store(tmp_path)
    add(store, "orphan", "active")
    assert close_orphans(store) == 1
    status, departure = statuses(store)["orphan"]
    assert status == "complete"
    assert departure is not None


def test_already_complete_sessions_are_untouched(tmp_path):
    store = make_store(tmp_path)
    add(store, "done", "complete", departure="2026-01-01T00:00:00+00:00")
    assert close_orphans(store) == 0
    assert statuses(store)["done"] == ("complete", "2026-01-01T00:00:00+00:00")


def test_existing_departure_time_is_preserved(tmp_path):
    # A session that recorded a departure but never flipped status should keep
    # the real departure time rather than being stamped with the restart time.
    store = make_store(tmp_path)
    add(store, "partial", "active", departure="2026-01-01T00:00:00+00:00")
    close_orphans(store)
    assert statuses(store)["partial"][1] == "2026-01-01T00:00:00+00:00"


def test_app_calls_the_reconciliation_at_startup():
    from pathlib import Path

    source = Path("src/jarvis_home/app.py").read_text()
    assert "def close_orphaned_sessions" in source
    # Defining it is not enough; it must run in lifespan.
    lifespan = source.split("async def lifespan(", 1)[1]
    assert "close_orphaned_sessions()" in lifespan
