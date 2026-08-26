# Claude handoff — Jarvis Home / AiPi

Last updated: 2026-08-26 evening. Stopped for the day mid-phase; the visual and
voice work is deployed and running, two physical checks are outstanding.

## State right now

- Firmware `1.4.0-endpointing`, deployed by signed OTA, no cable needed
- Repo clean, everything pushed to `SilentDev1/Jarvis`, latest `e26b0c2`
- 382 tests green; ruff, mypy and the ESP-IDF build all pass
- Jarvis core, device gateway and local device gateway all running
- Camera greeting **enabled**, door zones calibrated for the porch camera
- Arc light **off** — your last explicit choice, restored before stopping

The system is live overnight: a real visitor will be detected, greeted, heard
and answered.

## What was finished today

Automatic visual state, end to end. Jarvis is authoritative; the 128x128
display and the onboard arc light are two independent renderers of the same
state. State pushes carry a monotonic revision so a delayed packet cannot
revert the terminal, are only sent on real transitions, and are forced on
reconnect. Host-owned states expire on the device after two minutes so a
wedged host cannot leave it stuck showing SPEAKING.

The owner's light preference is persisted by the host and re-pushed on
reconnect, so it survives a gateway restart, an OTA and a power cycle. Verified:
the light stayed off through a full firmware update.

## The important fix

The terminal was greeting visitors, listening, recognising their speech, and
throwing it away. `last_transcript` was written by `start_listening` and read
by nobody: the conversation could only advance through the simulator endpoint.
From the doorstep it looked exactly like Jarvis ignoring you.

Now fixed and confirmed working:

```text
20:31:42  assistant  Hi, how can I help you?
20:32:01  user       I am looking for the owner looking to look at the car.
20:32:01  assistant  Please state your name and the company you represent.
```

## Where the latency goes

Measured from the moment the visitor stops speaking:

| Stage | Time |
| --- | --- |
| trailing silence before the turn ends | 1.3s |
| speech recognition | 0.27s |
| local AI reasoning | 1.44s |
| text to speech | 1.3s |
| total | about 4.3s |

Both large costs are at their floor. `num_predict` at 160, 96 and 48 all took
1.44s, because the model stops early regardless. `say` costs 0.45s just to
start, before synthesising anything.

The biggest remaining lever is a smaller local model; `qwen3.5:4b` is what is
configured. That is an owner decision, not a code change, because it trades
answer quality for speed.

## Endpointing, and two failed attempts worth remembering

Listening ends on trailing silence rather than a fixed window. Getting there
took three tries:

1. A fixed absolute threshold cannot work. The measured room level at this door
   is 0.041, seven times the nominal silence level, so nothing ever counted as
   silence and every turn ran its full ceiling.
2. Learning a floor from the quietest audio fails differently: a visitor who
   starts talking the instant the microphone opens sets the floor to their own
   voice, and nothing clears it.
3. Hysteresis works. Speech needs a high level to start and only a low one to
   continue, so noise cannot start an utterance and an unstressed syllable
   cannot end one.

Levels are recorded and classified against the finished turn, because whether a
chunk is speech depends on the loudest and quietest audio present and neither
is known while the first chunks are arriving.

## Outstanding — needs the owner, not code

1. **Conversation quality at the door.** Does it still truncate mid-sentence?
   Is the pause after speaking tolerable? The last observed truncation was
   "My name is Hung. I'm here to look at", which drove the hysteresis change;
   that change has not yet been tested by a real visitor.

2. **Manual override, physically.** Run `./scripts/arc-light.sh off`, trigger a
   visitor, and confirm the display still animates while the light stays dark.
   Verified in software and across an OTA, not yet watched.

## Known and deliberate

- External arc reactor is not implemented. `ARC_BACKEND_EXTERNAL` is
  intentionally absent: adding it before the light is identified would mean
  guessing a voltage, a current and a pin. Four facts are needed first, listed
  in `docs/AIPI_ARC_REACTOR.md`.
- Reboot durability still needs Full Disk Access granted to
  `~/Library/Application Support/JarvisHome/jarvis-gateway-launcher`, then
  re-running `./scripts/install-launch-agents.sh`. Until then the stack needs a
  manual `./scripts/start.sh` after a Mac reboot.
- Battery indicator is unavailable, not broken: there is no verified ADC
  mapping and a percentage will not be fabricated.

## Useful commands

```sh
./scripts/status.sh                 # is everything running
./scripts/arc-light.sh status       # light state
./scripts/arc-light.sh off|dim|on|bright
./scripts/publish-firmware.py       # build then publish a signed release
```

Do not paste the admin token by hand; the scripts read it from `.env`.
