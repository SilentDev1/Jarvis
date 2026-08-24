# Jarvis Home working constraints

- Never erase or flash the AiPi unless every factory recovery gate in
  `docs/AIPI_FACTORY_RECOVERY.md` passes and the owner has authorized the
  physical flash phase.
- Never commit or print factory flash, device credentials, camera credentials,
  visitor media, face data, or captured audio.
- Keep camera/biometric processing local. The voice terminal receives only
  bounded audio, minimal session identifiers, and display/control state.
- Do not introduce door, garage, alarm, arbitrary shell, filesystem, or public
  camera controls.
- Simulator results must never be reported as physical AiPi validation.
