#include "ccel.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

static int grid_is_valid(const CcelGrid *g) {\n    return g && g->height > 0 && g->width > 0 &&\n           g->height <= CCEL_MAX_SIDE && g->width <= CCEL_MAX_SIDE &&\n           g->height <= CCEL_MAX_CELLS / g->width;\n}\n\nstatic const CcelOperation all_operations[5] = {
    CCEL_ROTATE_CLOCKWISE, CCEL_ROTATE_COUNTERCLOCKWISE,
    CCEL_FLIP_HORIZONTAL, CCEL_FLIP_VERTICAL, CCEL_TRANSPOSE
};

const char *ccel_error_string(CcelError e) {
    static const char *const messages[] = {
        "success", "grid must contain at least one row", "grid rows must not be empty",
        "grid must be rectangular", "grid side exceeds 30", "grid exceeds 900 cells",
        "cell value is outside 0..=9", "program exceeds depth 5",
        "max_depth must be in 0..=5", "candidate budget must be in 1..=10000",
        "provide at least one example", "example count exceeds 100",
        "provide at least one program", "provide at least one candidate probe",
        "no program in the bounded DSL explains all examples",
        "consistent models exceed the candidate budget", "invalid operation", "memory allocation failed"
    };
    const size_t n = sizeof messages / sizeof messages[0];
    return (unsigned)e < n ? messages[e] : "unknown CCEL error";
}

CcelError ccel_grid_init(CcelGrid *out, size_t h, size_t w,
                         const uint8_t *cells, size_t count) {
    if (!out) return CCEL_ERR_ALLOCATION;
    if (h == 0) return CCEL_ERR_EMPTY_GRID;
    if (w == 0) return CCEL_ERR_EMPTY_ROW;
    if (h > CCEL_MAX_SIDE || w > CCEL_MAX_SIDE) return CCEL_ERR_SIDE_TOO_LARGE;
    if (h > SIZE_MAX / w || h * w > CCEL_MAX_CELLS) return CCEL_ERR_TOO_MANY_CELLS;
    if (!cells || count != h * w) return CCEL_ERR_NON_RECTANGULAR;
    for (size_t i = 0; i < count; ++i)
        if (cells[i] > 9) return CCEL_ERR_CELL_OUT_OF_RANGE;
    out->height = h;
    out->width = w;
    memcpy(out->cells, cells, count);
    return CCEL_OK;
}

int ccel_grid_equal(const CcelGrid *a, const CcelGrid *b) {
    return a && b && a->height == b->height && a->width == b->width &&
           memcmp(a->cells, b->cells, a->height * a->width) == 0;
}

int ccel_grid_compare(const CcelGrid *a, const CcelGrid *b) {
    if (!grid_is_valid(a) || !grid_is_valid(b)) return 0;\n    if (a->height != b->height) return a->height < b->height ? -1 : 1;
    if (a->width != b->width) return a->width < b->width ? -1 : 1;
    int c = memcmp(a->cells, b->cells, a->height * a->width);
    return (c > 0) - (c < 0);
}

CcelError ccel_operation_apply(CcelOperation op, const CcelGrid *in, CcelGrid *out) {
    if (!in || !out || in->height == 0 || in->width == 0 ||
        in->height > CCEL_MAX_SIDE || in->width > CCEL_MAX_SIDE)
        return CCEL_ERR_EMPTY_GRID;
    const size_t h = in->height, w = in->width;
    const int swaps = op == CCEL_ROTATE_CLOCKWISE ||
        op == CCEL_ROTATE_COUNTERCLOCKWISE || op == CCEL_TRANSPOSE;
    if ((unsigned)op >= 5u) return CCEL_ERR_INVALID_OPERATION;
    out->height = swaps ? w : h;
    out->width = swaps ? h : w;
    memset(out->cells, 0, sizeof out->cells);
    for (size_t r = 0; r < h; ++r) {
        for (size_t c = 0; c < w; ++c) {
            size_t rr = r, cc = c;
            switch (op) {
            case CCEL_ROTATE_CLOCKWISE: rr = c; cc = h - 1u - r; break;
            case CCEL_ROTATE_COUNTERCLOCKWISE: rr = w - 1u - c; cc = r; break;
            case CCEL_FLIP_HORIZONTAL: cc = w - 1u - c; break;
            case CCEL_FLIP_VERTICAL: rr = h - 1u - r; break;
            case CCEL_TRANSPOSE: rr = c; cc = r; break;
            }
            out->cells[rr * out->width + cc] = in->cells[r * w + c];
        }
    }
    return CCEL_OK;
}

CcelError ccel_program_init(CcelProgram *out, const CcelOperation *ops, size_t n) {
    if (!out) return CCEL_ERR_ALLOCATION;
    if (n > CCEL_MAX_PROGRAM_DEPTH) return CCEL_ERR_PROGRAM_TOO_DEEP;
    if (n && !ops) return CCEL_ERR_ALLOCATION;
    out->length = n;
    for (size_t i = 0; i < n; ++i) {
        if ((unsigned)ops[i] >= 5u) return CCEL_ERR_INVALID_OPERATION;
        out->operations[i] = ops[i];
    }
    return CCEL_OK;
}

CcelError ccel_program_apply(const CcelProgram *p, const CcelGrid *in, CcelGrid *out) {
    if (!p || !in || !out || p->length > CCEL_MAX_PROGRAM_DEPTH)
        return CCEL_ERR_PROGRAM_TOO_DEEP;
    CcelGrid current = *in, next;
    for (size_t i = 0; i < p->length; ++i) {
        CcelError e = ccel_operation_apply(p->operations[i], &current, &next);
        if (e != CCEL_OK) return e;
        current = next;
    }
    *out = current;
    return CCEL_OK;
}

typedef struct {
    const CcelExample *examples;
    size_t example_count, target_depth, budget, count;
    CcelProgram sequence;
    CcelProgram *matches;
    CcelError error;
} Search;

static void enumerate(Search *s, size_t at) {
    if (s->error != CCEL_OK) return;
    if (at == s->target_depth) {
        for (size_t i = 0; i < s->example_count; ++i) {
            CcelGrid result;
            CcelError e = ccel_program_apply(&s->sequence, &s->examples[i].source, &result);
            if (e != CCEL_OK) { s->error = e; return; }
            if (!ccel_grid_equal(&result, &s->examples[i].target)) return;
        }
        if (s->count == s->budget) { s->error = CCEL_ERR_SEARCH_LIMIT_EXCEEDED; return; }
        s->matches[s->count++] = s->sequence;
        return;
    }
    for (size_t i = 0; i < 5; ++i) {
        s->sequence.operations[at] = all_operations[i];
        enumerate(s, at + 1);
        if (s->error != CCEL_OK) return;
    }
}

CcelError ccel_synthesize(const CcelExample *examples, size_t n, size_t max_depth,
                          size_t budget, CcelSynthesisResult *out) {
    if (!out) return CCEL_ERR_ALLOCATION;
    memset(out, 0, sizeof *out);
    if (max_depth > CCEL_MAX_PROGRAM_DEPTH) return CCEL_ERR_INVALID_DEPTH;
    if (budget == 0 || budget > CCEL_MAX_CANDIDATES) return CCEL_ERR_INVALID_CANDIDATE_BUDGET;
    if (n == 0 || !examples) return CCEL_ERR_NO_EXAMPLES;
    if (n > CCEL_MAX_EXAMPLES) return CCEL_ERR_TOO_MANY_EXAMPLES;
    for (size_t depth = 0; depth <= max_depth; ++depth) {
        CcelProgram *matches = calloc(budget, sizeof *matches);
        if (!matches) return CCEL_ERR_ALLOCATION;
        Search s = { .examples = examples, .example_count = n, .target_depth = depth,
                     .budget = budget, .matches = matches, .error = CCEL_OK };
        s.sequence.length = depth;
        enumerate(&s, 0);
        if (s.error != CCEL_OK) { free(matches); return s.error; }
        if (s.count) {
            out->programs = matches; out->count = s.count;
            out->depth = depth; out->examples_seen = n;
            return CCEL_OK;
        }
        free(matches);
    }
    return CCEL_ERR_NO_CONSISTENT_MODEL;
}

void ccel_synthesis_result_free(CcelSynthesisResult *r) {
    if (r) { free(r->programs); memset(r, 0, sizeof *r); }
}

static int prediction_compare(const void *pa, const void *pb) {
    const CcelPrediction *a = pa, *b = pb;
    return ccel_grid_compare(&a->grid, &b->grid);
}

CcelError ccel_predict(const CcelProgram *programs, size_t n, const CcelGrid *input,
                       CcelPredictionSet *out) {
    if (!out) return CCEL_ERR_ALLOCATION;
    memset(out, 0, sizeof *out);
    if (!programs || n == 0) return CCEL_ERR_NO_PROGRAMS;
    CcelPrediction *items = calloc(n, sizeof *items);
    if (!items) return CCEL_ERR_ALLOCATION;
    for (size_t i = 0; i < n; ++i) {
        CcelError e = ccel_program_apply(&programs[i], input, &items[i].grid);
        if (e != CCEL_OK) { free(items); return e; }
        items[i].count = 1;
    }
    qsort(items, n, sizeof *items, prediction_compare);
    size_t unique = 0;
    for (size_t i = 0; i < n; ++i) {
        if (unique && ccel_grid_equal(&items[unique - 1].grid, &items[i].grid))
            ++items[unique - 1].count;
        else items[unique++] = items[i];
    }
    out->items = items; out->count = unique;
    return CCEL_OK;
}

void ccel_prediction_set_free(CcelPredictionSet *s) {
    if (s) { free(s->items); memset(s, 0, sizeof *s); }
}

CcelError ccel_select_probe(const CcelProgram *programs, size_t pn,
                            const CcelGrid *probes, size_t gn, CcelProbeChoice *out) {
    if (!out) return CCEL_ERR_ALLOCATION;
    memset(out, 0, sizeof *out);
    if (!programs || pn == 0) return CCEL_ERR_NO_PROGRAMS;
    if (!probes || gn == 0) return CCEL_ERR_NO_PROBES;
    int have_best = 0;
    for (size_t i = 0; i < gn; ++i) {
        CcelPredictionSet set;
        CcelError e = ccel_predict(programs, pn, &probes[i], &set);
        if (e != CCEL_OK) return e;
        double entropy = 0.0;
        for (size_t j = 0; j < set.count; ++j) {
            double p = (double)set.items[j].count / (double)pn;
            entropy -= p * log2(p);
        }
        int better = !have_best || entropy > out->entropy_bits ||
            (entropy == out->entropy_bits && set.count > out->distinct_outcomes) ||
            (entropy == out->entropy_bits && set.count == out->distinct_outcomes &&
             ccel_grid_compare(&probes[i], &out->grid) < 0);
        if (better) {
            free(out->predictions);
            out->grid = probes[i]; out->entropy_bits = entropy;
            out->distinct_outcomes = set.count;
            out->predictions = set.items; out->prediction_count = set.count;
            set.items = NULL; have_best = 1;
        }
        ccel_prediction_set_free(&set);
    }
    return have_best ? CCEL_OK : CCEL_ERR_NO_PROBES;
}

void ccel_probe_choice_free(CcelProbeChoice *c) {
    if (c) { free(c->predictions); memset(c, 0, sizeof *c); }
}
