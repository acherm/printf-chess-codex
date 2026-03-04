#!/usr/bin/env python3
"""Encode simple snake keys into 3-byte raw tape packets.

Packet format per tick:
  [quit][left][right]

Key mapping:
  q -> quit packet
  a -> left packet
  d -> right packet
  . -> no-op tick
Any other non-newline character is treated as no-op.
"""

from __future__ import annotations

import argparse
import sys


def encode_char(ch: str) -> bytes:
    if ch == "q":
        return bytes((1, 0, 0))
    if ch == "a":
        return bytes((0, 1, 0))
    if ch == "d":
        return bytes((0, 0, 1))
    return bytes((0, 0, 0))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Encode snake keys (a/d/./q) to raw 3-byte packets")
    ap.add_argument("keys", nargs="?", default="", help="Key stream, e.g. ...d..a...q")
    args = ap.parse_args(argv)

    data = args.keys if args.keys else sys.stdin.read()
    data = data.replace("\n", "")

    out = bytearray()
    for ch in data:
        out.extend(encode_char(ch))
    sys.stdout.buffer.write(bytes(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
