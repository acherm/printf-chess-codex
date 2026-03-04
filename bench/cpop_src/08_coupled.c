/* expected: POP-pure (10/10) */
enum { RUN = 0, STEPS = 1, X = 2, Y = 3 };
signed char d[10] = {1, 8, 1, 4, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[X] = d[X] + d[Y];
        d[Y] = d[Y] - 1;
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[X], "X\n");
        pop_print_if(d[Y], "Y\n");
    }
    return 0;
}
