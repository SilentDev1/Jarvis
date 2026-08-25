# Jarvis AiPi custom firmware

`firmware/aipi-jarvis` is version `0.2.0-local`. The controlled stage-1 image
was physically flashed on 2026-08-24 after the factory gate was reverified. It
boots on the exact ESP32-S3 revision 0.2 unit without panic, watchdog, brownout,
or partition errors. The boot log verifies 16 MB QIO flash, 8 MB octal PSRAM at
80 MHz, a passing PSRAM memory test, ESP-IDF 5.3.2, and ES8311 detection at the
expected control-bus address. The owner physically confirmed the `JARVIS /`
`BRING-UP 0.1.0 / CODEC: PASS` screen was visible. A monitored physical press
then produced exactly one `BUTTON_DOWN` and one `BUTTON_UP` transition, 200 ms
apart, confirming the GPIO42 input and debounce path.

The subsequent Wi-Fi image was physically validated on the same unit. Its
display-only setup password and local SoftAP portal successfully provisioned a
WPA3-SAE home connection, saved the credentials in the custom NVS namespace,
restarted automatically, and acquired a DHCP lease on the first connection
attempt. A one-time controlled disconnect/reconnect self-test completed and
persisted its success marker. The owner then held the physical side button
during boot for eight seconds: the device cleared only the custom Jarvis Wi-Fi
namespace, returned to setup mode, accepted fresh provisioning, restarted, and
reconnected. A phone-generated request initially exceeded the default HTTP
header limit; the bounded limit was raised to 2048 bytes and the physical retry
passed. Serial output omitted both the Wi-Fi password and network name.

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
| LCD backlight | 3 | physically verified on this unit |
| ES8311 I2C SCL/SDA | 4/5 | physically verified on this unit by codec probe |
| LCD D/C, CS, SCLK, MOSI, reset | 7/15/16/17/18 | physically verified on this unit |
| speaker amplifier enable | 9 | community corroborated; forced low only |
| function button | 42 | physically verified on this unit |
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
artifacts remain ignored. The stage-1 and Wi-Fi builds and physical flashes
passed.

Audio drivers, authenticated local WebSocket operation, local TTS/STT, and
camera-triggered conversation remain intentionally disabled until each
preceding physical bring-up stage passes. Wi-Fi provisioning, reboot
persistence, reconnect, and deliberate reconfiguration are physically verified.
No Wi-Fi, device, or admin credential is compiled into this image.

## Authenticated local connection

The physical unit now connects directly over the home LAN to the dedicated
Jarvis device gateway on port 8767. The gateway exposes only health and the
versioned device WebSocket; it does not expose the dashboard, admin API, MCP,
shell, filesystem, cameras, or audio. The board resolves the configured local
hostname (`jarvis.local` in the verified setup), authenticates with its own
revocable device password, sends `DEVICE_HELLO`, answers `PING` and
`STATUS_REQUEST`, and reports bounded non-secret health telemetry.

The device password is entered through the local setup portal and stored in the
custom NVS namespace. Jarvis stores only a password hash. Neither side logs the
credential. `scripts/set-aipi-device-password.py` rotates it without displaying
it. `scripts/start-local-device-gateway.sh` advertises the service over mDNS
when the host LAN address can be determined, while the NVS hostname remains the
safe configured fallback.

Physical validation on 2026-08-25 passed boot reconnect, authenticated ONLINE
registration, heartbeat/status telemetry, a controlled Wi-Fi interruption, and
a Jarvis gateway stop/start. The gateway restart exposed a library reconnect
gap; firmware now uses an explicit five-second supervised reconnect loop. The
same powered board then returned ONLINE without rebooting. Speaker, microphone,
STT, TTS, and camera-triggered speech remain disabled in this image.
