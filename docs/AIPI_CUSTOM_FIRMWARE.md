# Jarvis AiPi custom firmware

`firmware/aipi-jarvis` is version `0.1.0-preflash`: an ESP-IDF scaffold, not a
physical firmware release. It defines the explicit terminal states and protocol
commands. Hardware drivers are intentionally absent because GPIO/audio behavior
has not been verified on this exact unit. The mandatory factory-image gate
passed on 2026-08-24 with two identical full-flash reads and an exact partition
map; no custom firmware has yet been written.

ESP-IDF is selected for native ESP32-S3 bootloader, OTA rollback, NVS, Wi-Fi,
WebSocket/TLS, I2S, and diagnostics support. The intended modules are app/state,
protocol, networking/provisioning, audio/ES8311, display/ST7735, button, OTA,
and diagnostics. Intelligence remains on Jarvis.

Community reports suggest an ESP32-S3 with 16 MB flash and 8 MB PSRAM, 128×128
ST7735 display, ES8311 codec, I2S audio, GPIO42 function button, and GPIO46 LED.
These are research candidates—not authorization to configure pins. The exact
unit must be identified through bootloader/flash inspection and hardware probing
before those drivers are enabled.

Scripts:

- `aipi-info.sh`: read-only chip/flash identification
- `aipi-backup.sh`: double-read full flash and checksum
- `aipi-build.sh`: reproducible ESP-IDF build
- `aipi-flash.sh`: refuses without the recovery marker and explicit authorization
- `aipi-monitor.sh`: serial monitor
- `aipi-restore-factory.sh`: checksum-gated full-image restore
- `aipi-simulator.py`: host protocol simulator only

`esptool` 5.3.1 is installed in the project virtual environment. ESP-IDF
`idf.py` is not yet installed, so the full firmware has not been built. No
firmware has been flashed.
