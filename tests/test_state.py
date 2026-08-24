from jarvis_home.modules.front_door.state import Phase, VisitorStateMachine


def test_passerby_ignored():
    m = VisitorStateMachine(dwell=2, grace=1)
    m.update("observation", 0)
    m.update(None, 2)
    assert m.phase == Phase.EMPTY and not m.greeted


def test_dwell_and_one_greeting():
    m = VisitorStateMachine(dwell=2)
    assert not m.update("interaction", 0).event
    assert m.update("interaction", 2.1).event == "visitor.session_started"
    assert not m.update("interaction", 3).event


def test_approach_time_does_not_count_as_interaction_dwell():
    m = VisitorStateMachine(dwell=2)
    m.update("observation", 0)
    m.update("approach", 5)
    assert not m.update("interaction", 10).event
    assert m.phase == Phase.DWELLING
    assert m.update("interaction", 12.1).event == "visitor.session_started"


def test_leaving_interaction_resets_confirmation_window():
    m = VisitorStateMachine(dwell=2)
    m.update("interaction", 0)
    m.update("approach", 1)
    assert not m.update("interaction", 2).event
    assert not m.update("interaction", 3).event
    assert m.update("interaction", 4.1).event == "visitor.session_started"


def test_disappearance_grace_reuses_session():
    m = VisitorStateMachine(dwell=1, grace=3)
    m.update("interaction", 0)
    sid = m.update("interaction", 1.1).session_id
    m.update(None, 2)
    assert m.update("interaction", 2.5).session_id == sid


def test_leave_and_cooldown():
    m = VisitorStateMachine(dwell=1, grace=1, cooldown=10)
    m.update("interaction", 0)
    m.update("interaction", 1.1)
    assert m.update(None, 3).event == "visitor.departed"
    assert m.update("interaction", 4).session_id is None
    transition = m.update("interaction", 6)
    assert not transition.event
    assert transition.session_id is None


def test_genuine_return_after_cooldown_gets_new_session():
    m = VisitorStateMachine(dwell=1, grace=1, cooldown=2)
    m.update("interaction", 0)
    first = m.update("interaction", 1.1).session_id
    m.update(None, 3)
    m.update("interaction", 5.1)
    returned = m.update("interaction", 6.2)
    assert returned.event == "visitor.session_started"
    assert returned.session_id != first


def test_timeout():
    m = VisitorStateMachine(dwell=1, timeout=10)
    m.update("interaction", 0)
    assert m.update("interaction", 10).event == "session.timeout"
