from __future__ import annotations

from dataclasses import dataclass

from ...core.providers import Detection


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    left, top, right, bottom = (
        max(ax1, bx1),
        max(ay1, by1),
        min(ax2, bx2),
        min(ay2, by2),
    )
    intersection = max(0, right - left) * max(0, bottom - top)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0 else 0


@dataclass
class Track:
    id: int
    box: tuple[float, float, float, float]
    missed: int = 0


class CentroidTracker:
    """Small IoU tracker suitable for sparse porch inference frames."""

    def __init__(self, match_threshold=0.2, max_missed=12):
        self.match_threshold = match_threshold
        self.max_missed = max_missed
        self.tracks: dict[int, Track] = {}
        self.next_id = 1

    def update(self, detections: list[Detection]) -> list[Detection]:
        unmatched = set(self.tracks)
        for detection in sorted(
            detections, key=lambda item: item.confidence, reverse=True
        ):
            candidates = [
                (iou(detection.box, self.tracks[track_id].box), track_id)
                for track_id in unmatched
            ]
            score, track_id = max(candidates, default=(0.0, None))
            if track_id is None or score < self.match_threshold:
                track_id = self.next_id
                self.next_id += 1
                self.tracks[track_id] = Track(track_id, detection.box)
            else:
                unmatched.remove(track_id)
                self.tracks[track_id].box = detection.box
                self.tracks[track_id].missed = 0
            detection.track_id = track_id
        for track_id in unmatched:
            self.tracks[track_id].missed += 1
        self.tracks = {
            track_id: track
            for track_id, track in self.tracks.items()
            if track.missed <= self.max_missed
        }
        return detections
