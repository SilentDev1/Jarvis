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

Open <http://127.0.0.1:8765>. The dashboard asks for the admin token when a protected simulator action is first used. Test mode needs no camera: click **Start Visitor**, type visitor speech, and continue a multi-turn conversation. Stop with `./scripts/stop.sh`.

## Architecture

Core business logic is platform-neutral Python. `CameraProvider`, `VisionProvider`, `AIProvider`, `VoiceSatellite`, and `NotificationProvider` isolate hardware/services. An in-process event bus can later bridge to MQTT. SQLite and media use configurable persistent paths. The API/dashboard is FastAPI. See [architecture](docs/ARCHITECTURE.md).

Current recommended M4/16 GB configuration is Ollama with `qwen3.5:4b`, Tapo substream for YOLO nano person detection, high-resolution main stream for event snapshots, and the text VoiceSatellite simulator until AiPi is available. Deterministic policy-safe replies keep the concierge usable when Ollama is down.

## Live Tapo mode

Enable a Tapo camera account/RTSP credentials in the Tapo app, copy `.env.example` to `.env`, set `CAMERA_MODE=live`, host/user/password, `VISION_PROVIDER=yolo`, then install `.[vision]`. Jarvis constructs `stream1`/`stream2` URLs unless explicit URLs are supplied. Credentials are masked and excluded from Git. See [Tapo setup](docs/TAPO_SETUP.md).

## Privacy and security defaults

Event snapshots and transcripts are enabled; raw audio and face recognition are disabled. Jarvis never unlocks doors or exposes household state. Speech/OCR are untrusted; tools are allowlisted and no shell tool exists. The server binds to localhost by default and mutating endpoints require `X-Jarvis-Token`.

## Deployment

Mac native mode is best for present hardware acceleration. Docker/Linux deployment uses the same application and persistent `/app/data` and `/app/logs` volumes. All endpoints, models, paths, and device addresses are configuration. See [server migration](docs/SERVER_MIGRATION.md).

## Commands

`setup.sh`, `start.sh`, `stop.sh`, `restart.sh`, `status.sh`, `test.sh`, `doctor.sh`, and `backup.sh` live in `scripts/`. Logs rotate in `logs/jarvis.log`; server output is `logs/server.log`.

