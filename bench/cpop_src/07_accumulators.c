/* expected: POP-pure (10/10) */
enum { RUN = 0, STEPS = 1, A = 2, B = 3 };
signed char d[10] = {1, 8, 1, 2, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[A] = d[A] + 3;
        d[B] = d[B] + d[A];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[A], "A\n");
        pop_print_if(d[B], "B\n");
    }
    return 0;
}
