# Troubleshooting

Run `scripts/doctor.sh`, inspect `logs/server.log`, then `logs/jarvis.log`. Camera failures: verify IP reservation, camera account, VLC/ffprobe RTSP, and Wi-Fi; reconnect uses bounded backoff. AI failures: start Ollama and pull the configured model; Jarvis falls back safely. A 401 from simulator routes means the dashboard token differs from `.env`. Vision mock mode intentionally detects nothing.

