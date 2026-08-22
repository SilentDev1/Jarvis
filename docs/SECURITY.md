# Security

The API binds to loopback by default. Mutating simulator/test routes require a constant-time token comparison. Secrets live only in excluded `.env` files and camera URLs are masked. All speech/OCR is sanitized and explicitly labeled untrusted in the system policy. Actions pass through a seven-item allowlist; there is no shell, lock, garage, or alarm action. AI failure uses deterministic responses. Do not expose the service to a LAN without TLS and a trusted reverse proxy/VPN.

