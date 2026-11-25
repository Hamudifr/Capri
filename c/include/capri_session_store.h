#ifndef CAPRI_SESSION_STORE_H
#define CAPRI_SESSION_STORE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct CapriSessionStore CapriSessionStore;

typedef struct {
    char session_id[37];
    /* Up to 64 UTF-8 bytes plus NUL; accepts Python datetime.isoformat() timestamps. */
    char created_at[65];
    char updated_at[65];
    int64_t version;
    int closed;
    char *messages_json;
} CapriSession;

typedef enum {
    CAPRI_SESSION_OK = 0,
    CAPRI_SESSION_INVALID,
    CAPRI_SESSION_IO,
    CAPRI_SESSION_DATABASE,
    CAPRI_SESSION_NOT_FOUND,
    CAPRI_SESSION_CLOSED,
    CAPRI_SESSION_CONFLICT,
    CAPRI_SESSION_LIMIT,
    CAPRI_SESSION_CORRUPT,
    CAPRI_SESSION_NO_MEMORY
} CapriSessionError;

/* The parent directory must already exist and be private (0700 or stricter).
 * On POSIX, the database is owned by the effective user and mode 0600.
 * Transcript JSON is plaintext; callers own encryption, retention and backups.
 * Requires SQLite 3.38+ with built-in JSON support.
 */
CapriSessionStore *capri_session_store_open(
    const char *path,
    size_t max_session_messages,
    size_t max_input_chars,
    size_t max_output_chars,
    size_t max_tool_chars,
    CapriSessionError *error);
void capri_session_store_close(CapriSessionStore *store);

/* Compatibility operations are restricted to sessions with no principal-owner
 * row. They cannot read or mutate principal-owned sessions.
 */
CapriSessionError capri_session_create(CapriSessionStore *store, CapriSession *out);
CapriSessionError capri_session_get(
    CapriSessionStore *store, const char *session_id, CapriSession *out);
CapriSessionError capri_session_commit_turn(
    CapriSessionStore *store, const char *session_id, int64_t expected_version,
    const char *turn_json, const char *lease_owner, CapriSession *out);
CapriSessionError capri_session_close(
    CapriSessionStore *store, const char *session_id, CapriSession *out);
CapriSessionError capri_session_claim_turn_lease(
    CapriSessionStore *store, const char *session_id, const char *owner_token,
    double lease_seconds);
CapriSessionError capri_session_renew_turn_lease(
    CapriSessionStore *store, const char *session_id, const char *owner_token,
    double lease_seconds);
CapriSessionError capri_session_release_turn_lease(
    CapriSessionStore *store, const char *session_id, const char *owner_token,
    int *released);

/* Creates the session and immutable principal ownership in one transaction. */
CapriSessionError capri_session_create_for_principal(
    CapriSessionStore *store, const char *principal_id, CapriSession *out);
CapriSessionError capri_session_get_for_principal(
    CapriSessionStore *store, const char *session_id, const char *principal_id,
    CapriSession *out);

/* turn_json is a JSON array of {"role":"...","content":"..."} objects.
 * It must contain exactly one complete user turn. The append and version CAS
 * happen in one BEGIN IMMEDIATE transaction after principal/lease checks.
 */
CapriSessionError capri_session_commit_turn_for_principal(
    CapriSessionStore *store, const char *session_id, const char *principal_id,
    int64_t expected_version, const char *turn_json, const char *lease_owner,
    CapriSession *out);
CapriSessionError capri_session_claim_turn_lease_for_principal(
    CapriSessionStore *store, const char *session_id, const char *principal_id,
    const char *owner_token, double lease_seconds);
CapriSessionError capri_session_renew_turn_lease_for_principal(
    CapriSessionStore *store, const char *session_id, const char *principal_id,
    const char *owner_token, double lease_seconds);
CapriSessionError capri_session_release_turn_lease_for_principal(
    CapriSessionStore *store, const char *session_id, const char *principal_id,
    const char *owner_token, int *released);
CapriSessionError capri_session_close_for_principal(
    CapriSessionStore *store, const char *session_id, const char *principal_id,
    CapriSession *out);
/* Creates a consistent, validated, mode-0600 snapshot without overwriting an
 * existing destination. The destination parent must already be private.
 * If CAPRI_SESSION_IO is returned after publication, a complete destination may
 * already exist while directory durability is uncertain. Inspect before retrying.
 */
CapriSessionError capri_session_backup_to(CapriSessionStore *store, const char *destination_path);
/* Restores a validated snapshot to a new private database path. The destination
 * must not exist; the live store and source backup are never overwritten.
 * If CAPRI_SESSION_IO is returned after publication, a complete destination may
 * already exist while directory durability is uncertain. Inspect before retrying.
 */
CapriSessionError capri_session_restore_to(
    CapriSessionStore *store, const char *backup_path, const char *destination_path);
CapriSessionError capri_session_integrity_check(CapriSessionStore *store);
void capri_session_free(CapriSession *session);
const char *capri_session_error_string(CapriSessionError error);

#ifdef __cplusplus
}
#endif
#endif
