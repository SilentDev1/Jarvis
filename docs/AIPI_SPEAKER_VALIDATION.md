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


---

# Network PCM and local TTS physical validation

Date: 2026-08-26 (America/New_York)
Firmware: `0.3.0-audio-stream`
Binary SHA-256: `f0b4f20a943f398cd2a937b9ba9ed2a548092a545218a82230f4cd9185b46075`
Size: 1,026,528 bytes (`0xfa9e0`), 75% of the app partition free

## Result

**NETWORK PCM PHYSICAL: PASS.** **TTS PHYSICAL: PASS.**

The owner heard a streamed 1-second 440 Hz tone and then clearly understood the
synthesized phrase "Jarvis voice terminal online." delivered over the
authenticated LAN WebSocket to the physical speaker. As with the original tone
validation, owner confirmation is what establishes PASS; `result=ESP_OK` and a
successful socket write are not evidence that sound was produced.

## What this proves

The deterministic tone was validated before the spoken phrase deliberately, so
that network transport, protocol framing, streaming, and the speaker path were
proven independently of speech synthesis. Had the phrase failed after the tone
passed, the fault would have been isolated to TTS.

## Canonical format

16 kHz, mono, 16-bit signed PCM, little-endian, 2048-byte chunks (1024 samples,
64 ms). One format is supported deliberately: the ES8311 is physically
validated at it, macOS `say` produces it natively, and Whisper-family
recognition expects it, so nothing in the local path resamples.

Streams are bounded at 30 seconds. Chunks are capped at 4096 bytes and must be
sample-aligned. Control messages (AUDIO_BEGIN / AUDIO_END / AUDIO_ABORT) travel
as JSON; chunks travel as binary frames with an 8-byte header, because base64
would inflate every chunk by a third against a 4 KiB control cap.

## Amplifier fail-safety

GPIO9 is enabled by `audio_playback_begin` and is dropped by
`audio_playback_end`, by `audio_playback_abort`, by every rejecting validation
path in `audio_playback_write`, by the stall watchdog, and by WebSocket
disconnect and reconnect. Malformed input aborts the stream rather than
skipping a chunk: a skipped chunk would glitch and desynchronise the sequence,
and a stream already known malformed has no claim on the amplifier.

## Serial evidence

```text
I (199424) jarvis_audio: speaker amplifier ENABLED
I (199444) jarvis_audio: playback START rate=16000 expected=32000 bytes
I (200464) jarvis_audio: playback END bytes=32000 result=ESP_OK
I (200464) jarvis_audio: speaker amplifier DISABLED
I (205574) jarvis_audio: speaker amplifier ENABLED
I (205584) jarvis_audio: playback START rate=16000 expected=67072 bytes
I (207714) jarvis_audio: playback END bytes=67072 result=ESP_OK
I (207714) jarvis_audio: speaker amplifier DISABLED
```

Tone: 32,000 bytes, amplifier window 1.04 s against 1.000 s of audio.
Speech: 67,072 bytes, amplifier window 2.13 s against 2.096 s of audio.
Both returned `result=ESP_OK` with no abort, underrun, panic, reboot, or
watchdog, and the device stayed ONLINE throughout.

## Local TTS status

`MacSayTTS` is working. The previously recorded FAIL was environment-specific,
not a code defect: in this environment `say` returns 33,536 frames at 16 kHz
mono, peak 28,769, RMS 4,176. The provider still rejects zero-byte output, and
`/internal/speak` rejects empty synthesis with `tts_produced_no_audio` rather
than reporting success with no sound.

Caveat worth remembering: `say` can return a valid header with zero frames when
run without an audio session, which is plausible under launchd. If the gateway
is later moved under a launch agent, re-verify synthesis there rather than
assuming this result carries over.

## Operator controls

`POST /internal/play-test-tone` and `POST /internal/speak` require the admin
token and are additionally restricted to loopback, so exposing the gateway on
the LAN for the terminal never exposes the ability to make the house speak.

## Scope

Speaker output only. Microphone capture, STT, wake word, half-duplex
sequencing, and camera-triggered speech remain disabled and separately gated.


---

# Long-stream reassembly and amplifier fail-safe

Date: 2026-08-26 (America/New_York)
Firmware: `0.3.2-audio-watchdog`
Binary SHA-256: `02c3e9768bb1f167d9dfce6f38bfc717f2727446000144e46c91c0e37b20ce35`

## Defect found after the first streaming PASS

The 2.096-second validation phrase passed, but a deterministic 5-second stream
aborted at 145,408 of 160,000 bytes with `frame_bounds`, with nothing
interfering. `esp_websocket_client` delivers a payload in fragments whenever it
does not arrive in a single read, which happens routinely once a stream runs
past a few seconds. The frame validator rejected any fragmented delivery, so
every utterance longer than roughly four seconds was truncated part-way
through. The short validation phrase was simply too short to expose it.

Fragments are now accumulated into a static buffer sized for exactly one
maximum frame. Reassembly is bounded and allocation-free, so device memory does
not grow with utterance length. A fragment whose offset does not continue the
previous one aborts the stream as `frame_desync` rather than being stitched
into a corrupt frame.

After the fix the same 5-second stream completed: 160,000 bytes,
`result=ESP_OK`, amplifier window 5.04 s against 5.000 s of audio.

## Second defect: the stall watchdog was dead code

`audio_playback_poll_timeout()` was defined but never called, so the stall
timeout could not fire and a wedged sender could have held the amplifier open.
The existing periodic button task now drives it rather than spawning a second
task. The regression test was strengthened: asserting that the watchdog exists
was what allowed dead code to look verified, so the test now asserts it is
actually invoked.

## Disconnect cleanup: PASS

A 28-second utterance (896,000 bytes) was started and the gateway was killed
three seconds in:

```text
I (23574) jarvis_audio: playback START rate=16000 expected=896000 bytes
W (30684) jarvis_local: local Jarvis connection OFFLINE; reconnecting
W (30684) jarvis_audio: playback ABORT reason=connection_lost bytes=227328
I (30684) jarvis_audio: speaker amplifier DISABLED
```

The stream aborted at 227,328 bytes and the amplifier was dropped by the
`connection_lost` path. The device then reconnected without a reboot.

An earlier attempt at this test was inconclusive and is worth recording: a
5-second utterance is buffered by the sender almost instantly (gateway reports
`elapsedSeconds: 0.0`) and paced by device-side I2S, so killing the gateway
one second in did not interrupt anything. Only a stream too large to buffer
exercises the disconnect path. A shorter test would have produced a false PASS.

## Authorization: PASS

`/internal/speak` returns 401 with no token and with a wrong token, and 404
from a non-loopback address, so the endpoint is not even discoverable from the
LAN the terminal sits on.

## Bounds: PASS

A request beyond the 30-second stream limit is rejected before any device
traffic. The tone endpoint's own limit was aligned to the protocol bound rather
than being a second, stricter number, so tests exercise the real boundary.

## Long-utterance physical confirmation: PASS

The owner heard the 3.483-second phrase "Audio streaming and amplifier
fail-safe are verified." (111,446 bytes in 55 chunks) complete through its
final word on firmware `0.3.2-audio-watchdog`. This confirms fragment
reassembly physically, not merely by return code. The equivalent utterance
would have been truncated part-way through on `0.3.0-audio-stream`.

Lesson recorded for future validation: the original 2.096-second validation
phrase passed while the delivery path was still broken for anything longer.
A physical test phrase must exceed the buffer and fragmentation thresholds it
is meant to exercise, otherwise it certifies a path that does not work.


---

# Microphone, streaming, and local STT physical validation

Date: 2026-08-26 (America/New_York)
Firmware: `0.5.1-mic-gain`

## Result

**MICROPHONE: PASS. MIC STREAM: PASS. LOCAL STT: PASS. HALF-DUPLEX: PASS.**

The owner spoke "Jarvis microphone test" to the physical terminal and local
recognition returned it exactly:

```text
attempt 1  peak=9303   rms=0.01530  voiced=0.175  accepted  "microphone test"
attempt 2  peak=21348  rms=0.03563  voiced=0.292  accepted  "Jarvis microphone test"
attempt 3  peak=23164  rms=0.05275  voiced=0.317  rejected  duplicate_utterance
attempt 4  peak=8451   rms=0.01264  voiced=0.168  rejected  duplicate_utterance
```

## Signal quality

Quiet-room noise floor measured peak 205-540. Speech peaked 9,303-23,164, so
the margin over the floor is roughly 20-40x. The loudest sample reached 71% of
full scale, so there is real headroom and no clipping. Captured duration
matched the requested window: a 3-second capture returned 96,256 bytes against
96,000 expected.

## Half-duplex confirmed in practice

Jarvis spoke a prompt immediately before each capture. The transcripts are the
owner's voice, not the prompt, so the microphone did not open until the speaker
had finished and the tail had settled. This is the property that stops the
terminal talking to itself.

## Filtering confirmed in practice

Attempts 3 and 4 recognised the phrase correctly and were still rejected as
duplicates. This is the intended behaviour: one question gets one answer, and a
repeated recognition does not produce a second spoken reply.

## Codec configuration, verified by readback

```text
ADC register 0x14 = 0x1A   analog mic, single ended, PGA gain
ADC register 0x15 = 0x40   ADC ramp
ADC register 0x16 = 0x05   PGA gain scale, 30 dB
ADC register 0x17 = 0xBF   ADC digital volume
ADC register 0x1B = 0x0A   high-pass / DC removal
ADC register 0x1C = 0x6A
```

Register `0x16` was omitted in the first implementation. Espressif's reference
sets it, and without it the analog front end sat near unity: the same quiet
room measured peak 144 instead of 540, and speech would not have cleared the
noise gate. The registers are now read back after initialization rather than
trusted, because a quiet microphone is otherwise indistinguishable from a
register write that did not take.

## Inconclusive result recorded

An earlier run of this test returned silence on three attempts. That was not a
hardware fault: the owner was not at the device. It is recorded because the
measurements looked exactly like a failing microphone, and the correct response
was to ask rather than to start flashing speculative gain increases.

## Scope

Microphone capture and recognition only. Camera-triggered conversation and
multi-turn visitor sessions remain separate phases.


---

# Manual physical voice loop

Date: 2026-08-26 (America/New_York)
Firmware: `0.6.0-voice-turn`

## Result

**MANUAL VOICE LOOP: PASS (software path).** A physical GPIO42 press ran a
complete turn with no cloud involvement:

```text
button press reported to Jarvis
speaker amplifier DISABLED
microphone capture START rate=16000 PCM16
BUTTON_UP
microphone capture END
microphone stream END bytes=192000 reason=complete
speaker amplifier ENABLED
playback START rate=16000 expected=94378 bytes
playback END bytes=94378 result=ESP_OK
speaker amplifier DISABLED
```

```text
button voice turn: accepted=True reason=ok source=ai
  heard='What is the weather?'
  reply="I don't have access to the current weather data."
```

Capture ran 6.0 s (192,000 bytes), recognition and reasoning took about 3.3 s,
and the spoken reply was 2.95 s. Nothing left the machine: recognition is
faster-whisper locally, reasoning is the local Ollama model, synthesis is local.

The amplifier is disabled before the microphone opens and re-enabled only to
speak, visible in the trace above. That ordering is what stops the terminal
hearing itself.

## Defects found by running it, not by inspection

The AI never answered. The shared `AIProvider` requests `format=json` and
parses the model's content as JSON, while the voice prompt asked for a plain
spoken sentence. Every real answer failed to parse and the terminal apologised
instead. The prompt now asks for the shape the provider parses.

Local answers were nearly unreachable. They matched exact phrases, but
recognition of the same sentence varies run to run: "Is Jarvis online?" came
back as "It's Jarvis Online." Matching is now on keyword sets.

Voice turns were invisible in the log. uvicorn configures only its own loggers,
so application records were dropped. A door terminal needs its turns logged, or
a wrong answer leaves no trace to diagnose.

## Still outstanding

The owner has not yet confirmed hearing the spoken reply for this specific
turn, so this is recorded as a software PASS. Camera-triggered greeting,
multi-turn visitor sessions, and false-activation testing are separate phases.
