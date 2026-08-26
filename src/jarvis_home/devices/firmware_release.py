"""Firmware release manifests, signing, and the local firmware store.

OTA is the most dangerous operation this system performs: it replaces the code
running on a device mounted at the front door. Everything here fails closed.

Two independent checks guard an update. The SHA-256 must match the image
byte-for-byte, and the manifest must carry a valid RSA signature from a private
key that never leaves the owner's machine. The hash alone would be enough
against corruption but not against a compromised gateway, which is exactly the
attacker who could otherwise serve arbitrary firmware to the door.

The private key lives outside the repository and is never read by the gateway
process; only the signing tool touches it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# The only hardware this firmware may be installed on. A manifest naming
# anything else is refused before a byte is downloaded.
HARDWARE_ID = "aipi-lite-esp32s3"
DEVICE_ID = "aipi-front-door"

# Generous enough for any plausible build, far below the 3.875 MB slot. An
# oversized image is rejected by the manifest check rather than discovered
# part-way through writing flash.
MAX_IMAGE_BYTES = 3_500_000
MIN_IMAGE_BYTES = 100_000

CHANNELS = ("development", "beta", "stable")

_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUILD_ID = re.compile(r"^[0-9A-Za-z._-]{1,64}$")


class FirmwareError(ValueError):
    """Raised when a firmware artifact or manifest is unacceptable."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(block)
    return digest.hexdigest()


def version_tuple(version: str) -> tuple:
    """Comparable form of a semver-ish version.

    A release without a pre-release suffix sorts above one with it, so
    0.7.0 is newer than 0.7.0-rc1.
    """
    core, _, pre = version.partition("-")
    numbers = tuple(int(part) for part in core.split("."))
    return (numbers, 1, ()) if not pre else (numbers, 0, tuple(pre.split(".")))


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


@dataclass(frozen=True)
class FirmwareManifest:
    version: str
    hardware: str
    sha256: str
    size: int
    buildId: str
    minimumBootloaderVersion: int
    channel: str = "development"
    deviceId: str = DEVICE_ID

    def signing_payload(self) -> bytes:
        """Bytes actually signed.

        Serialised with sorted keys and no whitespace so the signer and the
        verifier cannot disagree about formatting.
        """
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()

    def public(self) -> dict:
        return asdict(self)


def validate_manifest(data: dict) -> FirmwareManifest:
    """Build a manifest from untrusted input, rejecting anything malformed."""
    if not isinstance(data, dict):
        raise FirmwareError("manifest_not_an_object")
    required = ("version", "hardware", "sha256", "size", "buildId",
                "minimumBootloaderVersion")
    for key in required:
        if key not in data:
            raise FirmwareError(f"manifest_missing_{key}")

    version = str(data["version"])
    if not _VERSION.match(version):
        raise FirmwareError("invalid_version")
    if str(data["hardware"]) != HARDWARE_ID:
        raise FirmwareError("wrong_hardware")
    sha = str(data["sha256"]).lower()
    if not _SHA256.match(sha):
        raise FirmwareError("invalid_sha256")
    if not isinstance(data["size"], int) or isinstance(data["size"], bool):
        raise FirmwareError("invalid_size")
    size = data["size"]
    if not MIN_IMAGE_BYTES <= size <= MAX_IMAGE_BYTES:
        raise FirmwareError("image_size_out_of_range")
    build_id = str(data["buildId"])
    if not _BUILD_ID.match(build_id):
        raise FirmwareError("invalid_build_id")
    bootloader = data["minimumBootloaderVersion"]
    if not isinstance(bootloader, int) or isinstance(bootloader, bool) or bootloader < 0:
        raise FirmwareError("invalid_bootloader_version")
    channel = str(data.get("channel", "development"))
    if channel not in CHANNELS:
        raise FirmwareError("unknown_channel")
    device_id = str(data.get("deviceId", DEVICE_ID))
    if device_id != DEVICE_ID:
        raise FirmwareError("wrong_device")

    return FirmwareManifest(
        version=version, hardware=HARDWARE_ID, sha256=sha, size=size,
        buildId=build_id, minimumBootloaderVersion=bootloader,
        channel=channel, deviceId=device_id,
    )


def sign_manifest(manifest: FirmwareManifest, private_key_path: Path) -> str:
    """Sign a manifest. Only the release tool calls this; the gateway never does."""
    key = serialization.load_pem_private_key(
        private_key_path.read_bytes(), password=None
    )
    if not isinstance(key, rsa.RSAPrivateKey):
        raise FirmwareError("signing_key_must_be_rsa")
    if key.key_size < 2048:
        raise FirmwareError("signing_key_too_small")
    signature = key.sign(
        manifest.signing_payload(), padding.PKCS1v15(), hashes.SHA256()
    )
    return signature.hex()


def verify_manifest_signature(manifest: FirmwareManifest, signature_hex: str,
                              public_key_pem: bytes) -> bool:
    """Verify a manifest signature. Returns False rather than raising."""
    try:
        key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key, rsa.RSAPublicKey):
            return False
        key.verify(
            bytes.fromhex(signature_hex),
            manifest.signing_payload(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


class FirmwareStore:
    """Serves only approved firmware artifacts from a dedicated directory.

    Deliberately not the build directory: publishing is an explicit act, so an
    in-progress or experimental build cannot be offered to the door by
    accident. Lookups are by version and the resolved path is confined to the
    store, so a crafted version string cannot escape it.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def _release_dir(self, version: str) -> Path:
        if not _VERSION.match(version):
            raise FirmwareError("invalid_version")
        candidate = (self.root / version).resolve()
        root = self.root.resolve()
        # Defence in depth: the regex already forbids separators.
        if candidate != root and root not in candidate.parents:
            raise FirmwareError("path_escape")
        return candidate

    def publish(self, version: str, image: Path, manifest: FirmwareManifest,
                signature: str) -> Path:
        target = self._release_dir(version)
        target.mkdir(parents=True, exist_ok=True)
        (target / "firmware.bin").write_bytes(image.read_bytes())
        (target / "manifest.json").write_text(
            json.dumps(
                {"manifest": manifest.public(), "signature": signature},
                indent=2, sort_keys=True,
            )
        )
        return target

    def available(self) -> list[dict]:
        if not self.root.exists():
            return []
        out = []
        for entry in sorted(self.root.iterdir()):
            record = entry / "manifest.json"
            if entry.is_dir() and record.exists():
                try:
                    out.append(json.loads(record.read_text()))
                except json.JSONDecodeError:
                    continue
        return out

    def latest(self, channel: str = "development") -> dict | None:
        releases = [
            r for r in self.available()
            if r.get("manifest", {}).get("channel") == channel
        ]
        if not releases:
            return None
        return max(releases, key=lambda r: version_tuple(r["manifest"]["version"]))

    def image_path(self, version: str) -> Path:
        path = self._release_dir(version) / "firmware.bin"
        if not path.is_file():
            raise FirmwareError("unknown_release")
        return path

    def record(self, version: str) -> dict:
        path = self._release_dir(version) / "manifest.json"
        if not path.is_file():
            raise FirmwareError("unknown_release")
        return json.loads(path.read_text())
