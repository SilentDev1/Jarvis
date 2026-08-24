# AiPi local audio

Jarvis owns TTS and STT. The terminal streams and plays audio; it does not run
the main AI. Protocol v1 uses PCM signed 16-bit little-endian mono, initially at
16 kHz, in frames no larger than 16 KiB. The ESP32 implementation must use a
small bounded queue and report underflow/overflow rather than allocating an
entire response in RAM.

`MacSayTTS` is the current local host implementation. It invokes macOS `say`
without a shell, requests WAVE/PCM16 mono output in a private temporary
directory, validates the format, reads frames, and deletes the file. The audio
is then chunked by the local provider. Physical codec playback remains
unverified. A host validation attempt returned a valid 16 kHz mono WAVE header
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
