import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict
    timestamp: str
    id: str

    @classmethod
    def create(cls, type, payload=None):
        return cls(
            type, payload or {}, datetime.now(UTC).isoformat(), str(uuid.uuid4())
        )

    def dict(self):
        return asdict(self)


class EventBus:
    def __init__(self, max_history=500):
        self.history = deque(maxlen=max_history)
        self.handlers = []

    def subscribe(self, handler: Callable):
        self.handlers.append(handler)

    def publish(self, type, payload=None):
        e = Event.create(type, payload)
        self.history.appendleft(e)
        for h in tuple(self.handlers):
            h(e)
        return e
