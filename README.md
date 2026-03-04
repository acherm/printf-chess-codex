# printf-chess (bis)

Authors: Mathieu Acher and Codex

## Overall idea

This project now contains a stricter POP chess demo in the spirit of
[`printf-tac-toe`](https://github.com/carlini/printf-tac-toe):
the repeated execution step is exactly one `printf(fmt, ARG)`, and `%hhn`
inside `fmt` mutates both control state and board state.

Core loop:

```c
int main(void) {
    while (*d) printf(fmt, ARG);
    return 0;
}
```

## How it works technically

- `d[]` is a POP control tape:
  - `d[0]`: run flag (`while (*d)`)
  - `d[1]`: instruction pointer (byte offset in script tape)
  - `d[2]`: white prompt precision
  - `d[3]`: black prompt precision
- `board_buf` is one mutable board tape (single pointer rendered every frame).
- `script[]` is a linear transition tape. For each instruction, it stores:
  - source/destination board offsets
  - write deltas/reset for piece mutation
  - pads to write next `ip`, `run`, and prompt bytes
- `fmt` performs state writes with `%hhn`:
  - board mutation:
    - `board[from] <- '.'` and `board[to] <- piece` via `%hhn`
  - control mutation:
    - writes next `ip`, `run`, `prompt` bytes in `d[]`
- Board rendering is inside `fmt` via `%15$s` (same board pointer each tick).
- Prompt branching is done by formatting itself:
  - `%16$.*18$s%17$.*19$s` prints `white>` or `black>` depending on precision
    bytes in `d[]` (0 or 6), not via C `if`.

## Is the spirit preserved?

Yes, for the strict constraints:
- Single `while (*d) printf(fmt, ...)` control loop
- No per-tick helper/interpreter call in C
- Essential state (`d[0..3]` and board bytes) changes through `%hhn`
- At least one branch is done by formatting (`%.*s` prompt selection)

Remaining hybrid part:
- `ARG` still selects script bytes in C (`script[d[1] + field]`). So the VM
  transition parameters are in one tape, but argument selection is not yet
  done purely by formatting.

## Coding session report

- First attempt was a partial failure regarding POP purity:
  - chess logic was run in C each cycle (`pop_cycle`-style driver), so `printf`
    was not the true execution engine.
- Main correction:
  - remove per-tick logic functions from the loop path
  - keep one execution step: `printf(fmt, ARG)`
  - move meaningful state transitions to `%hhn` writes in `fmt`
- Additional correction:
  - remove per-frame board/message selection (`board[d[1]]`, `move_msg[d[1]]`)
  - keep one mutable board tape updated by `%hhn`
  - flatten transitions into one script tape with an IP in `d[1]`
- User guidance was short but decisive:
  - the strict requirement ("printf must drive execution/state transition")
    forced the architecture to become much closer to pure POP.

## Chess features

- Replays a basic opening line as a POP state machine:
  - `1. e2e4 ... e7e5 2. g1f3 ... b8c6 3. f1b5`
- Board is one mutable tape; each move is applied by `%hhn` writes in `fmt`
- Side-to-move prompt alternates (`white>` / `black>`) via formatting-time
  selection (`%.*s`)

## Simplifications

- This strict POP version is not a full legal-move chess engine.
- It is an execution-model demonstration where `printf` is the VM and chess is
  the domain payload.

## Build and run

```bash
gcc -std=c11 -Wall -Wextra -O2 printf_chess.c -o printf_chess
./printf_chess
```

## Snake variant (C, printf-oriented)

A stricter POP Snake demo is available in `printf_snake.c`:

- single control loop: `while (*d) printf(fmt, ...)`
- `%hhn` mutates essential tape bytes (`run`, `steps`, `pos`, `padl`, `padr`)
- core state transition is in `fmt`:
  - `pos <- pos + 1` via `%hhn`
  - `steps <- steps - 1` via `%hhn`
  - `run <- steps` via `%hhn` (loop control)
- derived render widths (`padl`, `padr`) are also updated in `fmt` (no
  per-tick arithmetic like `pos-3` in C)
- no per-tick C update helper (`tick`/`step`/`render`) is called

Build and run:

```bash
gcc -std=c11 -Wall -Wextra -O2 printf_snake.c -o printf_snake
./printf_snake
```

This strict variant is auto-running (one-row snake).
