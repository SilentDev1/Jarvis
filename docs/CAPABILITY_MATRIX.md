# Jarvis capability and evidence matrix

Single authoritative status for every area in `.ai-coordination/PROJECT_SPEC.md`.
Produced for task JARVIS-001 from base commit `7d2af3b`.

**Every row is traced to code, tests, build output, commits, or a recorded
physical validation session.** No row is promoted because another document
asserts it. Where two documents disagreed, the disagreement is named and
resolved against source.

## Evidence labels

| Label | Means |
|---|---|
| `source verified` | Read in the repository source at this commit |
| `build verified` | Produced by a build that ran and succeeded |
| `simulator verified` | Exercised against a simulated device only |
| `service integration verified` | Exercised against a running local service |
| `hardware verified` | Recorded physical session on the actual AiPi Lite |
| `user action required` | Cannot be established without the owner |

`hardware verified` is used only where a dated physical session is recorded.
A simulator or build result is never promoted to it.

---

## Matrix

| # | Spec area | Status | Evidence |
|---|---|---|---|
| 1 | Repository reconciliation | `source verified` | This document; `.ai-coordination/DECISIONS.md` D-001 |
| 2 | Firmware selection | `source verified` | `firmware/aipi-jarvis` (ESP-IDF C, 12 `.c`); `../reference/aipi-lite` (MicroPython, 34 `.py`). See *Firmware selection* below |
| 3 | Firmware build | `build verified` | `idf.py -B build-verify build` → `jarvis_aipi.bin` `0x108950` bytes, 73% of app partition free, exit 0 |
| 4 | Factory recovery | `source verified` | `docs/AIPI_FACTORY_RECOVERY.md`; gate recorded as passed before the 2026-08-24 flash |
| 5 | GPIO42 push-to-talk | `hardware verified` | `AIPI_BUTTON GPIO_NUM_42` in `firmware/aipi-jarvis/main/aipi_board.h:19`; physical turn traced in `docs/AIPI_SPEAKER_VALIDATION.md` (2026-08-26) |
| 6 | Microphone capture | `hardware verified` | Trace: `microphone capture START rate=16000 PCM16` … `stream END bytes=192000 reason=complete` (6.0 s), 2026-08-26 |
| 7 | Speech recognition (STT) | `hardware verified` | Same session: `heard='What is the weather?'` via local faster-whisper |
| 8 | Speaker playback | `hardware verified` | `playback END bytes=94378 result=ESP_OK`, 2026-08-26; `docs/AIPI_AUDIO.md` |
| 9 | Feedback prevention | `hardware verified` | Amplifier disabled *before* the mic opens and re-enabled only to speak, visible in the 2026-08-26 trace; `amplifier_set()` in `main/audio_output.c:49` |
| 10 | ES8311 codec routing | `hardware verified` | `ES8311_ADDRESS 0x18` in `main/es8311_codec.c:8`; probed and initialised in the same session |
| 11 | ST7735 128×128 UI | `source verified` + `build verified` | `DISPLAY_W/H 128` in `main/display_render.h:15-16`; SPI panel in `main/bringup.c`; 20 FPS controller in `main/display_controller.c` |
| 12 | GPIO46 WS2812 state | `source verified` | `ARC_ONBOARD_GPIO 46` in `main/arc_light.c:19`; `espressif/led_strip` in `idf_component.yml`. **Initialised but disabled by default** (`main/app_main.c:49`) |
| 13 | Bounded listening | `source verified` | `hub.listen(max_milliseconds=…)` in `src/jarvis_home/devices/voice_loop.py:118` |
| 14 | Authenticated local connectivity | `hardware verified` | Boot reconnect + authenticated ONLINE, 2026-08-25 (`docs/AIPI_CUSTOM_FIRMWARE.md:98`) |
| 15 | OTA update | `hardware verified` | 2026-08-26 with the device fully off USB (`docs/AIPI_OTA.md:143`); `src/jarvis_home/devices/ota.py` |
| 16 | Wi-Fi reconnection | `hardware verified` | Boot reconnect in the 2026-08-25 session |
| 17 | Wi-Fi provisioning / network switching | `not implemented` | No dedicated provisioning partition identified (`docs/AIPI_FACTORY_RECOVERY.md:34`). Credentials are built in; changing networks requires a rebuild |
| 18 | Remote (off-LAN) connectivity | `not implemented` | Remote wake and remote TTS are **Unsupported** (`docs/AIPI_PROACTIVE_VOICE.md:29-30`). Local LAN only |
| 19 | Front Door status | `service integration verified` | `src/jarvis_home/modules`, `docs/FRONT_DOOR.md`; 382 tests pass |
| 20 | Face recognition | `service integration verified` | YuNet + SFace; dormant until an owner enrols someone (`README.md`) |
| 21 | Unavailable package detection | `source verified` (honest negative) | Package/uniform classification returns **unavailable** — no live classifier (`docs/AIPI_INTEGRATION.md:41`); after-departure detection is experimental and off (`docs/LIVE_FRONT_DOOR_TEST.md:25`) |
| 22 | Offline / degraded behaviour | `service integration verified` | Deterministic policy-safe replies when Ollama is down (`README.md`); stall watchdog (commit `a790fdc`) |
| 23 | Secrets handling | `source verified` | Credentials only in excluded `.env`; `safe_dict()` redaction; no secret in this document |
| 24 | Automated tests | `source verified` | `./scripts/test.sh` → **382 passed**, exit 0 |
| 25 | Lint | `source verified` | `ruff check src tests` → **All checks passed** |
| 26 | Type checking | `source verified` | `mypy src` → **Success: no issues found in 37 source files** |
| 27 | Reboot / autostart | `not enabled` | launchd **intentionally** not enabled until manual operation is reliable (`docs/MAC_DEPLOYMENT.md:3`) |
| 28 | Hardware checklist | `user action required` | See *Remaining physical checks* |

---

## Firmware selection

**The active path is `firmware/aipi-jarvis` (ESP-IDF C).** It is selected on
evidence, not preference:

- it is the only path with recorded physical validation on this unit — flashed
  2026-08-24 after the factory gate, then Wi-Fi, authenticated reconnect,
  speaker, microphone, STT and OTA sessions through 2026-08-26;
- it builds reproducibly here (exit 0, 73% partition headroom);
- it carries the feedback-prevention ordering that the audio design depends on.

`../reference/aipi-lite` is a **separate upstream repository** (MicroPython,
34 modules) and is *not* vendored into this product. Its value is corroborative:
`main/arc_light.c:12-13` cites it as the source for "WS2812 on GPIO46, 1 pixel",
and its `SPEC.md` carries the pinout and `RECOVERY.md` the restore procedure.
It remains the fallback reference if the C path ever needs re-derivation.

**Nothing was deleted and nothing was flashed.** Both ESP-IDF toolchains remain
in place — `../toolchains/esp-idf-v5.3.2` and `~/esp/esp-idf`, both `v5.3.2`.

## Reconciled contradictions

Four current-status claims were wrong at base commit and are corrected:

| Stale claim | Where | Reality |
|---|---|---|
| "AiPi remains simulated" | `README.md` | `.env` sets `VOICE_SATELLITE=aipi_gateway`; custom firmware flashed and hardware-validated |
| "text VoiceSatellite simulator until AiPi is available" | `README.md` | The gateway path is deployed; simulator is one of four modes and only the config *default* |
| "Microphone capture and STT remain disabled" | `docs/AIPI_AUDIO.md:22` | Both hardware verified 2026-08-26 in `docs/AIPI_SPEAKER_VALIDATION.md` |
| "physical light has not been identified… unknown" | `src/jarvis_home/devices/arc_reactor.py`, `docs/AIPI_VOICE_TERMINAL.md` | Identified as onboard WS2812 GPIO46 and implemented; still *disabled by default*, which is the part that remains true |

## Boundaries

- **Jarvis Home** — this repository. Owns events, state, policy, providers.
- **Front Door** — a *module* of Jarvis Home (`src/jarvis_home/modules`). The
  camera concierge. `../jarvis-front-door` is a **separate** RTSP/Tapo/OpenCV/
  YOLO project and is **not** AiPi firmware.
- **Custom AiPi firmware** — `firmware/aipi-jarvis`, active and deployed.
- **Stock AiPi / XDC / MCP** — `src/jarvis_home/devices/mcp_gateway.py`,
  reachable via `VOICE_SATELLITE=aipi_stock`. Retained as a fallback.
- **Lawyer AiPi** — unrelated product work in a different repository. No shared
  code, services, or ports with Jarvis Home.

## Remaining physical checks — `user action required`

1. WS2812 visual states with the arc reactor **enabled** (currently off by default).
2. Display legibility of each state on the physical 128×128 panel.
3. Long-press (2 s) GPIO42 behaviour.
4. Battery-only operation without USB.
5. Behaviour when the configured Wi-Fi network is absent at boot.
