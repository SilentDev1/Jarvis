# Mac deployment

Run setup, configure `.env`, run tests and doctor, then start manually. Ollama should run natively for Metal. Test the simulator before enabling live RTSP. macOS launchd is intentionally not enabled until manual operation is reliable.

Current native dependencies: Homebrew ffmpeg and Tesseract, Ollama with `qwen3.5:4b`, and Python `.[vision,ocr]`. `start.sh` checks the Ollama API before starting `ollama serve`, avoiding duplicates. Metal-backed Ollama remains outside Core and Linux can point the same provider at another host.
