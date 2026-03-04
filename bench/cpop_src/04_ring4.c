/* expected: POP-pure (10/10) */
enum {
    RUN = 0,
    STEPS = 1,
    S0 = 2,
    S1 = 3,
    S2 = 4,
    S3 = 5,
    T0 = 6,
    T1 = 7,
    T2 = 8,
    T3 = 9
};
signed char d[14] = {1, 12, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[T0] = d[S0];
        d[T1] = d[S1];
        d[T2] = d[S2];
        d[T3] = d[S3];
        d[S0] = d[T3];
        d[S1] = d[T0];
        d[S2] = d[T1];
        d[S3] = d[T2];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[S0], "S0\n");
        pop_print_if(d[S1], "S1\n");
        pop_print_if(d[S2], "S2\n");
        pop_print_if(d[S3], "S3\n");
    }
    return 0;
}
