/* expected: POP-pure (9/10; weak branch semantics) */
enum { RUN = 0, STEPS = 1, LEVEL = 2, REFILL = 3, LEAK = 4 };
signed char d[10] = {1, 8, 3, 2, -1, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[LEVEL] = d[LEVEL] + d[REFILL] + d[LEAK];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[LEVEL], "LEVEL\n");
    }
    return 0;
}
