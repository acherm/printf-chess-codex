/* expected: POP-pure (10/10) */
enum { RUN = 0, STEPS = 1, PHASE = 2 };
signed char d[8] = {1, 10, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[PHASE] = 1 - d[PHASE];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[PHASE], "ON\n");
        pop_print_if(1 - d[PHASE], "OFF\n");
    }
    return 0;
}
