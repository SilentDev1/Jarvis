# AiPi display: the Jarvis visual interface

The built-in 128x128 panel is the terminal's face. It renders a glowing energy
core, counter-rotating segmented rings and HUD ticks, with a JARVIS header and
a one-line status.

The visual language is original. It takes the general futuristic
arc-reactor/HUD idiom — concentric rings, segmented arcs, a bright centre — and
deliberately does not reproduce anyone's character artwork or logos.

## One state machine, not two

The display owns no state of its own. Jarvis pushes the authoritative terminal
state as `TERMINAL_STATE` and the device renders it, so the screen cannot
disagree with the speaker or the connection. Device-local events (playback
starting, capture opening) set the visual immediately for responsiveness, and
the host's next push is authoritative.

Visitor presence is a display-only hint. Greeting and session deduplication
remain owned by the front-door state machine; nothing visual can cause Jarvis
to speak.

## States

| State | Core | Rings | Colour |
| --- | --- | --- | --- |
| BOOT | point grows to full | assemble after the core | cyan |
| CONNECTING | steady | both rotate forward | amber |
| IDLE | slow breath | slow drift | dim cyan |
| VISITOR | bright, fast pulse | wake and counter-rotate | bright cyan |
| LISTENING | tracks input level | breathing, level bars | green |
| PROCESSING | steady bright | inner and outer counter-rotate | amber |
| SPEAKING | tracks outgoing PCM | drift, level bars | blue |
| OFFLINE | dim, very slow pulse | slow drift | red |
| UPDATING | steady | outer ring becomes progress | blue |
| ERROR | steady | slow drift | orange |

## Audio reactivity

The core follows the audio actually being played. The envelope is a decimated
peak over the PCM already being written to I2S — every eighth sample, integer
arithmetic only — smoothed with a faster attack than release so it tracks
speech without flickering between syllables.

It allocates nothing, logs nothing and never delays. Audio timing is untouched:
the speaker path is physically validated and the display is not permitted to
put anything in it.

## Rendering

Procedural, not a bundled animation. The firmware stays small and the artwork
reacts to real state and real audio.

Drawing goes to a 32 KB RGB565 framebuffer in internal DMA-capable RAM, pushed
to the panel in sixteen transfers per frame. The previous code issued an SPI
transaction per pixel for text, which is fine for a static screen and hopeless
for animation.

No sqrt or atan2 per pixel: filled shapes compare squared distances, and rings
and arcs walk a fixed 256-entry sine table. Overlapping elements plot
additively so the core reads as light rather than paint.

20 FPS, on a task at priority 2 — below audio, capture and OTA.

## Failure is not fatal

If the framebuffer cannot be allocated or the render task will not start, the
device logs it, disables animation and falls back to the plain text screens.
Voice, network, OTA and power all outrank the display. While the interface owns
the panel the legacy text screens are suppressed, because two writers tear.

## GPIO10

GPIO10 is the board power latch and is asserted before the display starts.
Nothing visual may claim it; a test pins both facts.

## Related fixes

Two reliability problems surfaced while deploying this, both since fixed and
both worth knowing about.

The reconnect loop waited forever on a disconnect notification. Calling
`stop()` then `start()` can return `ESP_OK` while the client never attempts a
connection, so no event fires and the task blocks for good. The loop now times
out and re-checks the real connection state.

mDNS resolution of `jarvis.local` stopped reaching the device when the host
moved from wireless to wired: multicast did not cross the segments. The device
now resolves the name, falls back to UDP broadcast discovery, then to the last
address that worked, caching it in NVS. See `AIPI_PROTOCOL.md`.
