# Front Door

Continuous person detection should consume the Tapo substream. The tracked bounding-box foot point is tested against normalized observation, approach, and interaction polygons. Dwell creates one session; disappearance grace preserves identity; cooldown suppresses repeats; timeout closes abandoned sessions. Main-stream snapshots are reserved for meaningful events.

In test mode the dashboard simulator drives the same conversation state and persistence as a VoiceSatellite. Delivery receives a minimal response. Service visitors progress through claimed company, name, reason, and badge request. Friend and emergency flows notify without interrogation. Package-after-departure comparison remains experimental until real camera samples can calibrate it.

The live runtime consumes the substream at a configured maximum inference rate (default 3 FPS), applies YOLO11n person boxes to normalized zones, and drives the same state machine. The main stream is used only for visitor images and a 3-second badge burst. Badge frames are ranked by Laplacian sharpness; only the best is retained and submitted to Tesseract. OCR name/company candidates remain separate evidence fields and never overwrite claims.

Live preview uses a throttled JPEG endpoint rather than proxying full RTSP bandwidth. Disconnects surface through camera health, and the Tapo provider reconnects with bounded exponential backoff.
# Visitor media and enrollment

Default configured zones are active immediately; saving custom zones is optional.
A stable visitor session collects candidate frames at a bounded interval. The
local `VisitorMediaService` scores candidates and stores at most one snapshot
and one padded face crop per visit under the configured data directory. Better
candidates replace poorer ones; ambiguous multi-person/face candidates cannot
be enrolled.

Recent Visitors uses authenticated thumbnail endpoints. Remember opens a local
review form and requires a clear unambiguous face. Enrollment creates a
`KnownPerson` plus a `FaceSample`, saves the local embedding, associates the
visitor immediately, and marks approved media for retention. The FaceSample
schema supports multiple samples per person; recognition loads all enabled
samples without a restart.

Unknown completed-visit media expires after seven days by default. Cleanup is
database-bounded, ignores active visits, protects enrolled samples, tolerates
missing files, and records a system event when it removes rows.
