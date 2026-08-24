from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class Frame:
    data: object
    timestamp: float
    width: int
    height: int


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]
    track_id: int | None = None


class CameraProvider(ABC):
    @abstractmethod
    async def frames(self) -> AsyncIterator[Frame]: ...
    @abstractmethod
    async def snapshot(self, high_quality=True) -> Frame | None: ...
    @abstractmethod
    def health(self) -> dict: ...


class VisionProvider(ABC):
    @abstractmethod
    async def detect(self, frame: Frame) -> list[Detection]: ...


class AIProvider(ABC):
    @abstractmethod
    async def respond(self, system: str, messages: list[dict], state: dict) -> dict: ...
    @abstractmethod
    async def health(self) -> dict: ...


class VoiceTerminalProvider(ABC):
    async def set_session(self, session_id: str | None) -> None:
        """Associate subsequent terminal operations with a visitor session."""

    @abstractmethod
    async def speak(self, text: str) -> None: ...

    @abstractmethod
    async def start_listening(self) -> None: ...

    @abstractmethod
    async def stop_listening(self) -> None: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def health(self) -> dict: ...


# Compatibility name for integrations that still describe this boundary as a
# satellite. New code should use VoiceTerminalProvider.
VoiceSatellite = VoiceTerminalProvider


class NotificationProvider(ABC):
    @abstractmethod
    async def send(
        self, title: str, body: str, image_path: str | None = None
    ) -> None: ...
