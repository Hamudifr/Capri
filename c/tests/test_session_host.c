#define _POSIX_C_SOURCE 200809L
#include "capri_session_host.h"

#include <assert.h>
#include <pthread.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int credential_is(
    const unsigned char *credential,
    size_t credential_len,
    const char *expected)
{
    size_t expected_len = strlen(expected);
    return credential != NULL && credential_len == expected_len
        && memcmp(credential, expected, expected_len) == 0;
}

static CapriHostCredentialStatus resolver(
    void *context,
    const unsigned char *credential,
    size_t credential_len,
    char *principal_id_out,
    size_t principal_id_capacity,
    size_t *principal_id_len)
{
    (void)context;
    if (principal_id_out == NULL || principal_id_len == NULL
        || principal_id_capacity == 0u) return CAPRI_HOST_CREDENTIAL_ERROR;

    *principal_id_len = 0u;
    if (credential_is(credential, credential_len, "resolver-error")) {
        return CAPRI_HOST_CREDENTIAL_ERROR;
    }
    if (credential_is(credential, credential_len, "malformed-utf8")) {
        principal_id_out[0] = (char)0xFF;
        *principal_id_len = 1u;
        return CAPRI_HOST_CREDENTIAL_RESOLVED;
    }
    if (credential_is(credential, credential_len, "embedded-nul")) {
        principal_id_out[0] = 'p';
        principal_id_out[1] = '\0';
        principal_id_out[2] = 'x';
        *principal_id_len = 3u;
        return CAPRI_HOST_CREDENTIAL_RESOLVED;
    }
    if (credential_is(credential, credential_len, "empty-principal")) {
        return CAPRI_HOST_CREDENTIAL_RESOLVED;
    }
    if (credential_is(credential, credential_len, "too-long-principal")) {
        memset(principal_id_out, 'x', principal_id_capacity);
        *principal_id_len = principal_id_capacity;
        return CAPRI_HOST_CREDENTIAL_RESOLVED;
    }
    if (credential_is(credential, credential_len, "overlong-principal")) {
        memset(principal_id_out, 'a', 257u);
        *principal_id_len = 257u;
        return CAPRI_HOST_CREDENTIAL_RESOLVED;
    }
    if (credential_is(credential, credential_len, "whitespace-principal")) {
        principal_id_out[0] = ' ';
        principal_id_out[1] = '\t';
        *principal_id_len = 2u;
        return CAPRI_HOST_CREDENTIAL_RESOLVED;
    }

    const char *principal = NULL;
    if (credential_is(credential, credential_len, "credential-a")) {
        principal = "principal-a";
    } else if (credential_is(credential, credential_len, "credential-b")) {
        principal = "principal-b";
    } else if (credential_is(credential, credential_len, "credential-unicode")) {
        principal = "principal-\xF0\x9F\x94\x90";
    } else {
        return CAPRI_HOST_CREDENTIAL_DENIED;
    }

    size_t length = strlen(principal);
    if (length >= principal_id_capacity) return CAPRI_HOST_CREDENTIAL_ERROR;
    memcpy(principal_id_out, principal, length);
    *principal_id_len = length;
    return CAPRI_HOST_CREDENTIAL_RESOLVED;
}

typedef struct {
    CapriSessionHost *host;
    const unsigned char *credential;
    size_t credential_len;
    CapriSessionHostError result;
    CapriSession session;
} CreateThread;

static void *create_session_thread(void *opaque) {
    CreateThread *argument = (CreateThread *)opaque;
    argument->result = capri_session_host_create_session(
        argument->host,
        argument->credential,
        argument->credential_len,
        &argument->session);
    return NULL;
}

static void assert_owner_count(sqlite3 *db, const char *sql, int expected) {
    sqlite3_stmt *statement = NULL;
    assert(sqlite3_prepare_v2(db, sql, -1, &statement, NULL) == SQLITE_OK);
    assert(sqlite3_step(statement) == SQLITE_ROW);
    assert(sqlite3_column_int(statement, 0) == expected);
    sqlite3_finalize(statement);
}

int main(void) {
    char directory[] = "/tmp/capri-host-session-test-XXXXXX";
    assert(mkdtemp(directory) != NULL);
    assert(chmod(directory, 0700) == 0);

    char database_path[512];
    int written = snprintf(
        database_path, sizeof(database_path), "%s/sessions.sqlite3", directory);
    assert(written > 0 && (size_t)written < sizeof(database_path));

    CapriSessionError store_error = CAPRI_SESSION_INVALID;
    CapriSessionStore *store = capri_session_store_open(
        database_path, 100u, 4096u, 4096u, 4096u, &store_error);
    assert(store != NULL && store_error == CAPRI_SESSION_OK);

    CapriSessionHostError host_error = CAPRI_SESSION_HOST_INVALID;
    CapriSessionHost *host = capri_session_host_create(
        store, resolver, NULL, &host_error);
    assert(host != NULL && host_error == CAPRI_SESSION_HOST_OK);
    assert(capri_session_host_create(NULL, resolver, NULL, &host_error) == NULL);
    assert(host_error == CAPRI_SESSION_HOST_INVALID);
    assert(capri_session_host_create(store, NULL, NULL, &host_error) == NULL);
    assert(host_error == CAPRI_SESSION_HOST_INVALID);

    const unsigned char credential_a[] = "credential-a";
    const unsigned char credential_b[] = "credential-b";
    const unsigned char bad_credential[] = "not-valid";
    const unsigned char resolver_error[] = "resolver-error";
    const unsigned char malformed_utf8[] = "malformed-utf8";
    const unsigned char embedded_nul[] = "embedded-nul";
    const unsigned char empty_principal[] = "empty-principal";
    const unsigned char too_long_principal[] = "too-long-principal";
    const unsigned char overlong_principal[] = "overlong-principal";
    const unsigned char whitespace_principal[] = "whitespace-principal";

    CapriSession session_a = {0};
    assert(capri_session_host_create_session(
        host, credential_a, sizeof(credential_a) - 1u, &session_a)
        == CAPRI_SESSION_HOST_OK);

    CapriSession loaded_a = {0};
    assert(capri_session_host_get_session(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, &loaded_a) == CAPRI_SESSION_HOST_OK);
    assert(strcmp(loaded_a.session_id, session_a.session_id) == 0);

    CapriSession foreign = {0};
    assert(capri_session_host_get_session(
        host, credential_b, sizeof(credential_b) - 1u,
        session_a.session_id, &foreign) == CAPRI_SESSION_HOST_NOT_FOUND);
    assert(capri_session_host_get_session(
        host, credential_b, sizeof(credential_b) - 1u,
        "00000000-0000-4000-8000-000000000000", &foreign)
        == CAPRI_SESSION_HOST_NOT_FOUND);

    CapriSession session_b = {0};
    assert(capri_session_host_create_session(
        host, credential_b, sizeof(credential_b) - 1u, &session_b)
        == CAPRI_SESSION_HOST_OK);
    assert(strcmp(session_a.session_id, session_b.session_id) != 0);

    const char *turn =
        "[{\"role\":\"user\",\"content\":\"hello\"},"
        "{\"role\":\"assistant\",\"content\":\"world\"}]";
    CapriSession committed = {0};
    assert(capri_session_host_commit_turn(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, 0, turn, NULL, &committed)
        == CAPRI_SESSION_HOST_OK);
    assert(committed.version == 1);

    assert(capri_session_host_claim_turn_lease(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, "lease-owner-a", 30.0)
        == CAPRI_SESSION_HOST_OK);
    assert(capri_session_host_renew_turn_lease(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, "lease-owner-a", 30.0)
        == CAPRI_SESSION_HOST_OK);
    int released = 0;
    assert(capri_session_host_release_turn_lease(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, "lease-owner-a", &released)
        == CAPRI_SESSION_HOST_OK);
    assert(released == 1);

    CapriSession closed = {0};
    assert(capri_session_host_close_session(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, &closed) == CAPRI_SESSION_HOST_OK);
    CapriSession after_close = {0};
    assert(capri_session_host_get_session(
        host, credential_a, sizeof(credential_a) - 1u,
        session_a.session_id, &after_close) == CAPRI_SESSION_HOST_CLOSED);

    assert(capri_session_host_create_session(
        host, bad_credential, sizeof(bad_credential) - 1u, &foreign)
        == CAPRI_SESSION_HOST_UNAUTHORIZED);
    assert(capri_session_host_create_session(
        host, resolver_error, sizeof(resolver_error) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(
        host, malformed_utf8, sizeof(malformed_utf8) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(
        host, embedded_nul, sizeof(embedded_nul) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(
        host, empty_principal, sizeof(empty_principal) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(
        host, too_long_principal, sizeof(too_long_principal) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(
        host, overlong_principal, sizeof(overlong_principal) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(
        host, whitespace_principal, sizeof(whitespace_principal) - 1u, &foreign)
        == CAPRI_SESSION_HOST_RESOLVER_ERROR);
    assert(capri_session_host_create_session(host, NULL, 1u, &foreign)
        == CAPRI_SESSION_HOST_INVALID);
    assert(capri_session_host_create_session(host, credential_a, 0u, &foreign)
        == CAPRI_SESSION_HOST_INVALID);
    unsigned char oversized_credential[CAPRI_SESSION_HOST_MAX_CREDENTIAL_BYTES + 1u] = {0};
    assert(capri_session_host_create_session(
        host, oversized_credential, sizeof(oversized_credential), &foreign)
        == CAPRI_SESSION_HOST_INVALID);

    const unsigned char unicode_credential[] = "credential-unicode";
    CapriSession unicode_session = {0};
    assert(capri_session_host_create_session(
        host, unicode_credential, sizeof(unicode_credential) - 1u, &unicode_session)
        == CAPRI_SESSION_HOST_OK);

    CreateThread thread_a = {
        host, credential_a, sizeof(credential_a) - 1u, CAPRI_SESSION_HOST_INVALID, {0}
    };
    CreateThread thread_b = {
        host, credential_b, sizeof(credential_b) - 1u, CAPRI_SESSION_HOST_INVALID, {0}
    };
    pthread_t thread_a_id, thread_b_id;
    assert(pthread_create(&thread_a_id, NULL, create_session_thread, &thread_a) == 0);
    assert(pthread_create(&thread_b_id, NULL, create_session_thread, &thread_b) == 0);
    assert(pthread_join(thread_a_id, NULL) == 0);
    assert(pthread_join(thread_b_id, NULL) == 0);
    assert(thread_a.result == CAPRI_SESSION_HOST_OK);
    assert(thread_b.result == CAPRI_SESSION_HOST_OK);
    assert(strcmp(thread_a.session.session_id, thread_b.session.session_id) != 0);

    assert(capri_session_integrity_check(store) == CAPRI_SESSION_OK);
    capri_session_host_destroy(host);
    capri_session_store_close(store);

    sqlite3 *database = NULL;
    assert(sqlite3_open(database_path, &database) == SQLITE_OK);
    assert_owner_count(
        database,
        "SELECT COUNT(*) FROM session_owners "
        "WHERE principal_id IN ('credential-a','credential-b','not-valid')",
        0);
    assert_owner_count(
        database,
        "SELECT COUNT(*) FROM sessions "
        "WHERE messages_json LIKE '%credential-a%' "
        "OR messages_json LIKE '%credential-b%'",
        0);
    sqlite3_close(database);

    capri_session_free(&session_a);
    capri_session_free(&loaded_a);
    capri_session_free(&foreign);
    capri_session_free(&session_b);
    capri_session_free(&committed);
    capri_session_free(&closed);
    capri_session_free(&after_close);
    capri_session_free(&unicode_session);
    capri_session_free(&thread_a.session);
    capri_session_free(&thread_b.session);

    char wal_path[520], shm_path[520];
    (void)snprintf(wal_path, sizeof(wal_path), "%s-wal", database_path);
    (void)snprintf(shm_path, sizeof(shm_path), "%s-shm", database_path);
    (void)unlink(wal_path);
    (void)unlink(shm_path);
    assert(unlink(database_path) == 0);
    assert(rmdir(directory) == 0);

    puts("native C authenticated session host tests: ok");
    return 0;
}
