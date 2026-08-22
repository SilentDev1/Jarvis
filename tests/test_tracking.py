from jarvis_home.core.providers import Detection
from jarvis_home.modules.front_door.tracking import CentroidTracker, iou


def person(box):
    return Detection("person", 0.9, box)


def test_iou_tracker_keeps_id_during_lateral_motion():
    tracker = CentroidTracker(match_threshold=0.1)
    first = tracker.update([person((0.1, 0.1, 0.4, 0.8))])[0]
    moved = tracker.update([person((0.15, 0.1, 0.45, 0.8))])[0]
    assert moved.track_id == first.track_id
    assert iou(first.box, moved.box) > 0


def test_tracker_keeps_candidate_through_short_occlusion():
    tracker = CentroidTracker(max_missed=2)
    track_id = tracker.update([person((0.1, 0.1, 0.4, 0.8))])[0].track_id
    tracker.update([])
    returned = tracker.update([person((0.1, 0.1, 0.4, 0.8))])[0]
    assert returned.track_id == track_id


def test_tracker_expires_after_long_absence():
    tracker = CentroidTracker(max_missed=1)
    old = tracker.update([person((0.1, 0.1, 0.4, 0.8))])[0].track_id
    tracker.update([])
    tracker.update([])
    new = tracker.update([person((0.1, 0.1, 0.4, 0.8))])[0].track_id
    assert new != old
