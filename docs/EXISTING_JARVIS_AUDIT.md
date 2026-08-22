# Existing Jarvis audit — 2026-08-22

## Discovery

Reasonable project locations under Projects, Development, Documents, Desktop, Code, and Developer were searched by name and for Git repositories. No established Jarvis Home, Home Assistant, Frigate, or OpenClaw project was found. No relevant service responded. Ollama 0.18.0 is installed but its API was not running. Docker CLI is installed; no running containers were returned. Homebrew is installed.

## Findings

- `SilentDev-Workspace/jarvis-api`: Node/Express developer-workspace API. It manages projects, files, terminals and processes; uses OpenAI and has no database, tests, docs, authentication boundary suitable for visitors, or front-door architecture. Port 3001 was not running. Classification: **legacy for this use case / unsuitable to reuse**. It was not modified.
- `SilentDev-Workspace/SilentDev-OS-App`: Electron desktop application with Jarvis icon assets; not a home automation core. Not modified.
- `SilentDev-Workspace/jarvis-front-door`: a partial Python prototype created immediately before this superseding specification. It contains early configuration, policy, state, and database concepts but is named and bounded around one module. Classification: **partially reusable as design input**. It was left intact; concepts were incorporated into a clean Jarvis Home structure rather than copied as a dependency.

No discovered directory was a Git repository and no remote or commit history existed to preserve. No existing Jarvis database or device data was found.

## Decision and risks

Build a new sibling `jarvis-home` repository without changing prior work. This avoids coupling a security-adjacent visitor system to a shell-capable developer API. The main migration risks are future AiPi protocol uncertainty, absent Tapo credentials, and selecting Linux acceleration hardware later; provider interfaces contain each risk.

