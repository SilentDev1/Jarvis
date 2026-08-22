import numpy as np

from jarvis_home.modules.front_door.media import parse_badge_candidates, select_sharpest


def test_badge_candidates_are_evidence_fields():
    name, company = parse_badge_candidates("COMCAST\nJohn Smith\nTechnician")
    assert name == "John Smith"
    assert company == "COMCAST"


def test_sharpest_frame_selection():
    blurred = np.full((100, 100, 3), 120, dtype=np.uint8)
    sharp = blurred.copy()
    sharp[::2, ::2] = 255
    selected, score = select_sharpest([blurred, sharp])
    assert selected is sharp
    assert score > 0
