/* expected: POP-pure (10/10) */
enum { RUN = 0, CNT = 1 };
signed char d[8] = {1, 8, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        d[CNT] = d[CNT] - 1;
        d[RUN] = d[CNT];
        pop_print_if(d[RUN], "tick\n");
    }
    return 0;
}
