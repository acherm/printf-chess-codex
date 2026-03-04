/*
 * Non-trivial CPOP showcase #2:
 * - dual one-hot clocks (period 5 and period 7)
 * - coupled output stream with formatting-time gates
 * - all runtime state transitions via assignments lowered to %hhn
 */
enum {
    RUN = 0,
    STEPS = 1,

    A0 = 2,
    A1 = 3,
    A2 = 4,
    A3 = 5,
    A4 = 6,

    B0 = 7,
    B1 = 8,
    B2 = 9,
    B3 = 10,
    B4 = 11,
    B5 = 12,
    B6 = 13,

    TA0 = 14,
    TA1 = 15,
    TA2 = 16,
    TA3 = 17,
    TA4 = 18,

    TB0 = 19,
    TB1 = 20,
    TB2 = 21,
    TB3 = 22,
    TB4 = 23,
    TB5 = 24,
    TB6 = 25
};

signed char d[28] = {
    1, 35,
    1, 0, 0, 0, 0,
    1, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0,
    0, 0
};

int main(void) {
    while (d[RUN]) {
        d[TA0] = d[A0];
        d[TA1] = d[A1];
        d[TA2] = d[A2];
        d[TA3] = d[A3];
        d[TA4] = d[A4];

        d[A0] = d[TA4];
        d[A1] = d[TA0];
        d[A2] = d[TA1];
        d[A3] = d[TA2];
        d[A4] = d[TA3];

        d[TB0] = d[B0];
        d[TB1] = d[B1];
        d[TB2] = d[B2];
        d[TB3] = d[B3];
        d[TB4] = d[B4];
        d[TB5] = d[B5];
        d[TB6] = d[B6];

        d[B0] = d[TB6];
        d[B1] = d[TB0];
        d[B2] = d[TB1];
        d[B3] = d[TB2];
        d[B4] = d[TB3];
        d[B5] = d[TB4];
        d[B6] = d[TB5];

        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];

        pop_print_if(d[A0], "A");
        pop_print_if(d[A1], ".");
        pop_print_if(d[A2], ".");
        pop_print_if(d[A3], ".");
        pop_print_if(d[A4], ".");

        pop_print(":");

        pop_print_if(d[B0], "B");
        pop_print_if(d[B1], ".");
        pop_print_if(d[B2], ".");
        pop_print_if(d[B3], ".");
        pop_print_if(d[B4], ".");
        pop_print_if(d[B5], ".");
        pop_print_if(d[B6], ".");

        pop_print("\n");
    }
    return 0;
}
