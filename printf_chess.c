#include <ctype.h>
#include <stdio.h>
#include <string.h>

#define WHITE 0
#define BLACK 1
#define MAX_MOVES 256
#define SEARCH_DEPTH 3
#define INF 100000000
#define MATE_SCORE 30000
#define IDX(r, f) ((r) * 8 + (f))
#define FILE_OF(sq) ((sq) & 7)
#define RANK_OF(sq) ((sq) >> 3)

typedef struct {
    int from;
    int to;
    char promo;
} Move;

typedef struct {
    Move moves[MAX_MOVES];
    int count;
} MoveList;

typedef struct {
    char moved;
    char captured;
} Undo;

typedef struct {
    char board[64];
    char input[16];
    char status[256];
    char prompt[64];
    char screen[2048];
    int ply;
} Game;

enum {
    TERM_NONE = 0,
    TERM_WHITE_WIN = 1,
    TERM_BLACK_WIN = 2,
    TERM_DRAW = 3,
};

static Game g;

/*
 * POP state bytes (mutated by %hhn in fmt):
 * d[0]: keep running (0/1)
 * d[1]: side to move (0 white / 1 black)
 * d[2]: boot frame (1 once, then 0)
 * d[16], d[17]: scratch pair for ZERO macro
 */
static char d[64] = {1, WHITE, 1, 0};

static const char *tok_run = "x";
static const char *tok_side = "";
static const char *tok_boot = "x";
static const char *tok_lut[] = {"", "x", "xx", "xxx"};

static const char *VIEW_FMT =
    "\033[2J\033[H"
    "printf-chess (printf-oriented)\n\n"
    "    a b c d e f g h\n"
    "  +-----------------+\n"
    "8 | %c %c %c %c %c %c %c %c | 8\n"
    "7 | %c %c %c %c %c %c %c %c | 7\n"
    "6 | %c %c %c %c %c %c %c %c | 6\n"
    "5 | %c %c %c %c %c %c %c %c | 5\n"
    "4 | %c %c %c %c %c %c %c %c | 4\n"
    "3 | %c %c %c %c %c %c %c %c | 3\n"
    "2 | %c %c %c %c %c %c %c %c | 2\n"
    "1 | %c %c %c %c %c %c %c %c | 1\n"
    "  +-----------------+\n"
    "    a b c d e f g h\n\n"
    "%s\n"
    "%s";

static int on_board(int r, int f) {
    return r >= 0 && r < 8 && f >= 0 && f < 8;
}

static int color_of(char piece) {
    if (piece >= 'A' && piece <= 'Z') {
        return WHITE;
    }
    if (piece >= 'a' && piece <= 'z') {
        return BLACK;
    }
    return -1;
}

static int piece_value(char piece) {
    switch ((int)tolower((unsigned char)piece)) {
        case 'p':
            return 100;
        case 'n':
            return 320;
        case 'b':
            return 330;
        case 'r':
            return 500;
        case 'q':
            return 900;
        case 'k':
            return 0;
        default:
            return 0;
    }
}

static int eval_material(const Game *game) {
    int score = 0;
    int i;

    for (i = 0; i < 64; i++) {
        char p = game->board[i];
        if (p == '.') {
            continue;
        }
        if (color_of(p) == BLACK) {
            score += piece_value(p);
        } else {
            score -= piece_value(p);
        }
    }
    return score;
}

static int eval_for_side(const Game *game, int side) {
    int black = eval_material(game);
    return side == BLACK ? black : -black;
}

static int is_square_attacked(const Game *game, int sq, int by_side) {
    static const int knight_offsets[8][2] = {
        {-2, -1}, {-2, 1}, {-1, -2}, {-1, 2},
        {1, -2},  {1, 2},  {2, -1},  {2, 1},
    };
    static const int king_offsets[8][2] = {
        {-1, -1}, {-1, 0}, {-1, 1}, {0, -1},
        {0, 1},   {1, -1}, {1, 0},  {1, 1},
    };
    static const int bishop_dirs[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1},
    };
    static const int rook_dirs[4][2] = {
        {-1, 0}, {1, 0}, {0, -1}, {0, 1},
    };
    int r = RANK_OF(sq);
    int f = FILE_OF(sq);
    int i;

    if (by_side == WHITE) {
        int pr = r + 1;
        if (on_board(pr, f - 1) && game->board[IDX(pr, f - 1)] == 'P') {
            return 1;
        }
        if (on_board(pr, f + 1) && game->board[IDX(pr, f + 1)] == 'P') {
            return 1;
        }
    } else {
        int pr = r - 1;
        if (on_board(pr, f - 1) && game->board[IDX(pr, f - 1)] == 'p') {
            return 1;
        }
        if (on_board(pr, f + 1) && game->board[IDX(pr, f + 1)] == 'p') {
            return 1;
        }
    }

    for (i = 0; i < 8; i++) {
        int rr = r + knight_offsets[i][0];
        int ff = f + knight_offsets[i][1];
        if (on_board(rr, ff)) {
            char p = game->board[IDX(rr, ff)];
            if (by_side == WHITE && p == 'N') {
                return 1;
            }
            if (by_side == BLACK && p == 'n') {
                return 1;
            }
        }
    }

    for (i = 0; i < 4; i++) {
        int dr = bishop_dirs[i][0];
        int df = bishop_dirs[i][1];
        int rr = r + dr;
        int ff = f + df;
        while (on_board(rr, ff)) {
            char p = game->board[IDX(rr, ff)];
            if (p != '.') {
                if (by_side == WHITE && (p == 'B' || p == 'Q')) {
                    return 1;
                }
                if (by_side == BLACK && (p == 'b' || p == 'q')) {
                    return 1;
                }
                break;
            }
            rr += dr;
            ff += df;
        }
    }

    for (i = 0; i < 4; i++) {
        int dr = rook_dirs[i][0];
        int df = rook_dirs[i][1];
        int rr = r + dr;
        int ff = f + df;
        while (on_board(rr, ff)) {
            char p = game->board[IDX(rr, ff)];
            if (p != '.') {
                if (by_side == WHITE && (p == 'R' || p == 'Q')) {
                    return 1;
                }
                if (by_side == BLACK && (p == 'r' || p == 'q')) {
                    return 1;
                }
                break;
            }
            rr += dr;
            ff += df;
        }
    }

    for (i = 0; i < 8; i++) {
        int rr = r + king_offsets[i][0];
        int ff = f + king_offsets[i][1];
        if (on_board(rr, ff)) {
            char p = game->board[IDX(rr, ff)];
            if (by_side == WHITE && p == 'K') {
                return 1;
            }
            if (by_side == BLACK && p == 'k') {
                return 1;
            }
        }
    }

    return 0;
}

static int find_king(const Game *game, int side) {
    int i;
    char target = side == WHITE ? 'K' : 'k';
    for (i = 0; i < 64; i++) {
        if (game->board[i] == target) {
            return i;
        }
    }
    return -1;
}

static int in_check(const Game *game, int side) {
    int king_sq = find_king(game, side);
    if (king_sq < 0) {
        return 1;
    }
    return is_square_attacked(game, king_sq, side ^ 1);
}

static void make_move(Game *game, Move m, Undo *u) {
    char piece = game->board[m.from];
    u->moved = piece;
    u->captured = game->board[m.to];
    game->board[m.from] = '.';
    if (m.promo) {
        piece = color_of(piece) == WHITE ? (char)toupper((unsigned char)m.promo)
                                         : (char)tolower((unsigned char)m.promo);
    }
    game->board[m.to] = piece;
}

static void unmake_move(Game *game, Move m, Undo u) {
    game->board[m.from] = u.moved;
    game->board[m.to] = u.captured;
}

static void push_move(MoveList *ml, int from, int to, char promo) {
    if (ml->count >= MAX_MOVES) {
        return;
    }
    ml->moves[ml->count].from = from;
    ml->moves[ml->count].to = to;
    ml->moves[ml->count].promo = promo;
    ml->count++;
}

static void try_push_legal(Game *game, MoveList *ml, int side, int from, int to,
                           char promo) {
    Move m;
    Undo u;
    m.from = from;
    m.to = to;
    m.promo = promo;
    make_move(game, m, &u);
    if (!in_check(game, side)) {
        push_move(ml, from, to, promo);
    }
    unmake_move(game, m, u);
}

static void gen_piece_moves(Game *game, MoveList *ml, int side, int sq) {
    static const int knight_offsets[8][2] = {
        {-2, -1}, {-2, 1}, {-1, -2}, {-1, 2},
        {1, -2},  {1, 2},  {2, -1},  {2, 1},
    };
    static const int king_offsets[8][2] = {
        {-1, -1}, {-1, 0}, {-1, 1}, {0, -1},
        {0, 1},   {1, -1}, {1, 0},  {1, 1},
    };
    static const int bishop_dirs[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1},
    };
    static const int rook_dirs[4][2] = {
        {-1, 0}, {1, 0}, {0, -1}, {0, 1},
    };
    char piece = game->board[sq];
    int r = RANK_OF(sq);
    int f = FILE_OF(sq);
    int i;

    switch ((int)tolower((unsigned char)piece)) {
        case 'p': {
            int dir = side == WHITE ? -1 : 1;
            int start_row = side == WHITE ? 6 : 1;
            int promo_row = side == WHITE ? 0 : 7;
            int rr = r + dir;

            if (on_board(rr, f) && game->board[IDX(rr, f)] == '.') {
                if (rr == promo_row) {
                    try_push_legal(game, ml, side, sq, IDX(rr, f), 'q');
                } else {
                    try_push_legal(game, ml, side, sq, IDX(rr, f), 0);
                    if (r == start_row && game->board[IDX(rr + dir, f)] == '.') {
                        try_push_legal(game, ml, side, sq, IDX(rr + dir, f), 0);
                    }
                }
            }

            if (on_board(rr, f - 1) &&
                color_of(game->board[IDX(rr, f - 1)]) == (side ^ 1)) {
                try_push_legal(game, ml, side, sq, IDX(rr, f - 1),
                               rr == promo_row ? 'q' : 0);
            }
            if (on_board(rr, f + 1) &&
                color_of(game->board[IDX(rr, f + 1)]) == (side ^ 1)) {
                try_push_legal(game, ml, side, sq, IDX(rr, f + 1),
                               rr == promo_row ? 'q' : 0);
            }
            break;
        }

        case 'n':
            for (i = 0; i < 8; i++) {
                int rr = r + knight_offsets[i][0];
                int ff = f + knight_offsets[i][1];
                if (on_board(rr, ff) &&
                    color_of(game->board[IDX(rr, ff)]) != side) {
                    try_push_legal(game, ml, side, sq, IDX(rr, ff), 0);
                }
            }
            break;

        case 'b':
            for (i = 0; i < 4; i++) {
                int dr = bishop_dirs[i][0];
                int df = bishop_dirs[i][1];
                int rr = r + dr;
                int ff = f + df;
                while (on_board(rr, ff)) {
                    int to = IDX(rr, ff);
                    if (color_of(game->board[to]) == side) {
                        break;
                    }
                    try_push_legal(game, ml, side, sq, to, 0);
                    if (game->board[to] != '.') {
                        break;
                    }
                    rr += dr;
                    ff += df;
                }
            }
            break;

        case 'r':
            for (i = 0; i < 4; i++) {
                int dr = rook_dirs[i][0];
                int df = rook_dirs[i][1];
                int rr = r + dr;
                int ff = f + df;
                while (on_board(rr, ff)) {
                    int to = IDX(rr, ff);
                    if (color_of(game->board[to]) == side) {
                        break;
                    }
                    try_push_legal(game, ml, side, sq, to, 0);
                    if (game->board[to] != '.') {
                        break;
                    }
                    rr += dr;
                    ff += df;
                }
            }
            break;

        case 'q':
            for (i = 0; i < 4; i++) {
                int dr = bishop_dirs[i][0];
                int df = bishop_dirs[i][1];
                int rr = r + dr;
                int ff = f + df;
                while (on_board(rr, ff)) {
                    int to = IDX(rr, ff);
                    if (color_of(game->board[to]) == side) {
                        break;
                    }
                    try_push_legal(game, ml, side, sq, to, 0);
                    if (game->board[to] != '.') {
                        break;
                    }
                    rr += dr;
                    ff += df;
                }
            }
            for (i = 0; i < 4; i++) {
                int dr = rook_dirs[i][0];
                int df = rook_dirs[i][1];
                int rr = r + dr;
                int ff = f + df;
                while (on_board(rr, ff)) {
                    int to = IDX(rr, ff);
                    if (color_of(game->board[to]) == side) {
                        break;
                    }
                    try_push_legal(game, ml, side, sq, to, 0);
                    if (game->board[to] != '.') {
                        break;
                    }
                    rr += dr;
                    ff += df;
                }
            }
            break;

        case 'k':
            for (i = 0; i < 8; i++) {
                int rr = r + king_offsets[i][0];
                int ff = f + king_offsets[i][1];
                if (on_board(rr, ff) &&
                    color_of(game->board[IDX(rr, ff)]) != side) {
                    try_push_legal(game, ml, side, sq, IDX(rr, ff), 0);
                }
            }
            break;

        default:
            break;
    }
}

static void generate_legal_moves(Game *game, int side, MoveList *ml) {
    int i;
    ml->count = 0;
    for (i = 0; i < 64; i++) {
        if (color_of(game->board[i]) == side) {
            gen_piece_moves(game, ml, side, i);
        }
    }
}

static int negamax(Game *game, int side, int depth, int alpha, int beta,
                   int ply) {
    MoveList ml;
    int i;
    int best = -INF;

    generate_legal_moves(game, side, &ml);
    if (depth == 0) {
        return eval_for_side(game, side);
    }
    if (ml.count == 0) {
        if (in_check(game, side)) {
            return -MATE_SCORE + ply;
        }
        return 0;
    }

    for (i = 0; i < ml.count; i++) {
        Undo u;
        int score;

        make_move(game, ml.moves[i], &u);
        score = -negamax(game, side ^ 1, depth - 1, -beta, -alpha, ply + 1);
        unmake_move(game, ml.moves[i], u);

        if (score > best) {
            best = score;
        }
        if (score > alpha) {
            alpha = score;
        }
        if (alpha >= beta) {
            break;
        }
    }

    return best;
}

static Move choose_engine_move(Game *game, int side) {
    MoveList ml;
    Move best_move;
    int best_score = -INF;
    int i;

    best_move.from = -1;
    best_move.to = -1;
    best_move.promo = 0;

    generate_legal_moves(game, side, &ml);
    if (ml.count == 0) {
        return best_move;
    }

    best_move = ml.moves[0];
    for (i = 0; i < ml.count; i++) {
        Undo u;
        int score;
        make_move(game, ml.moves[i], &u);
        score = -negamax(game, side ^ 1, SEARCH_DEPTH - 1, -INF, INF, 1);
        unmake_move(game, ml.moves[i], u);
        if (score > best_score) {
            best_score = score;
            best_move = ml.moves[i];
        }
    }

    return best_move;
}

static int parse_square(const char *s) {
    int file = tolower((unsigned char)s[0]) - 'a';
    int rank = s[1] - '1';
    if (file < 0 || file > 7 || rank < 0 || rank > 7) {
        return -1;
    }
    return IDX(7 - rank, file);
}

static void move_to_text(Move m, char out[8]) {
    int ff = FILE_OF(m.from);
    int rf = 7 - RANK_OF(m.from);
    int ft = FILE_OF(m.to);
    int rt = 7 - RANK_OF(m.to);
    out[0] = (char)('a' + ff);
    out[1] = (char)('1' + rf);
    out[2] = (char)('a' + ft);
    out[3] = (char)('1' + rt);
    if (m.promo) {
        out[4] = m.promo;
        out[5] = '\0';
    } else {
        out[4] = '\0';
    }
}

static int parse_user_move(Game *game, int side, const char *text, Move *out) {
    MoveList legal;
    int from;
    int to;
    char promo = 0;
    size_t len = strlen(text);
    int i;

    if (len < 4) {
        return 0;
    }
    from = parse_square(text);
    to = parse_square(text + 2);
    if (from < 0 || to < 0) {
        return 0;
    }
    if (len >= 5) {
        promo = (char)tolower((unsigned char)text[4]);
    }

    generate_legal_moves(game, side, &legal);
    for (i = 0; i < legal.count; i++) {
        Move m = legal.moves[i];
        if (m.from == from && m.to == to) {
            if (!m.promo && !promo) {
                *out = m;
                return 1;
            }
            if (m.promo && (!promo || promo == m.promo)) {
                *out = m;
                return 1;
            }
        }
    }
    return 0;
}

static int terminal_state(Game *game, int side_to_move) {
    MoveList ml;

    generate_legal_moves(game, side_to_move, &ml);
    if (ml.count > 0) {
        return TERM_NONE;
    }
    if (in_check(game, side_to_move)) {
        return side_to_move == WHITE ? TERM_BLACK_WIN : TERM_WHITE_WIN;
    }
    return TERM_DRAW;
}

static void set_terminal_message(Game *game, int term) {
    switch (term) {
        case TERM_WHITE_WIN:
            snprintf(game->status, sizeof(game->status), "Checkmate. White wins.");
            break;
        case TERM_BLACK_WIN:
            snprintf(game->status, sizeof(game->status), "Checkmate. Black wins.");
            break;
        case TERM_DRAW:
            snprintf(game->status, sizeof(game->status), "Stalemate. Draw.");
            break;
        default:
            snprintf(game->status, sizeof(game->status), "Game over.");
            break;
    }
}

static void render(Game *game, int run, int side) {
    const char *prompt = "";

    if (!run) {
        prompt = "Game over.";
    } else if (side == WHITE) {
        prompt = "Your move (e2e4, e7e8q, resign, quit):";
    } else {
        prompt = "Engine is thinking...";
    }

    snprintf(game->prompt, sizeof(game->prompt), "%s", prompt);
    snprintf(
        game->screen, sizeof(game->screen), VIEW_FMT, game->board[0],
        game->board[1], game->board[2], game->board[3], game->board[4],
        game->board[5], game->board[6], game->board[7], game->board[8],
        game->board[9], game->board[10], game->board[11], game->board[12],
        game->board[13], game->board[14], game->board[15], game->board[16],
        game->board[17], game->board[18], game->board[19], game->board[20],
        game->board[21], game->board[22], game->board[23], game->board[24],
        game->board[25], game->board[26], game->board[27], game->board[28],
        game->board[29], game->board[30], game->board[31], game->board[32],
        game->board[33], game->board[34], game->board[35], game->board[36],
        game->board[37], game->board[38], game->board[39], game->board[40],
        game->board[41], game->board[42], game->board[43], game->board[44],
        game->board[45], game->board[46], game->board[47], game->board[48],
        game->board[49], game->board[50], game->board[51], game->board[52],
        game->board[53], game->board[54], game->board[55], game->board[56],
        game->board[57], game->board[58], game->board[59], game->board[60],
        game->board[61], game->board[62], game->board[63], game->status,
        game->prompt);
}

static void pop_cycle(void) {
    int side = d[1] ? BLACK : WHITE;
    int boot = d[2] ? 1 : 0;
    int next_run = 1;
    int next_side = side;
    int next_boot = 0;

    if (boot) {
        snprintf(g.status, sizeof(g.status),
                 "White to move. You are White; engine is Black.");
    } else if (side == WHITE) {
        Move m;
        Undo u;
        int term;

        if (scanf("%15s", g.input) != 1) {
            next_run = 0;
            snprintf(g.status, sizeof(g.status),
                     "Input ended. Session terminated.");
        } else if (!strcmp(g.input, "quit") || !strcmp(g.input, "resign")) {
            next_run = 0;
            snprintf(g.status, sizeof(g.status), "White resigns. Black wins.");
        } else if (!parse_user_move(&g, WHITE, g.input, &m)) {
            next_run = 0;
            snprintf(g.status, sizeof(g.status),
                     "Illegal move \"%s\". Black wins by forfeit.", g.input);
        } else {
            char move_txt[8];
            make_move(&g, m, &u);
            g.ply++;
            next_side = BLACK;
            term = terminal_state(&g, next_side);
            if (term != TERM_NONE) {
                next_run = 0;
                set_terminal_message(&g, term);
            } else {
                move_to_text(m, move_txt);
                snprintf(g.status, sizeof(g.status),
                         "You played %s. Engine to move.", move_txt);
            }
        }
    } else {
        Move m = choose_engine_move(&g, BLACK);
        Undo u;
        int term;
        char move_txt[8];

        if (m.from < 0) {
            next_run = 0;
            term = terminal_state(&g, BLACK);
            if (term == TERM_NONE) {
                term = TERM_DRAW;
            }
            set_terminal_message(&g, term);
        } else {
            make_move(&g, m, &u);
            g.ply++;
            next_side = WHITE;
            move_to_text(m, move_txt);
            term = terminal_state(&g, next_side);
            if (term != TERM_NONE) {
                next_run = 0;
                set_terminal_message(&g, term);
            } else {
                snprintf(g.status, sizeof(g.status),
                         "Engine played %s. Your turn.", move_txt);
            }
        }
    }

    render(&g, next_run, next_side);
    tok_run = tok_lut[next_run];
    tok_side = tok_lut[next_side];
    tok_boot = tok_lut[next_boot];
}

static void init_game(Game *game) {
    static const char start[64] = {
        'r', 'n', 'b', 'q', 'k', 'b', 'n', 'r', 'p', 'p', 'p', 'p', 'p',
        'p', 'p', 'p', '.', '.', '.', '.', '.', '.', '.', '.', '.', '.',
        '.', '.', '.', '.', '.', '.', '.', '.', '.', '.', '.', '.', '.',
        '.', '.', '.', '.', '.', '.', '.', '.', '.', 'P', 'P', 'P', 'P',
        'P', 'P', 'P', 'P', 'R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R',
    };
    int i;

    for (i = 0; i < 64; i++) {
        game->board[i] = start[i];
    }
    game->input[0] = '\0';
    game->status[0] = '\0';
    game->prompt[0] = '\0';
    game->screen[0] = '\0';
    game->ply = 0;
}

static unsigned pop_seen_mask = 0;

static void pop_arg_enter(unsigned bit) {
    if (pop_seen_mask == 0) {
        pop_cycle();
    }
    pop_seen_mask |= bit;
    if (pop_seen_mask == 0xFFu) {
        pop_seen_mask = 0;
    }
}

static char *pop_a1_zero(void) {
    pop_arg_enter(1u << 0);
    return d + 16;
}

static char *pop_a2_screen(void) {
    pop_arg_enter(1u << 1);
    return g.screen;
}

static const char *pop_a3_run_tok(void) {
    pop_arg_enter(1u << 2);
    return tok_run;
}

static char *pop_a4_run_ptr(void) {
    pop_arg_enter(1u << 3);
    return d + 0;
}

static const char *pop_a5_side_tok(void) {
    pop_arg_enter(1u << 4);
    return tok_side;
}

static char *pop_a6_side_ptr(void) {
    pop_arg_enter(1u << 5);
    return d + 1;
}

static const char *pop_a7_boot_tok(void) {
    pop_arg_enter(1u << 6);
    return tok_boot;
}

static char *pop_a8_boot_ptr(void) {
    pop_arg_enter(1u << 7);
    return d + 2;
}

static char *fmt =
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%3$s%4$hhn%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%5$s%6$hhn%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s%1$hhn%1$s"
    "%1$hhn%1$s%1$hhn%1$s%7$s%8$hhn%2$s"
    ;

int main(void) {
    init_game(&g);
    while (*d)
        printf(fmt, pop_a1_zero(), pop_a2_screen(), pop_a3_run_tok(),
               pop_a4_run_ptr(), pop_a5_side_tok(), pop_a6_side_ptr(),
               pop_a7_boot_tok(), pop_a8_boot_ptr());
    return 0;
}
