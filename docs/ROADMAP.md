# Roadmap

## Current bounded integration

- Stock AiPi/XDC voice terminal with status and front-door read-only tools
- Local camera, person detection, face identity hints, and bounded event memory
- Per-device authentication, allowlist, health, audit, rate limit, and Hub UI
- Best-frame visitor snapshots, padded face crops, secure thumbnails, and local enrollment

## Owner/account validation

- Verify the two-press AiPi workflow and self-hearing behavior physically
- Connect AiPi by data-capable USB, enter ROM download mode, and complete the
  verified factory backup/recovery gate before any custom flash
- Install pinned ESP-IDF/esptool and build the non-flashed firmware scaffold
- Physically verify display/audio/button pins before enabling hardware drivers
- Add and validate local Whisper STT; then run simulated and physical voice flow
- Enroll a consenting visitor at the door, then verify recognition on return
- Replace the temporary Quick Tunnel with an account-owned named tunnel
- Confirm XDC publish/deploy semantics and physical-device agent assignment

## Future, separately approved work

- Package/uniform classification only after a tested local evidence provider
- Display controls only if the stock XDC API officially exposes them
- Safe HomeSkill queries behind per-device policy
- Action tools only with explicit permission, idempotency, and confirmation

Door/garage access and security-system changes are intentionally out of scope.
