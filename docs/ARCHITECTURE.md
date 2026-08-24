# Architecture

Jarvis Core is a modular application with logical boundaries: events, state, security, devices, AI, notifications, persistence, API/dashboard, and modules. The initial in-process deployment keeps operations simple, while interfaces prevent a monolith from becoming a coupling boundary.

The event bus publishes stable dotted event names and retains bounded recent history. A future MQTT bridge can subscribe without changing publishers. SQLite is authoritative for structured visitor/device/event data; media remains on disk. Providers isolate Tapo/OpenCV, Ollama/OpenClaw, VoiceSatellite, vision, and notifications.

Front Door owns zones, tracking/session lifecycle, concierge policy, badge/package workflows. It cannot execute shell commands or access-control actions. Platform-specific acceleration belongs only in providers. Relative/configured persistent paths make Mac and Linux deployments behaviorally equivalent.

The AiPi device boundary is a separate localhost MCP gateway. Device bearer
credentials are hashed and independent from Hub administrator sessions. An
explicit database-backed `(device, tool)` allowlist maps only named read-only
tools to existing Core services; no generic dispatch exists. The external
tunnel terminates at this gateway, never at the Hub. See
`docs/AIPI_INTEGRATION.md` for its threat boundary, lifecycle, and verification.

The custom-firmware path adds an authenticated local WebSocket boundary inside
Jarvis Core. It is layered as Front Door -> Visitor/Voice services ->
AiPiLocalVoice -> LocalVoiceHub -> WebSocket terminal. It does not replace or
weaken the stock MCP gateway, and it is not externally exposed. See
`AIPI_PROTOCOL.md` and `AIPI_CUSTOM_FIRMWARE.md`.
