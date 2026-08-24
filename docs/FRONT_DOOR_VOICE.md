# Front-door local voice

The existing camera pipeline remains authoritative. A greeting is eligible only
after stable presence in the Door Interaction zone, with no active conversation
and cooldown satisfied. Observation and Approach never greet.

`VisitorStateMachine` emits the session event. `VisitorGreetingPolicy` selects
the neutral greeting. `VoiceTerminalService` enforces no-speech, maximum
duration, maximum turns, and departure cleanup. The selected provider may be
stock/fail-closed, simulator, or authenticated local AiPi. Camera frames,
snapshots, face crops, embeddings, identities, and RTSP URLs never enter the
voice protocol.

The custom terminal stays IDLE and silent until Jarvis commands a greeting or
the owner presses the manual button. After speech playback it listens only for
the bounded active session. Departure, timeout, tool completion, protocol error,
or connection loss returns it to IDLE. Physical behavior remains blocked pending
factory backup and flash.
