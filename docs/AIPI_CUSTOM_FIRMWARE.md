# Jarvis AiPi custom firmware

Firmware is updated over the LAN; see `AIPI_OTA.md`. USB flashing is now only
needed to embed a new OTA signing key, or to recover from a corrupt bootloader
or partition table.

`firmware/aipi-jarvis` is version `0.2.3-speaker-clock`. The controlled stage-1
image was physically flashed on 2026-08-24 after the factory gate was
reverified. It boots on the exact ESP32-S3 revision 0.2 unit without panic,
watchdog, brownout, or partition errors. The boot log verifies 16 MB QIO flash, 8 MB octal PSRAM at
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
| I2S MCLK | 6 | physically verified on this unit by audible tone |
| speaker amplifier enable | 9 | physically verified on this unit by audible tone |
| I2S DOUT | 11 | physically verified on this unit by audible tone |
| I2S WS/LRCLK | 12 | physically verified on this unit by audible tone |
| I2S DIN | 13 | known mapping; deliberately unused |
| I2S BCLK | 14 | physically verified on this unit by audible tone |
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
same powered board then returned ONLINE without rebooting.

## Speaker output — physically validated

Speaker output passed physical validation on 2026-08-26 on this exact unit.

Implementation. The failed `espressif/es8311` component integration was removed
because it linked the legacy I2C driver alongside the new one and panicked the
device. It is replaced by a narrow project-local adapter that uses only the
ESP-IDF 5.3 modern I2C master API: `i2c_master_bus_handle_t`,
`i2c_master_dev_handle_t`, `i2c_master_transmit()`, and
`i2c_master_transmit_receive()`. `driver/i2c.h` and every legacy I2C call are
absent. One shared singleton I2C bus and one persistent ES8311 device handle
are created once at startup.

Signal path. I2S standard mode, Philips framing, 16 kHz PCM16, 4.096 MHz MCLK,
stereo slots carrying duplicated mono samples, on MCLK GPIO6, BCLK GPIO14, WS
GPIO12, and DOUT GPIO11. ES8311 register `0x13 = 0x18` enables HP and speaker
outputs. Register `0x04 = 0x20` sets the DAC OSR required by Espressif's
`{4096000, 16000}` coefficient entry; an earlier `0x10` was wrong and produced
silence. I2S and GDMA are allocated once during startup with the amplifier
disabled. An earlier build allocated them inside a 2048-byte button task and
hit an interrupt watchdog panic in `gdma_acquire_pair_handle`; the button task
now has 6144 bytes of stack and performs no allocation.

Safety envelope. The only audio in this image is one bounded diagnostic tone:
880 Hz, 400 ms, PCM amplitude 16,000 against a 32,767 full scale, codec volume
capped at 60%. It is armed only when the authenticated local connection reaches
ONLINE and is triggered only by an explicit right-side GPIO42 press. There is
no boot-time autoplay and no repeating loop. The GPIO9 amplifier is enabled
only for the playback window and disabled immediately afterward. GPIO10 board
power is never configured and the microphone is never enabled.

Evidence. Binary `build/jarvis_aipi.bin`, SHA-256
`f2040d216ee447b78e2d702c7c480e68ef6819bcba742bebee7c5b19da3bb17b`, 1,023,968
bytes, `0xf9fe0` of the app partition with 75% free. A clean rebuild reproduces
the identical hash, so the tree matches the flashed image. Boot serial verified
`GPIO10 board-power control is untouched`, `ES8311 new-I2C probe: PASS`,
`ES8311 speaker-only init PASS MCLK=4096000 rate=16000 PCM16`, `I2S TX ready
MCLK=GPIO6 BCLK=GPIO14 WS=GPIO12 DOUT=GPIO11`, `display=PASS button=PASS
codec=PASS audio=PASS`, and `authenticated local connection ONLINE`. One
monitored GPIO42 press produced:

```text
BUTTON_DOWN
speaker amplifier ENABLED
one-shot low-volume speaker tone START
speaker amplifier DISABLED
one-shot speaker tone END result=ESP_OK
BUTTON_UP
```

The amplifier window measured 430 ms against the 400 ms tone. No panic,
reboot, brownout, or watchdog occurred and the device stayed ONLINE. The owner
audibly confirmed a clear tone from the physical speaker. That owner
confirmation, not the `ESP_OK` return, is what makes this a PASS.

Microphone capture, STT, TTS, network-delivered audio, and camera-triggered
speech remain disabled in this image.
