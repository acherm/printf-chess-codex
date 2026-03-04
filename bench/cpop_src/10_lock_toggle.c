/* expected: POP-pure (10/10) */
enum { RUN = 0, STEPS = 1, LOCKED = 2, UNLOCKED = 3, T = 4 };
signed char d[10] = {1, 8, 1, 0, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[T] = d[LOCKED];
        d[LOCKED] = d[UNLOCKED];
        d[UNLOCKED] = d[T];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[LOCKED], "LOCKED\n");
        pop_print_if(d[UNLOCKED], "UNLOCKED\n");
    }
    return 0;
}
