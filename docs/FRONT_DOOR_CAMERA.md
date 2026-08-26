# Front door camera

Updated 2026-08-26.

## The configured camera was the wrong one

`CAMERA_HOST` pointed at `192.168.1.34`, which is an **indoor camera watching a
living room**, not the front door. The zone polygons were never customised
either: they were still the stock defaults, generic rectangles covering most of
the frame.

Together that meant camera-triggered greeting would have spoken to anyone
crossing the living room, household members included, once per cooldown. That
is the failure mode the greeting gate now exists to prevent.

The real front door camera is `192.168.1.11`.

## Enabling RTSP

The door camera refused RTSP until a Camera Account was created in the Tapo
app. The distinction matters when diagnosing: a refused connection means no
RTSP server is listening, so no credentials can help. A Tapo cloud account is
also not the same as the Camera Account; only the latter authenticates RTSP.

    Tapo app -> camera -> Settings -> Advanced Settings -> Camera Account

Once created, `554` accepts and both streams work: main 1920x1080,
sub 640x360.

## Zones

Zones are fractions of the frame, so they survive a resolution change but not a
camera change. The door camera looks outward from behind a screen door across a
yard, driveway and street, so the provisional zones:

- exclude the sky entirely above y=0.52, since a visitor cannot be there and
  including it only invites false positives
- keep the interaction zone in the near foreground, so the street and the
  neighbouring property cannot trigger a greeting

These are **provisional**. Nobody has yet stood where a visitor stands, so the
interaction polygon is an educated guess and currently overlaps the driveway.
Someone walking to their own car would register as at the door.

## Detection

`YoloVision` passes `classes=[0]`, so it reports **people only**. A parked car
or a sofa will never appear in detections; zero detections on a busy-looking
frame means no people, not a broken detector. This was briefly mistaken for the
screen mesh blinding the model.

Confirmed on the door camera: connected, ~16 fps, vision loop running, presence
ABSENT with an empty yard.

Whether detection works reliably *through the screen mesh* is still unproven,
because nobody has been in frame. That is the one open question.

## Presence never guesses

With the camera disconnected the pipeline reported presence `UNKNOWN`, not
`ABSENT`. That invariant matters: an unavailable camera must never read as
"nobody is there".

## Greeting is opt-in

`CAMERA_GREETING_ENABLED` defaults to false. Detection, the visitor session,
the snapshot and face recognition all still run; only the unprompted speech is
withheld. Enable it after standing where a visitor stands and confirming the
interaction zone matches.

## Camera-triggered greeting: validated in two halves

2026-08-26. Confirmed, but not simultaneously, because the camera was in the
living room and the AiPi is in the office.

Camera half. With the camera bench-mounted indoors, a person entering the
interaction zone produced:

```text
session    3507277f-b5f3-4090-90ae-dcce7ce7dc6f
greeting   "Hi, how can I help you?"
phase      complete   end_reason: no_speech_timeout   turns: 0
```

`no_speech_timeout` is the useful detail: it proves the greeting was spoken and
the microphone then opened and listened, timing out only because nobody
answered. A failure to speak would have ended `provider_error` instead.

Speaker half. The same greeting text was streamed to the terminal and the owner
confirmed hearing it clearly: 45,910 bytes, 1.435 s.

## Re-greeting is expected, and loud on a bench

Standing in view produced a new session roughly every 90 seconds: the 60-second
cooldown plus the 15-second no-speech timeout. At a real door that is wanted, a
lingering visitor gets re-engaged. Pointed at a living room it means the
household is greeted every 90 seconds, which is why the greeting is opt-in.

## Current state and what must be redone

`CAMERA_GREETING_ENABLED` is back to false.

The zones currently in `.env` are **bench zones**, with the interaction zone
covering most of the frame so any detected person exercised the greeting path.
They are meaningless for a real door view and must be redrawn once the camera
is mounted in its final position and someone stands where a visitor stands.

Detection through the screen door is still unproven. The detection that
validated the pipeline happened indoors with no screen between camera and
subject.

Minor: two visitor sessions were left `active` and never closed during bench
testing. Worth a look before this runs unattended.
