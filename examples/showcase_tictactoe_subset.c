/*
 * Tic-tac-toe in the CPOP subset (scripted, non-interactive):
 * moves: X0, O4, X1, O8, X2  -> X wins top row.
 */
enum {
    RUN = 0,
    STEPS = 1,

    M0 = 2,
    M1 = 3,
    M2 = 4,
    M3 = 5,
    M4 = 6,

    TM0 = 7,
    TM1 = 8,
    TM2 = 9,
    TM3 = 10,
    TM4 = 11,

    X0 = 12,
    X1 = 13,
    X2 = 14,
    X3 = 15,
    X4 = 16,
    X5 = 17,
    X6 = 18,
    X7 = 19,
    X8 = 20,

    O0 = 21,
    O1 = 22,
    O2 = 23,
    O3 = 24,
    O4 = 25,
    O5 = 26,
    O6 = 27,
    O7 = 28,
    O8 = 29,

    XWIN = 30
};

signed char d[32] = {
    1, 5,
    1, 0, 0, 0, 0,
    0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0,
    0
};

int main(void) {
    while (d[RUN]) {
        d[TM0] = d[M0];
        d[TM1] = d[M1];
        d[TM2] = d[M2];
        d[TM3] = d[M3];
        d[TM4] = d[M4];

        d[X0] = d[X0] + d[TM0];
        d[O4] = d[O4] + d[TM1];
        d[X1] = d[X1] + d[TM2];
        d[O8] = d[O8] + d[TM3];
        d[X2] = d[X2] + d[TM4];
        d[XWIN] = d[XWIN] + d[TM4];

        d[M0] = d[TM4];
        d[M1] = d[TM0];
        d[M2] = d[TM1];
        d[M3] = d[TM2];
        d[M4] = d[TM3];

        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];

        pop_print("tic-tac-toe (subset)\n");

        pop_print_if(d[X0], "X");
        pop_print_if(d[O0], "O");
        pop_print_if(1 - d[X0] - d[O0], ".");
        pop_print(" ");
        pop_print_if(d[X1], "X");
        pop_print_if(d[O1], "O");
        pop_print_if(1 - d[X1] - d[O1], ".");
        pop_print(" ");
        pop_print_if(d[X2], "X");
        pop_print_if(d[O2], "O");
        pop_print_if(1 - d[X2] - d[O2], ".");
        pop_print("\n");

        pop_print_if(d[X3], "X");
        pop_print_if(d[O3], "O");
        pop_print_if(1 - d[X3] - d[O3], ".");
        pop_print(" ");
        pop_print_if(d[X4], "X");
        pop_print_if(d[O4], "O");
        pop_print_if(1 - d[X4] - d[O4], ".");
        pop_print(" ");
        pop_print_if(d[X5], "X");
        pop_print_if(d[O5], "O");
        pop_print_if(1 - d[X5] - d[O5], ".");
        pop_print("\n");

        pop_print_if(d[X6], "X");
        pop_print_if(d[O6], "O");
        pop_print_if(1 - d[X6] - d[O6], ".");
        pop_print(" ");
        pop_print_if(d[X7], "X");
        pop_print_if(d[O7], "O");
        pop_print_if(1 - d[X7] - d[O7], ".");
        pop_print(" ");
        pop_print_if(d[X8], "X");
        pop_print_if(d[O8], "O");
        pop_print_if(1 - d[X8] - d[O8], ".");
        pop_print("\n");

        pop_print_if(d[XWIN], "X wins\n");
        pop_print_if(1 - d[XWIN], "in progress\n");
        pop_print("\n");
    }
    return 0;
}
