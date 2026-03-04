/*
 * Playable tic-tac-toe in the CPOP subset.
 *
 * Input (one byte per tick):
 * - '1'..'9': attempt to play that cell
 * - 'q': quit
 *
 * Rules:
 * - legal move required (cell must be empty)
 * - turn toggles only after a legal move
 * - win/draw detection is computed in tape
 */
enum {
    RUN = 0,
    TURN = 1, /* 1 -> X, 0 -> O */
    KEY = 2,
    VALID = 3,
    XWIN = 4,
    OWIN = 5,
    DRAW = 6,
    QUIT = 7,

    SEL0 = 8,
    SEL1 = 9,
    SEL2 = 10,
    SEL3 = 11,
    SEL4 = 12,
    SEL5 = 13,
    SEL6 = 14,
    SEL7 = 15,
    SEL8 = 16,

    X0 = 17,
    X1 = 18,
    X2 = 19,
    X3 = 20,
    X4 = 21,
    X5 = 22,
    X6 = 23,
    X7 = 24,
    X8 = 25,

    O0 = 26,
    O1 = 27,
    O2 = 28,
    O3 = 29,
    O4 = 30,
    O5 = 31,
    O6 = 32,
    O7 = 33,
    O8 = 34,

    HASSEL = 35,
    ILLEGAL = 36
};

signed char d[40] = {
    1, 1, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0,
    0, 0, 0
};

int main(void) {
    while (d[RUN]) {
        pop_read_byte(KEY);

        d[QUIT] = (d[KEY] == 113); /* 'q' */

        d[SEL0] = (d[KEY] == 49); /* '1' */
        d[SEL1] = (d[KEY] == 50); /* '2' */
        d[SEL2] = (d[KEY] == 51); /* '3' */
        d[SEL3] = (d[KEY] == 52); /* '4' */
        d[SEL4] = (d[KEY] == 53); /* '5' */
        d[SEL5] = (d[KEY] == 54); /* '6' */
        d[SEL6] = (d[KEY] == 55); /* '7' */
        d[SEL7] = (d[KEY] == 56); /* '8' */
        d[SEL8] = (d[KEY] == 57); /* '9' */

        d[HASSEL] = d[SEL0] | d[SEL1] | d[SEL2] | d[SEL3] | d[SEL4] | d[SEL5] | d[SEL6] | d[SEL7] | d[SEL8];

        d[VALID] = (
            (d[SEL0] & (1 - d[X0] - d[O0])) |
            (d[SEL1] & (1 - d[X1] - d[O1])) |
            (d[SEL2] & (1 - d[X2] - d[O2])) |
            (d[SEL3] & (1 - d[X3] - d[O3])) |
            (d[SEL4] & (1 - d[X4] - d[O4])) |
            (d[SEL5] & (1 - d[X5] - d[O5])) |
            (d[SEL6] & (1 - d[X6] - d[O6])) |
            (d[SEL7] & (1 - d[X7] - d[O7])) |
            (d[SEL8] & (1 - d[X8] - d[O8]))
        );

        d[ILLEGAL] = d[HASSEL] & (1 - d[VALID]);

        d[X0] = d[X0] | (d[TURN] & d[SEL0] & (1 - d[X0] - d[O0]));
        d[X1] = d[X1] | (d[TURN] & d[SEL1] & (1 - d[X1] - d[O1]));
        d[X2] = d[X2] | (d[TURN] & d[SEL2] & (1 - d[X2] - d[O2]));
        d[X3] = d[X3] | (d[TURN] & d[SEL3] & (1 - d[X3] - d[O3]));
        d[X4] = d[X4] | (d[TURN] & d[SEL4] & (1 - d[X4] - d[O4]));
        d[X5] = d[X5] | (d[TURN] & d[SEL5] & (1 - d[X5] - d[O5]));
        d[X6] = d[X6] | (d[TURN] & d[SEL6] & (1 - d[X6] - d[O6]));
        d[X7] = d[X7] | (d[TURN] & d[SEL7] & (1 - d[X7] - d[O7]));
        d[X8] = d[X8] | (d[TURN] & d[SEL8] & (1 - d[X8] - d[O8]));

        d[O0] = d[O0] | ((1 - d[TURN]) & d[SEL0] & (1 - d[X0] - d[O0]));
        d[O1] = d[O1] | ((1 - d[TURN]) & d[SEL1] & (1 - d[X1] - d[O1]));
        d[O2] = d[O2] | ((1 - d[TURN]) & d[SEL2] & (1 - d[X2] - d[O2]));
        d[O3] = d[O3] | ((1 - d[TURN]) & d[SEL3] & (1 - d[X3] - d[O3]));
        d[O4] = d[O4] | ((1 - d[TURN]) & d[SEL4] & (1 - d[X4] - d[O4]));
        d[O5] = d[O5] | ((1 - d[TURN]) & d[SEL5] & (1 - d[X5] - d[O5]));
        d[O6] = d[O6] | ((1 - d[TURN]) & d[SEL6] & (1 - d[X6] - d[O6]));
        d[O7] = d[O7] | ((1 - d[TURN]) & d[SEL7] & (1 - d[X7] - d[O7]));
        d[O8] = d[O8] | ((1 - d[TURN]) & d[SEL8] & (1 - d[X8] - d[O8]));

        d[XWIN] = (
            (d[X0] & d[X1] & d[X2]) |
            (d[X3] & d[X4] & d[X5]) |
            (d[X6] & d[X7] & d[X8]) |
            (d[X0] & d[X3] & d[X6]) |
            (d[X1] & d[X4] & d[X7]) |
            (d[X2] & d[X5] & d[X8]) |
            (d[X0] & d[X4] & d[X8]) |
            (d[X2] & d[X4] & d[X6])
        );

        d[OWIN] = (
            (d[O0] & d[O1] & d[O2]) |
            (d[O3] & d[O4] & d[O5]) |
            (d[O6] & d[O7] & d[O8]) |
            (d[O0] & d[O3] & d[O6]) |
            (d[O1] & d[O4] & d[O7]) |
            (d[O2] & d[O5] & d[O8]) |
            (d[O0] & d[O4] & d[O8]) |
            (d[O2] & d[O4] & d[O6])
        );

        d[DRAW] = (
            (d[X0] | d[O0]) & (d[X1] | d[O1]) & (d[X2] | d[O2]) &
            (d[X3] | d[O3]) & (d[X4] | d[O4]) & (d[X5] | d[O5]) &
            (d[X6] | d[O6]) & (d[X7] | d[O7]) & (d[X8] | d[O8]) &
            (1 - (d[XWIN] | d[OWIN]))
        );

        d[TURN] = d[TURN] ^ d[VALID];
        d[RUN] = (1 - (d[XWIN] | d[OWIN] | d[DRAW])) & (1 - d[QUIT]);

        pop_print("tic-tac-toe (playable subset)\n");
        pop_print("keys: 1..9 to play, q to quit\n\n");

        pop_print_if(d[X0], "X"); pop_print_if(d[O0], "O"); pop_print_if(1 - d[X0] - d[O0], "1");
        pop_print(" |");
        pop_print_if(d[X1], "X"); pop_print_if(d[O1], "O"); pop_print_if(1 - d[X1] - d[O1], "2");
        pop_print(" |");
        pop_print_if(d[X2], "X"); pop_print_if(d[O2], "O"); pop_print_if(1 - d[X2] - d[O2], "3");
        pop_print("\n--+--+--\n");

        pop_print_if(d[X3], "X"); pop_print_if(d[O3], "O"); pop_print_if(1 - d[X3] - d[O3], "4");
        pop_print(" |");
        pop_print_if(d[X4], "X"); pop_print_if(d[O4], "O"); pop_print_if(1 - d[X4] - d[O4], "5");
        pop_print(" |");
        pop_print_if(d[X5], "X"); pop_print_if(d[O5], "O"); pop_print_if(1 - d[X5] - d[O5], "6");
        pop_print("\n--+--+--\n");

        pop_print_if(d[X6], "X"); pop_print_if(d[O6], "O"); pop_print_if(1 - d[X6] - d[O6], "7");
        pop_print(" |");
        pop_print_if(d[X7], "X"); pop_print_if(d[O7], "O"); pop_print_if(1 - d[X7] - d[O7], "8");
        pop_print(" |");
        pop_print_if(d[X8], "X"); pop_print_if(d[O8], "O"); pop_print_if(1 - d[X8] - d[O8], "9");
        pop_print("\n\n");

        pop_print_if(d[ILLEGAL], "illegal move (occupied)\n");
        pop_print_if((1 - (d[XWIN] | d[OWIN] | d[DRAW])) & d[TURN], "turn: X\n");
        pop_print_if((1 - (d[XWIN] | d[OWIN] | d[DRAW])) & (1 - d[TURN]), "turn: O\n");
        pop_print_if(d[XWIN], "X wins\n");
        pop_print_if(d[OWIN], "O wins\n");
        pop_print_if(d[DRAW], "draw\n");
        pop_print_if(d[QUIT], "quit\n");
        pop_print("\n");
    }
    return 0;
}
