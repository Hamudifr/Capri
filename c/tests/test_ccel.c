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
    assert(ccel_operation_apply(CCEL_ROTATE_CLOCKWISE, &g, &out) == CCEL_OK);
    assert(ccel_grid_equal(&out, &(CcelGrid){.height=3,.width=2,.cells={4,1,5,2,6,3}}));
    assert(ccel_operation_apply(CCEL_ROTATE_COUNTERCLOCKWISE, &g, &out) == CCEL_OK);
    assert(ccel_grid_equal(&out, &(CcelGrid){.height=3,.width=2,.cells={3,6,2,5,1,4}}));
    assert(ccel_operation_apply(CCEL_TRANSPOSE, &g, &out) == CCEL_OK);
    assert(ccel_grid_equal(&out, &(CcelGrid){.height=3,.width=2,.cells={1,4,2,5,3,6}}));
    (void)clockwise; (void)counter; (void)transpose;

    CcelExample ex = {g, out};
    CcelSynthesisResult result;
    assert(ccel_synthesize(&ex, 1, 1, 4096, &result) == CCEL_OK);
    assert(result.depth == 1 && result.count >= 1);
    CcelPredictionSet predictions;
    assert(ccel_predict(result.programs, result.count, &g, &predictions) == CCEL_OK);
    assert(predictions.count >= 1);
    ccel_prediction_set_free(&predictions);
    ccel_synthesis_result_free(&result);

    assert(ccel_grid_init(&out, 1, 1, (const uint8_t[]){10}, 1) == CCEL_ERR_CELL_OUT_OF_RANGE);
    assert(ccel_synthesize(NULL, 0, 1, 10, &result) == CCEL_ERR_NO_EXAMPLES);
    assert(ccel_program_init(&(CcelProgram){0}, NULL, 6) == CCEL_ERR_PROGRAM_TOO_DEEP);
    puts("CCEL C tests passed");
    return 0;
}
