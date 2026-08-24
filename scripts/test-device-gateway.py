#!/usr/bin/env python3
"""Authenticated local MCP preflight. This does not test the physical AiPi."""

import asyncio
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    token_file = Path(os.getenv("AIPI_TOKEN_FILE", "data/aipi-device-token.txt"))
    lines = [line.strip() for line in token_file.read_text().splitlines() if line.strip()]
    token = lines[-1]
    if not token.startswith("jdv_"):
        raise RuntimeError("AiPi token file does not end with a device token")
    url = os.getenv("AIPI_MCP_URL", "http://127.0.0.1:8766/mcp")
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=10
        ) as client,
        streamable_http_client(url, http_client=client) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        names = [tool.name for tool in tools.tools]
        expected = [
            "jarvis.frontDoor.recent",
            "jarvis.frontDoor.status",
            "jarvis.status",
        ]
        if sorted(names) != expected:
            raise RuntimeError(f"Unexpected tool allowlist: {names}")
        for name in expected:
            result = await session.call_tool(name, {})
            if result.is_error:
                raise RuntimeError(f"{name} failed")
            speech = (result.structured_content or {}).get("speech")
            print(f"PASS {name}: {speech}")
    print("PASS gateway preflight (physical speaker not tested)")


if __name__ == "__main__":
    asyncio.run(main())
