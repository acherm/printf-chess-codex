# printf-chess (bis)

Authors: Mathieu Acher and Codex

## Overall idea

This project builds a basic chess engine in the spirit of
[`printf-tac-toe`](https://github.com/carlini/printf-tac-toe): one loop,
one `printf`, and state changes driven by format-string side effects.
POP aka Printf Oriented Programming. 

Core loop:

```c
int main(void) {
    init_game(&g);
    while (*d)
        printf(fmt, pop_a1_zero(), pop_a2_screen(), pop_a3_run_tok(),
               pop_a4_run_ptr(), pop_a5_side_tok(), pop_a6_side_ptr(),
               pop_a7_boot_tok(), pop_a8_boot_ptr());
    return 0;
}
```

## How it works technically

- `d[]` stores tiny POP control bytes:
  - `d[0]`: run flag
  - `d[1]`: side to move
  - `d[2]`: boot flag
- `fmt` is one long string using `%hhn` and `%s`.
- `%1$hhn%1$s` is repeated to force the print counter back to `0 (mod 256)`.
- Then `%3$s%4$hhn`, `%5$s%6$hhn`, `%7$s%8$hhn` write next values into `d[]`.
  - Tokens have length 0 or 1 (`""` or `"x"`), so `%hhn` writes 0/1 bytes.
- `%2$s` prints the full board/status frame (`g.screen`) each cycle.

The side-effect arguments also call the turn driver (`pop_cycle`) once per
`printf` evaluation, which computes chess state, engine move, and next frame.

## Is the spirit preserved?

Mostly yes:
- Single `while (*d) printf(fmt, ...)` control loop
- Single `fmt` string, `%n`-style state mutation, and byte-level loop control

Not fully pure POP:
- Chess legality, check detection, and search are implemented in normal C
  helpers for practicality and readability.

## Coding session report

- First attempt: functional chess engine, but not faithful to POP spirit.
  - It used a regular per-turn function call structure, even if `printf` was
    central to rendering.
- I thus corrected the direction:
  - enforce the canonical shape `while (*d) printf(fmt, arg);`
  - require `fmt` as one format string and `arg` as argument-side effects.
- Refactor stages:
  - moved loop control to byte state (`d[]`) with `%hhn` writes
  - concentrated frame output and state update in one `printf`
  - unfolded helper macros for `fmt`
  - unfolded `arg` into explicit arguments in the final `printf` call
- Guidance note:
  - limited technical guidance, let say key constraint ("respect POP spirit")
    was decisive and improved both architecture and faithfulness.

## Chess features

- Human plays White, engine plays Black
- Coordinate input: `e2e4`, `g1f3`, `e7e8q`
- `quit` or `resign` to stop
- Legal move generation for all pieces
- Check detection
- Checkmate and stalemate detection
- Basic alpha-beta search (fixed depth)

## Simplifications

- No castling
- No en passant
- No threefold repetition / fifty-move rule
- Promotions handled as queen promotions in practice

## Build and run

```bash
gcc -std=c11 -Wall -Wextra -O2 printf_chess.c -o printf_chess
./printf_chess
```
