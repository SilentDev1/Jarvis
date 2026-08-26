"""Voice terminal backed by the physically validated local device gateway.

The older `AiPiLocalVoice` speaks a device protocol that was designed but never
validated against hardware. This provider drives the path that actually passed
physical validation: authenticated LAN WebSocket, bounded PCM streaming,
half-duplex gating, and local recognition.

The gateway runs as its own process, so this talks to it over loopback using
the same admin-gated internal endpoints an operator uses. That keeps the device
gateway's LAN surface unchanged: exposing it to the terminal never exposes the
ability to make the house speak.
"""

from __future__ import annotations

import contextlib
import logging

import httpx

from ..core.providers import VoiceTerminalProvider

logger = logging.getLogger("jarvis_home.gateway_voice")

# Generous enough to cover synthesis plus the full spoken duration, since the
# gateway now waits for the device to finish playing rather than for the send.
SPEAK_TIMEOUT_SECONDS = 60.0
LISTEN_TIMEOUT_SECONDS = 45.0
HEALTH_TIMEOUT_SECONDS = 3.0


class AiPiGatewayVoice(VoiceTerminalProvider):
    def __init__(self, base_url: str, admin_token: str,
                 listen_milliseconds: int = 6000):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.listen_milliseconds = listen_milliseconds
        self.session_id: str | None = None
        self.last_transcript: str = ""
        self.last_reason: str = ""
        # health() is synchronous in VoiceTerminalProvider, matching the other
        # providers, so the last known state is cached here and refreshed by
        # refresh_health(). Callers that need freshness await that first.
        self._health: dict = {"status": "unknown", "provider": "aipi_gateway"}

    @property
    def _headers(self) -> dict:
        return {"x-jarvis-admin-token": self.admin_token}

    async def set_session(self, session_id: str | None) -> None:
        self.session_id = session_id
        # Tell the terminal a visitor is present so the display wakes before
        # Jarvis speaks, rather than only once audio starts.
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
                await client.post(
                    f"{self.base_url}/internal/visitor",
                    headers=self._headers,
                    json={"present": session_id is not None},
                )

    async def speak(self, text: str) -> None:
        async with httpx.AsyncClient(timeout=SPEAK_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/internal/speak",
                headers=self._headers,
                json={"text": text[:500]},
            )
            response.raise_for_status()

    async def start_listening(self) -> None:
        """Capture and recognise one utterance.

        The result is stored rather than returned, because VoiceTerminalProvider
        models listening as a state change. Callers read `last_transcript`.
        """
        self.last_transcript = ""
        self.last_reason = ""
        async with httpx.AsyncClient(timeout=LISTEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/internal/listen",
                headers=self._headers,
                json={"milliseconds": self.listen_milliseconds},
            )
            response.raise_for_status()
            payload = response.json()
        self.last_reason = str(payload.get("reason", ""))
        if payload.get("accepted"):
            self.last_transcript = str(payload.get("transcript", ""))

    async def stop_listening(self) -> None:
        # Capture is bounded on the device and ends on its own; there is no
        # separate stop to issue, and inventing one would risk racing the
        # in-flight teardown.
        return None

    async def refresh_health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self.base_url}/health")
                payload = response.json()
        except Exception as error:  # noqa: BLE001 - health normalizes transport failures
            self._health = {"status": "unavailable", "provider": "aipi_gateway",
                            "detail": type(error).__name__}
            return self._health
        device = payload.get("device", {})
        terminal = payload.get("terminal", {})
        ready = bool(device.get("connected") and device.get("ready"))
        self._health = {
            "status": "ready" if ready else "offline",
            "provider": "aipi_gateway",
            "firmware_version": device.get("firmware_version"),
            "terminal_state": terminal.get("state"),
            "capabilities": device.get("capabilities", []),
        }
        return self._health

    def is_available(self) -> bool:
        return self._health.get("status") == "ready"

    def health(self) -> dict:
        return dict(self._health)
