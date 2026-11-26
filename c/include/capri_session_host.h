#ifndef CAPRI_SESSION_HOST_H
#define CAPRI_SESSION_HOST_H

#include "capri_session_store.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CAPRI_SESSION_HOST_MAX_CREDENTIAL_BYTES 4096u
#define CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES 1024u

typedef struct CapriSessionHost CapriSessionHost;

typedef enum {
    CAPRI_HOST_CREDENTIAL_RESOLVED = 0,
    CAPRI_HOST_CREDENTIAL_DENIED,
    CAPRI_HOST_CREDENTIAL_ERROR
} CapriHostCredentialStatus;

/*
 * The embedding host resolves an opaque credential to an authenticated
 * principal. The gateway supplies a bounded output buffer and receives the
 * exact UTF-8 byte length. The callback must not retain the credential or
 * output-buffer pointers. Return DENIED for invalid/expired/revoked credentials
 * and ERROR for resolver infrastructure failures.
 */
typedef CapriHostCredentialStatus (*CapriHostCredentialResolver)(
    void *context,
    const unsigned char *credential,
    size_t credential_len,
    char *principal_id_out,
    size_t principal_id_capacity,
    size_t *principal_id_len);

typedef enum {
    CAPRI_SESSION_HOST_OK = 0,
    CAPRI_SESSION_HOST_INVALID,
    CAPRI_SESSION_HOST_UNAUTHORIZED,
    CAPRI_SESSION_HOST_RESOLVER_ERROR,
    CAPRI_SESSION_HOST_NOT_FOUND,
    CAPRI_SESSION_HOST_CLOSED,
    CAPRI_SESSION_HOST_CONFLICT,
    CAPRI_SESSION_HOST_LIMIT,
    CAPRI_SESSION_HOST_CORRUPT,
    CAPRI_SESSION_HOST_IO,
    CAPRI_SESSION_HOST_DATABASE,
    CAPRI_SESSION_HOST_NO_MEMORY
} CapriSessionHostError;

/*
 * The store and resolver context are borrowed and must outlive the host
 * gateway. The gateway never owns, logs, persists, or retains credential
 * bytes. Principal IDs are copied into a bounded stack buffer, validated, and
 * cleared before each operation returns.
 *
 * A gateway may be shared across threads if the resolver callback and its
 * context are thread-safe. The gateway does not hold a SQLite transaction or
 * store lock while invoking the resolver.
 */
CapriSessionHost *capri_session_host_create(
    CapriSessionStore *store,
    CapriHostCredentialResolver resolver,
    void *resolver_context,
    CapriSessionHostError *error);
void capri_session_host_destroy(CapriSessionHost *host);

CapriSessionHostError capri_session_host_create_session(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    CapriSession *out);
CapriSessionHostError capri_session_host_get_session(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    CapriSession *out);
CapriSessionHostError capri_session_host_close_session(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    CapriSession *out);
CapriSessionHostError capri_session_host_commit_turn(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    int64_t expected_version,
    const char *turn_json,
    const char *lease_owner,
    CapriSession *out);
CapriSessionHostError capri_session_host_claim_turn_lease(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    const char *owner_token,
    double lease_seconds);
CapriSessionHostError capri_session_host_renew_turn_lease(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    const char *owner_token,
    double lease_seconds);
CapriSessionHostError capri_session_host_release_turn_lease(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    const char *owner_token,
    int *released);

const char *capri_session_host_error_string(CapriSessionHostError error);

#ifdef __cplusplus
}
#endif

#endif
