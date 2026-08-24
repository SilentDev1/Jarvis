import httpx


class JarvisStatusSkill:
    def __init__(self, core_url: str, transport=None):
        self.core_url = core_url.rstrip("/")
        self.transport = transport

    async def invoke(self) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=5, transport=self.transport
            ) as client:
                response = await client.get(f"{self.core_url}/health")
                response.raise_for_status()
                health = response.json()
        except (httpx.HTTPError, ValueError):
            return {
                "ok": False,
                "speech": "Jarvis Core is temporarily unavailable.",
                "status": "provider_failure",
            }
        online = health.get("status") == "ready"
        return {
            "ok": online,
            "speech": "Jarvis is online." if online else "Jarvis is not ready.",
            "status": "online" if online else "not_ready",
        }
