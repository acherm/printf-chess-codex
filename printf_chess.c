#include <stdio.h>

/*
 * POP tape (mutated by %hhn in fmt):
 * d[0]: run flag (loop condition)
 * d[1]: instruction pointer (offset in script tape)
 * d[2]: white prompt precision (0 or 6)
 * d[3]: black prompt precision (0 or 6)
 */
static signed char d[8] = {1, 0, 6, 0, 0, 0, 0, 0};

static const char z[] = "";
static const char white_prompt[] = "white>";
static const char black_prompt[] = "black>";

/*
 * One mutable board tape (always rendered from the same pointer).
 * 8x8 chars + '\n' per row.
 */
static char board_buf[] =
    "rnbqkbnr\n"
    "pppppppp\n"
    "........\n"
    "........\n"
    "........\n"
    "........\n"
    "PPPPPPPP\n"
    "RNBQKBNR\n";

enum {
    I_FROM = 0,
    I_TO = 1,
    I_DELTA = 2,
    I_ZERO = 3,
    I_STEP_PAD = 4,
    I_RUN_PAD = 5,
    I_W_PAD = 6,
    I_B_PAD = 7,
    I_STRIDE = 8,
};

/*
 * Script tape (6 instructions x 8 bytes), addressed by d[1] as byte offset:
 *   [from_idx, to_idx, piece_delta, zero_after_piece, step_pad, run_pad,
 *    w_pad, b_pad]
 *
 * Opening:
 *   no-op, e2e4, e7e5, g1f3, b8c6, f1b5
 */
static const unsigned char script[] = {
    18, 18, 0, 210, 8, 249, 255, 6,
    58, 40, 34, 176, 16, 241, 5, 250,
    13, 31, 66, 144, 24, 233, 255, 6,
    69, 50, 32, 178, 32, 225, 5, 250,
    1, 20, 64, 146, 40, 217, 255, 0,
    68, 28, 20, 190, 40, 216, 0, 0,
};

/*
 * POP core:
 * 1) mutate board tape (from/to writes) via %hhn
 * 2) mutate control tape d[] via %hhn (ip/run/prompts)
 * 3) render from a single board pointer
 * 4) formatting-time branch for prompts via %.*s
 */
static char *fmt =
    "%1$*2$s%3$hhn"
    "%1$*4$s%5$hhn"
    "%1$*6$s"
    "%1$*7$s%8$hhn"
    "%1$*9$s%10$hhn"
    "%1$*11$s%12$hhn"
    "%1$*13$s%14$hhn"
    "\033[2J\033[H"
    "printf-chess POP (board tape)\n\n"
    "%15$s\n"
    "%16$.*18$s%17$.*19$s\n";

#define ARG                                                                \
    z,                                                                     \
        46, board_buf + script[(unsigned char)d[1] + I_FROM],              \
        (int)script[(unsigned char)d[1] + I_DELTA],                        \
        board_buf + script[(unsigned char)d[1] + I_TO],                    \
        (int)script[(unsigned char)d[1] + I_ZERO],                         \
        (int)script[(unsigned char)d[1] + I_STEP_PAD], d + 1,              \
        (int)script[(unsigned char)d[1] + I_RUN_PAD], d + 0,               \
        (int)script[(unsigned char)d[1] + I_W_PAD], d + 2,                 \
        (int)script[(unsigned char)d[1] + I_B_PAD], d + 3,                 \
        board_buf,                                                          \
        white_prompt, black_prompt, (int)(unsigned char)d[2],              \
        (int)(unsigned char)d[3]

int main(void) {
    while (*d) printf(fmt, ARG);
    return 0;
}
