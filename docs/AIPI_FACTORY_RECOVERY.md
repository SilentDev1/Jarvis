# AiPi factory backup and recovery

## Verified factory image — 2026-08-24

The physical unit on `/dev/cu.usbmodem21101` was identified read-only as an
ESP32-S3 QFN56 revision 0.2 with 8 MB embedded PSRAM, 40 MHz crystal,
USB-Serial/JTAG, and 16 MB quad SPI flash. Secure Boot and flash encryption are
disabled. Two complete 16 MB reads match byte-for-byte at SHA-256
`4121917d9de680499ceb595a76b65e166901e6404fc28bdddbc8f1563011cb39`.
The private backup is outside the repository at
`/Users/silentd3v/Documents/SilentDev-Workspace/private-backups/aipi/<device-id>/20260824T192347Z`.
Stock firmware remains intact; no write or erase command was executed.

Update: on 2026-08-24, after the recovery gate was reverified, the authorized
Jarvis `0.1.0-bringup` stage-1 image was written. The complete factory backup and
checksum-gated restore remain available. The custom write did not erase the
factory NVS range at `0x9000`; nevertheless, complete restoration at `0x0`
remains the preferred recovery path.

The physically decoded map is:

| Image | Address | Size |
| --- | ---: | ---: |
| bootloader | `0x00000000` | `0x00008000` |
| partition table | `0x00008000` | `0x00001000` |
| nvs | `0x00009000` | `0x00004000` |
| otadata | `0x0000D000` | `0x00002000` |
| phy_init | `0x0000F000` | `0x00001000` |
| model | `0x00010000` | `0x000F0000` |
| ota_0 | `0x00100000` | `0x00600000` |
| ota_1 | `0x00700000` | `0x00600000` |

`ota_0` contains a valid xiaozhi 1.0.41 image and `ota_1` a valid xiaozhi
1.2.5 image. No dedicated provisioning partition was identified. NVS, model,
unpartitioned space, and the complete flash image are all preserved privately.

Never infer that a backup is valid from filenames alone. Factory images may
contain Wi-Fi credentials, XDC provisioning, device certificates, tokens, and
calibration. `backups/` is ignored by Git; do not display, upload, attach, or
commit its contents.

## Read-only identification and backup

1. Place the AiPi beside the Mac and connect it with a known data-capable USB-C
   cable. Do not hold BOOT yet.
2. Run `ls /dev/cu.*` before and after connection and identify the one newly
   appearing device. Do not select a Bluetooth port.
3. If normal USB does not expose the ESP32-S3 ROM, hold the physical BOOT button,
   tap RESET or reconnect power, then release BOOT. This is the unavoidable
   physical action needed to enter download mode.
4. Install a pinned `esptool` in the project environment and run:

   ```sh
   AIPI_PORT=/dev/cu.usbmodemXXXX ./scripts/aipi-info.sh
   ```

   Record chip model/revision, MAC, flash manufacturer/device ID, detected flash
   size, crystal, and serial path in the local backup directory. Do not commit
   the device identity.
5. Set the exact byte count reported by the tool—do not assume 16 MB—and run:

   ```sh
   AIPI_PORT=/dev/cu.usbmodemXXXX \
   AIPI_FLASH_SIZE_BYTES=<verified-byte-count> \
   ./scripts/aipi-backup.sh
   ```

   The script performs two independent reads from address `0x0`, requires a
   byte-for-byte match, verifies the expected length, and creates SHA-256 sums.
6. Parse the partition table with `scripts/aipi-parse-partitions.py`, which scans
   aligned candidates, validates magic, labels, ranges, overlap, and application
   presence, and requires exactly one result. On this image it located the table
   at `0x8000`. Save its raw bytes and decoded map as `partition-table.bin` and
   `flash-map.txt`.
7. Extract each partition from the verified full image using the parsed offset
   and length. At minimum preserve bootloader, partition table, NVS/device data,
   OTA data, PHY/calibration, factory app, and both OTA app slots if present.
   Record exact hexadecimal restore addresses and lengths, then add every file
   to `SHA256SUMS`.
8. Compare every range with the independent second full read. The bootloader,
   partition table, and NVS were additionally extracted from read #2 and matched
   directly; both complete images match, which verifies all other ranges too.

Only create local `RECOVERY_GATE_PASSED` inside the private timestamped backup
after every hard gate item has documentary evidence and all hashes match. The
repository never creates this marker automatically.

## Full factory restoration

Restoration is destructive and is not a backup test. Use it only after custom
firmware needs removal or recovery is intentionally being physically proven.

1. Verify the exact device port again with `aipi-info.sh`.
2. Enter the ESP32-S3 ROM bootloader using BOOT/RESET.
3. Set the exact timestamped backup directory and explicitly authorize restore:

   ```sh
   AIPI_PORT=/dev/cu.usbmodemXXXX \
   AIPI_FACTORY_BACKUP_DIR=/Users/silentd3v/Documents/SilentDev-Workspace/private-backups/aipi/<device-id>/20260824T192347Z \
   AIPI_EXPECTED_MAC=<from-private-device-info.txt> \
   AIPI_ALLOW_FACTORY_RESTORE=RESTORE_FACTORY_IMAGE \
   ./scripts/aipi-restore-factory.sh
   ```

4. The wrapper checks SHA-256, waits ten seconds, writes the complete original
   image to address `0x0`, and invokes flash verification.
5. Reset normally. Confirm stock logo/firmware, display, function button,
   microphone capture, speaker response, Wi-Fi provisioning/connection, and XDC
   binding. If binding does not survive, stop and inspect the preserved NVS and
   provisioning partitions; do not factory-reset or invent credentials.

A complete image restore to `0x0` is preferred because it preserves every
original offset. Partition-specific commands are recovery diagnostics only and
must use the verified `flash-map.txt` addresses.

Exact partition-level recovery commands, if full restore is inappropriate, are:

```sh
esptool --chip esp32s3 --port /dev/cu.usbmodem21101 write-flash \
  0x00000000 bootloader.bin \
  0x00008000 partition-table.bin \
  0x00009000 nvs.bin \
  0x0000D000 ota-data.bin \
  0x0000F000 phy-init.bin \
  0x00010000 model.bin \
  0x00100000 ota-0.bin \
  0x00700000 ota-1.bin
```

Do not run that command unless recovery is required. A complete-image restore
also preserves bytes outside declared partitions and is therefore the preferred
factory restoration method. Recovery becomes physically proven only after a
post-write restore and complete stock acceptance test; the pre-flash recovery
gate relies on the verified double read, exact map, valid images, manifest, and
read-only restore dry run.
