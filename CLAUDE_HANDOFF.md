# Claude handoff — Jarvis Home / AiPi Lite speaker bring-up

Last updated: 2026-08-26 (America/New_York) — speaker phase COMPLETE

## Start here

Continue in this existing repository. Do not create a replacement project.

- Repository: `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home`
- Branch: `main`
- Git remote: `https://github.com/SilentDev1/Jarvis.git`
- Last committed and pushed baseline: `ed59baf feat: connect AiPi over authenticated local gateway`
- ESP-IDF: `/Users/silentd3v/Documents/SilentDev-Workspace/toolchains/esp-idf-v5.3.2`
- ESP-IDF tools: `/Users/silentd3v/Documents/SilentDev-Workspace/toolchains/espressif-tools`
- Physical serial device: `/dev/cu.usbmodem21101`
- Verified device MAC: `80:b5:4e:d6:0f:68`
- Factory recovery backup: `/Users/silentd3v/Documents/SilentDev-Workspace/private-backups/aipi/80b54ed60f68/20260824T192347Z`

The working tree contains intentional, uncommitted speaker-bring-up work. Preserve it. Do not reset, discard, or replace it. Do not claim it is backed up to GitHub until it has been committed and pushed. Commit and push to `origin/main` only after the physical speaker test passes and the repository checks remain green, unless the owner explicitly asks for an earlier checkpoint commit.

Never put passwords, Wi-Fi credentials, device credentials, admin tokens, or `.env` contents in source control, logs, screenshots, or this handoff. The device password and the Jarvis admin password already exist outside tracked source and are not needed for codec debugging.

## Owner's required safety constraints

- Use only ESP-IDF 5.3 modern I2C APIs:
  - `i2c_master_bus_handle_t`
  - `i2c_master_dev_handle_t`
  - `i2c_master_transmit()`
  - `i2c_master_transmit_receive()`
- Never reintroduce `driver/i2c.h` or legacy I2C calls.
- Maintain one shared singleton I2C bus and one persistent ES8311 device handle.
- Do not enable the microphone yet.
- Do not configure or touch GPIO10.
- Do not erase the entire flash and do not run `idf.py erase-flash`.
- Every physical flash must pass the existing recovery gate.
- Keep the amplifier off/muted except during a bounded explicit test.
- No boot-time autoplay and no repeating tone loop.
- Do not proceed to TTS/network speech until the owner audibly confirms the local test tone.

## Verified hardware and services

Physical AiPi Lite:

| Function | GPIO / setting | Verification |
| --- | --- | --- |
| LCD | BL 3, DC 7, CS 15, SCLK 16, MOSI 17, reset 18 | Physically verified |
| Function button | GPIO42, active-low | Physically verified; serial reports down/up |
| ES8311 I2C | SCL 4, SDA 5, address `0x18`, 100 kHz | Physically probed and register writes succeed |
| I2S MCLK | GPIO6 | Physically verified by audible tone |
| Amplifier enable | GPIO9, active-high | Physically verified by audible tone |
| I2S DOUT | GPIO11 | Physically verified by audible tone |
| I2S WS/LRCLK | GPIO12 | Physically verified by audible tone |
| I2S DIN | GPIO13 | Known mapping but deliberately unused |
| I2S BCLK | GPIO14 | Physically verified by audible tone |
| Board power | GPIO10 | Unsafe/unverified; deliberately untouched |

Other physically verified state:

- ESP32-S3 revision 0.2
- 16 MB QIO flash
- 8 MB octal PSRAM at 80 MHz; memory test passes
- display and button pass
- Wi-Fi provisioning, persistence, reconnect, and reset flow pass
- DHCP address observed: `192.168.1.189`
- authenticated local WebSocket reports `ONLINE`
- gateway is a restricted local device gateway; dashboard/admin/camera/shell/filesystem access is not exposed through it

## Work completed in this speaker phase

Current tracked modifications and new files:

- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/CMakeLists.txt`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/CMakeLists.txt`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/aipi_board.h`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/app_main.c`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/bringup.c`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/local_connection.c`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/es8311_codec.c` (new)
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/es8311_codec.h` (new)
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/audio_output.c` (new)
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/main/audio_output.h` (new)
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/tests/test_firmware_modern_es8311.py` (new)

Implementation summary:

1. Replaced the failed legacy ES8311 component integration with a narrow project-local modern-I2C adapter.
2. The codec bus/device are initialized once. ES8311 register access uses the new I2C master driver only.
3. Added speaker-only ES8311 initialization, volume, mute, probe, and register read/write operations.
4. Added I2S standard-mode TX with PCM16 stereo framing containing duplicated mono samples.
5. Added a bounded, manually triggered sine tone and conservative amp/mute sequencing.
6. The tone is permitted only after the authenticated device connection is online.
7. Microphone input remains disabled and GPIO10 remains untouched.
8. Moved I2S/GDMA initialization out of the button-press playback path and increased the button task stack to 6144 bytes.
9. Enabled ES8311 HP+speaker outputs with register `0x13 = 0x18` based on a working AiPi Lite implementation.
10. Corrected the 4.096 MHz / 16 kHz ES8311 DAC OSR value to register `0x04 = 0x20` using Espressif's coefficient table.

Current firmware version physically flashed:

- `0.2.3-speaker-clock`
- binary: `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/build/jarvis_aipi.bin`
- SHA-256: `f2040d216ee447b78e2d702c7c480e68ef6819bcba742bebee7c5b19da3bb17b`
- size: 1,023,968 bytes
- application partition remains 75% free

Current test tone:

- 880 Hz
- 400 ms
- PCM amplitude 16,000 (below full-scale 32,767)
- codec volume capped at 60%
- explicit right-function-button trigger only
- amplifier enabled only during bounded playback

## Failures encountered and resolved

### Legacy I2C conflict

The first speaker attempt pulled in `espressif/es8311`, which used the legacy I2C driver. ESP-IDF panicked because the old and new I2C driver families were linked together. The device was immediately restored to the safe `0.2.0-local` image. The local adapter now contains no legacy driver calls.

### I2S/GDMA watchdog crash

The first modern-I2C speaker build (`0.2.1-speaker-bringup`) initialized I2S/GDMA inside the 2048-byte button task. A press caused an interrupt watchdog panic while allocating the GDMA channel. Backtrace included:

- `gdma_acquire_pair_handle`
- `i2s_init_dma_intr`
- `i2s_channel_init_std_mode`
- `audio_output.c:initialize`
- `bringup.c:button_task`

This is resolved. Audio/I2S now prepare once during startup with the amplifier disabled, and the button task has 6144 bytes of stack. Subsequent button presses complete without crash, reboot, brownout, or watchdog.

### Silent playback attempts

`0.2.1-speaker-bringup` completed software playback but was silent. It used HP-only output (`0x13 = 0x10`), volume 20%, amplitude 1500, and initially also crashed before the preparation fix.

`0.2.2-speaker-route` enabled HP+speaker output (`0x13 = 0x18`), volume 40%, amplitude 6000, and completed playback without error. The owner reported no sound from either physical button. Serial proved GPIO42 triggered the full sequence. The other/left button is not the audio trigger.

During the next audit, the 16 kHz DAC coefficient was found wrong: register `0x04` was `0x10`, but Espressif's `{4096000, 16000}` table entry requires DAC OSR `0x20`. Firmware `0.2.3-speaker-clock` corrects this and raises the still-bounded diagnostic tone to volume 60% and amplitude 16000.

### Resolved: `0.2.3-speaker-clock` is audible

On 2026-08-26 the owner pressed the right GPIO42 button exactly once under serial monitoring on `0.2.3-speaker-clock` and **audibly confirmed a clear tone**. The DAC OSR correction at register `0x04 = 0x20` was the fix. Speaker output is PASS. The full record is in `docs/AIPI_SPEAKER_VALIDATION.md`.

One environment defect surfaced during that test and is worth remembering: the device resolves its gateway as the mDNS name `jarvis.local`, which is published by the `dns-sd -P` proxy inside `scripts/start-local-device-gateway.sh`. The gateway had been started with a bare `uvicorn` command, so the name never resolved, the device logged `ESP_ERR_ESP_TLS_CANNOT_RESOLVE_HOSTNAME`, and it never reached ONLINE. Because `audio_output_set_manual_test_enabled(true)` is called only from the WebSocket CONNECTED handler, the button tone was disarmed and a press would have been silent for reasons unrelated to the codec. Always start the gateway with the script.

## Latest verified boot state

The serial log for `0.2.3-speaker-clock` verified:

- stable boot, no panic/reboot/brownout/watchdog
- `GPIO10 board-power control is untouched`
- ES8311 new-I2C probe PASS at `0x18`
- amplifier disabled during startup
- `ES8311 speaker-only init PASS MCLK=4096000 rate=16000 PCM16`
- `I2S TX ready MCLK=GPIO6 BCLK=GPIO14 WS=GPIO12 DOUT=GPIO11`
- `display=PASS button=PASS codec=PASS audio=PASS`
- Wi-Fi connected at `192.168.1.189`
- authenticated local connection `ONLINE`

For `0.2.2`, monitored button presses produced:

```text
BUTTON_DOWN
speaker amplifier ENABLED
one-shot low-volume speaker tone START
speaker amplifier DISABLED
one-shot speaker tone END result=ESP_OK
BUTTON_UP
```

This proves the silent result is downstream of button handling and high-level I2S writes. It does not prove that MCLK/BCLK/WS/DOUT or GPIO9 electrically toggle on the board.

## Tests and build status

At handoff:

- Full Python suite: `117 passed in 2.63s`
- Speaker regression suite: `5 passed`
- `git diff --check`: pass
- ESP-IDF build of `0.2.3-speaker-clock`: pass
- App binary: `0xf9fe0`; 75% of smallest app partition free

Run from the repository root:

```sh
cd /Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home
./.venv/bin/pytest -q
git diff --check
```

Build environment:

```sh
cd /Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis
export IDF_TOOLS_PATH=/Users/silentd3v/Documents/SilentDev-Workspace/toolchains/espressif-tools
. /Users/silentd3v/Documents/SilentDev-Workspace/toolchains/esp-idf-v5.3.2/export.sh
idf.py build
```

On this managed environment, ESP-IDF/CMake may need approval to read process information through `psutil/sysctl`. Do not work around that by changing project code.

## Safe flash and monitor procedure

Never bypass the wrapper. It validates all factory-backup hashes, the 16 MB image, chip identity, MAC, exact serial port, and recovery base before writing.

```sh
cd /Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home
export IDF_TOOLS_PATH=/Users/silentd3v/Documents/SilentDev-Workspace/toolchains/espressif-tools
export AIPI_PORT=/dev/cu.usbmodem21101
export AIPI_FACTORY_BACKUP_DIR=/Users/silentd3v/Documents/SilentDev-Workspace/private-backups/aipi/80b54ed60f68/20260824T192347Z
export AIPI_EXPECTED_MAC=80:b5:4e:d6:0f:68
export AIPI_ALLOW_CUSTOM_FLASH=YES
. /Users/silentd3v/Documents/SilentDev-Workspace/toolchains/esp-idf-v5.3.2/export.sh
./scripts/aipi-flash.sh
```

Monitor:

```sh
cd /Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home
export IDF_TOOLS_PATH=/Users/silentd3v/Documents/SilentDev-Workspace/toolchains/espressif-tools
export AIPI_PORT=/dev/cu.usbmodem21101
. /Users/silentd3v/Documents/SilentDev-Workspace/toolchains/esp-idf-v5.3.2/export.sh
./scripts/aipi-monitor.sh
```

Quit the serial monitor with Ctrl+]. Stop it before flashing so the port is not held open.

Factory restore instructions are in:

- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/docs/AIPI_FACTORY_RECOVERY.md`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/scripts/aipi-restore-factory.sh`

## References already compared

Working AiPi Lite firmware downloaded temporarily during diagnosis:

- Repository: `https://github.com/delacerda-mrd/Claude-Monitor-AiPi-Lite`
- Temporary checkout used: `/private/tmp/claude-monitor-aipi-reference`
- Relevant file: `/private/tmp/claude-monitor-aipi-reference/main/audio.c`

That implementation physically claims working tones with:

- the same I2C/I2S/amp pin map
- GPIO9 active-high
- 24 kHz, MCLK multiple 256
- standard Philips I2S, stereo slots, duplicated mono
- HP+speaker output via register `0x13 = 0x18`
- RX channel held active to maintain MCLK
- TX data preloaded before channel enable
- amplifier enabled before TX playback
- explicit delay through tone duration before amplifier shutdown

Espressif references:

- `https://github.com/espressif/esp-adf/blob/release/v2.x/components/esp_codec_dev/device/es8311/es8311.c`
- `https://github.com/espressif/esp-idf/tree/master/examples/peripherals/i2s/i2s_codec/i2s_es8311`
- `https://dl.espressif.com/dl/schematics/Audio_ES8311.pdf`

The project-local adapter intentionally ports only the required control behavior to the modern I2C API; do not copy the legacy component's I2C transport.

## What Claude should do next

The speaker bring-up sequence below is COMPLETE. It is retained for provenance.

1. ~~Inspect `git status` and preserve all listed changes.~~ Done.
2. ~~Open a serial monitor for the already-flashed `0.2.3-speaker-clock` image.~~ Done.
3. ~~Confirm `ONLINE`, then ask the owner to press only the right GPIO42 function button once.~~ Done.
4. ~~Capture the complete press/playback log and ask what was heard.~~ Done; owner reported a clear tone.
5. ~~Stop codec debugging, run the full tests/build, document the physical PASS, update stale `0.2.0-local` documentation, then commit and push.~~ Done.

The diagnostic sequence below was NOT needed and was never run. It is retained in case a future audio regression requires it.

If `0.2.3` is still silent, the next diagnostic should be a safe signal-level audit:

- Read back and log ES8311 registers after initialization and again after unmute: at minimum `0x00`–`0x14`, `0x31`, `0x32`, `0x37`, `0x44`, and `0x45`. Compare values against intended writes.
- Confirm I2S runtime clock configuration if the ESP-IDF API exposes it.
- If suitable measuring hardware is available, verify GPIO9, MCLK GPIO6, BCLK GPIO14, WS GPIO12, and DOUT GPIO11 during the one-shot tone. Ask the owner before requiring probes or opening the enclosure.
- Port the known-working 24 kHz profile exactly (6.144 MHz MCLK) if the 16 kHz signals/registers cannot be proven. Keep modern I2C transport.
- Consider matching the known-working DMA pattern: allocate both TX and RX channels, use RX only to maintain MCLK (do not capture/process microphone audio), preload the complete bounded PCM buffer while TX is disabled, enable PA, then enable TX and wait through the full playback duration before muting/disabling.
- Verify whether the external amplifier input is fed by ES8311 HPOUT or differential analog DAC/SPK pins; do not assume register `0x13` alone proves routing.
- Check GPIO9 polarity electrically rather than trying uncontrolled toggles. The working AiPi reference uses active-high, but this exact unit has not been electrically measured.
- Keep every experiment one-shot, bounded, monitored, and nonfatal.

Do not enable local TTS/network audio, microphone capture, STT, wake-word handling, visitor conversation, or broader AiPi permissions until the owner audibly confirms the local tone.

After speaker PASS, the next product phase is:

1. replace the temporary tone-only API with bounded PCM playback primitives;
2. add authenticated gateway-delivered audio with strict size/format limits;
3. implement local/network TTS playback while preserving mute/amp safety;
4. validate disconnect/reconnect and interrupted-audio cleanup;
5. only afterward begin microphone capture as a separate gated phase;
6. integrate camera-triggered visitor conversation only after both output and input audio pass independently.

## Documentation that must be updated after physical PASS

These files still describe audio as disabled or version `0.2.0-local` and must not be updated to claim PASS before the owner hears sound:

- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/docs/AIPI_CUSTOM_FIRMWARE.md`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/firmware/aipi-jarvis/README.md`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/docs/AIPI_AUDIO.md`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/docs/AIPI_INTEGRATION.md`
- `/Users/silentd3v/Documents/SilentDev-Workspace/jarvis-home/docs/AIPI_PROACTIVE_VOICE.md`

Record exact firmware version, binary hash, serial evidence, audible owner confirmation, test counts, and the commit pushed to GitHub.
