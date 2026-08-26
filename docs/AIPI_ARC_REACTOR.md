# AiPi arc reactor light

The terminal has a physical status light that follows the same authoritative
Jarvis state as the display, so the two can never disagree.

## The light in use today

The AiPi Lite carries an **onboard single-pixel WS2812 addressable RGB LED on
GPIO46**. It is wired and powered by the board, so it needs no external
circuitry: no MOSFET, no separate supply, no connector, no level shifter.

That was found rather than assumed. It is documented by the known-working AiPi
Lite reference firmware (`LED : WS2812 on GPIO46 (1 pixel)`, driven with
`led_strip_new_rmt_device`) and by this project's own hardware notes, and it is
now physically confirmed: the owner watched it go dark and bright under
firmware control, then follow live Jarvis states.

| Property | Value |
| --- | --- |
| Type | Addressable RGB, WS2812, single pixel |
| Location | Onboard, GPIO46 |
| Supply | Board's own rail; no external supply |
| Control | RMT via `espressif/led_strip` |
| Driver circuit | None required; the LED is already driven on-board |
| External wiring | None |
| Brightness cap | 80% of full scale, enforced in firmware |

Current draw is not independently measured here. A WS2812 is roughly 60 mA at
full white; the firmware caps output at 80% and typical states sit far below
that, and a three-minute soak showed no brownout, no heap movement and no
effect on Wi-Fi or audio.

GPIO46 is a strapping pin on the ESP32-S3, sampled only at reset. Driving it as
an output afterwards is normal and is what the reference firmware does.

## GPIO safety

GPIO10 is the board power latch and is not touched by anything visual. The
display, audio, I2C, I2S, button and latch pins are all excluded. No external
GPIO has been selected, because no external light has been identified.

## State behaviour

| State | Colour | Pattern |
| --- | --- | --- |
| BOOT | cyan | short ramp up |
| CONNECTING | amber | slow searching pulse |
| IDLE | blue | dim, slow breath |
| VISITOR | bright cyan | faster pulse |
| LISTENING | green | breathing, lifted by input level |
| PROCESSING | amber | faster pulse |
| SPEAKING | blue | tracks the outgoing voice |
| UPDATING | blue | steady pulse |
| OFFLINE | red | distinctive slow blink |
| ERROR | orange | slow double blink |

Offline blinks rather than going dark, so an offline terminal looks offline
rather than dead. Error is a deliberate slow double blink, not a strobe.

## Audio reactivity

The light reuses the envelope already computed on the audio path for the
display. There is no second analysis pipeline, nothing is added to the audio
path, and the speaker timing is untouched.

## Owner settings

Brightness and quiet hours are settings, not firmware constants, so adjusting
them needs no rebuild or reflash:

```
POST /internal/arc-light
{ "enabled": true, "idleBrightness": 15, "activeBrightness": 55,
  "quietHoursStart": 22, "quietHoursEnd": 7 }
```

In ordinary use it is controlled by `scripts/arc-light.sh`, which reads the
token from `.env` so nobody has to handle a credential by hand:

```sh
./scripts/arc-light.sh off
./scripts/arc-light.sh dim
./scripts/arc-light.sh on            # normal
./scripts/arc-light.sh on 20 60      # custom idle and active percent
./scripts/arc-light.sh bright
./scripts/arc-light.sh status
```

The light is **off by default**. A light at a front door that switches itself
on is the owner's decision, not the firmware's.

Quiet hours dim to 25% rather than extinguishing: an offline or listening
terminal still has something worth indicating at night. Quiet hours that wrap
past midnight are handled; equal bounds mean never quiet rather than always.

Brightness is clamped on both sides. A bad setting dims the light instead of
stopping the terminal, and a host sending nonsense cannot drive the light hard.

## Failure behaviour

The light is optional everywhere. If the LED cannot be initialised, the
firmware logs it and carries on; the terminal works normally without it. It
starts dark at boot rather than flashing on before anyone has asked for it.

## A larger external arc reactor

Not implemented, deliberately. Adding an external backend before the physical
light is identified would mean guessing a voltage, a current and a pin, and
the firmware refuses to do that: `ARC_BACKEND_EXTERNAL` is intentionally absent.

To add one, the following must be known first:

- supply voltage and maximum current
- connector type, wire count and wire functions
- whether it is a plain LED, analog RGB, addressable, or has its own controller
- whether it needs PWM, a data line, or level shifting

With that, the driver architecture follows: a logic-level MOSFET with a gate
resistor and gate pull-down for a constant-voltage load, one channel per colour
for analog RGB, or a series data resistor and common ground for addressable.
The light would be powered from its own supply sharing ground with the AiPi,
never from a GPIO or the 3.3 V rail.

The `ArcLightController` abstraction already separates state and policy from
the output, so adding that backend does not touch any visitor or session code.

## Troubleshooting

- Light never illuminates: confirm `arcLightAvailable` is true in device
  health. That only proves the RMT peripheral allocated; WS2812 gives no
  feedback, so it cannot confirm a LED is present.
- Light stays dark although enabled: check quiet hours; at 25% of a low idle
  brightness the output can be very dim.
- Light is on but does not react: the state comes from Jarvis, so check the
  terminal state in health rather than the light.
