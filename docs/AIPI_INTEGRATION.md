# AiPi Lite integration

## Status and architecture

Stock firmware is preserved. AiPi uses its factory microphone, speaker, display,
button, Wi-Fi, and XDC cloud agent. XDC calls an authenticated HTTPS Streamable
HTTP MCP endpoint. Cloudflare ingress targets only the localhost device gateway
on port 8766; Jarvis Hub remains separately available only through the private
Tailscale path.

```text
AiPi stock firmware -> XDC cloud agent -> HTTPS tunnel -> :8766 /mcp
  -> device authentication -> per-device tool allowlist -> Jarvis Core :8765
  -> local camera, vision, face hints, and event database
```

The camera stream, images, RTSP credentials, administrator APIs, shell,
filesystem, database, and secrets are not MCP tools. Video and face matching
stay local. XDC receives the user's cloud-routed voice interaction and only the
small structured result of the selected Jarvis tool. Cloudflare transports the
encrypted MCP request and response.

## Device and tools

The stable device ID is `aipi-front-door`; it is independent of the XDC binding
code. Each device has independently enabled tool rows. There is no dynamic
method invocation. The current allowlist is:

- `jarvis.status` — authoritative Core availability
- `jarvis.frontDoor.status` — current local camera/person/verified identity facts
- `jarvis.frontDoor.recent` — at most five sanitized events from the last 24 hours

Package and uniform classification are returned as unavailable because no live
detector currently produces those facts. A name is returned only for an
existing `KNOWN_HIGH_CONFIDENCE` face-recognition result. Identity/company
context remains a hint, never authentication. General `jarvis.ask` is omitted:
the current intelligence layer cannot safely guarantee that it will never
reach privileged capabilities.

Current presence is derived from the continuously processed local Tapo feed,
not event history or the visitor database. Every response includes
`presence` (`PRESENT`, `ABSENT`, or `UNKNOWN`), `observedAt`, `ageMs`, and
`source`. A positive detection is held for 2.5 seconds so one missed inference
does not flicker to absent. State older than three seconds triggers a fresh
snapshot through the same camera and YOLO provider; a failed refresh becomes
`UNKNOWN`, never a false `ABSENT`. Face identity is evaluated separately and
cannot change whether a detected human is present.

Every authorized call records device, tool/category, bounded result, duration,
time, and success/failure. Tokens and raw audio are not stored in audit rows.
Requests time out at the Core client after five seconds, bodies are limited to
64 KiB, and each device is limited to 30 gateway requests per minute. Disabled
devices, revoked/bad tokens, malformed MCP, and unknown tools are rejected.
Read-only query tools may be retried. Any future action tool requires explicit
permission, idempotency, and confirmation policy. Locks, garage doors, alarm
controls, shell, and filesystem access remain prohibited.

## Registration and credential rotation

```sh
PYTHONPATH=src ./.venv/bin/python scripts/register-aipi.py
```

Registration revokes prior credentials and prints a high-entropy bearer token
once. Jarvis stores only SHA-256, a non-secret prefix, and lifecycle timestamps.
Copy the token directly into XDC; never place it in Git or logs. The Devices UI
can rotate the token, which immediately revokes the old one and shows the new
token once. Disabling a device also revokes its active credentials.

XDC custom MCP shape:

```json
{
  "mcpServers": {
    "jarvis-device-gateway": {
      "url": "https://YOUR-NAMED-HOST/mcp",
      "type": "streamable",
      "headers": {"Authorization": "Bearer DEVICE_TOKEN"}
    }
  }
}
```

Attach it to the deployed AiPi agent, enable all three tools, choose a model
that supports MCP tool calling, publish/deploy the agent, and sync or restart
the stock device if XDC requires it. Agent instructions must say that status,
current front-door, package, identity, and recent-activity questions MUST call
the matching tool and must speak exactly the returned `speech` field.

## Startup and tunnel

`./scripts/start.sh` starts Core and the device gateway together;
`./scripts/stop.sh` stops both; `./scripts/status.sh` checks both. For a durable
tunnel, create a named Cloudflare tunnel whose ingress maps one hostname only
to `http://127.0.0.1:8766`, with a final `http_status:404` catch-all. Put the
absolute path to its uncommitted config in `CLOUDFLARE_TUNNEL_CONFIG`. Startup
then also manages `cloudflared`. Creating the named tunnel and DNS record needs
the owner's Cloudflare account. The current account-less Quick Tunnel is valid
only for temporary testing and its URL/uptime are not durable.

No Mac username, LAN IP, or repository path is embedded in the integration.
For a future server, copy data/config securely, run setup, point the named
tunnel ingress at the new localhost gateway, and leave the stable device ID and
XDC hostname unchanged.

## Owner setup and physical verification

1. Power AiPi and confirm Wi-Fi and the intended deployed XDC agent.
2. Run `./scripts/status.sh`; confirm Core and Device Gateway are running.
3. In Jarvis Hub > Devices, run **Gateway Test**. This does not test the speaker.
4. Say: “Jarvis, what is your status?” Expected: “Jarvis is online.”
5. Say: “Who’s at the front door?” The answer must reflect the live local result.
6. Confirm a new successful device audit row after each phrase.

Physical AiPi -> XDC -> MCP -> speaker delivery is **AWAITING PHYSICAL
VERIFICATION**. An official external MCP client has successfully discovered and
called the gateway, but XDC Preview Chat previously answered without invoking
the tool. Discovery alone is not proof of the physical round trip.

Troubleshooting:

- Cloud answer/no audit: verify the physical device's assigned agent/version,
  publish/deploy, enabled MCP tools, model tool support, and forced instructions.
- 401: token is missing/revoked; rotate once and update XDC immediately.
- Gateway offline: run `./scripts/start.sh`, inspect `logs/device-gateway.log`.
- Tunnel offline: inspect `logs/cloudflared.log` and named-tunnel account state.
- Jarvis offline: inspect `logs/server.log`; status deliberately reports failure.
- Camera offline: Jarvis reports camera offline and never fabricates a visitor.
- Physical device offline: gateway health may still pass; check AiPi power/Wi-Fi
  and XDC binding. Server-initiated speaker testing is not exposed by XDC.

Display lifecycle control is not available through the verified stock XDC MCP
surface, so factory listening/thinking/speaking UI remains in use. Push-to-talk
or the stock activation behavior is retained. Do not flash firmware; any future
firmware path requires a verified full-flash/NVS backup plan and owner approval.
The exact stock activation boundary and safe standby workflow are documented in
`docs/AIPI_ACTIVATION.md`.
