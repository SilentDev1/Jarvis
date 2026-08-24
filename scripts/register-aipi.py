#!/usr/bin/env python3
import json

from jarvis_home.config import get_settings
from jarvis_home.devices.auth import issue_device_token, revoke_device_tokens
from jarvis_home.persistence import Device, Store, utcnow


def main():
    cfg = get_settings()
    store = Store(cfg.data_dir / "jarvis.db")
    store.init()
    device_id = "aipi-front-door"
    with store.Session() as session:
        device = session.get(Device, device_id)
        device.name = "Front Door AiPi"
        device.device_type = "AIPI_LITE"
        device.provider = "aipi_stock_mcp"
        device.status = "registered"
        device.enabled = True
        device.location = "Front Door"
        device.capabilities = json.dumps(
            ["VOICE_INPUT", "VOICE_OUTPUT", "DISPLAY", "BUTTON"]
        )
        device.updated_at = utcnow()
        session.commit()
    revoke_device_tokens(store, device_id)
    token = issue_device_token(store, device_id)
    print("AiPi registered. Copy this token now; Jarvis stores only its hash:")
    print(token)


if __name__ == "__main__":
    main()
