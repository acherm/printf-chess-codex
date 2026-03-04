/*
 * Non-trivial CPOP showcase:
 * - 15-state one-hot ring (mod 15)
 * - Fizz/Buzz/FizzBuzz token emission via pop_print_if gates
 * - no per-iteration C control flow beyond while(d[0])
 */
enum {
    RUN = 0,
    STEPS = 1,

    P0 = 2,
    P1 = 3,
    P2 = 4,
    P3 = 5,
    P4 = 6,
    P5 = 7,
    P6 = 8,
    P7 = 9,
    P8 = 10,
    P9 = 11,
    P10 = 12,
    P11 = 13,
    P12 = 14,
    P13 = 15,
    P14 = 16,

    T0 = 17,
    T1 = 18,
    T2 = 19,
    T3 = 20,
    T4 = 21,
    T5 = 22,
    T6 = 23,
    T7 = 24,
    T8 = 25,
    T9 = 26,
    T10 = 27,
    T11 = 28,
    T12 = 29,
    T13 = 30,
    T14 = 31
};

signed char d[32] = {
    1, 30,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

int main(void) {
    while (d[RUN]) {
        d[T0] = d[P0];
        d[T1] = d[P1];
        d[T2] = d[P2];
        d[T3] = d[P3];
        d[T4] = d[P4];
        d[T5] = d[P5];
        d[T6] = d[P6];
        d[T7] = d[P7];
        d[T8] = d[P8];
        d[T9] = d[P9];
        d[T10] = d[P10];
        d[T11] = d[P11];
        d[T12] = d[P12];
        d[T13] = d[P13];
        d[T14] = d[P14];

        d[P0] = d[T14];
        d[P1] = d[T0];
        d[P2] = d[T1];
        d[P3] = d[T2];
        d[P4] = d[T3];
        d[P5] = d[T4];
        d[P6] = d[T5];
        d[P7] = d[T6];
        d[P8] = d[T7];
        d[P9] = d[T8];
        d[P10] = d[T9];
        d[P11] = d[T10];
        d[P12] = d[T11];
        d[P13] = d[T12];
        d[P14] = d[T13];

        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];

        pop_print_if(d[P0], "Fizz");
        pop_print_if(d[P3], "Fizz");
        pop_print_if(d[P6], "Fizz");
        pop_print_if(d[P9], "Fizz");
        pop_print_if(d[P12], "Fizz");

        pop_print_if(d[P0], "Buzz");
        pop_print_if(d[P5], "Buzz");
        pop_print_if(d[P10], "Buzz");

        pop_print_if(d[P1], ".");
        pop_print_if(d[P2], ".");
        pop_print_if(d[P4], ".");
        pop_print_if(d[P7], ".");
        pop_print_if(d[P8], ".");
        pop_print_if(d[P11], ".");
        pop_print_if(d[P13], ".");
        pop_print_if(d[P14], ".");

        pop_print("\n");
    }
    return 0;
}
