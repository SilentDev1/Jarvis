# Jarvis AiPi custom firmware

`firmware/aipi-jarvis` is version `0.1.0-bringup`. The controlled stage-1 image
was physically flashed on 2026-08-24 after the factory gate was reverified. It
boots on the exact ESP32-S3 revision 0.2 unit without panic, watchdog, brownout,
or partition errors. The boot log verifies 16 MB QIO flash, 8 MB octal PSRAM at
80 MHz, a passing PSRAM memory test, ESP-IDF 5.3.2, and ES8311 detection at the
expected control-bus address. Visual display orientation/readability and
physical GPIO42 button transitions still require owner observation and are not
yet marked physically verified.

ESP-IDF is selected for native ESP32-S3 bootloader, OTA rollback, NVS, Wi-Fi,
WebSocket/TLS, I2S, and diagnostics support. The intended modules are app/state,
protocol, networking/provisioning, audio/ES8311, display/ST7735, button, OTA,
and diagnostics. Intelligence remains on Jarvis.

The AIPI maker page confirms ESP32-S3, 16 MB flash, 8 MB PSRAM, ES8311, onboard
microphone, and onboard speaker. It links the community hardware audit and says
its exposed-pad map matches internal documentation. Stock logs, two independent
community implementations, and a prior physical validation run corroborate the
internal display, codec, and function-button candidates below. GPIO10 remains
unsafe and is never configured.

| Signal | GPIO | Evidence state |
| --- | ---: | --- |
| LCD backlight | 3 | community + stock-log corroborated; visual check pending |
| ES8311 I2C SCL/SDA | 4/5 | physically verified on this unit by codec probe |
| LCD D/C, CS, SCLK, MOSI, reset | 7/15/16/17/18 | community + stock-log corroborated; visual check pending |
| speaker amplifier enable | 9 | community corroborated; forced low only |
| function button | 42 | community corroborated; press/release check pending |
| board power control | 10 | unverified; never configure |

The custom partition table keeps the original factory NVS bytes at `0x9000`
outside the declared custom layout. Stage-1 flashing wrote only bootloader
`0x0`, partition table `0x8000`, OTA metadata `0x12000`, and application
`0x20000`. The private complete image remains the authoritative factory restore.

Scripts:

- `aipi-info.sh`: read-only chip/flash identification
- `aipi-backup.sh`: double-read full flash and checksum
- `aipi-build.sh`: reproducible ESP-IDF build
- `aipi-flash.sh`: refuses without the recovery marker and explicit authorization
- `aipi-monitor.sh`: serial monitor
- `aipi-restore-factory.sh`: checksum-gated full-image restore
- `aipi-simulator.py`: host protocol simulator only

The maintained ESP-IDF 5.3.2 toolchain is installed outside Git under the
workspace toolchains directory. CMake and Ninja are installed locally. Build
artifacts remain ignored. The stage-1 build and physical flash both passed.

Audio drivers, Wi-Fi provisioning, authenticated local WebSocket operation,
local TTS/STT, and camera-triggered conversation remain intentionally disabled
until each preceding physical bring-up stage passes. No Wi-Fi, device, or admin
credential is compiled into this image.
