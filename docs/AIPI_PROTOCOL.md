# Jarvis local voice protocol v1

The custom terminal initiates an authenticated WebSocket connection to
`/ws/devices/voice` using subprotocol `jarvis.voice.v1` and an independently
revocable `aipi-front-door` bearer token. The token is shown once during
provisioning; Jarvis stores only its SHA-256 hash. Normal LAN operation needs no
XDC, MCP, Cloudflare, camera data, or administrator credential.

JSON control messages are limited to 8 KiB and contain `version`, `type`, and a
unique `id`. Commands are acknowledged with `ACK` and `reply_to`. Binary frames
are raw little-endian PCM16 mono and limited to 16 KiB. Incoming session audio
is capped at 4 MB, held only in memory, and cleared at disconnect or after the
future STT handoff.

Server commands:

- `PING`
- `PLAY_AUDIO_START` with codec, sample rate, channels, length, and session ID
- binary PCM chunks
- `PLAY_AUDIO_END`
- `START_LISTENING` with bounded timeout
- `STOP_LISTENING`
- `RETURN_IDLE`
- `SET_DISPLAY_STATE`

Device messages:

- `DEVICE_HELLO` with firmware and hardware-ready flags
- `DEVICE_STATUS` with state, uptime, RSSI, and session
- `ACK`
- `AUDIO_START`, bounded binary PCM chunks, and `AUDIO_END`
- `ERROR`

Malformed versions/types, oversized messages, audio without an active session,
oversized audio, invalid/revoked tokens, and a missing subprotocol fail closed.
Only one front-door terminal may be active. State-changing camera logic never
constructs WebSocket frames; it calls `VoiceTerminalService`, which calls
`AiPiLocalVoice`, which calls the broker.

TLS (`wss`) is required when the connection leaves a trusted segmented LAN.
For initial same-LAN operation, bearer authentication and network isolation are
mandatory; plain `ws` must never be exposed through Tailscale Funnel,
Cloudflare, port forwarding, or the public internet.
