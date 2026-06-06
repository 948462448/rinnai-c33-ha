#!/usr/bin/env python3
"""Decode captured Rinnai C33/HF-LPB100 TCP frames into field triples."""

from __future__ import annotations

import argparse
import pathlib
import re

HEX_RE = re.compile(r"\bhex=([0-9a-fA-F ]+)\s+ascii=")


def parse_frame(data: bytes) -> tuple[dict[str, int | str], list[tuple[int, int, bytes]]]:
    if len(data) < 8:
        return {"error": "short_frame", "length": len(data)}, []
    meta: dict[str, int | str] = {
        "magic": data[:2].hex(" "),
        "checksum_or_id": int.from_bytes(data[2:4], "big"),
        "target": data[4:6].hex(" "),
        "payload_len": int.from_bytes(data[6:8], "little"),
        "actual_payload_len": len(data) - 8,
    }
    fields: list[tuple[int, int, bytes]] = []
    offset = 8
    while offset + 3 <= len(data):
        field_id = data[offset]
        op = data[offset + 1]
        size = data[offset + 2]
        offset += 3
        if offset + size > len(data):
            fields.append((field_id, op, data[offset:]))
            break
        fields.append((field_id, op, data[offset : offset + size]))
        offset += size
    if offset != len(data):
        meta["trailing_bytes"] = len(data) - offset
    return meta, fields


def decode_value(value: bytes) -> str:
    if not value:
        return "-"
    hex_value = value.hex(" ")
    if len(value) == 1:
        return f"{hex_value} ({value[0]})"
    if len(value) == 2:
        return f"{hex_value} (le={int.from_bytes(value, 'little')}, be={int.from_bytes(value, 'big')})"
    return hex_value


def iter_log_frames(path: pathlib.Path) -> list[tuple[str, str, bytes]]:
    frames: list[tuple[str, str, bytes]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = HEX_RE.search(line)
        if not match:
            continue
        prefix = line.split(" hex=", 1)[0]
        direction = "unknown"
        if "remote->cloud" in prefix:
            direction = "remote->cloud"
        elif "cloud->remote" in prefix:
            direction = "cloud->remote"
        elif " RX " in prefix:
            direction = "rx"
        hex_text = match.group(1).strip()
        frames.append((prefix, direction, bytes.fromhex(hex_text)))
    return frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=pathlib.Path)
    parser.add_argument("--last", type=int, default=20)
    args = parser.parse_args()

    frames = iter_log_frames(args.log)
    for prefix, direction, data in frames[-args.last :]:
        meta, fields = parse_frame(data)
        print(prefix)
        print(
            "  "
            + " ".join(
                [
                    f"dir={direction}",
                    f"len={len(data)}",
                    f"payload={meta.get('actual_payload_len')}/{meta.get('payload_len')}",
                    f"id=0x{int(meta.get('checksum_or_id', 0)):04x}",
                ]
            )
        )
        for field_id, op, value in fields:
            print(f"    {field_id:02x} op={op:02x} size={len(value):02d} value={decode_value(value)}")


if __name__ == "__main__":
    main()
