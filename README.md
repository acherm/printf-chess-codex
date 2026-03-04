# printf-chess (bis)

Authors: Mathieu Acher and Codex

## Framing Question

Can coding agents really master Printf-Oriented Programming (POP)?

First rough impression: yes. We quickly got a working chess engine-like program.
But careful observation showed POP purity was only partly met: too much
interpretation/logic still happened in C, with `printf` not always acting as
the true interpreter.

Main takeaway: getting a working program is easy; getting strict POP purity is
much harder.

## Overall idea

This project now contains a stricter pad-interactive POP chess demo in the
spirit of [`printf-tac-toe`](https://github.com/carlini/printf-tac-toe):
`printf` is the execution engine and `%hhn` mutates both control state and the
mutable board tape.

It took many iterations to get here. The main difficulty was avoiding a common
anti-pattern: implementing chess logic directly in C and using `printf` mostly
as a renderer. In strict POP, `printf` must be the interpreter/VM.

Core loop:

```c
int main(void) {
    while (*d &&
           scanf("%u %u %u %u %u %u %u",
                 &i_pf, &i_pt, &i_pp, &i_pr, &i_ppr, &i_pdel, &i_pzero) == 7)
        printf(fmt, ARG);
    return 0;
}
```

## How it works technically

- `d[]` is a POP control tape:
  - `d[0]`: run flag (`while (*d)`)
  - `d[1]`: from square index (apply stage)
  - `d[2]`: to square index (apply stage)
  - `d[3]`: piece byte (apply stage)
  - `d[4]`: prompt precision
- `d[5]`: piece delta (`piece - '.'`)
- `d[6]`: piece zero pad (`-piece mod 256`)
- `board_buf` is one mutable board tape (single pointer rendered every frame).
- User inputs 7 pad bytes per tick:
  - `pf pt pp pr ppr pdel pzero`
  - these are *already assembled* modulo-256 deltas for the commit writes.
- `printf`:
  - applies current move from `d[1..3]` onto board via `%hhn`
  - commits next `d[0..6]` from user pads via `%hhn`
- So per tick, C does ingestion only (`scanf`), no decode/assembler logic.
- `fmt` performs state writes with `%hhn`:
  - board mutation:
    - `board[d1] <- '.'` and `board[d2] <- d3` via `%hhn`
  - control mutation:
    - writes next `run/from/to/piece/prompt/delta/zero` in `d[]`
- Board rendering is inside `fmt` via `%21$s` (same board pointer each tick).
- Prompt branching is done by formatting itself:
  - `%22$.*23$s` prints prompt or nothing depending on precision (0/31),
    not via C `if`.
- Note: render arguments are evaluated before `printf` writes, so prompt precision
  is effectively one tick behind commit writes.

## Is the spirit preserved?

Yes, for the strict constraints:
- `printf` is the state-transition engine
- No per-tick helper/interpreter call in C
- Essential state (`d[0..6]` and board bytes) changes through `%hhn`
- At least one branch is done by formatting (`%.*s` prompt selection)
- Loop body is one `printf` call

Remaining hybrid part:
- Raw pad ingestion still starts in C (`scanf`), then `%hhn` commits next-state
  bytes into the POP tape.

## Coding session report

- There was significant back and forth to meet POP purity constraints.
- Early versions were hybrid by construction:
  - chess logic/decoding lived in C
  - `printf` was central, but not the real interpreter
- Main anti-pattern encountered repeatedly:
  - writing game logic in C each tick (even branchless/LUT-based), then feeding
    computed arguments to `printf`
- Refactor path:
  - remove per-tick helper drivers
  - move state transitions to `%hhn` writes
  - move board to one mutable tape
  - reduce C from logic to ingestion
  - finally remove per-tick assembler logic by requiring raw pad-byte commands
- Net result:
  - much higher POP purity
  - much lower chess ambition/functionality

## Chess features

- Interactive move application:
  - command format: `pf pt pp pr ppr pdel pzero`
  - stop by setting `run=0`
- Board is one mutable tape; each move is applied by `%hhn` writes in `fmt`
  (one-tick pipeline)
- Prompt visibility is formatting-controlled (`%.*s`)
- Board mapping used in the program is: `idx = (rank-1)*9 + file`.
- Example pad sequence:
  - `13 18 49 177 30 3 142`
  - `58 238 72 145 30 35 78`
  - `18 0 28 210 0 0 210`

## Simplifications

- This strict POP version is not a full chess engine.
- It is closer to a chess state/game displayer driven by a POP byte-VM.
- Building a strong chess engine in hybrid POP is straightforward (logic in C,
  POP-style rendering/state writes), but reaching near-pure POP is much harder
  and forces a major reduction in engine scope.

## Build and run

```bash
gcc -std=c11 -Wall -Wextra -O2 printf_chess.c -o printf_chess
./printf_chess
```

## Snake variant (C, printf-oriented)

A stricter POP Snake demo is available in `printf_snake.c` with lightweight
user interaction:

- single control loop: `while (*d) printf(fmt, ...)`
- `%hhn` mutates essential tape bytes (`run`, `pos`)
- core state transition is in `fmt`:
  - `run <- key + 143` via `%hhn` (so key `'q'` writes `0` to run)
  - `pos <- pos + 1` via `%hhn`
- nonblocking `read()` in `main` writes one raw byte (`d[KEY]`) only
  (no pause/quit semantics in C)
- no per-tick C update helper (`tick`/`step`/`render`) is called

Build and run:

```bash
gcc -std=c11 -Wall -Wextra -O2 printf_snake.c -o printf_snake
./printf_snake
```

This strict variant is a one-row interactive snake.

## C-to-POP compiler (MVP)

This repository now includes a restricted-subset compiler:

- input: a small C subset (byte tape + one `while (d[0])` loop)
- output: C code with canonical POP runtime:
  - `while (*d) printf(fmt, ...);`
  - tape bytes mutated only via `%hhn`
  - optional formatting-time gating via `%.*s`

Compiler script:

```bash
./tools/c2pop.py bench/cpop_src/*.c -o generated
```

Purity modes:

- default `--purity strict`: rejects comparison/boolean operators in expressions
- `--purity hybrid`: allows comparison/boolean operators (reported in cheat audit and purity score as hybrid POP)
- VM-purity audit is independent: if non-trivial expressions are still evaluated in C argument expressions,
  generated output is classified as hybrid POP even in `--purity strict` mode
- optional `--vm-pure`: hard-rejects any C-evaluated expression in assignments/print gates
  (only constants or raw `d[idx]` are allowed there)
- optional `--vm-pure-backend simple|micro|phase|vm`:
  - `simple` (default): direct vm-pure lowering; expressions must already be raw constants/`d[idx]`
  - `micro` (experimental): attempts boolean-expression lowering into `%hhn` micro-ops inside `fmt`
  - `phase` (experimental): executes one source statement per runtime phase (`switch(pc)`), prioritizing correctness for read-after-write dependencies
  - `vm` (experimental): lowers boolean/state expressions to `%hhn` micro-phases and writes tape `VM_PC_LO/VM_PC_HI` plus `vm_fmt` pointer bytes via `%hhn` (no C expression eval); loop dispatch is a single `printf(vm_fmt, ...)`
- optional `--vm-immutable-fmt` (requires `--vm-pure --vm-pure-backend vm`):
  - forbids vm format-pointer rewriting (`vm_fmt` byte updates)
  - requires lowering to a single immutable `fmt` (`printf(fmt, ...)`)
  - hard-fails when vm lowering needs multiple phases
- optional `--reject-delta-compiler`: hard-rejects non-vm-pure backend C-side write-delta construction
  (`%w[i] - %w[i-1]`)
- host-snapshot input note: feeding many input bytes per tick is classified as host-driven hybrid POP
- in `--vm-pure`, multi-write lowering uses a counter-reset template (no `%w[i]-%w[i-1]`)
- current status (2026-03): `--vm-pure-backend vm` can report `10/10 (POP-pure)` for supported non-host-snapshot programs

Experimental notes (`--vm-pure-backend micro|phase|vm`):
- designed to explore moving expression semantics from C into `printf` micro-ops
- currently boolean-oriented (`|`, `&`, `^`, and subtraction chains rooted at `1`) and still under validation
- expect large generated format strings/output volume; treat results as experimental
- safety rule: rejects read-after-write dependencies within one source tick
  (single-call `printf` pre-evaluates varargs, so those dependencies are semantically unsafe)
- `phase` backend keeps read-after-write correctness by sequencing statements across phases, but this is explicitly hybrid:
  C dispatches phases and evaluates expressions each phase (not strict POP-pure)
- `vm` backend removes C expression evaluation for supported boolean/state forms and avoids C state-indexed dispatch
- `vm` backend runtime shape is canonical: `while (*d) { tape-in(size=d[VM_BOUNDARY]); printf(vm_fmt, ...); }`
- `vm` backend still depends on host ABI details for pointer-byte writes and uses C raw IO (`fread`) as Gate-E tape-in
- `vm` backend currently uses a 16-bit tape PC (`VM_PC_LO/VM_PC_HI`), so it supports at most 65536 micro-phases
- `--vm-immutable-fmt` is a stricter vm mode: it forbids `vm_fmt` rewrites and rejects programs that need more than one lowered phase

Why generated files can be very large (compared to hand-written POP):
- current generator prioritizes explicit/auditable IR over source-size golf
- each lowered VM phase is materialized as a separate `fmt_k` string (for strict tic-tac-toe: `fmt_0..fmt_1096`)
- argument lists are fully expanded (many positional args to avoid hidden C-side logic)
- compliance artifacts are embedded in each output (`tape map`, exact `%...hhn` write fragments, full cheat audit)
- hand-written POP programs like Carlini's use dense macro compression; this compiler intentionally emits unfolded code

Build generated programs:

```bash
mkdir -p bench/compiled
for f in generated/*.pop.c; do
  cc -std=c11 -Wall -Wextra -O2 "$f" -o "bench/compiled/$(basename "${f%.c}")"
done
```

Or run the helper:

```bash
./tools/build_bench.sh
```

### Supported source subset (MVP)

- optional `enum { ... };` index/constants
- one tape declaration:
  - `signed char d[N] = {...};` or `unsigned char d[N] = {...};`
- one canonical loop:
  - `while (d[0]) { ... }`
- loop statements:
  - `pop_read_byte(IDX);` or `pop_read_byte(d[IDX]);` (optional, any number, first in loop body)
  - `d[IDX] = <expr>;`
  - `pop_print_if(<expr>, "literal");`
  - `pop_print("literal");`
- expression support:
  - arithmetic: `+`, `-`, `*`
  - bitwise: `&`, `|`, `^`, `<<`, `>>`
  - unary: `+`, `-`, `~`
  - comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=` (result is `0/1`)
  - integers, enum constants, `d[IDX]`, parentheses
- `pop_read_byte(...)` semantics:
  - generated runtime reads one raw byte via `getchar()` per `pop_read_byte(...)` call each tick
  - EOF is stored as raw byte `(signed char)EOF`; stopping behavior must be encoded in tape logic
  - in `--purity strict`, derived semantics on raw input bytes in C expressions are rejected

### Generated compliance artifacts

Each generated `.pop.c` contains:

- POP compliance report
- tape byte map
- exact `%...hhn` fragments for every write
- cheat audit answers
- purity score/classification (POP rubric)
- input audit line when `pop_read_byte(...)` is used (Gate E exception)

### Benchmarks

A 10-program benchmark suite is available under [`bench/README.md`](bench/README.md).

### Input Example

Input-aware tic-tac-toe stream demo:

```bash
./tools/c2pop.py examples/showcase_tictactoe_input_subset.c -o generated --purity hybrid
cc -std=c11 -Wall -Wextra -O2 generated/showcase_tictactoe_input_subset.pop.c -o /tmp/showcase_tictactoe_input_subset.pop
printf 'XOXOOXXOX' | /tmp/showcase_tictactoe_input_subset.pop
```

Notes:
- one input byte is consumed per tick via `pop_read_byte(KEY)`
- expected bytes are `X` or `O` (no newline)

Playable tic-tac-toe demo (legal move checks, turns, win/draw):

```bash
./tools/c2pop.py examples/showcase_tictactoe_playable_subset.c -o generated --purity hybrid
cc -std=c11 -Wall -Wextra -O2 generated/showcase_tictactoe_playable_subset.pop.c -o /tmp/showcase_tictactoe_playable_subset.pop
printf '12539' | /tmp/showcase_tictactoe_playable_subset.pop
```

Keys:
- `1..9` place on that cell
- `q` quit

Strict-mode playable tic-tac-toe with tape input protocol (`--vm-pure-backend vm`):

```bash
./tools/c2pop.py examples/showcase_tictactoe_playable_strict_subset.c -o generated --purity strict --vm-pure --vm-pure-backend vm
cc -std=c11 -Wall -Wextra -O2 generated/showcase_tictactoe_playable_strict_subset.pop.c -o /tmp/showcase_tictactoe_playable_strict_subset.pop
./tools/ttt_key_to_tape.py 12539 | /tmp/showcase_tictactoe_playable_strict_subset.pop
```

Readable output tip (hides `%hhn` padding spaces):

```bash
./tools/ttt_key_to_tape.py 12539 | /tmp/showcase_tictactoe_playable_strict_subset.pop | tr -d ' ' | sed '/^$/d'
```

Note:
- key decoding is moved outside generated C (raw tape-in only inside loop)
- runtime enforces one-hot selection; multi-cell packets are rejected as illegal
- this path is currently reported as `10/10 (POP-pure)` by the generated compliance report

Legacy host-snapshot tic-tac-toe variant (accepted by `--vm-pure`, but hybrid by design):

```bash
./tools/c2pop.py examples/showcase_tictactoe_playable_vm_pure_subset.c -o generated --purity strict --vm-pure --vm-pure-backend vm
cc -std=c11 -Wall -Wextra -O2 generated/showcase_tictactoe_playable_vm_pure_subset.pop.c -o /tmp/showcase_tictactoe_playable_vm_pure_subset.pop
./tools/ttt_vm_pure_packets.py 12539 | /tmp/showcase_tictactoe_playable_vm_pure_subset.pop
```

Notes:
- game semantics (move validation, turn/win/draw) are produced externally by `tools/ttt_vm_pure_packets.py`
- in `--vm-pure`, `pop_print_if(gate, lit)` uses `gate` directly as precision, so full-string gates should use a large non-zero byte (e.g., `255`)
- purity classification for this variant is host-driven hybrid POP (`7/10` currently)

Minimal VM-pure example:

```bash
./tools/c2pop.py examples/showcase_vm_pure_tape_gate.c -o generated --purity strict --vm-pure
cc -std=c11 -Wall -Wextra -O2 generated/showcase_vm_pure_tape_gate.pop.c -o /tmp/showcase_vm_pure_tape_gate.pop
printf '\\377' | /tmp/showcase_vm_pure_tape_gate.pop
```

VM-backed rule-kernel example (boolean lowering in `--vm-pure-backend vm`):

```bash
./tools/c2pop.py examples/showcase_vm_pure_rule_kernel_subset.c -o generated --purity strict --vm-pure --vm-pure-backend vm
cc -std=c11 -Wall -Wextra -O2 generated/showcase_vm_pure_rule_kernel_subset.pop.c -o /tmp/showcase_vm_pure_rule_kernel_subset.pop
# packet: [quit][sel0][sel1][sel2][occ0][occ1][occ2][force_o]
printf '\\001\\001\\000\\000\\000\\000\\000\\000' | /tmp/showcase_vm_pure_rule_kernel_subset.pop
```

Note:
- supported expression lowering is currently boolean/state oriented (`|`, `&`, `^`, `1-...`) plus raw copy/constants
- current generated artifact is reported as `10/10 (POP-pure)`
