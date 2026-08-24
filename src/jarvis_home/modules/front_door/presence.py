from dataclasses import dataclass, field

from ...core.providers import Detection


@dataclass
class PresenceObservation:
    presence: str = "UNKNOWN"
    person_count: int | None = None
    observed_at: float | None = None
    source: str = "unavailable"
    detections: list[Detection] = field(default_factory=list)


class PresenceTracker:
    """Turn sampled detections into fresh, debounced current-presence state."""

    def __init__(self, hold_seconds: float = 2.5):
        self.hold_seconds = hold_seconds
        self.last_positive_at: float | None = None
        self.last_positive_detections: list[Detection] = []
        self.current = PresenceObservation()

    def observe(
        self, detections: list[Detection], observed_at: float
    ) -> PresenceObservation:
        people = [item for item in detections if item.label == "person"]
        if people:
            self.last_positive_at = observed_at
            self.last_positive_detections = people
            self.current = PresenceObservation(
                presence="PRESENT",
                person_count=len(people),
                observed_at=observed_at,
                source="live_detection",
                detections=people,
            )
        elif (
            self.last_positive_at is not None
            and observed_at - self.last_positive_at <= self.hold_seconds
        ):
            self.current = PresenceObservation(
                presence="PRESENT",
                person_count=len(self.last_positive_detections),
                observed_at=observed_at,
                source="live_detection_debounced",
                detections=self.last_positive_detections,
            )
        else:
            self.current = PresenceObservation(
                presence="ABSENT",
                person_count=0,
                observed_at=observed_at,
                source="live_detection",
                detections=[],
            )
        return self.current

    def unknown(self, source: str = "unavailable") -> PresenceObservation:
        self.current = PresenceObservation(presence="UNKNOWN", source=source)
        return self.current
