#define _POSIX_C_SOURCE 200809L
#include "capri_session_store.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail(CapriSessionError error) {
    fprintf(stderr, "%s\n", capri_session_error_string(error));
    return 20 + (int)error;
}

static int parse_version(const char *text, int64_t *version) {
    if (!text || !*text || !version) return 0;
    errno = 0;
    char *end = NULL;
    long long value = strtoll(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value < 0) return 0;
    *version = (int64_t)value;
    return 1;
}

static int print_session(const CapriSession *session) {
    if (!session || !session->messages_json) return 2;
    if (printf("%s\n%" PRId64 "\n%d\n%s\n",
               session->session_id, session->version,
               session->closed, session->messages_json) < 0) return 2;
    return 0;
}

static CapriSessionStore *open_store(const char *path, CapriSessionError *error) {
    return capri_session_store_open(path, 200u, 16000u, 64000u, 131072u, error);
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    const char *mode = argv[1];
    const char *path = argc > 2 ? argv[2] : NULL;
    if (!path) return 2;

    CapriSessionError error = CAPRI_SESSION_INVALID;
    CapriSessionStore *store = open_store(path, &error);
    if (!store) return fail(error);

    CapriSession session = {0};
    CapriSessionError result = CAPRI_SESSION_INVALID;
    int output = 0;

    if (strcmp(mode, "create-principal") == 0 && argc == 5) {
        CapriSession initial = {0};
        result = capri_session_create_for_principal(store, argv[3], &initial);
        if (result == CAPRI_SESSION_OK) {
            result = capri_session_commit_turn_for_principal(
                store, initial.session_id, argv[3], 0, argv[4], NULL, &session);
        }
        capri_session_free(&initial);
    } else if (strcmp(mode, "create-legacy") == 0 && argc == 4) {
        CapriSession initial = {0};
        result = capri_session_create(store, &initial);
        if (result == CAPRI_SESSION_OK) {
            result = capri_session_commit_turn(
                store, initial.session_id, 0, argv[3], NULL, &session);
        }
        capri_session_free(&initial);
    } else if (strcmp(mode, "read-principal") == 0 && argc == 5) {
        result = capri_session_get_for_principal(store, argv[3], argv[4], &session);
    } else if (strcmp(mode, "read-legacy") == 0 && argc == 4) {
        result = capri_session_get(store, argv[3], &session);
    } else if (strcmp(mode, "commit-principal") == 0 && argc == 7) {
        int64_t version = 0;
        if (!parse_version(argv[5], &version)) {
            capri_session_store_close(store);
            return 2;
        }
        result = capri_session_commit_turn_for_principal(
            store, argv[3], argv[4], version, argv[6], NULL, &session);
    } else if (strcmp(mode, "commit-legacy") == 0 && argc == 6) {
        int64_t version = 0;
        if (!parse_version(argv[4], &version)) {
            capri_session_store_close(store);
            return 2;
        }
        result = capri_session_commit_turn(
            store, argv[3], version, argv[5], NULL, &session);
    } else if (strcmp(mode, "close-principal") == 0 && argc == 5) {
        result = capri_session_close_for_principal(
            store, argv[3], argv[4], &session);
    } else if (strcmp(mode, "close-legacy") == 0 && argc == 4) {
        result = capri_session_close(store, argv[3], &session);
    } else {
        capri_session_store_close(store);
        return 2;
    }

    if (result == CAPRI_SESSION_OK) output = print_session(&session);
    capri_session_free(&session);
    capri_session_store_close(store);
    return result == CAPRI_SESSION_OK ? output : fail(result);
}
