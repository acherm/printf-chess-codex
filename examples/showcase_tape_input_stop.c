/*
 * Tape-input demo for CPOP subset:
 * - pop_read_byte(KEY) loads one raw byte per tick into tape
 * - RUN mirrors KEY, so a '\0' byte stops the loop
 * - shows Gate E style tape-in before printf VM step
 */
enum { RUN = 0, KEY = 1, COUNT = 2 };

signed char d[8] = {1, 0, 0, 0, 0, 0, 0, 0};

int main(void) {
    while (d[RUN]) {
        pop_read_byte(KEY);
        d[COUNT] = d[COUNT] + 1;
        d[RUN] = d[KEY];
        pop_print_if(d[KEY], "tick\n");
    }
    return 0;
}
