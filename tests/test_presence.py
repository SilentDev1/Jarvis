from jarvis_home.core.providers import Detection
from jarvis_home.modules.front_door.presence import PresenceTracker


def person(confidence=0.8):
    return Detection("person", confidence, (0.1, 0.1, 0.8, 0.9))


def test_empty_person_standing_leave_and_return_transitions():
    tracker = PresenceTracker(hold_seconds=2.5)
    assert tracker.observe([], 1).presence == "ABSENT"
    assert tracker.observe([person()], 2).presence == "PRESENT"
    assert tracker.observe([person()], 3).presence == "PRESENT"
    held = tracker.observe([], 4)
    assert held.presence == "PRESENT"
    assert held.source == "live_detection_debounced"
    assert tracker.observe([], 6).presence == "ABSENT"
    assert tracker.observe([person()], 7).presence == "PRESENT"


def test_face_result_is_not_required_for_person_presence():
    observation = PresenceTracker().observe([person()], 1)
    assert observation.presence == "PRESENT"
    assert observation.person_count == 1


def test_unavailable_source_is_explicitly_unknown():
    observation = PresenceTracker().unknown("camera_offline")
    assert observation.presence == "UNKNOWN"
    assert observation.person_count is None
    assert observation.source == "camera_offline"
