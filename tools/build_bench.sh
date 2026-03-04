#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p generated bench/compiled

./tools/c2pop.py bench/cpop_src/*.c -o generated

for src in bench/cpop_src/*.c; do
  base="$(basename "${src%.c}")"
  f="generated/${base}.pop.c"
  out="bench/compiled/${base}.pop"
  cc -std=c11 -Wall -Wextra -O2 "$f" -o "$out"
  echo "built $out"
done
