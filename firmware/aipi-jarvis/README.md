# Jarvis AiPi firmware

Version `0.1.0-preflash` is a non-flashed ESP-IDF scaffold. It contains the
terminal state machine and protocol constants only. Display, audio, button,
Wi-Fi provisioning, and WebSocket drivers remain intentionally disabled until
the factory backup gate passes and hardware pins are physically verified.

Do not run `idf.py erase-flash` against the factory device. Build with
`scripts/aipi-build.sh`. The flash wrapper refuses to run unless the separately
verified recovery gate marker exists and explicit flash authorization is set.
