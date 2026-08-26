"""Host-side OTA state for the local device.

The terminal is an appliance at a front door. An update that interrupts a
visitor conversation, or that starts while the amplifier is driving the
speaker, is worse than an update that waits, so an offer is refused unless the
terminal is genuinely idle.

Nothing here decides to update on its own. An offer is always the result of an
explicit owner action.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from .terminal_state import TerminalState


class OtaState(StrEnum):
    IDLE = "IDLE"
    OFFERED = "OFFERED"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    REBOOTING = "REBOOTING"
    CONFIRMING = "CONFIRMING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


# Terminal states in which an update may begin. Anything else means a person is
# mid-interaction with the device.
UPDATABLE_STATES = {TerminalState.IDLE}

# An update that has not reported progress in this long is treated as dead, so
# a stalled download cannot pin the terminal in UPDATING forever.
OTA_STALL_SECONDS = 180


@dataclass
class OtaStatus:
    state: OtaState = OtaState.IDLE
    version: str | None = None
    progress: int = 0
    detail: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    previous_version: str | None = None
    history: list[dict] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "state": str(self.state),
            "version": self.version,
            "progress": self.progress,
            "detail": self.detail,
            "previousVersion": self.previous_version,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "history": self.history[-5:],
        }

    def begin(self, version: str, previous: str | None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.state = OtaState.OFFERED
        self.version = version
        self.previous_version = previous
        self.progress = 0
        self.detail = None
        self.started_at = now
        self.updated_at = now

    def advance(self, state: OtaState, progress: int | None = None,
                detail: str | None = None, now: float | None = None) -> None:
        self.state = state
        if progress is not None:
            self.progress = max(0, min(100, progress))
        if detail is not None:
            self.detail = detail
        self.updated_at = time.time() if now is None else now
        if state in (OtaState.SUCCEEDED, OtaState.FAILED, OtaState.ROLLED_BACK):
            self.history.append({
                "version": self.version,
                "state": str(state),
                "detail": self.detail,
                "at": self.updated_at,
            })

    def is_active(self) -> bool:
        return self.state in (
            OtaState.OFFERED, OtaState.DOWNLOADING,
            OtaState.VERIFYING, OtaState.REBOOTING, OtaState.CONFIRMING,
        )

    def is_stalled(self, now: float | None = None) -> bool:
        if not self.is_active() or self.updated_at is None:
            return False
        now = time.time() if now is None else now
        return (now - self.updated_at) > OTA_STALL_SECONDS
