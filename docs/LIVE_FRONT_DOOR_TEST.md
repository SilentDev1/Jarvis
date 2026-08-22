# Live Front Door test

## Preparation

1. In the Tapo app, create/confirm the camera account and reserve the C101 address.
2. Run `./scripts/configure-tapo.sh`; the password input is hidden.
3. Run `./scripts/test-camera.sh`. Do not continue until main, sub, snapshot, and reconnect pass.
4. Run `./scripts/doctor.sh`, then `./scripts/restart.sh` and open <http://127.0.0.1:8765>.
5. On the camera canvas choose each zone, clear it, click at least three polygon vertices, and save. Observation should cover general porch visibility; approach should narrow toward the door; interaction should cover the waiting position.

## State scenarios

- **Walk past:** cross only observation and leave before dwell. Expect `person.detected`, no `visitor.session_started`.
- **Approach:** cross approach, enter interaction, wait more than 2.5 seconds. Expect one session and `jarvis.greeting` in the simulator chat.
- **Remain:** stay at the door. Expect no second greeting.
- **Brief occlusion:** leave the image for less than four seconds and return. Expect the same session ID.
- **Leave:** leave longer than four seconds. Expect `visitor.departed` and `session.completed`.

Type `I'm from Comcast`, a name, then the service reason. The policy must collect claimed company/name/reason and request a badge. Hold the badge close, level, and still for three seconds. Review `visitor.badge_captured`; OCR is supporting visible evidence only.

## Badge calibration matrix

Test close/front-facing, farther away, slight angle, low light, and motion. Record the sharpness and OCR confidence events. With a 1080p fixed-focus C101, no distance claim is made until real samples are measured; begin close enough that badge text occupies at least roughly one quarter of image width. Never treat missing or matching OCR as authentication.

Package-after-departure detection is intentionally experimental. Do not enable delivery notification from image comparison until false positives are measured with real before/after frames.
