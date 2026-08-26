"""Manifest, signature and store guards for OTA.

OTA replaces the code running on a device at the front door, so every test here
checks that something bad is refused rather than that something good works.
"""


import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from jarvis_home.devices.firmware_release import (
    HARDWARE_ID,
    MAX_IMAGE_BYTES,
    FirmwareError,
    FirmwareStore,
    is_newer,
    sha256_file,
    sign_manifest,
    validate_manifest,
    verify_manifest_signature,
    version_tuple,
)


@pytest.fixture
def keypair(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = tmp_path / "k.pem"
    priv.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, pub


def base(**over):
    data = {
        "version": "0.7.0", "hardware": HARDWARE_ID,
        "sha256": "a" * 64, "size": 1_000_000,
        "buildId": "build-1", "minimumBootloaderVersion": 1,
    }
    data.update(over)
    return data


def test_a_wellformed_manifest_is_accepted():
    m = validate_manifest(base())
    assert m.version == "0.7.0"
    assert m.hardware == HARDWARE_ID


@pytest.mark.parametrize("field", [
    "version", "hardware", "sha256", "size", "buildId", "minimumBootloaderVersion",
])
def test_missing_fields_are_rejected(field):
    data = base(); del data[field]
    with pytest.raises(FirmwareError, match="missing"):
        validate_manifest(data)


def test_wrong_hardware_is_rejected():
    with pytest.raises(FirmwareError, match="wrong_hardware"):
        validate_manifest(base(hardware="esp32-c3-someone-elses-board"))


def test_wrong_device_is_rejected():
    with pytest.raises(FirmwareError, match="wrong_device"):
        validate_manifest(base(deviceId="somebody-elses-doorbell"))


def test_oversized_and_undersized_images_are_rejected():
    with pytest.raises(FirmwareError, match="size_out_of_range"):
        validate_manifest(base(size=MAX_IMAGE_BYTES + 1))
    with pytest.raises(FirmwareError, match="size_out_of_range"):
        validate_manifest(base(size=10))


def test_malformed_values_are_rejected():
    for over, match in [
        ({"version": "not-a-version"}, "invalid_version"),
        ({"sha256": "xyz"}, "invalid_sha256"),
        ({"size": "1000000"}, "invalid_size"),
        ({"size": True}, "invalid_size"),
        ({"buildId": "../../etc/passwd"}, "invalid_build_id"),
        ({"minimumBootloaderVersion": -1}, "invalid_bootloader"),
        ({"channel": "chaos"}, "unknown_channel"),
    ]:
        with pytest.raises(FirmwareError, match=match):
            validate_manifest(base(**over))


def test_uppercase_hashes_are_canonicalised_not_rejected():
    # The hash value is identical either way and the signer canonicalises the
    # same, so rejecting uppercase would only cause spurious failures.
    assert validate_manifest(base(sha256="A" * 64)).sha256 == "a" * 64


def test_non_object_manifest_is_rejected():
    for junk in ([], "string", 5, None):
        with pytest.raises(FirmwareError, match="not_an_object"):
            validate_manifest(junk)


def test_signature_round_trip(keypair):
    priv, pub = keypair
    m = validate_manifest(base())
    assert verify_manifest_signature(m, sign_manifest(m, priv), pub) is True


def test_tampering_with_any_field_breaks_the_signature(keypair):
    priv, pub = keypair
    m = validate_manifest(base())
    signature = sign_manifest(m, priv)
    # The hash is what points at the actual bytes; swapping it must invalidate.
    tampered = validate_manifest(base(sha256="b" * 64))
    assert verify_manifest_signature(tampered, signature, pub) is False
    tampered = validate_manifest(base(version="9.9.9"))
    assert verify_manifest_signature(tampered, signature, pub) is False


def test_signature_from_the_wrong_key_is_rejected(keypair, tmp_path):
    _priv, pub = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_path = tmp_path / "other.pem"
    other_path.write_bytes(other.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    m = validate_manifest(base())
    assert verify_manifest_signature(m, sign_manifest(m, other_path), pub) is False


def test_garbage_signature_returns_false_rather_than_raising(keypair):
    _, pub = keypair
    m = validate_manifest(base())
    for junk in ("", "zz", "00" * 256, "not-hex"):
        assert verify_manifest_signature(m, junk, pub) is False


def test_weak_signing_keys_are_refused(tmp_path):
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    path = tmp_path / "weak.pem"
    path.write_bytes(weak.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    with pytest.raises(FirmwareError, match="too_small"):
        sign_manifest(validate_manifest(base()), path)


def test_version_ordering_treats_prereleases_as_older():
    assert is_newer("0.7.0", "0.6.9")
    assert is_newer("0.7.0", "0.7.0-rc1")
    assert not is_newer("0.7.0", "0.7.0")
    assert not is_newer("0.6.0", "0.7.0")
    assert version_tuple("1.0.0") > version_tuple("0.99.99")


def test_store_publishes_and_serves_only_known_releases(tmp_path, keypair):
    priv, _ = keypair
    image = tmp_path / "firmware.bin"
    image.write_bytes(b"\x00" * 200_000)
    m = validate_manifest(base(sha256=sha256_file(image), size=image.stat().st_size))
    store = FirmwareStore(tmp_path / "store")
    store.publish(m.version, image, m, sign_manifest(m, priv))
    assert store.image_path("0.7.0").is_file()
    assert store.record("0.7.0")["manifest"]["version"] == "0.7.0"
    with pytest.raises(FirmwareError, match="unknown_release"):
        store.image_path("9.9.9")


def test_store_refuses_path_traversal(tmp_path):
    store = FirmwareStore(tmp_path / "store")
    for evil in ("../../etc", "..", "/etc/passwd", "0.1.0/../../x"):
        with pytest.raises(FirmwareError):
            store.image_path(evil)


def test_store_latest_picks_the_highest_version_in_channel(tmp_path, keypair):
    priv, _ = keypair
    image = tmp_path / "f.bin"; image.write_bytes(b"\x01" * 150_000)
    store = FirmwareStore(tmp_path / "store")
    for v in ("0.6.0", "0.7.0", "0.6.5"):
        m = validate_manifest(base(version=v, sha256=sha256_file(image),
                                   size=image.stat().st_size))
        store.publish(v, image, m, sign_manifest(m, priv))
    assert store.latest("development")["manifest"]["version"] == "0.7.0"
    assert store.latest("stable") is None


def test_store_ignores_corrupt_manifest_files(tmp_path):
    store = FirmwareStore(tmp_path / "store")
    bad = tmp_path / "store" / "0.1.0"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{not json")
    assert store.available() == []
