# AI providers

`AIProvider` currently includes Ollama. M4/16 GB default: `qwen3.5:4b`, selected for responsive structured conversation without per-message cost. Ollama remains native on Mac for Metal. Safe deterministic conversation logic handles unavailable/time-out/model-invalid responses. OpenClaw was not found and is not required; a future adapter can implement the interface.

