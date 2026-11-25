#include "ccel.h"
#include <assert.h>
#include <stdio.h>

static CcelGrid grid(size_t h, size_t w, const uint8_t *v) {
    CcelGrid g;
    assert(ccel_grid_init(&g, h, w, v, h * w) == CCEL_OK);
    return g;
}

int main(void) {
    const uint8_t input[] = {1,2,3,4,5,6};
    const uint8_t clockwise[] = {4,1,5,2,6,3};
    const uint8_t counter[] = {3,6,2,5,1,4};
    const uint8_t transpose[] = {1,4,2,5,3,6};
    CcelGrid g = grid(2, 3, input), out;
    CcelGrid self_init = g;
    assert(ccel_grid_init(&self_init, 2, 3, self_init.cells, 6) == CCEL_OK);
    assert(ccel_grid_equal(&self_init, &g));
    assert(ccel_operation_apply(CCEL_ROTATE_CLOCKWISE, &g, &out) == CCEL_OK);
    assert(ccel_grid_equal(&out, &(CcelGrid){.height=3,.width=2,.cells={4,1,5,2,6,3}}));
    assert(ccel_operation_apply(CCEL_ROTATE_COUNTERCLOCKWISE, &g, &out) == CCEL_OK);
    assert(ccel_grid_equal(&out, &(CcelGrid){.height=3,.width=2,.cells={3,6,2,5,1,4}}));
    assert(ccel_operation_apply(CCEL_TRANSPOSE, &g, &out) == CCEL_OK);
    assert(ccel_grid_equal(&out, &(CcelGrid){.height=3,.width=2,.cells={1,4,2,5,3,6}}));
    CcelGrid in_place = g;
    assert(ccel_operation_apply(CCEL_FLIP_HORIZONTAL, &in_place, &in_place) == CCEL_OK);
    assert(ccel_grid_equal(&in_place, &(CcelGrid){.height=2,.width=3,.cells={3,2,1,6,5,4}}));
    (void)clockwise; (void)counter; (void)transpose;

    CcelExample ex = {g, out};
    CcelSynthesisResult result;
    assert(ccel_synthesize(&ex, 1, 1, 4096, &result) == CCEL_OK);
    assert(result.depth == 1 && result.count >= 1);
    CcelPredictionSet predictions;
    assert(ccel_predict(result.programs, result.count, &g, &predictions) == CCEL_OK);
    assert(predictions.count >= 1);
    CcelPredictionSet too_many_programs = {0};
    assert(ccel_predict(result.programs, CCEL_MAX_CANDIDATES + 1u, &g, &too_many_programs) == CCEL_ERR_TOO_MANY_PROGRAMS);
    assert(too_many_programs.items == NULL && too_many_programs.count == 0);
    CcelProbeChoice too_many_probes = {0};
    assert(ccel_select_probe(result.programs, result.count, &g, CCEL_MAX_PROBES + 1u, &too_many_probes) == CCEL_ERR_TOO_MANY_PROBES);
    assert(too_many_probes.predictions == NULL && too_many_probes.prediction_count == 0);
    ccel_prediction_set_free(&predictions);
    ccel_synthesis_result_free(&result);

    assert(ccel_grid_init(&out, 1, 1, (const uint8_t[]){10}, 1) == CCEL_ERR_CELL_OUT_OF_RANGE);
    CcelGrid malformed = g;
    malformed.cells[0] = 255u;
    assert(!ccel_grid_equal(&malformed, &g));
    assert(ccel_grid_compare(&malformed, &g) < 0);
    assert(ccel_grid_compare(&g, &malformed) > 0);
    CcelGrid malformed2 = malformed;
    malformed2.cells[1] = 0u;
    assert(ccel_grid_compare(&malformed, &malformed2) != 0);
    assert(ccel_grid_compare(NULL, &g) < 0);
    assert(ccel_grid_compare(&g, NULL) > 0);
    assert(ccel_operation_apply(CCEL_FLIP_HORIZONTAL, &malformed, &out) == CCEL_ERR_CELL_OUT_OF_RANGE);
    CcelProgram identity = {0};
    assert(ccel_program_apply(&identity, &malformed, &out) == CCEL_ERR_CELL_OUT_OF_RANGE);
    CcelPredictionSet invalid_predictions = {0};
    assert(ccel_predict(&identity, 1, &malformed, &invalid_predictions) == CCEL_ERR_CELL_OUT_OF_RANGE);
    assert(invalid_predictions.items == NULL && invalid_predictions.count == 0);
    CcelExample invalid_example = {malformed, g};
    assert(ccel_synthesize(&invalid_example, 1, 1, 10, &result) == CCEL_ERR_CELL_OUT_OF_RANGE);
    CcelGrid probes[] = {g, malformed};
    CcelProbeChoice failed_probe = {0};
    assert(ccel_select_probe(&identity, 1, probes, 2, &failed_probe) == CCEL_ERR_CELL_OUT_OF_RANGE);
    assert(failed_probe.predictions == NULL && failed_probe.prediction_count == 0);
    assert(failed_probe.distinct_outcomes == 0 && failed_probe.grid.height == 0);
    malformed = (CcelGrid){.height=SIZE_MAX, .width=2};
    assert(!ccel_grid_equal(&malformed, &g));
    assert(ccel_synthesize(NULL, 0, 1, 10, &result) == CCEL_ERR_NO_EXAMPLES);
    assert(ccel_program_init(&(CcelProgram){0}, NULL, 6) == CCEL_ERR_PROGRAM_TOO_DEEP);
    CcelProgram unchanged = {0};
    const CcelOperation invalid_ops[] = {CCEL_ROTATE_CLOCKWISE, (CcelOperation)99};
    assert(ccel_program_init(&unchanged, invalid_ops, 2) == CCEL_ERR_INVALID_OPERATION);
    assert(unchanged.length == 0);
    puts("CCEL C tests passed");
    return 0;
}
