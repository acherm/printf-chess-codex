/*
 * Basic snake in the restricted CPOP subset.
 *
 * One-row snake head (length 1), 8 cells, wrap-around movement.
 * Input tape protocol per tick (3 raw bytes):
 *   [quit][left][right]
 *
 * No collision logic and no growth: this is intentionally minimal to keep
 * generated POP size manageable while remaining playable.
 */
enum {
    RUN = 0,
    DIR = 1, /* 1 -> right, 0 -> left */

    H0 = 2,
    H1 = 3,
    H2 = 4,
    H3 = 5,
    H4 = 6,
    H5 = 7,
    H6 = 8,
    H7 = 9,

    N0 = 10,
    N1 = 11,
    N2 = 12,
    N3 = 13,
    N4 = 14,
    N5 = 15,
    N6 = 16,
    N7 = 17,

    IN_QUIT = 18,
    IN_LEFT = 19,
    IN_RIGHT = 20
};

/* Initial state: running, direction right, head at cell 0. */
signed char d[24] = {
    1, 1,
    1, 0, 0, 0, 0, 0, 0, 0
};

int main(void) {
    while (d[RUN]) {
        pop_read_byte(IN_QUIT);
        pop_read_byte(IN_LEFT);
        pop_read_byte(IN_RIGHT);

        /* Direction update from raw packet bytes (0/1). */
        d[DIR] = d[DIR] | d[IN_RIGHT];
        d[DIR] = d[DIR] & (1 - d[IN_LEFT]);

        /* Next head position (wrap-around), then commit. */
        d[N0] = (d[DIR] & d[H7]) | ((1 - d[DIR]) & d[H1]);
        d[N1] = (d[DIR] & d[H0]) | ((1 - d[DIR]) & d[H2]);
        d[N2] = (d[DIR] & d[H1]) | ((1 - d[DIR]) & d[H3]);
        d[N3] = (d[DIR] & d[H2]) | ((1 - d[DIR]) & d[H4]);
        d[N4] = (d[DIR] & d[H3]) | ((1 - d[DIR]) & d[H5]);
        d[N5] = (d[DIR] & d[H4]) | ((1 - d[DIR]) & d[H6]);
        d[N6] = (d[DIR] & d[H5]) | ((1 - d[DIR]) & d[H7]);
        d[N7] = (d[DIR] & d[H6]) | ((1 - d[DIR]) & d[H0]);

        d[H0] = d[N0];
        d[H1] = d[N1];
        d[H2] = d[N2];
        d[H3] = d[N3];
        d[H4] = d[N4];
        d[H5] = d[N5];
        d[H6] = d[N6];
        d[H7] = d[N7];

        d[RUN] = 1 - d[IN_QUIT];

        pop_print("snake (basic subset)\n");
        pop_print("packet per tick: [quit][left][right]\n");
        pop_print("helper keys: a=left d=right .=tick q=quit\n\n");

        pop_print("|");
        pop_print_if(d[H0], "O"); pop_print_if(1 - d[H0], ".");
        pop_print(" ");
        pop_print_if(d[H1], "O"); pop_print_if(1 - d[H1], ".");
        pop_print(" ");
        pop_print_if(d[H2], "O"); pop_print_if(1 - d[H2], ".");
        pop_print(" ");
        pop_print_if(d[H3], "O"); pop_print_if(1 - d[H3], ".");
        pop_print(" ");
        pop_print_if(d[H4], "O"); pop_print_if(1 - d[H4], "*");
        pop_print(" ");
        pop_print_if(d[H5], "O"); pop_print_if(1 - d[H5], ".");
        pop_print(" ");
        pop_print_if(d[H6], "O"); pop_print_if(1 - d[H6], ".");
        pop_print(" ");
        pop_print_if(d[H7], "O"); pop_print_if(1 - d[H7], ".");
        pop_print("|\n");

        pop_print_if(d[DIR], "dir: right\n");
        pop_print_if(1 - d[DIR], "dir: left\n");
        pop_print_if(d[IN_QUIT], "quit\n");
        pop_print("\n");
    }
    return 0;
}
