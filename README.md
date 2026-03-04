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
  - `pop_read_byte(IDX);` or `pop_read_byte(d[IDX]);` (optional, at most one, first in loop body)
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
  - generated runtime reads one raw byte via `getchar()` each tick and stores it into that tape byte before `printf`
  - EOF is stored as raw byte `(signed char)EOF`; stopping behavior must be encoded in tape logic

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
./tools/c2pop.py examples/showcase_tictactoe_input_subset.c -o generated
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

Strict-mode playable tic-tac-toe (no comparisons in source subset):

```bash
./tools/c2pop.py examples/showcase_tictactoe_playable_strict_subset.c -o generated --purity strict
cc -std=c11 -Wall -Wextra -O2 generated/showcase_tictactoe_playable_strict_subset.pop.c -o /tmp/showcase_tictactoe_playable_strict_subset.pop
printf '12539' | /tmp/showcase_tictactoe_playable_strict_subset.pop
```

Note:
- this is strict *subset* compliant (`--purity strict`) but still hybrid under VM-purity audit,
  because non-trivial per-tick expressions are evaluated in C argument expressions.
