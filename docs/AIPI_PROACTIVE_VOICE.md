# Camera-triggered AiPi visitor voice

## Stock capability decision (verified 2026-08-24)

**Stock AiPi server-initiated speech: unsupported on firmware 1.2.5.**

The official [AiPi instruction book](https://static.aipi.com/AIPI_InstructionBook/AIPI_InstructionBook.html)
documents only device-initiated activation: the right function button or the
`computer` wake word moves the unit from standby to listening. The official
[setup guide](https://aipi.com/pages/manual) likewise describes only Standby,
Listening, and Speaking with a physical button start. The current
[product page](https://aipi.com/products/aipi-lite) advertises press-to-talk,
agent binding, and MCP integrations, but publishes no device-control API.

The signed-in XDC Device Management screen was also inspected with the bound
physical unit on stock firmware 1.2.5. Its available actions are remark edit,
OTA auto-update, and unbind. There is no push message, remote wake, TTS, listen,
standby, WebSocket, MQTT, webhook, SDK, or device-command control. The public
[changelog](https://aipi.com/pages/changelog) lists an SDK as upcoming rather
than available.

MCP is not a reverse transport. It lets an active XDC agent call Jarvis tools;
it does not let Jarvis initiate a device turn. No unpublished endpoint was
guessed or invoked.

| Capability | Stock 1.2.5 result | Verified mechanism |
| --- | --- | --- |
| Server-initiated speech | Unsupported | None published or exposed |
| Remote wake | Unsupported | Button or `computer` only |
| Remote TTS | Unsupported | None |
| Remote listen start/stop | Unsupported | Button/device state machine only |
| Proactive agent message | Unsupported | Preview chat is browser-only |

## Jarvis-side architecture

The local pipeline is complete and provider-neutral:

```text
Tapo frame -> existing person tracker -> zone classifier
           -> stable interaction-zone dwell -> VisitorStateMachine
           -> visitor.session_started -> VisitorGreetingPolicy
           -> voice.greeting_requested -> VoiceTerminalService
           -> VoiceTerminalProvider
```

Observation tracks only. Approach prepares only. The dwell timer starts when a
person enters the Door Interaction zone and resets if they leave it before
confirmation. Existing disappearance grace and greeting cooldown prevent a
brief detector miss or a stationary visitor from producing another greeting.

The neutral greeting is `Hi, how can I help you?`. Known-person personalization
is disabled by default and is used only when both explicitly enabled and backed
by a high-confidence local recognition result. Camera frames, face crops,
embeddings, RTSP data, and identity metadata are never sent to the terminal.

`VoiceTerminalService` provides the required state boundary:

```text
GREETING -> LISTENING -> PROCESSING -> SPEAKING -> LISTENING
                                      | timeout / departure / max duration
                                      v
                                   STANDBY
```

It enforces a 15-second no-speech timeout, 120-second maximum duration, and
eight-turn limit by default. Departure ends the voice session immediately. A
watchdog applies timeouts even when camera frames stall. The stock adapter is
intentionally unavailable: it emits `voice.terminal_unavailable` with no image
or identity data and never claims the greeting was delivered.

For development only, the simulator exercises the entire state flow. It is not
a claim that the physical AiPi spoke.

## Safest fallback

The recommended near-term fallback is a separate LAN speaker provider. It can
implement `speak`, while a separate bounded microphone/STT provider handles the
visitor reply. Keep it on the trusted LAN, authenticate each request, accept
text only, and return to standby after every bounded session. The stock AiPi can
remain available for owner-initiated button/wake-word queries.

Waiting for an official AiPi API is preferred if one gains all of these
capabilities:

- authenticated device-scoped command delivery;
- `speak(text)` delivery acknowledgement;
- bounded `startListening(timeout)` and `stopListening()`;
- device state/heartbeat events;
- explicit standby confirmation;
- replay protection, revocation, and least-privilege credentials.

## Custom firmware migration plan — preparation only

Custom firmware is the only current path to use the AiPi hardware itself for
event-initiated speech and bounded listening. It has **not** been flashed.
Before any future owner-approved migration:

1. Record model, firmware, serial-console boot log, Wi-Fi/binding state, and
   current partition table.
2. Connect USB/UART without changing flash; verify bootloader and chip identity.
3. Read and checksum the full 16 MB flash and every partition, including factory,
   NVS/credentials, OTA data, bootloader, partition table, and application slots.
   Store two encrypted offline copies and prove a read-back match.
4. Document the recovery procedure and test the exact restore command on a
   disposable image or second unit before touching the door device.
5. Electrically verify the community-reported hardware mapping: ES8311 codec on
   I2C GPIO 4/5, I2S MCLK/BCLK/WS/DOUT/DIN on 6/14/12/11/13, amplifier enable 9,
   ST7735 display SPI on 7/15/16/17/18 with backlight 3, function button 42,
   status LED 46, and power-control path 10. Do not rely on these pins without
   verification.
6. Prototype local audio capture/playback, echo suppression, button behavior,
   display states, and safe power handling before network integration.
7. Use outbound authenticated TLS WebSocket from device to Jarvis. Negotiate
   codec/sample rate and support `hello`, `heartbeat`, `state`, `speak`,
   `listen_start`, `audio`, `listen_stop`, `standby`, acknowledgements, sequence
   numbers, expiry, and reconnect backoff. Never expose an unauthenticated LAN
   listener.
8. Keep STT, policy, visitor records, face recognition, and orchestration local
   to Jarvis. Stream only bounded microphone audio during an active session;
   perform local TTS and send bounded audio back to the device.
9. Provide local Wi-Fi provisioning without preserving cloud credentials in the
   new application. Use signed OTA images, A/B application slots, rollback, and
   a physical recovery path.
10. Run bench acceptance tests for mic/speaker/display/button, network loss,
    timeout-to-standby, power loss, rollback, privacy, and restore-to-stock.

Stop before erase/write/flash until the owner explicitly approves this plan and
the factory backup and recovery proof are complete.
