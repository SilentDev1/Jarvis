#!/usr/bin/env python3
"""Publish a built firmware image to the local Jarvis firmware store.

Publishing is a deliberate act, separate from building. The store is not the
build directory, so an experimental or half-finished build cannot be offered to
a device at the front door by accident.

The private signing key is read here and nowhere else; the gateway process
never touches it.

    ./scripts/publish-firmware.py --channel development

Reads the version from the firmware's own CMakeLists so the published version
cannot drift from what the image reports about itself.
"""

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jarvis_home.devices.firmware_release import (
    HARDWARE_ID,
    FirmwareError,
    FirmwareStore,
    sha256_file,
    sign_manifest,
    validate_manifest,
)

FIRMWARE_DIR = ROOT / "firmware" / "aipi-jarvis"
IMAGE = FIRMWARE_DIR / "build" / "jarvis_aipi.bin"
STORE = ROOT / "data" / "firmware"


def project_version() -> str:
    text = (FIRMWARE_DIR / "CMakeLists.txt").read_text()
    match = re.search(r'set\(PROJECT_VER "([^"]+)"\)', text)
    if not match:
        raise SystemExit("could not read PROJECT_VER from CMakeLists.txt")
    return match.group(1)


def firmware_version() -> str:
    text = (FIRMWARE_DIR / "main" / "local_connection.c").read_text()
    match = re.search(r'#define FIRMWARE_VERSION "([^"]+)"', text)
    if not match:
        raise SystemExit("could not read FIRMWARE_VERSION")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="development",
                        choices=("development", "beta", "stable"))
    parser.add_argument("--key", default=os.environ.get(
        "AIPI_OTA_SIGNING_KEY",
        str(Path.home() / "Documents/SilentDev-Workspace/private-keys/aipi-ota/ota_signing_key.pem"),
    ))
    parser.add_argument("--build-id", default=None)
    args = parser.parse_args()

    if not IMAGE.is_file():
        raise SystemExit(f"no built image at {IMAGE}; run idf.py build first")
    key = Path(args.key)
    if not key.is_file():
        raise SystemExit(f"signing key not found: {key}")
    # A key inside the repository would end up committed sooner or later.
    if ROOT in key.resolve().parents:
        raise SystemExit("refusing: signing key must live outside the repository")

    declared, reported = project_version(), firmware_version()
    if declared != reported:
        raise SystemExit(
            f"version mismatch: PROJECT_VER={declared} FIRMWARE_VERSION={reported}"
        )

    size = IMAGE.stat().st_size
    digest = sha256_file(IMAGE)
    build_id = args.build_id or f"{declared}-{digest[:8]}"

    try:
        manifest = validate_manifest({
            "version": declared,
            "hardware": HARDWARE_ID,
            "sha256": digest,
            "size": size,
            "buildId": build_id,
            "minimumBootloaderVersion": 1,
            "channel": args.channel,
        })
    except FirmwareError as error:
        raise SystemExit(f"manifest rejected: {error}") from error

    signature = sign_manifest(manifest, key)
    target = FirmwareStore(STORE).publish(declared, IMAGE, manifest, signature)

    print(f"published {declared} ({args.channel})")
    print(f"  image   : {size:,} bytes")
    print(f"  sha256  : {digest}")
    print(f"  buildId : {build_id}")
    print(f"  signed  : yes ({key.name})")
    print(f"  store   : {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
