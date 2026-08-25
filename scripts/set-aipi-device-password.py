#!/usr/bin/env python3
import getpass
from pathlib import Path

from jarvis_home.config import get_settings
from jarvis_home.devices.auth import (
    revoke_device_token,
    set_device_password,
)
from jarvis_home.persistence import Store


def main():
    password = getpass.getpass("New AiPi-only device password: ")
    confirmation = getpass.getpass("Confirm device password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match")
    cfg = get_settings()
    store = Store(cfg.data_dir / "jarvis.db")
    store.init()
    old_token_file = Path("/private/tmp/jarvis-aipi-local-token")
    if old_token_file.exists():
        revoke_device_token(store, old_token_file.read_text().strip())
        old_token_file.unlink()
    set_device_password(store, "aipi-front-door", password)
    password = ""
    confirmation = ""
    print("AiPi device password hash saved; plaintext was not written to disk.")


if __name__ == "__main__":
    main()
