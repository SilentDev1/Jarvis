# Jarvis Home

Jarvis Home is a portable, local-first home intelligence platform. Jarvis Core owns events, state, devices, policy, notifications, and provider interfaces. **Front Door** is its first module, not the product boundary.

## Quick start (Mac)

```sh
cd /Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home
./scripts/setup.sh
# edit .env and replace JARVIS_ADMIN_TOKEN
./scripts/doctor.sh
./scripts/start.sh
```

Open <http://127.0.0.1:8765>. Sign in with `JARVIS_ADMIN_USERNAME` and `JARVIS_ADMIN_PASSWORD`; the browser cookie keeps the dashboard signed in for the configured session period. `JARVIS_ADMIN_TOKEN` remains available for scripts and API clients. Test mode needs no camera: click **Start Visitor**, type visitor speech, and continue a multi-turn conversation. Stop with `./scripts/stop.sh`.

## Architecture

Core business logic is platform-neutral Python. `CameraProvider`, `VisionProvider`, `AIProvider`, `VoiceSatellite`, and `NotificationProvider` isolate hardware/services. An in-process event bus can later bridge to MQTT. SQLite and media use configurable persistent paths. The API/dashboard is FastAPI. See [architecture](docs/ARCHITECTURE.md).

Current recommended M4/16 GB configuration is Ollama with `qwen3.5:4b`, Tapo substream for YOLO nano person detection, and the high-resolution main stream for event snapshots. Deterministic policy-safe replies keep the concierge usable when Ollama is down.

`VOICE_SATELLITE` selects the voice terminal: `simulator` (text, no hardware), `aipi_stock` (stock XDC/MCP gateway), `aipi_local` (older protocol, never hardware-validated), or `aipi_gateway` (custom firmware, the physically validated path). The configuration default is `simulator`; **this deployment runs `aipi_gateway`**.

## Live Tapo mode

Enable a Tapo camera account/RTSP credentials in the Tapo app, then run `./scripts/configure-tapo.sh` and `./scripts/test-camera.sh`. The helper stores the hidden password only in excluded `.env`. Jarvis accepts host/user/password and constructs `stream1`/`stream2`, or accepts explicit main/sub URLs instead. Use the dashboard camera canvas to draw and save normalized zones. See [Tapo setup](docs/TAPO_SETUP.md) and the [live test procedure](docs/LIVE_FRONT_DOOR_TEST.md).

Live dependencies are ffmpeg 9.0.1, Tesseract 5.5.3, OpenCV, Ultralytics/YOLO11n, and Ollama `qwen3.5:4b`. `start.sh` starts Ollama only when its API is absent; it never starts a duplicate service.

## Known people and face recognition

Run `./scripts/setup-face-recognition.sh` once to install OpenCV Zoo's local YuNet detector and SFace embedding model. In the dashboard, a homeowner can select **Remember** on a saved visitor photo, provide a name, and later disable or delete that person. The admin token protects enrollment, listing, changes, deletion, and the current-frame recognition test. Face templates are separate `.npy` files under excluded `data/faces/`; they are never uploaded or committed.

Jarvis uses `KNOWN_HIGH_CONFIDENCE`, `POSSIBLE_MATCH`, `UNKNOWN`, and `INSUFFICIENT_FACE`. Only a high-confidence match may influence the greeting. Possible matches stay unnamed. Face matching is a convenience hint and can never authorize access, unlock a door, reveal occupancy, or bypass the action allowlist. Unknown visitors are never automatically enrolled.

## Privacy and security defaults

Event snapshots and transcripts are enabled; raw audio is disabled. The local face provider can be ready, but visitor matching remains dormant until a homeowner explicitly enrolls a person. Jarvis never unlocks doors or exposes household state. Speech/OCR are untrusted; tools are allowlisted and no shell tool exists. The server binds to localhost by default; protected endpoints accept the signed dashboard session cookie or `X-Jarvis-Token` for automation clients.

## Deployment

Mac native mode is best for present hardware acceleration. Docker/Linux deployment uses the same application and persistent `/app/data` and `/app/logs` volumes. All endpoints, models, paths, and device addresses are configuration. See [server migration](docs/SERVER_MIGRATION.md).

## Commands

`setup.sh`, `start.sh`, `stop.sh`, `restart.sh`, `status.sh`, `test.sh`, `doctor.sh`, and `backup.sh` live in `scripts/`. Logs rotate in `logs/jarvis.log`; server output is `logs/server.log`.

## AiPi voice terminal

The custom ESP-IDF firmware in `firmware/aipi-jarvis` is flashed and running on
the physical AiPi Lite. A complete voice turn was validated on hardware on
2026-08-26: a GPIO42 press disables the speaker amplifier, captures 16 kHz PCM16
from the ES8311, recognises speech with local faster-whisper, reasons with the
local Ollama model, then re-enables the amplifier only to speak. Nothing leaves
the machine. Disabling the amplifier before the microphone opens is what stops
the terminal hearing itself.

Build it with `./scripts/aipi-build.sh` (ESP-IDF v5.3.2). `firmware/aipi-jarvis`
is the active path; `../reference/aipi-lite` is a separate upstream MicroPython
reference, not vendored here.

**Not yet supported.** Wi-Fi provisioning: credentials are built in, so changing
network requires a rebuild. Remote wake and remote TTS are unsupported — the
terminal is LAN-only. The WS2812 status light on GPIO46 is implemented but
disabled by default. macOS launchd autostart is deliberately not enabled until
manual operation is proven.

## Status and evidence

[`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) is the authoritative
per-area status. Every claim there is labelled *source*, *build*, *simulator*,
*service integration*, or *hardware* verified, and traced to a path, commit, or
dated physical session. A simulator or build result is never reported as
hardware validation.

At the current commit: 382 Python tests pass, `ruff` and `mypy` are clean over
`src` and `tests`, and the firmware builds (`jarvis_aipi.bin`, 73% of the app
partition free). Package and uniform classification honestly return
*unavailable* — there is no live classifier.

## Recovery

`docs/AIPI_FACTORY_RECOVERY.md` holds the factory gate and restore procedure.
The device is never erased or flashed without those gates passing and explicit
owner authorization.
