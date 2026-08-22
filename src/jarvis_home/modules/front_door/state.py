import uuid
from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    EMPTY = "EMPTY"
    PERSON_DETECTED = "PERSON_DETECTED"
    TRACKING = "TRACKING"
    APPROACHING = "APPROACHING"
    INTERACTION_ZONE = "INTERACTION_ZONE"
    DWELLING = "DWELLING"
    SESSION_STARTED = "SESSION_STARTED"
    GREETING = "GREETING"
    CONVERSATION = "CONVERSATION"
    WAITING_FOR_BADGE = "WAITING_FOR_BADGE"
    WAITING = "WAITING"
    LEAVING = "LEAVING"
    SESSION_COMPLETE = "SESSION_COMPLETE"


@dataclass
class Transition:
    phase: Phase
    event: str | None = None
    session_id: str | None = None


class VisitorStateMachine:
    def __init__(self, dwell=2.5, grace=4, cooldown=60, timeout=300):
        self.dwell = dwell
        self.grace = grace
        self.cooldown = cooldown
        self.timeout = timeout
        self.last_completed = -1e20
        self.reset()

    def reset(self, keep_phase=False):
        if not keep_phase:
            self.phase = Phase.EMPTY
        self.first_seen = self.last_seen = self.started = None
        self.session_id = None
        self.greeted = False

    def update(self, zone, now):
        if self.started is not None and now - self.started >= self.timeout:
            return self.complete(now, "session.timeout")
        if zone is None:
            if self.last_seen is None:
                return Transition(self.phase)
            if now - self.last_seen <= self.grace:
                return Transition(self.phase, session_id=self.session_id)
            if self.session_id:
                return self.complete(now, "visitor.departed")
            self.reset()
            return Transition(self.phase)
        self.last_seen = now
        if self.first_seen is None:
            self.first_seen = now
        if zone == "observation":
            self.phase = Phase.PERSON_DETECTED
        elif zone == "approach":
            self.phase = Phase.APPROACHING
        elif zone == "interaction":
            if not self.session_id:
                self.session_id = str(uuid.uuid4())
                self.started = now
            if now - self.first_seen < self.dwell:
                self.phase = Phase.DWELLING
            elif not self.greeted and now - self.last_completed >= self.cooldown:
                self.greeted = True
                self.phase = Phase.GREETING
                return Transition(
                    self.phase, "visitor.session_started", self.session_id
                )
            else:
                self.phase = Phase.CONVERSATION
        return Transition(self.phase, session_id=self.session_id)

    def request_badge(self):
        self.phase = Phase.WAITING_FOR_BADGE

    def complete(self, now, event="session.completed"):
        sid = self.session_id
        self.last_completed = now
        self.phase = Phase.SESSION_COMPLETE
        r = Transition(self.phase, event, sid)
        self.reset(True)
        return r
