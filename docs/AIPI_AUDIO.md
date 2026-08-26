# AiPi local audio

## Physical codec status

Physical codec playback is VERIFIED as of 2026-08-26 on firmware
`0.2.3-speaker-clock`. The ES8311 drives the onboard speaker over I2S standard
mode at 16 kHz PCM16 with a 4.096 MHz MCLK, and the owner audibly confirmed a
clear bounded test tone. See `AIPI_CUSTOM_FIRMWARE.md` for the register values,
pin evidence, binary hash, and serial log.

That validation covers speaker output only. The firmware currently exposes a
single bounded 880 Hz / 400 ms diagnostic tone gated on the authenticated
ONLINE connection and an explicit GPIO42 press. It does not yet accept streamed
PCM. The protocol below describes the target playback path, not shipped
firmware behavior.

Microphone capture and STT remain disabled on the device and are a separate
gated phase that must not begin until streamed output playback passes on its
own.

## Protocol

Jarvis owns TTS and STT. The terminal streams and plays audio; it does not run
the main AI. Protocol v1 uses PCM signed 16-bit little-endian mono, initially at
16 kHz, in frames no larger than 16 KiB. The ESP32 implementation must use a
small bounded queue and report underflow/overflow rather than allocating an
entire response in RAM.

`MacSayTTS` is the current local host implementation. It invokes macOS `say`
without a shell, requests WAVE/PCM16 mono output in a private temporary
directory, validates the format, reads frames, and deletes the file. The audio
is then chunked by the local provider. A host validation attempt returned a
valid 16 kHz mono WAVE header
but zero audio frames in the current execution environment; the provider now
rejects that output. TTS is therefore FAIL/unavailable until a real local engine
produces non-empty PCM.

No local STT engine is currently installed. `UnavailableSTT` fails closed; it
never converts silence into a tool call. A future Whisper provider must accept
the same `PCM16Audio` interface, run locally, discard temporary audio after
transcription, and pass text through existing meaningful-utterance, duplicate,
and policy checks.

While the device is SPEAKING, microphone streaming must be disabled. After
playback acknowledgement, apply a short settling delay before LISTENING. Barge-in
is intentionally deferred. IDLE never streams microphone audio.
