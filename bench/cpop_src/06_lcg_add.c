/* expected: POP-pure (9/10; weak branch semantics) */
enum { RUN = 0, STEPS = 1, X = 2 };
signed char d[8] = {1, 10, 7, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[X] = d[X] + 17;
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[X], "x!=0\n");
    }
    return 0;
}
