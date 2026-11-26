#define _POSIX_C_SOURCE 200809L
#include "capri_session_host.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct CapriSessionHost {
    CapriSessionStore *store;
    CapriHostCredentialResolver resolver;
    void *resolver_context;
};

static void secure_clear(void *memory, size_t size) {
    volatile unsigned char *cursor = (volatile unsigned char *)memory;
    while (size > 0u) {
        *cursor++ = 0u;
        --size;
    }
}

static bool continuation(unsigned char value) {
    return value >= 0x80u && value <= 0xBFu;
}

static bool utf8_next(
    const unsigned char *text,
    size_t length,
    size_t *offset,
    uint32_t *codepoint)
{
    size_t i = *offset;
    if (i >= length) return false;

    unsigned char first = text[i];
    size_t width = 0u;
    uint32_t value = 0u;

    if (first < 0x80u) {
        width = 1u;
        value = first;
    } else if (first >= 0xC2u && first <= 0xDFu) {
        width = 2u;
        if (i + width > length || !continuation(text[i + 1u])) return false;
        value = ((uint32_t)(first & 0x1Fu) << 6u)
              | (uint32_t)(text[i + 1u] & 0x3Fu);
    } else if (first >= 0xE0u && first <= 0xEFu) {
        width = 3u;
        if (i + width > length
            || !continuation(text[i + 1u])
            || !continuation(text[i + 2u])) return false;
        unsigned char second = text[i + 1u];
        if ((first == 0xE0u && second < 0xA0u)
            || (first == 0xEDu && second > 0x9Fu)) return false;
        value = ((uint32_t)(first & 0x0Fu) << 12u)
              | ((uint32_t)(second & 0x3Fu) << 6u)
              | (uint32_t)(text[i + 2u] & 0x3Fu);
    } else if (first >= 0xF0u && first <= 0xF4u) {
        width = 4u;
        if (i + width > length
            || !continuation(text[i + 1u])
            || !continuation(text[i + 2u])
            || !continuation(text[i + 3u])) return false;
        unsigned char second = text[i + 1u];
        if ((first == 0xF0u && second < 0x90u)
            || (first == 0xF4u && second > 0x8Fu)) return false;
        value = ((uint32_t)(first & 0x07u) << 18u)
              | ((uint32_t)(second & 0x3Fu) << 12u)
              | ((uint32_t)(text[i + 2u] & 0x3Fu) << 6u)
              | (uint32_t)(text[i + 3u] & 0x3Fu);
    } else {
        return false;
    }

    *offset = i + width;
    *codepoint = value;
    return true;
}

static bool unicode_space(uint32_t codepoint) {
    return (codepoint >= 0x09u && codepoint <= 0x0Du)
        || (codepoint >= 0x1Cu && codepoint <= 0x20u)
        || codepoint == 0x85u
        || codepoint == 0xA0u
        || codepoint == 0x1680u
        || (codepoint >= 0x2000u && codepoint <= 0x200Au)
        || codepoint == 0x2028u
        || codepoint == 0x2029u
        || codepoint == 0x202Fu
        || codepoint == 0x205Fu
        || codepoint == 0x3000u;
}

static bool principal_id_valid(const unsigned char *text, size_t length) {
    if (text == NULL || length == 0u
        || length > CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES
        || memchr(text, 0, length) != NULL) return false;

    size_t offset = 0u;
    size_t characters = 0u;
    bool non_whitespace = false;
    while (offset < length) {
        uint32_t codepoint = 0u;
        if (!utf8_next(text, length, &offset, &codepoint)) return false;
        ++characters;
        if (characters > 256u) return false;
        if (!unicode_space(codepoint)) non_whitespace = true;
    }
    return characters > 0u && non_whitespace;
}

static CapriSessionHostError resolve_principal(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u])
{
    if (host == NULL || credential == NULL || credential_len == 0u
        || credential_len > CAPRI_SESSION_HOST_MAX_CREDENTIAL_BYTES) {
        return CAPRI_SESSION_HOST_INVALID;
    }

    memset(principal_id, 0, CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u);
    size_t principal_len = 0u;
    CapriHostCredentialStatus status = host->resolver(
        host->resolver_context,
        credential,
        credential_len,
        principal_id,
        CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u,
        &principal_len);

    if (status == CAPRI_HOST_CREDENTIAL_DENIED) {
        secure_clear(principal_id, CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u);
        return CAPRI_SESSION_HOST_UNAUTHORIZED;
    }
    if (status != CAPRI_HOST_CREDENTIAL_RESOLVED
        || !principal_id_valid((const unsigned char *)principal_id, principal_len)) {
        secure_clear(principal_id, CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u);
        return CAPRI_SESSION_HOST_RESOLVER_ERROR;
    }

    principal_id[principal_len] = '\0';
    return CAPRI_SESSION_HOST_OK;
}

static CapriSessionHostError map_store_error(CapriSessionError error) {
    switch (error) {
        case CAPRI_SESSION_OK: return CAPRI_SESSION_HOST_OK;
        case CAPRI_SESSION_INVALID: return CAPRI_SESSION_HOST_INVALID;
        case CAPRI_SESSION_NOT_FOUND: return CAPRI_SESSION_HOST_NOT_FOUND;
        case CAPRI_SESSION_CLOSED: return CAPRI_SESSION_HOST_CLOSED;
        case CAPRI_SESSION_CONFLICT: return CAPRI_SESSION_HOST_CONFLICT;
        case CAPRI_SESSION_LIMIT: return CAPRI_SESSION_HOST_LIMIT;
        case CAPRI_SESSION_CORRUPT: return CAPRI_SESSION_HOST_CORRUPT;
        case CAPRI_SESSION_IO: return CAPRI_SESSION_HOST_IO;
        case CAPRI_SESSION_DATABASE: return CAPRI_SESSION_HOST_DATABASE;
        case CAPRI_SESSION_NO_MEMORY: return CAPRI_SESSION_HOST_NO_MEMORY;
        default: return CAPRI_SESSION_HOST_DATABASE;
    }
}

CapriSessionHost *capri_session_host_create(
    CapriSessionStore *store,
    CapriHostCredentialResolver resolver,
    void *resolver_context,
    CapriSessionHostError *error)
{
    if (error != NULL) *error = CAPRI_SESSION_HOST_INVALID;
    if (store == NULL || resolver == NULL) return NULL;

    CapriSessionHost *host = (CapriSessionHost *)calloc(1u, sizeof(*host));
    if (host == NULL) {
        if (error != NULL) *error = CAPRI_SESSION_HOST_NO_MEMORY;
        return NULL;
    }
    host->store = store;
    host->resolver = resolver;
    host->resolver_context = resolver_context;
    if (error != NULL) *error = CAPRI_SESSION_HOST_OK;
    return host;
}

void capri_session_host_destroy(CapriSessionHost *host) {
    if (host == NULL) return;
    secure_clear(host, sizeof(*host));
    free(host);
}

CapriSessionHostError capri_session_host_create_session(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    CapriSession *out)
{
    if (out != NULL) memset(out, 0, sizeof(*out));
    if (host == NULL || out == NULL) return CAPRI_SESSION_HOST_INVALID;

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_create_for_principal(host->store, principal_id, out);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

CapriSessionHostError capri_session_host_get_session(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    CapriSession *out)
{
    if (out != NULL) memset(out, 0, sizeof(*out));
    if (host == NULL || out == NULL || session_id == NULL) return CAPRI_SESSION_HOST_INVALID;

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_get_for_principal(
        host->store, session_id, principal_id, out);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

CapriSessionHostError capri_session_host_close_session(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    CapriSession *out)
{
    if (out != NULL) memset(out, 0, sizeof(*out));
    if (host == NULL || out == NULL || session_id == NULL) return CAPRI_SESSION_HOST_INVALID;

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_close_for_principal(
        host->store, session_id, principal_id, out);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

CapriSessionHostError capri_session_host_commit_turn(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    int64_t expected_version,
    const char *turn_json,
    const char *lease_owner,
    CapriSession *out)
{
    if (out != NULL) memset(out, 0, sizeof(*out));
    if (host == NULL || out == NULL || session_id == NULL || turn_json == NULL) {
        return CAPRI_SESSION_HOST_INVALID;
    }

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_commit_turn_for_principal(
        host->store, session_id, principal_id, expected_version, turn_json, lease_owner, out);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

CapriSessionHostError capri_session_host_claim_turn_lease(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    const char *owner_token,
    double lease_seconds)
{
    if (host == NULL || session_id == NULL || owner_token == NULL) {
        return CAPRI_SESSION_HOST_INVALID;
    }

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_claim_turn_lease_for_principal(
        host->store, session_id, principal_id, owner_token, lease_seconds);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

CapriSessionHostError capri_session_host_renew_turn_lease(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    const char *owner_token,
    double lease_seconds)
{
    if (host == NULL || session_id == NULL || owner_token == NULL) {
        return CAPRI_SESSION_HOST_INVALID;
    }

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_renew_turn_lease_for_principal(
        host->store, session_id, principal_id, owner_token, lease_seconds);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

CapriSessionHostError capri_session_host_release_turn_lease(
    CapriSessionHost *host,
    const unsigned char *credential,
    size_t credential_len,
    const char *session_id,
    const char *owner_token,
    int *released)
{
    if (released != NULL) *released = 0;
    if (host == NULL || session_id == NULL || owner_token == NULL || released == NULL) {
        return CAPRI_SESSION_HOST_INVALID;
    }

    char principal_id[CAPRI_SESSION_HOST_MAX_PRINCIPAL_ID_BYTES + 1u];
    CapriSessionHostError auth = resolve_principal(host, credential, credential_len, principal_id);
    if (auth != CAPRI_SESSION_HOST_OK) return auth;
    CapriSessionError result = capri_session_release_turn_lease_for_principal(
        host->store, session_id, principal_id, owner_token, released);
    secure_clear(principal_id, sizeof(principal_id));
    return map_store_error(result);
}

const char *capri_session_host_error_string(CapriSessionHostError error) {
    switch (error) {
        case CAPRI_SESSION_HOST_OK: return "ok";
        case CAPRI_SESSION_HOST_INVALID: return "invalid input";
        case CAPRI_SESSION_HOST_UNAUTHORIZED: return "credential denied";
        case CAPRI_SESSION_HOST_RESOLVER_ERROR: return "credential resolver failed";
        case CAPRI_SESSION_HOST_NOT_FOUND: return "session not found";
        case CAPRI_SESSION_HOST_CLOSED: return "session closed";
        case CAPRI_SESSION_HOST_CONFLICT: return "session conflict";
        case CAPRI_SESSION_HOST_LIMIT: return "session limit";
        case CAPRI_SESSION_HOST_CORRUPT: return "session corrupt";
        case CAPRI_SESSION_HOST_IO: return "session I/O error";
        case CAPRI_SESSION_HOST_DATABASE: return "session database error";
        case CAPRI_SESSION_HOST_NO_MEMORY: return "out of memory";
        default: return "unknown session host error";
    }
}
