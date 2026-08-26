"""Guards on when a camera-triggered greeting may fire.

The terminal speaks to strangers by itself, so the gate matters more than the
greeting. Everything here checks that a greeting does NOT happen: a false
greeting to an empty porch is worse than a missed one.
"""

from jarvis_home.modules.front_door.state import Phase, VisitorStateMachine
from jarvis_home.modules.front_door.zones import classify


def machine(dwell=2.5, grace=4, cooldown=60, timeout=300):
    return VisitorStateMachine(dwell, grace, cooldown, timeout)


def greeted(transition) -> bool:
    return transition.event == "visitor.session_started"


def test_greeting_requires_the_interaction_zone():
    # Someone on the pavement is not at the door.
    for zone in ("observation", "approach"):
        m = machine()
        assert not greeted(m.update(zone, 0))
        assert not greeted(m.update(zone, 100))


def test_greeting_requires_stable_presence_not_a_single_frame():
    m = machine(dwell=2.5)
    assert not greeted(m.update("interaction", 0))
    assert m.phase is Phase.DWELLING
    # A brief detection that vanishes must never have greeted.
    assert not greeted(m.update(None, 1.0))


def test_greeting_fires_once_presence_is_stable():
    m = machine(dwell=2.5)
    m.update("interaction", 0)
    transition = m.update("interaction", 3.0)
    assert greeted(transition)
    assert transition.session_id


def test_a_single_missed_frame_does_not_restart_or_repeat_the_greeting():
    m = machine(dwell=2.5, grace=4)
    m.update("interaction", 0)
    assert greeted(m.update("interaction", 3.0))
    # Camera drops one frame; the visitor has not left.
    m.update(None, 3.5)
    assert not greeted(m.update("interaction", 4.0))


def test_greeting_does_not_repeat_within_the_same_session():
    m = machine(dwell=2.5)
    m.update("interaction", 0)
    assert greeted(m.update("interaction", 3.0))
    for t in (4.0, 5.0, 10.0, 30.0):
        assert not greeted(m.update("interaction", t))


def test_cooldown_blocks_an_immediate_second_greeting():
    m = machine(dwell=2.5, grace=4, cooldown=60)
    m.update("interaction", 0)
    assert greeted(m.update("interaction", 3.0))
    m.update(None, 10.0)
    m.update(None, 20.0)  # beyond grace: session completes
    # Same person steps back to the door straight away.
    assert not greeted(m.update("interaction", 21.0))
    assert not greeted(m.update("interaction", 40.0))


def test_a_later_visitor_is_greeted_once_the_cooldown_expires():
    m = machine(dwell=2.5, grace=4, cooldown=60)
    m.update("interaction", 0)
    m.update("interaction", 3.0)
    m.update(None, 20.0)
    m.update("interaction", 100.0)
    assert greeted(m.update("interaction", 103.0))


def test_session_times_out_rather_than_listening_forever():
    m = machine(dwell=2.5, timeout=300)
    m.update("interaction", 0)
    m.update("interaction", 3.0)
    transition = m.update("interaction", 400.0)
    assert transition.event == "session.timeout"


def test_departure_completes_the_session():
    m = machine(dwell=2.5, grace=4)
    m.update("interaction", 0)
    m.update("interaction", 3.0)
    m.update(None, 4.0)
    transition = m.update(None, 20.0)
    assert transition.event == "visitor.departed"


def test_empty_porch_never_greets():
    m = machine()
    for t in range(0, 600, 10):
        assert not greeted(m.update(None, t))


def test_zone_classification_prefers_the_innermost_zone():
    # A box inside the interaction polygon is also inside the wider approach
    # polygon; it must classify as interaction or the greeting never fires.
    wide = [(0, 0), (100, 0), (100, 100), (0, 100)]
    inner = [(40, 40), (60, 40), (60, 60), (40, 60)]
    zones = {"observation": wide, "approach": wide, "interaction": inner}
    assert classify((45, 45, 55, 55), zones) == "interaction"
    assert classify((5, 5, 15, 15), zones) in ("observation", "approach")
