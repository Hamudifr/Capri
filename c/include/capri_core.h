#ifndef CAPRI_CORE_H
#define CAPRI_CORE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CAPRI_RUN_ID_MAX 128u
#define CAPRI_SCENARIO_ID_MAX 128u
#define CAPRI_DIMENSION_MAX 32u
#define CAPRI_TIMESTAMP_MAX 40u
#define CAPRI_EVIDENCE_REF_MAX 512u
#define CAPRI_RUBRIC_VERSION_MAX 128u

typedef enum {
    CAPRI_STATUS_NOT_RUN = 0,
    CAPRI_STATUS_PASS,
    CAPRI_STATUS_FAIL,
    CAPRI_STATUS_RETEST_NEEDED
} CapriStatus;

typedef enum {
    CAPRI_EVALUATOR_SELF = 0,
    CAPRI_EVALUATOR_INDEPENDENT
} CapriEvaluatorType;

typedef enum {
    CAPRI_EVIDENCE_NOT_RUN = 0,
    CAPRI_EVIDENCE_ATTEMPTED,
    CAPRI_EVIDENCE_CAPTURED,
    CAPRI_EVIDENCE_SELF_SCORED,
    CAPRI_EVIDENCE_INDEPENDENTLY_REVIEWED
} CapriEvidenceStage;

typedef struct {
    char run_id[CAPRI_RUN_ID_MAX + 1u];
    char scenario_id[CAPRI_SCENARIO_ID_MAX + 1u];
    char dimension[CAPRI_DIMENSION_MAX + 1u];
    CapriStatus status;
    CapriEvaluatorType evaluator_type;
    CapriEvidenceStage evidence_stage;
    char run_at[CAPRI_TIMESTAMP_MAX + 1u];
    char evidence_ref[CAPRI_EVIDENCE_REF_MAX + 1u];
    char parent_run_id[CAPRI_RUN_ID_MAX + 1u];
    char rubric_version[CAPRI_RUBRIC_VERSION_MAX + 1u];
} CapriEvaluationRecord;

typedef enum {
    CAPRI_RECORD_VALID = 0,
    CAPRI_RECORD_NULL,
    CAPRI_RECORD_REQUIRED_FIELD,
    CAPRI_RECORD_INVALID_UTF8,
    CAPRI_RECORD_INVALID_DIMENSION,
    CAPRI_RECORD_INVALID_ENUM,
    CAPRI_RECORD_INVALID_TIMESTAMP,
    CAPRI_RECORD_INVALID_EVIDENCE,
    CAPRI_RECORD_INVALID_LINEAGE
} CapriRecordError;

CapriRecordError capri_record_validate(const CapriEvaluationRecord *record,
                                       char *error, size_t error_size);
const char *capri_record_error_string(CapriRecordError error);

#ifdef __cplusplus
}
#endif
#endif
