#!/usr/bin/env python3
"""Locate and validate an ESP-IDF partition table without assuming its offset."""

import argparse
import json
import struct
from itertools import pairwise
from pathlib import Path

ENTRY = struct.Struct("<HBBII16sI")
MAGIC = 0x50AA


def candidate(data: bytes, table_offset: int):
    entries = []
    cursor = table_offset
    for _ in range(96):
        raw = data[cursor : cursor + ENTRY.size]
        if len(raw) != ENTRY.size:
            return None
        if raw == b"\xff" * ENTRY.size or raw[:2] == b"\xeb\xeb":
            break
        magic, kind, subtype, offset, size, label_raw, flags = ENTRY.unpack(raw)
        if magic != MAGIC or not size or offset + size > len(data):
            return None
        label = label_raw.split(b"\0", 1)[0]
        try:
            label_text = label.decode("ascii")
        except UnicodeDecodeError:
            return None
        if not label_text or not all(32 <= byte < 127 for byte in label):
            return None
        entries.append(
            {
                "name": label_text,
                "type": kind,
                "subtype": subtype,
                "offset": offset,
                "size": size,
                "flags": flags,
                "encrypted": bool(flags & 1),
            }
        )
        cursor += ENTRY.size
    if not entries or not any(item["type"] == 0 for item in entries):
        return None
    ranges = sorted((item["offset"], item["offset"] + item["size"]) for item in entries)
    if any(left[1] > right[0] for left, right in pairwise(ranges)):
        return None
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    found = []
    for offset in range(0, min(len(data), 0x100000), 0x1000):
        entries = candidate(data, offset)
        if entries:
            found.append({"table_offset": offset, "partitions": entries})
    if len(found) != 1:
        raise SystemExit(f"Expected exactly one valid partition table, found {len(found)}")
    print(json.dumps(found[0], indent=2))


if __name__ == "__main__":
    main()
