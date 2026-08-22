# Architecture

Jarvis Core is a modular application with logical boundaries: events, state, security, devices, AI, notifications, persistence, API/dashboard, and modules. The initial in-process deployment keeps operations simple, while interfaces prevent a monolith from becoming a coupling boundary.

The event bus publishes stable dotted event names and retains bounded recent history. A future MQTT bridge can subscribe without changing publishers. SQLite is authoritative for structured visitor/device/event data; media remains on disk. Providers isolate Tapo/OpenCV, Ollama/OpenClaw, VoiceSatellite, vision, and notifications.

Front Door owns zones, tracking/session lifecycle, concierge policy, badge/package workflows. It cannot execute shell commands or access-control actions. Platform-specific acceleration belongs only in providers. Relative/configured persistent paths make Mac and Linux deployments behaviorally equivalent.

