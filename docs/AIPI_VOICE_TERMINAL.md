# AiPi local voice terminal

Status as of 2026-08-26. Firmware `0.6.0-voice-turn`.

## What works, physically confirmed by the owner

- Speaker output (bounded diagnostic tone)
- Streamed network PCM over the authenticated LAN WebSocket
- Local text to speech, spoken through the terminal
- Long utterances beyond the fragmentation threshold
- Microphone capture and local speech recognition
- Half-duplex: the terminal does not hear itself
- A complete manual voice turn: press the button, ask a question, hear the answer

Nothing in that list touches the cloud. Recognition is faster-whisper locally,
reasoning is the local Ollama model, synthesis is local, and the transport is
the home LAN. XDC and Cloudflare are not required for any of it.

## Canonical audio format

16 kHz, mono, 16-bit signed little-endian PCM, 2048-byte chunks (1024 samples,
64 ms). One format on purpose: the ES8311 is validated at it, macOS `say`
produces it natively, and Whisper-family recognition expects it, so nothing in
the local path resamples. Streams are capped at 30 seconds, chunks at 4096
bytes. Firmware constants mirror `devices/audio_stream.py` and a test pins them
together.

## Protocol

Control messages are JSON on the existing authenticated channel: `AUDIO_BEGIN`,
`AUDIO_END`, `AUDIO_ABORT`, `AUDIO_DONE`, `LISTEN_START`, `LISTEN_STOP`,
`MIC_BEGIN`, `MIC_END`, `MIC_ABORT`, `BUTTON_PRESSED`. Audio payloads are
binary frames with an 8-byte header, because base64 in JSON would inflate every
chunk by a third against a 4 KiB control cap.

`AUDIO_DONE` exists because the host finishes sending long before the device
finishes playing. Without it the host would leave SPEAKING while the speaker was
still running and could open the microphone into Jarvis's own voice.

## Terminal state

One authoritative state machine in `devices/terminal_state.py`. Audio, display
and the arc reactor consume it; none keeps a parallel notion of what the
terminal is doing. Half-duplex is a property of the state machine rather than
something each caller must remember: the microphone is permitted only in
LISTENING, and SPEAKING has no edge to LISTENING so the settling delay cannot
be skipped.

## Safety invariants

- The amplifier is enabled only to speak, and is dropped on normal end, abort,
  any rejected chunk, stall timeout, disconnect, and reconnect.
- Malformed audio aborts the stream rather than skipping a chunk: a skipped
  chunk glitches and desynchronises the sequence.
- Capture and playback share one lock on the device, so the microphone cannot
  open while the amplifier drives the speaker even if the host is wrong.
- Silence produces no recognition call, no AI call, and no speech.
- GPIO10 is never configured. `driver/i2c.h` is absent.
- Nothing is stored on the device; captured audio is streamed, not buffered.

## Operator controls

`/internal/speak`, `/internal/listen`, `/internal/play-test-tone` and
`/internal/voice-turn` require the admin token and are restricted to loopback,
so exposing the gateway on the LAN for the terminal never exposes the ability
to make the house speak. They return 401 without a valid token and 404 from any
non-loopback address.

## Configuration

`VOICE_SATELLITE=aipi_gateway` routes the visitor conversation through this
validated path. `aipi_local` selects the older device protocol, which was
designed but never validated against hardware. `aipi_stock` is the XDC cloud
path.

## Not yet validated

Camera-triggered greeting and multi-turn visitor sessions are implemented and
unit-tested but not physically confirmed, because the front-door camera at the
configured address is not currently reachable on the network.

The arc reactor is software only. No GPIO is assigned and it is disabled by
default: the light's voltage, current draw, connector, and type are unknown,
and an ESP32 pin must never source the current a decorative light wants.
