# AiPi integration

AiPi capabilities are deliberately not assumed. On arrival inspect microphone/speaker APIs, onboard STT/TTS, raw streaming, codecs/sample rates, transport, volume, reconnect behavior, latency, and firmware customization. Then implement `AiPiVoiceSatellite`; switch `VOICE_SATELLITE=simulator` to `aipi`. Core, conversation, state, storage, and vision stay unchanged.

