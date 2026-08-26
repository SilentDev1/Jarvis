# macOS deployment

Use the root scripts and native Python environment. Keep Ollama native for
Metal acceleration.

## Local AiPi device gateway

The physical terminal resolves Jarvis by the mDNS discovery name
`jarvis.local`. That name is published by the gateway supervisor,
`scripts/start-local-device-gateway.sh`, which owns the application process,
the advertisement, duplicate protection, and cleanup.

Never start this gateway with a bare `uvicorn` command. Doing so leaves the
discovery name unpublished. The device then cannot resolve Jarvis, never
reaches ONLINE, and — because the speaker test tone is armed only from the
WebSocket CONNECTED handler — the speaker appears broken even though the codec
is fine. This exact failure cost a debugging session on 2026-08-26.

Start it through `./scripts/start.sh`, or install the launch agent for
reboot durability:

```sh
./scripts/install-launch-agents.sh
```

### Full Disk Access

This repository lives under `~/Documents`, which macOS protects with TCC. A
launchd job cannot read it until access is granted. TCC attributes a shell
script's access to its *interpreter*, so granting access to the supervisor
script would really mean granting Full Disk Access to `/bin/sh`, and therefore
to every shell script on the machine.

The installer therefore compiles a dedicated launcher binary whose only action
is to exec the supervisor at a compile-time path. It accepts no arguments and
reads no environment, so the grant cannot be repurposed. Grant access to that
one binary:

1. System Settings > Privacy & Security > Full Disk Access
2. `+`, then Shift-Cmd-G and paste:
   `~/Library/Application Support/JarvisHome/jarvis-gateway-launcher`
3. Re-run `./scripts/install-launch-agents.sh`

Moving the repository outside `~/Documents` removes the requirement entirely
and is the alternative if you prefer granting nothing.

Agent logs are written to `~/Library/Logs/JarvisHome/` rather than into the
repository, because launchd opens those paths before the granted process
starts.
