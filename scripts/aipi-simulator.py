#!/usr/bin/env python3
"""Development-only AiPi protocol simulator; never represents physical hardware."""

import asyncio
import json
import os
import time

import websockets

SUBPROTOCOL = "jarvis.voice.v1"


async def send(socket, message_type, **payload):
    await socket.send(
        json.dumps(
            {
                "version": 1,
                "type": message_type,
                "id": f"sim-{time.monotonic_ns()}",
                **payload,
            },
            separators=(",", ":"),
        )
    )


async def run():
    url = os.environ.get("JARVIS_VOICE_URL", "ws://127.0.0.1:8765/ws/devices/voice")
    token = os.environ.get("JARVIS_DEVICE_TOKEN")
    if not token:
        raise SystemExit("JARVIS_DEVICE_TOKEN is required and will not be printed")
    headers = {"Authorization": f"Bearer {token}"}
    async with websockets.connect(
        url, additional_headers=headers, subprotocols=[SUBPROTOCOL]
    ) as socket:
        await send(
            socket,
            "DEVICE_HELLO",
            firmware_version="simulator-0.1.0",
            mic_ready=True,
            speaker_ready=True,
        )
        await send(socket, "DEVICE_STATUS", state="IDLE", uptime_seconds=0, wifi_rssi=-42)
        audio_bytes = 0
        async for raw in socket:
            if isinstance(raw, bytes):
                audio_bytes += len(raw)
                continue
            message = json.loads(raw)
            await send(socket, "ACK", reply_to=message.get("id"), ok=True)
            message_type = message.get("type")
            if message_type == "PLAY_AUDIO_START":
                audio_bytes = 0
                await send(socket, "DEVICE_STATUS", state="SPEAKING")
            elif message_type == "PLAY_AUDIO_END":
                print(f"simulated playback complete: {audio_bytes} PCM bytes")
                await send(socket, "DEVICE_STATUS", state="IDLE")
            elif message_type == "START_LISTENING":
                await send(socket, "DEVICE_STATUS", state="LISTENING")
            elif message_type in {"STOP_LISTENING", "RETURN_IDLE"}:
                await send(socket, "DEVICE_STATUS", state="IDLE")


if __name__ == "__main__":
    asyncio.run(run())
