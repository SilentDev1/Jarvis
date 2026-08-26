"""The calibrated front-door zones must keep excluding what they excluded.

These polygons were derived from 22 recorded detections of a person standing
where a visitor stands, then checked against places a person can be without
being a visitor. Both halves matter: a zone that misses the doorstep never
greets, and one that reaches the street greets strangers walking past.
"""

import re
from pathlib import Path

from jarvis_home.modules.front_door.zones import classify, parse_polygon

ROOT = Path(__file__).parents[1]


def zones():
    text = (ROOT / ".env.example").read_text()
    out = {}
    for name in ("observation", "approach", "interaction"):
        m = re.search(rf'^ZONE_{name.upper()}="([^"]+)"', text, re.MULTILINE)
        assert m, f"ZONE_{name.upper()} missing from .env.example"
        out[name] = parse_polygon(m.group(1))
    return out


# Recorded feet positions from the calibration run, as (x1,y1,x2,y2) boxes.
DOOR_STANCE = [
    (0.2154, 0.0634, 0.4108, 0.9925),
    (0.2515, 0.0939, 0.4376, 0.9953),
    (0.2514, 0.1206, 0.3986, 0.9924),
    (0.2537, 0.1113, 0.4016, 0.9872),
    (0.2534, 0.0798, 0.4373, 0.9930),
]

NOT_A_VISITOR = {
    "far down driveway": (0.55, 0.50, 0.62, 0.68),
    "street passer-by": (0.70, 0.50, 0.75, 0.63),
    "neighbours yard": (0.88, 0.52, 0.93, 0.66),
    "mid driveway": (0.50, 0.60, 0.58, 0.85),
    "just past railing": (0.52, 0.62, 0.60, 0.95),
    "right side lawn": (0.80, 0.70, 0.86, 0.95),
    "by the parked car": (0.60, 0.55, 0.70, 0.90),
}


def test_every_recorded_door_stance_is_interaction():
    z = zones()
    for box in DOOR_STANCE:
        assert classify(box, z) == "interaction", box


def test_nobody_outside_the_porch_counts_as_a_visitor():
    z = zones()
    for name, box in NOT_A_VISITOR.items():
        assert classify(box, z) != "interaction", name


def test_zones_reach_the_bottom_edge_of_the_frame():
    # A visitor at the door has their feet on the frame's bottom edge. An
    # earlier polygon stopped at 0.99 and silently excluded exactly them.
    for name, poly in zones().items():
        assert max(y for _, y in poly) >= 1.0, name


def test_sky_is_excluded():
    # A person cannot be in the sky; including it only invites false positives.
    for name, poly in zones().items():
        assert min(y for _, y in poly) >= 0.40, name
