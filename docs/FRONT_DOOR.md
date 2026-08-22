# Front Door

Continuous person detection should consume the Tapo substream. The tracked bounding-box foot point is tested against normalized observation, approach, and interaction polygons. Dwell creates one session; disappearance grace preserves identity; cooldown suppresses repeats; timeout closes abandoned sessions. Main-stream snapshots are reserved for meaningful events.

In test mode the dashboard simulator drives the same conversation state and persistence as a VoiceSatellite. Delivery receives a minimal response. Service visitors progress through claimed company, name, reason, and badge request. Friend and emergency flows notify without interrogation. Package-after-departure comparison remains experimental until real camera samples can calibrate it.

The live runtime consumes the substream at a configured maximum inference rate (default 3 FPS), applies YOLO11n person boxes to normalized zones, and drives the same state machine. The main stream is used only for visitor images and a 3-second badge burst. Badge frames are ranked by Laplacian sharpness; only the best is retained and submitted to Tesseract. OCR name/company candidates remain separate evidence fields and never overwrite claims.

Live preview uses a throttled JPEG endpoint rather than proxying full RTSP bandwidth. Disconnects surface through camera health, and the Tapo provider reconnects with bounded exponential backoff.
