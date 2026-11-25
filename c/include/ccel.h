#ifndef CAPRI_CCEL_H
#define CAPRI_CCEL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CCEL_MAX_SIDE 30u
#define CCEL_MAX_CELLS 900u
#define CCEL_MAX_PROGRAM_DEPTH 5u
#define CCEL_MAX_EXAMPLES 100u
#define CCEL_MAX_CANDIDATES 10000u
#define CCEL_MAX_PROBES 10000u

typedef enum {
    CCEL_OK = 0,
    CCEL_ERR_EMPTY_GRID,
    CCEL_ERR_EMPTY_ROW,
    CCEL_ERR_NON_RECTANGULAR,
    CCEL_ERR_SIDE_TOO_LARGE,
    CCEL_ERR_TOO_MANY_CELLS,
    CCEL_ERR_CELL_OUT_OF_RANGE,
    CCEL_ERR_PROGRAM_TOO_DEEP,
    CCEL_ERR_INVALID_DEPTH,
    CCEL_ERR_INVALID_CANDIDATE_BUDGET,
    CCEL_ERR_NO_EXAMPLES,
    CCEL_ERR_TOO_MANY_EXAMPLES,
    CCEL_ERR_NO_PROGRAMS,
    CCEL_ERR_NO_PROBES,
    CCEL_ERR_NO_CONSISTENT_MODEL,
    CCEL_ERR_SEARCH_LIMIT_EXCEEDED,
    CCEL_ERR_INVALID_OPERATION,
    CCEL_ERR_TOO_MANY_PROGRAMS,
    CCEL_ERR_TOO_MANY_PROBES,
    CCEL_ERR_ALLOCATION
} CcelError;

typedef struct {
    size_t height;
    size_t width;
    uint8_t cells[CCEL_MAX_CELLS];
} CcelGrid;

typedef enum {
    CCEL_ROTATE_CLOCKWISE = 0,
    CCEL_ROTATE_COUNTERCLOCKWISE,
    CCEL_FLIP_HORIZONTAL,
    CCEL_FLIP_VERTICAL,
    CCEL_TRANSPOSE
} CcelOperation;

typedef struct {
    size_t length;
    CcelOperation operations[CCEL_MAX_PROGRAM_DEPTH];
} CcelProgram;

typedef struct {
    CcelGrid source;
    CcelGrid target;
} CcelExample;

typedef struct {
    CcelProgram *programs;
    size_t count;
    size_t depth;
    size_t examples_seen;
} CcelSynthesisResult;

typedef struct {
    CcelGrid grid;
    size_t count;
} CcelPrediction;

typedef struct {
    CcelPrediction *items;
    size_t count;
} CcelPredictionSet;

typedef struct {
    CcelGrid grid;
    double entropy_bits;
    size_t distinct_outcomes;
    CcelPrediction *predictions;
    size_t prediction_count;
} CcelProbeChoice;

const char *ccel_error_string(CcelError error);
/* The source may overlap out->cells; input bytes are snapshotted before writing. */
CcelError ccel_grid_init(CcelGrid *out, size_t height, size_t width,
                         const uint8_t *cells, size_t cell_count);
int ccel_grid_equal(const CcelGrid *a, const CcelGrid *b);
/* Total order: invalid grids sort before valid grids; NULL sorts first. */
int ccel_grid_compare(const CcelGrid *a, const CcelGrid *b);
/* Supports input == out. */
CcelError ccel_operation_apply(CcelOperation operation, const CcelGrid *input,
                               CcelGrid *out);
CcelError ccel_program_init(CcelProgram *out, const CcelOperation *operations,
                            size_t length);
CcelError ccel_program_apply(const CcelProgram *program, const CcelGrid *input,
                             CcelGrid *out);
CcelError ccel_synthesize(const CcelExample *examples, size_t example_count,
                          size_t max_depth, size_t max_candidates,
                          CcelSynthesisResult *out);
void ccel_synthesis_result_free(CcelSynthesisResult *result);
/* program_count is bounded by CCEL_MAX_CANDIDATES. */
CcelError ccel_predict(const CcelProgram *programs, size_t program_count,
                       const CcelGrid *input, CcelPredictionSet *out);
void ccel_prediction_set_free(CcelPredictionSet *set);
/* program_count <= CCEL_MAX_CANDIDATES and probe_count <= CCEL_MAX_PROBES. */
CcelError ccel_select_probe(const CcelProgram *programs, size_t program_count,
                            const CcelGrid *probes, size_t probe_count,
                            CcelProbeChoice *out);
void ccel_probe_choice_free(CcelProbeChoice *choice);

#ifdef __cplusplus
}
#endif
#endif
