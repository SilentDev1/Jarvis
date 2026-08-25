# Jarvis AiPi firmware

Version `0.2.0-local` extends the controlled hardware-validation image. It
initializes serial logging and octal PSRAM, renders a simple ST7735 status
screen, debounces the active-low GPIO42 side button, and probes the ES8311 on
GPIO4/GPIO5. The speaker amplifier is forced off and GPIO10 board power is never
configured. When unconfigured, it creates a temporary WPA2 SoftAP with a random
per-boot password shown only on the physical display and serves a two-field local
portal at `192.168.4.1`. Submitted credentials are length-checked, never logged,
stored only in the custom NVS partition at `0xD000`, and used after an automatic
restart. An eight-second boot hold clears only the Jarvis Wi-Fi namespace.
It also connects to the configured local Jarvis hostname using the
`jarvis.device.v1` WebSocket subprotocol and a dedicated device password stored
in custom NVS. It displays CONNECTING, AUTHENTICATING, ONLINE, and OFFLINE,
reports bounded health telemetry, and retries every five seconds without
rebooting when Jarvis is unavailable. Audio remains disabled.

Do not run `idf.py erase-flash` against the factory device. Build with
`scripts/aipi-build.sh`. The flash wrapper refuses to run unless the separately
verified recovery gate marker exists and explicit flash authorization is set.
