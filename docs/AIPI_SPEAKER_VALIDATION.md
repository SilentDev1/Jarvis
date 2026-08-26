# AiPi speaker physical validation record

Date: 2026-08-26 (America/New_York)
Unit: physical AiPi Lite, ESP32-S3 revision 0.2, MAC `80:b5:4e:d6:0f:68`
Serial port: `/dev/cu.usbmodem21101`

## Result

**PASS.** The owner audibly confirmed a clear tone from the onboard speaker on
a single monitored right-side GPIO42 press. Owner confirmation, not the
firmware's `ESP_OK` return, is what establishes this PASS.

## Firmware under test

| Field | Value |
| --- | --- |
| Version | `0.2.3-speaker-clock` |
| Binary | `firmware/aipi-jarvis/build/jarvis_aipi.bin` |
| SHA-256 | `f2040d216ee447b78e2d702c7c480e68ef6819bcba742bebee7c5b19da3bb17b` |
| Size | 1,023,968 bytes (`0xf9fe0`) |
| App partition | 75% free |
| Toolchain | ESP-IDF 5.3.2 |

A clean `idf.py build` after the test reproduced a byte-identical binary with
the same SHA-256, proving the committed tree matches the image that was
physically flashed and validated.

## Signal configuration

ES8311 over the ESP-IDF 5.3 modern I2C master API only, at address `0x18` on
SCL GPIO4 / SDA GPIO5 at 100 kHz. One shared bus, one persistent device handle,
no `driver/i2c.h`. I2S standard mode, Philips framing, 16 kHz PCM16, 4.096 MHz
MCLK, stereo slots carrying duplicated mono samples, on MCLK GPIO6, BCLK
GPIO14, WS GPIO12, DOUT GPIO11. Register `0x13 = 0x18` for HP + speaker output;
register `0x04 = 0x20` for the DAC OSR required by Espressif's
`{4096000, 16000}` coefficient entry. Amplifier enable on GPIO9, active-high.

Test stimulus: 880 Hz, 400 ms, PCM amplitude 16,000 of 32,767 full scale, codec
volume capped at 60%, armed only by the authenticated ONLINE connection and
triggered only by one explicit GPIO42 press.

## Serial evidence

```text
I (668) app_init: App version:      0.2.3-speaker-clock
W (684) jarvis_aipi: GPIO10 board-power control is untouched
I (1154) aipi_bringup: speaker amplifier forced OFF for stage-1 validation
I (1154) jarvis_es8311: ES8311 new-I2C probe: PASS
I (1164) jarvis_audio: speaker amplifier DISABLED
I (1174) jarvis_es8311: ES8311 speaker-only init PASS MCLK=4096000 rate=16000 PCM16
I (1174) jarvis_audio: I2S TX ready MCLK=GPIO6 BCLK=GPIO14 WS=GPIO12 DOUT=GPIO11
I (1264) jarvis_aipi: state=CONNECTING display=PASS button=PASS codec=PASS audio=PASS
I (6204) jarvis_local: authenticated local connection ONLINE
I (121554) aipi_bringup: BUTTON_DOWN
I (121554) jarvis_audio: speaker amplifier ENABLED
I (121564) jarvis_audio: one-shot low-volume speaker tone START
I (121994) jarvis_audio: speaker amplifier DISABLED
I (121994) jarvis_audio: one-shot speaker tone END result=ESP_OK
I (122054) aipi_bringup: BUTTON_UP
```

The amplifier window measured 430 ms against the 400 ms tone. No panic, reboot,
brownout, or watchdog occurred. The device remained ONLINE throughout.

## Repository checks at validation time

- Full Python suite: 117 passed
- Speaker regression suite (`tests/test_firmware_modern_es8311.py`): 5 passed
- `git diff --check`: clean
- ESP-IDF build: pass, reproducible hash

## Environment note

The device resolves its gateway as the mDNS name `jarvis.local`. That record is
published by the `dns-sd -P` proxy inside
`scripts/start-local-device-gateway.sh`. When the gateway is started with a bare
`uvicorn` command instead, the name does not resolve, the device logs
`ESP_ERR_ESP_TLS_CANNOT_RESOLVE_HOSTNAME`, never reaches ONLINE, and the test
tone stays disarmed because it is armed only from the WebSocket CONNECTED
handler. Always start the gateway with the script.

## Scope

Speaker output only. Microphone capture, STT, TTS, streamed PCM playback, and
camera-triggered visitor speech remain disabled and are separately gated phases.
