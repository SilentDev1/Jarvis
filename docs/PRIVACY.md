# Privacy

Defaults: selected visitor snapshots on, transcripts on, badge images only when requested, raw audio off, and unknown visitor media retained for 7 days. Continuous analysis does not imply continuous recording. Jarvis keeps only the best snapshot and best padded face candidate for a visit, not every frame. Unknown completed-visit media expires; active visits and user-approved enrolled samples are protected. Known-person samples remain until the owner forgets that person.

Visitor images are stored below the configured data directory and served only by narrow administrator-authenticated endpoints with private/no-store headers. API responses never disclose filesystem paths. Camera frames, crops, embeddings, and biometric templates stay local and are excluded from Git. AiPi/XDC receives only sanitized textual MCP facts.
