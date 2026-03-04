#include <stdio.h>

enum {
    RUN = 0,
    STEPS = 1,
    POS = 2,
};

/*
 * POP tape bytes mutated by %hhn:
 * d[RUN]   : loop byte (non-zero => continue)
 * d[STEPS] : countdown (12 -> 0)
 * d[POS]   : snake head position on a 16-cell row (3 -> 15)
 *
 * Invariant while running: POS + STEPS = 15.
 */
static signed char d[16] = {1, 12, 3, 0};

/*
 * One format string does both state transition and rendering.
 *
 * Transition section:
 * 1) POS <- POS + 1        via "%8$c%8$*5$c%3$hhn"
 * 2) STEPS <- STEPS - 1    via "%9$239s%8$*4$c%8$*4$c%2$hhn"
 * 3) RUN <- STEPS          via "%1$hhn"
 *
 * Rendering section uses dynamic widths from POS:
 * left pad = POS - 3, right pad = 15 - POS.
 */
static const char *fmt =
    "%8$c%8$*5$c%3$hhn"
    "%9$239s%8$*4$c%8$*4$c%2$hhn%1$hhn"
    "\033[2J\033[H"
    "printf-snake (strict POP core)\n"
    "state before writeback: steps=%4$u, pos=%5$u\n"
    "rule: one-cell right per tick, stop when countdown hits 0\n\n"
    "+----------------+\n"
    "|%9$*6$s%10$s%9$*7$s|\n"
    "+----------------+\n";

int main(void) {
    while (*d)
        printf(fmt, d + RUN, d + STEPS, d + POS, (unsigned)(unsigned char)d[STEPS],
               (unsigned)(unsigned char)d[POS], (int)(unsigned char)d[POS] - 3,
               15 - (int)(unsigned char)d[POS], '\r', "", "ooo@");

    printf("\nDone. Final tape: run=%u steps=%u pos=%u\n",
           (unsigned)(unsigned char)d[RUN], (unsigned)(unsigned char)d[STEPS],
           (unsigned)(unsigned char)d[POS]);
    return 0;
}
