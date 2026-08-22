#!/usr/bin/env python3
from __future__ import annotations

import getpass
import ipaddress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_env(values: dict[str, str]) -> None:
    lines = (
        ENV.read_text().splitlines()
        if ENV.exists()
        else (ROOT / ".env.example").read_text().splitlines()
    )
    found = set()
    output = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else ""
        if key in values:
            output.append(f"{key}={quoted(values[key])}")
            found.add(key)
        else:
            output.append(line)
    output.extend(
        f"{key}={quoted(value)}" for key, value in values.items() if key not in found
    )
    ENV.write_text("\n".join(output) + "\n")
    ENV.chmod(0o600)


def main() -> None:
    print(
        "Tapo C101 local RTSP setup (credentials will be stored only in excluded .env)"
    )
    host = input("Camera IP or hostname: ").strip()
    if not host:
        raise SystemExit("Camera host is required")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if any(ch.isspace() for ch in host) or "/" in host:
            raise SystemExit("Invalid hostname") from None
    username = input("Tapo camera account username: ").strip()
    password = getpass.getpass("Tapo camera password (hidden): ")
    if not username or not password:
        raise SystemExit("Username and password are required")
    update_env(
        {
            "CAMERA_MODE": "live",
            "CAMERA_HOST": host,
            "CAMERA_USERNAME": username,
            "CAMERA_PASSWORD": password,
            "VISION_PROVIDER": "yolo",
        }
    )
    print("Saved live camera configuration to .env with mode 0600.")
    print("Run ./scripts/test-camera.sh next. The password will not be printed.")


if __name__ == "__main__":
    main()
