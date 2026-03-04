/*
 * Input-aware tic-tac-toe (subset, stream mode).
 *
 * Per tick:
 * - read one raw byte with pop_read_byte(KEY)
 * - decode ASCII 'X'/'O' into one-hot INX/INO (linear affine decode)
 * - shift board history and insert newest mark at cell 0
 *
 * Expected input bytes: 'X' or 'O' (no newline).
 */
enum {
    RUN = 0,
    STEPS = 1,
    KEY = 2,
    INX = 3,
    INO = 4,

    X0 = 5,
    X1 = 6,
    X2 = 7,
    X3 = 8,
    X4 = 9,
    X5 = 10,
    X6 = 11,
    X7 = 12,
    X8 = 13,

    O0 = 14,
    O1 = 15,
    O2 = 16,
    O3 = 17,
    O4 = 18,
    O5 = 19,
    O6 = 20,
    O7 = 21,
    O8 = 22
};

signed char d[24] = {
    1, 9, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0
};

int main(void) {
    while (d[RUN]) {
        pop_read_byte(KEY);

        /* INX=1 for 'X'(88), 0 for 'O'(79): 57*KEY + 105 (mod 256). */
        d[INX] = 57 * d[KEY] + 105;
        /* INO=0 for 'X', 1 for 'O': -57*KEY + 152 (mod 256). */
        d[INO] = -57 * d[KEY] + 152;

        d[X8] = d[X7];
        d[X7] = d[X6];
        d[X6] = d[X5];
        d[X5] = d[X4];
        d[X4] = d[X3];
        d[X3] = d[X2];
        d[X2] = d[X1];
        d[X1] = d[X0];
        d[X0] = d[INX];

        d[O8] = d[O7];
        d[O7] = d[O6];
        d[O6] = d[O5];
        d[O5] = d[O4];
        d[O4] = d[O3];
        d[O3] = d[O2];
        d[O2] = d[O1];
        d[O1] = d[O0];
        d[O0] = d[INO];

        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];

        pop_print("tic-tac-toe input stream\n");

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
        pop_print("\n\n");
    }
    return 0;
}
