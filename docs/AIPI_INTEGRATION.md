# AiPi Lite stock-firmware integration

## Verified stock path

The August 2026 XDC agent editor supports custom MCP servers using SSE or
Streamable HTTP. Jarvis uses Streamable HTTP because it supersedes SSE. XDC
accepts an HTTPS URL and custom `Authorization` header. Stock AiPi speech,
agent routing, and TTS remain cloud-routed; this is not a fully local voice
pipeline.

No firmware was flashed. The factory microphone, speaker, display, button,
Wi-Fi configuration, device identity, and credentials remain untouched.

## Architecture

```text
AiPi Lite stock firmware
  -> XDC cloud agent
  -> HTTPS Streamable HTTP MCP
  -> bearer-authenticated Jarvis Device Gateway
  -> allowlisted Jarvis skill
  -> Jarvis Core
```

The gateway runs separately from the dashboard on localhost port 8766. The
initial MCP surface contains exactly one tool: `jarvis.status`. It cannot call
the dashboard, camera, shell, filesystem, admin APIs, or other Jarvis tools.

## Device identity and credential

The stable Jarvis device ID is `aipi-front-door`, independent of the XDC
six-digit binding code. `scripts/register-aipi.py` registers the device,
revokes prior credentials, and prints a new high-entropy token once. Jarvis
stores only its SHA-256 hash, prefix, state, and timestamps. Tokens can be
revoked without changing the administrator login.

The XDC MCP configuration uses this shape:

```json
{
  "mcpServers": {
    "jarvis-device-gateway": {
      "url": "https://YOUR_GATEWAY/mcp",
      "type": "streamable",
      "headers": {
        "Authorization": "Bearer DEVICE_TOKEN"
      }
    }
  }
}
```

Never commit the token. Local token handoff files matching `data/*token*` are
ignored. Use a named, durable HTTPS tunnel for production; an account-less
Cloudflare quick tunnel is suitable only for a temporary integration test and
has no uptime guarantee.

## First test status

The official MCP client successfully discovered only `jarvis.status` through
the authenticated HTTPS tunnel and received:

```json
{"ok": true, "speech": "Jarvis is online.", "status": "online"}
```

XDC saved the custom MCP and attached it to the existing Jarvis agent. XDC
Preview Chat did not invoke MCP even with an explicit must-call instruction;
it generated a cloud-model response and no Jarvis device audit appeared. No
physical-device MCP request arrived during the initial monitored test window.
Therefore physical AiPi speech delivery is not yet verified and must not be
reported as passing.

## Commands

```sh
PYTHONPATH=src ./.venv/bin/python scripts/register-aipi.py
./scripts/start-device-gateway.sh
```

The gateway records device ID, normalized request, invoked skill, result,
delivery status, and timestamp. It does not retain raw audio.

## Custom firmware fallback

Do not flash while the stock MCP path remains under evaluation. If it becomes
necessary, first read and verify a full-flash backup and separately preserve
factory NVS/device credentials. Flashing requires explicit homeowner approval.
