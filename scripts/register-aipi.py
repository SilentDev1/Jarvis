#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

from jarvis_home.config import get_settings
from jarvis_home.devices.auth import issue_device_token, revoke_device_tokens
from jarvis_home.persistence import Device, Store, utcnow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preserve-existing", action="store_true")
    args = parser.parse_args()
    cfg = get_settings()
    store = Store(cfg.data_dir / "jarvis.db")
    store.init()
    device_id = "aipi-front-door"
    with store.Session() as session:
        device = session.get(Device, device_id)
        device.name = "Front Door AiPi"
        device.device_type = "AIPI_LITE"
        device.provider = "AIPI_LOCAL"
        device.status = "registered"
        device.enabled = True
        device.location = "Front Door"
        device.capabilities = json.dumps(
            ["DISPLAY", "BUTTON", "WIFI", "LOCAL_CONNECTION", "STATUS"]
        )
        device.updated_at = utcnow()
        session.commit()
    if not args.preserve_existing:
        revoke_device_tokens(store, device_id)
    token = issue_device_token(store, device_id)
    args.output.write_text(token + "\n")
    os.chmod(args.output, 0o600)
    print(f"AiPi registered. One-time token saved with mode 0600 at {args.output}")


if __name__ == "__main__":
    main()
