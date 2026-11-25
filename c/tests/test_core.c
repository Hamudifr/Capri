#include "capri_core.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static CapriEvaluationRecord valid_record(void) {
    CapriEvaluationRecord r = {0};
    strcpy(r.run_id, "run-1");
    strcpy(r.scenario_id, "scenario-1");
    strcpy(r.dimension, "Reasoning");
    r.status = CAPRI_STATUS_NOT_RUN;
    r.evaluator_type = CAPRI_EVALUATOR_SELF;
    r.evidence_stage = CAPRI_EVIDENCE_NOT_RUN;
    strcpy(r.run_at, "2026-11-25T00:00:00Z");
    return r;
}

int main(void) {
    CapriEvaluationRecord r = valid_record();
    char error[160];
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_VALID);
    r.status = CAPRI_STATUS_PASS;
    r.evidence_stage = CAPRI_EVIDENCE_SELF_SCORED;
    strcpy(r.evidence_ref, "evidence://run-1");
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_VALID);
    r.evidence_ref[0] = '\0';
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_EVIDENCE);
    r = valid_record(); strcpy(r.dimension, "Unknown");
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_DIMENSION);
    r = valid_record(); strcpy(r.run_at, "2026-02-29T00:00:00Z");
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_TIMESTAMP);
    r = valid_record(); strcpy(r.parent_run_id, "run-1");
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_LINEAGE);
    r = valid_record(); strcpy(r.run_id, "bad-\xed\xa0\x80");
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_UTF8);
    r = valid_record(); r.run_id[0] = (char)0xE2; r.run_id[1] = '\0';
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_UTF8);
    r = valid_record(); memset(r.run_id, 'x', sizeof(r.run_id));
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_REQUIRED_FIELD);
    r = valid_record(); r.evaluator_type = CAPRI_EVALUATOR_INDEPENDENT;
    assert(capri_record_validate(&r, error, sizeof(error)) == CAPRI_RECORD_INVALID_EVIDENCE);
    assert(capri_record_validate(NULL, error, sizeof(error)) == CAPRI_RECORD_NULL);
    puts("core validation tests: ok");
    return 0;
}
