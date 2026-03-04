/* expected: POP-pure (10/10) */
enum {
    RUN = 0,
    STEPS = 1,
    RED = 2,
    GREEN = 3,
    YELLOW = 4,
    TRED = 5,
    TGREEN = 6,
    TYELLOW = 7
};
signed char d[12] = {1, 9, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[TRED] = d[RED];
        d[TGREEN] = d[GREEN];
        d[TYELLOW] = d[YELLOW];
        d[RED] = d[TYELLOW];
        d[GREEN] = d[TRED];
        d[YELLOW] = d[TGREEN];
        d[STEPS] = d[STEPS] - 1;
        d[RUN] = d[STEPS];
        pop_print_if(d[RED], "RED\n");
        pop_print_if(d[GREEN], "GREEN\n");
        pop_print_if(d[YELLOW], "YELLOW\n");
    }
    return 0;
}
