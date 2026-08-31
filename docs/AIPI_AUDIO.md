# AiPi local audio

## Physical codec status

Physical codec playback is VERIFIED as of 2026-08-26 on firmware
`0.2.3-speaker-clock`. The ES8311 drives the onboard speaker over I2S standard
mode at 16 kHz PCM16 with a 4.096 MHz MCLK, and the owner audibly confirmed a
clear bounded test tone. See `AIPI_CUSTOM_FIRMWARE.md` for the register values,
pin evidence, binary hash, and serial log.

Streamed network playback is also VERIFIED as of 2026-08-26 on firmware
`0.3.0-audio-stream`. The owner heard both a deterministic 440 Hz tone and the
intelligible synthesized phrase "Jarvis voice terminal online." delivered from
Jarvis over the authenticated LAN WebSocket to the physical speaker. The
deterministic tone was validated first, on purpose, so that transport,
framing, and the speaker path were proven independently of speech synthesis.

Local TTS is working. The previously recorded FAIL was environment-specific
rather than a code defect. Empty synthesis is still rejected rather than
reported as success.

Microphone capture and STT are **no longer disabled**. That gate was written
before streamed playback passed; playback passed on 2026-08-26 and the
microphone phase then ran on the same unit. A complete physical voice turn is
recorded in `AIPI_SPEAKER_VALIDATION.md` — 6.0 s of 16 kHz PCM16 capture
(192,000 bytes), local faster-whisper recognition, local reasoning, and spoken
reply — with the amplifier disabled before the microphone opens.

## Protocol

Jarvis owns TTS and STT. The terminal streams and plays audio; it does not run
the main AI. The canonical format is PCM signed 16-bit little-endian mono at
16 kHz, in 2048-byte chunks (1024 samples, 64 ms), capped at 4096 bytes per
chunk and 30 seconds per stream. Exactly one format is supported: the ES8311 is
physically validated at it, macOS `say` produces it natively, and
Whisper-family recognition expects it, so nothing in the local path resamples.
See `devices/audio_stream.py`, whose constants the firmware mirrors. The ESP32 implementation must use a
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
