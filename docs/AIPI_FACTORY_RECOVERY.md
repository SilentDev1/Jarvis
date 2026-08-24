# AiPi factory backup and recovery

## Current gate status

As of 2026-08-24, no AiPi USB serial device is visible on the Jarvis Mac and
`esptool` is not installed. Only Bluetooth and macOS debug serial devices are
present. Therefore no factory bytes have been read and the custom-flash gate is
**closed**. Stock firmware remains intact.

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
6. Parse the partition table from the full image using the `gen_esp32part.py`
   shipped with the same pinned ESP-IDF release. Determine its actual location
   from the boot log/image metadata; do not assume `0x8000`. Save both the raw
   partition-table bytes and parsed CSV as `partition-table.bin` and
   `flash-map.txt`.
7. Extract each partition from the verified full image using the parsed offset
   and length. At minimum preserve bootloader, partition table, NVS/device data,
   OTA data, PHY/calibration, factory app, and both OTA app slots if present.
   Record exact hexadecimal restore addresses and lengths, then add every file
   to `SHA256SUMS`.
8. Re-read the bootloader, partition table, NVS/device partitions, and factory
   application directly from the device. Compare each direct read to the range
   extracted from `full-flash.bin`.

Only create local `backups/aipi-factory/RECOVERY_GATE_PASSED` after every hard
gate item has documentary evidence and all hashes match. The repository never
creates this marker automatically.

## Full factory restoration

Restoration is destructive and is not a backup test. Use it only after custom
firmware needs removal or recovery is intentionally being physically proven.

1. Verify the exact device port again with `aipi-info.sh`.
2. Enter the ESP32-S3 ROM bootloader using BOOT/RESET.
3. Set the exact timestamped backup directory and explicitly authorize restore:

   ```sh
   AIPI_PORT=/dev/cu.usbmodemXXXX \
   AIPI_FACTORY_BACKUP_DIR=backups/aipi-factory/<timestamp> \
   AIPI_ALLOW_FACTORY_RESTORE=YES \
   ./scripts/aipi-restore-factory.sh
   ```

4. The wrapper checks SHA-256, waits ten seconds, writes the complete original
   image to address `0x0`, and invokes flash verification.
5. Reset normally. Confirm stock logo/firmware, display, function button,
   microphone capture, speaker response, Wi-Fi provisioning/connection, and XDC
   binding. If binding does not survive, stop and inspect the preserved NVS and
   provisioning partitions; do not factory-reset or invent credentials.

A complete image restore is preferred because it preserves every original
offset. Partition-specific commands are recovery diagnostics only and must use
the verified `flash-map.txt` addresses.

Recovery is not “proven” until a post-write physical restore and the complete
stock acceptance checklist pass. Before the first custom flash, the current
minimum gate requires validated reads, exact addresses, checksums, and a credible
restore command; its current status is FAIL because the device is not connected.
