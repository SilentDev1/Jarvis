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

Enable a Tapo camera account/RTSP credentials in the Tapo app, then run `./scripts/configure-tapo.sh` and `./scripts/test-camera.sh`. The helper stores the hidden password only in excluded `.env`. Jarvis accepts host/user/password and constructs `stream1`/`stream2`, or accepts explicit main/sub URLs instead. Use the dashboard camera canvas to draw and save normalized zones. See [Tapo setup](docs/TAPO_SETUP.md) and the [live test procedure](docs/LIVE_FRONT_DOOR_TEST.md).

Live dependencies are ffmpeg 9.0.1, Tesseract 5.5.3, OpenCV, Ultralytics/YOLO11n, and Ollama `qwen3.5:4b`. `start.sh` starts Ollama only when its API is absent; it never starts a duplicate service. AiPi remains simulated.

## Known people and face recognition

Run `./scripts/setup-face-recognition.sh` once to install OpenCV Zoo's local YuNet detector and SFace embedding model. In the dashboard, a homeowner can select **Remember** on a saved visitor photo, provide a name, and later disable or delete that person. The admin token protects enrollment, listing, changes, deletion, and the current-frame recognition test. Face templates are separate `.npy` files under excluded `data/faces/`; they are never uploaded or committed.

Jarvis uses `KNOWN_HIGH_CONFIDENCE`, `POSSIBLE_MATCH`, `UNKNOWN`, and `INSUFFICIENT_FACE`. Only a high-confidence match may influence the greeting. Possible matches stay unnamed. Face matching is a convenience hint and can never authorize access, unlock a door, reveal occupancy, or bypass the action allowlist. Unknown visitors are never automatically enrolled.

## Privacy and security defaults

Event snapshots and transcripts are enabled; raw audio is disabled. The local face provider can be ready, but visitor matching remains dormant until a homeowner explicitly enrolls a person. Jarvis never unlocks doors or exposes household state. Speech/OCR are untrusted; tools are allowlisted and no shell tool exists. The server binds to localhost by default and mutating or biometric endpoints require `X-Jarvis-Token`.

## Deployment

Mac native mode is best for present hardware acceleration. Docker/Linux deployment uses the same application and persistent `/app/data` and `/app/logs` volumes. All endpoints, models, paths, and device addresses are configuration. See [server migration](docs/SERVER_MIGRATION.md).

## Commands

`setup.sh`, `start.sh`, `stop.sh`, `restart.sh`, `status.sh`, `test.sh`, `doctor.sh`, and `backup.sh` live in `scripts/`. Logs rotate in `logs/jarvis.log`; server output is `logs/server.log`.
