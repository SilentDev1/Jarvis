# AiPi activation and false-trigger boundary

## Verified stock behavior

The bound AiPi Lite reports firmware `1.2.5` with OTA auto-update enabled. The
current XDC device and character pages expose no controls for VAD threshold,
silence timeout, microphone sensitivity, minimum speech duration, echo
cancellation, barge-in policy, or automatic exit from Listen Mode.

The official stock manual documents these states:

```text
STANDBY -> (right button or "computer") -> LISTENING
LISTENING -> (speech ends) -> RESPONSE
RESPONSE -> (response completes) -> LISTENING
LISTENING -> (right button) -> STANDBY
```

That final return to `LISTENING` is the cause of the open-ended behavior. Once
Listen Mode is entered, the stock device—not Jarvis Core or MCP—owns the
microphone, VAD, cloud STT, and turn lifecycle. Ambient audio can therefore
create another cloud turn. XDC does not expose the transcript confidence or a
raw-input callback to Jarvis, so the particular sound behind a false turn
cannot be proven from Jarvis audit data.

The built-in wake word is `computer`. A custom `Jarvis` wake word is listed by
AiPi as upcoming, not currently available. Wake word activation still enters
the same continuous Listen Mode, so it does not solve the single-turn issue.

## Safe operating mode

Use controlled button activation:

1. Leave AiPi in **standby**, not persistent Listen Mode.
2. Briefly press the right function button and speak one complete command.
3. Let AiPi give its single response.
4. Briefly press the right function button once to return from listening to
   standby. Confirm the standby display before walking away.

This requires a second press because stock firmware 1.2.5 automatically returns
to listening after speaking. It is the only verified stock method that closes
the microphone turn reliably. Do not use always-on Listen Mode near the front
door. The `computer` wake word is optional, but button activation is recommended
around traffic, wind, HVAC, television audio, and distant conversation.

## Protections applied

The deployed XDC Jarvis character now:

- responds only to a meaningful, complete user utterance;
- calls no tool and emits no speech for silence/noise/empty/incomplete input;
- produces one concise response and ends the model turn;
- never follows up, repeats its TTS, or initiates unsolicited alerts;
- routes status/current-door/recent-door questions to their authoritative tools.

Jarvis adapters that receive transcript text reject empty, whitespace,
punctuation-only, common noise markers, and one-character fragments before AI
or tool routing. XDC MCP calls contain only a selected tool call—no transcript,
VAD confidence, or activation metadata—so Jarvis cannot independently reject a
plausible transcript invented upstream. MCP tools are passive request/response
handlers and contain no scheduler, event subscription, or speech initiation.
As a bounded self-hearing mitigation, an identical device/tool request within
four seconds reuses the authorized structured result but returns an empty
`speech` field and does not call Core again. Different tools remain available,
and normal requests work again after the window. This does not replace the
recommended second button press or prove physical echo cancellation.

Unsolicited front-door event speech remains disabled. A future proactive alert
path must be a separate event -> notification policy -> permitted device design.

## Physical acceptance tests

- **Silence:** enter listening, say nothing, then press the right button to
  standby. There must be no response before the press.
- **Background:** repeat with normal room noise. There must be no response.
- **Command:** press, say “Jarvis, what is your status?”, hear exactly one
  answer, then press once to standby.
- **Self-hearing:** during and after TTS, verify no second answer occurs; press
  once after the response to ensure standby.
- **Front door:** press, ask “Is anyone at the front door?”, hear one live
  result, then press once to standby.
- **Repeat:** start from standby and repeat as a separate turn.

Automatic single-turn return to standby, configurable silence timeout, custom
wake word, and device-level transcript confidence require a future stock
firmware/XDC feature. Custom firmware is not required for the safe two-press
workflow and must not be flashed for this issue.
