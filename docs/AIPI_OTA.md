# AiPi local OTA updates

The terminal can be updated over the home LAN without unplugging it. Firmware
is fetched from the same authenticated Jarvis gateway the device already
trusts. XDC, Cloudflare, the public Internet and third-party firmware hosting
are not involved.

## Why two checks, not one

Every update must satisfy both a signature and a hash.

The SHA-256 proves the image is the one the manifest describes, which catches
corruption and truncation. It does not help if the gateway itself is
compromised, because whoever controls the gateway controls both the image and
the hash. The RSA-2048 signature closes that: it is made by a key that never
leaves the owner's machine and is verified on the device against an embedded
public key. A compromised gateway can refuse to serve firmware, but it cannot
forge a release.

This is a device at a front door with a microphone and a speaker. The extra
check is proportionate.

## Keys

    private  ~/Documents/SilentDev-Workspace/private-keys/aipi-ota/ota_signing_key.pem
    public   firmware/aipi-jarvis/main/ota_public_key.pem   (embedded, committed)

The private key is mode 0600, lives outside the repository, and is read only by
`scripts/publish-firmware.py`. The gateway process never touches it. Losing it
means new releases cannot be signed; a replacement key requires one USB flash
to embed the new public key.

ESP-IDF Secure Boot V2 is supported by this chip and is deliberately **not**
enabled: it burns eFuses, is irreversible, and can permanently brick a board.
Application-level signature verification gives most of the benefit and can be
undone.

## Release process

    cd firmware/aipi-jarvis && idf.py build
    ./scripts/publish-firmware.py --channel development

Publishing is separate from building on purpose. The store is not the build
directory, so a half-finished or experimental build cannot be offered to the
door by accident. The publisher refuses if `PROJECT_VER` and `FIRMWARE_VERSION`
disagree, so a released image cannot misreport its own version, and refuses a
signing key located inside the repository.

## Manifest

    version, hardware, sha256, size, buildId,
    minimumBootloaderVersion, channel, deviceId

Signed as canonical JSON: keys sorted, no whitespace. The device rebuilds that
string field by field rather than re-serialising what it received, because any
difference in key order or spacing would fail verification for a legitimate
update.

Rejected before a byte is downloaded: wrong hardware, wrong device id,
implausible size, malformed fields, bad signature. Rejected during: a stream
larger than promised, a short read, a flash write error. Rejected after: a
SHA-256 that does not match.

## Update flow

    IDLE -> OFFERED -> DOWNLOADING -> VERIFYING -> REBOOTING
         -> CONFIRMING -> SUCCEEDED

An update is refused unless the terminal is idle. Speaking, listening, an
active visitor session or an in-flight audio stream all block it, enforced
independently on both the host and the device. An update that interrupts a
visitor is worse than one that waits.

Nothing updates automatically. An offer is always an explicit owner action, and
a same or older version requires an explicit force.

## Rollback

The image is written to the inactive slot; the running slot is never touched.
After reboot the new image is unconfirmed. Reaching an authenticated Jarvis
connection already proves boot, PSRAM, display, Wi-Fi and the handshake work,
and the image is then held through a 30-second health window before being
marked valid. A build that boots and then panics, watchdogs or loses its
connection is never confirmed, and the bootloader rolls back on the next reset.

Verified on hardware. A deliberately unconfirming build was installed:

```text
App version: 0.7.4-rollback-test
authenticated local connection ONLINE
starting health window
ROLLBACK TEST build: refusing to confirm this image
esp_ota_ops: Rollback to previously worked partition. Restart.
App version: 0.7.3-ota-test
authenticated local connection ONLINE
```

The rollback path uses `esp_ota_mark_app_invalid_rollback_and_reboot()` rather
than crashing, so the test cannot leave the device in a boot loop. It is
compile-time gated behind `JARVIS_OTA_ROLLBACK_TEST` and off in normal builds.

## Power loss

- During download: only the inactive slot is being written; the running image
  is untouched and still boots.
- During flash write: same. The partial slot is never marked bootable because
  `esp_ota_set_boot_partition` has not run.
- After slot write, before reboot: the new slot is marked bootable but
  unconfirmed. It boots on next power-up and must still pass the health window.
- During first boot of the new image: unconfirmed, so a reset rolls back.

At no point is the only working image erased.

## Recovery

Normal recovery is OTA rollback, automatic and requiring no cable.

Hard recovery is the USB full-flash restore in `AIPI_FACTORY_RECOVERY.md`,
using the verified factory backup. OTA does not replace it: a corrupt
bootloader or partition table is beyond OTA's reach.

## What OTA never touches

Wi-Fi provisioning, the device credential, device identity, the factory NVS at
`0x9000`, and the factory backup. Confirmed in practice: after an update the
device kept its IP, credentials and all seven capabilities, and audio still
worked.

## Troubleshooting

- `bad_signature`: the release was signed with a different key than the one
  embedded in the running firmware.
- `wrong_hardware` / `wrong_device`: the manifest is for another board.
- `sha256_mismatch`: the served image is not the one that was signed.
- `terminal_busy` / `audio_in_progress`: the device is mid-interaction; retry
  when idle.
- `not_newer_than_installed`: pass `force` to reinstall deliberately.
- Update reported but version unchanged: the health window failed and the
  bootloader rolled back. Check the serial log for a panic in the new build.
