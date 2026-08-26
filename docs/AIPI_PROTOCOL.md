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

## Firmware update messages

Jarvis to device:

- `OTA_OFFER` — `manifest`, `signature`, `url`. Refused unless the session is
  authenticated and the terminal is idle.

Device to Jarvis:

- `OTA_STATUS` — `state`, `percent`, optional `detail`. States are
  DOWNLOADING, VERIFYING, REBOOTING, SUCCEEDED, FAILED, ROLLED_BACK. An
  unrecognised state is treated as a failure rather than guessed at.

`DEVICE_STATUS` additionally reports `otaSlot` and `otaPendingVerify`, so
Jarvis can see which slot is running and whether it is still unconfirmed.

Firmware images are fetched over HTTP from the gateway at
`/firmware/{version}/image`, authenticated with the same device credential as
the WebSocket. Details in `AIPI_OTA.md`.

## Finding Jarvis

The device resolves its configured gateway host, then falls back in order:

1. `getaddrinfo` on the configured name (mDNS for a `.local` name)
2. UDP broadcast discovery on port 8768
3. the last address that worked, cached in NVS

Discovery is a fixed probe, `JARVIS-DISCOVER-V1`, broadcast to port 8768. The
gateway replies with its address and port and nothing else. It is unauthenticated
because it grants nothing: reaching the device WebSocket still requires the
device credential.

This exists because mDNS stopped reaching the device when the host moved from
wireless to wired. Multicast did not cross the segments and the terminal sat
online but unable to find Jarvis, needing a physical power cycle. Broadcast is
forwarded as ordinary link-layer traffic within a subnet.

## Display messages

Jarvis to device:

- `TERMINAL_STATE` — `visual`, one of IDLE, VISITOR, LISTENING, PROCESSING,
  SPEAKING, OFFLINE, CONNECTING, ERROR. The device renders what Jarvis decided
  rather than inferring it. UPDATING is driven locally by OTA progress, which
  is finer grained than anything the host can push.
