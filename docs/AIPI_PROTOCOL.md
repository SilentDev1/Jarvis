# Proposed VoiceSatellite protocol

This is a compatibility target, not a claim about AiPi. A secure LAN WebSocket may carry JSON control frames: `hello`, `heartbeat`, `health`, `mute`, `volume`, `speech_text`, `audio_start/chunk/end`, and `speak`; binary frames carry negotiated Opus/PCM. Each connection authenticates, advertises capabilities, sequence numbers, codec/sample rate, and reconnects with backoff. If AiPi provides STT/TTS, text is preferred. If raw audio only, a server provider handles speech services.

