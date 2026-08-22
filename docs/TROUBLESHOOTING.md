# Troubleshooting

Run `scripts/doctor.sh`, inspect `logs/server.log`, then `logs/jarvis.log`. Camera failures: verify IP reservation, camera account, VLC/ffprobe RTSP, and Wi-Fi; reconnect uses bounded backoff. AI failures: start Ollama and pull the configured model; Jarvis falls back safely. A 401 from simulator routes means the dashboard token differs from `.env`. Vision mock mode intentionally detects nothing.

If `test-camera.sh` reports authentication failure, confirm these are Tapo **camera account** credentials. If main works and sub fails, set an explicit substream URL. If detection is expensive, keep the substream and reduce `DETECTION_FPS`; 2–3 FPS is the intended porch range. A blank preview means no decodable frame and should coincide with a camera health error. Badge OCR needs large, steady, front-facing text; glare and motion blur are not evidence of identity.
