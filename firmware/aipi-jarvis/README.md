# Jarvis AiPi firmware

Version `0.3.0-audio-stream` extends the controlled hardware-validation
image. It initializes serial logging and octal PSRAM, renders a simple ST7735
status screen, debounces the active-low GPIO42 side button, and probes the
ES8311 on GPIO4/GPIO5. The speaker amplifier is held off except during one
bounded, explicitly triggered test tone, and GPIO10 board power is never
configured. When unconfigured, it creates a temporary WPA2 SoftAP with a random
per-boot password shown only on the physical display and serves a two-field
local portal at `192.168.4.1`. Submitted credentials are length-checked, never
logged, stored only in the custom NVS partition at `0xD000`, and used after an
automatic restart. An eight-second boot hold clears only the Jarvis Wi-Fi
namespace. It also connects to the configured local Jarvis hostname using the
`jarvis.device.v1` WebSocket subprotocol and a dedicated device password stored
in custom NVS. It displays CONNECTING, AUTHENTICATING, ONLINE, and OFFLINE,
reports bounded health telemetry, and retries every five seconds without
rebooting when Jarvis is unavailable.

Speaker output is physically validated. A project-local ES8311 adapter drives
the codec over the ESP-IDF 5.3 modern I2C master API only; `driver/i2c.h` and
every legacy I2C call are deliberately absent. One shared I2C bus and one
persistent ES8311 device handle are created at startup. I2S standard mode runs
at 16 kHz PCM16 with a 4.096 MHz MCLK, stereo slots carrying duplicated mono
samples, on MCLK GPIO6, BCLK GPIO14, WS GPIO12, and DOUT GPIO11. I2S and GDMA
are initialized once during startup with the amplifier disabled, never inside
the button task.

Streamed playback is physically verified. Jarvis sends AUDIO_BEGIN, binary
chunk frames, and AUDIO_END over the authenticated connection; the device plays
them through the same validated signal path as the diagnostic tone. The
amplifier is dropped on normal end, on abort, on any rejected chunk, on stall
timeout, and on disconnect or reconnect. Microphone capture remains disabled.

The local diagnostic tone remains available: 880 Hz, 400 ms,
PCM amplitude 16,000, codec volume capped at 60%. It is armed solely by the
authenticated local connection reaching ONLINE and is triggered solely by an
explicit right-side GPIO42 press. There is no boot-time autoplay and no
repeating loop. The GPIO9 amplifier is enabled only for the playback window and
disabled immediately afterward.

Microphone capture, STT, TTS, and network-delivered audio remain disabled.

Do not run `idf.py erase-flash` against the factory device. Build with
`scripts/aipi-build.sh`. The flash wrapper refuses to run unless the separately
verified recovery gate marker exists and explicit flash authorization is set.
