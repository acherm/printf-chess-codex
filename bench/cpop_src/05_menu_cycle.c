/* expected: POP-pure (10/10) */
enum {
    RUN = 0,
    STEPS = 1,
    C0 = 2,
    C1 = 3,
    C2 = 4,
    T0 = 5,
    T1 = 6,
    T2 = 7
};
signed char d[12] = {1, 9, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[T0] = d[C0];
        d[T1] = d[C1];
        d[T2] = d[C2];
        d[C0] = d[T2];
        d[C1] = d[T0];
        d[C2] = d[T1];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[C0], "[x] Play\n");
        pop_print_if(d[C1], "[x] Settings\n");
        pop_print_if(d[C2], "[x] Quit\n");
    }
    return 0;
}
