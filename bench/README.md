# CPOP Benchmark Suite (MVP)

This directory contains 10 restricted-C examples intended to be compiled by `tools/c2pop.py`.

Source files are in `bench/cpop_src/`.

## Programs

1. `01_countdown.c` - decrement to zero with gated tick output
2. `02_blink.c` - phase toggle (`ON/OFF`) with finite steps
3. `03_traffic_light.c` - one-hot traffic light FSM rotation
4. `04_ring4.c` - 4-state one-hot ring counter
5. `05_menu_cycle.c` - one-hot menu cursor cycling
6. `06_lcg_add.c` - additive generator with step-bound run flag
7. `07_accumulators.c` - coupled accumulators (`A`, `B`)
8. `08_coupled.c` - coupled linear updates (`X += Y`, `Y--`)
9. `09_token_leak.c` - refill/leak linear byte dynamics
10. `10_lock_toggle.c` - lock/unlock one-hot toggle

## Compile all benchmarks to POP C

```bash
./tools/c2pop.py bench/cpop_src/*.c -o generated
```

## Build generated programs

```bash
mkdir -p bench/compiled
for f in generated/*.pop.c; do
  cc -std=c11 -Wall -Wextra -O2 "$f" -o "bench/compiled/$(basename "${f%.c}")"
done
```

## Notes

- The subset is intentionally constrained to keep generated output close to POP purity:
  - canonical loop
  - optional raw tape input via `pop_read_byte(...)` (Gate E)
  - tape writes only via `%hhn`
  - formatting-time gated output via `%.*s`
- Purity mode:
  - default is strict (`--purity strict`)
  - use `--purity hybrid` only when expressions need comparisons/boolean operators
- This MVP subset is byte-tape focused (with arithmetic, bitwise, and comparisons)
  and does not attempt full ISO C coverage.
