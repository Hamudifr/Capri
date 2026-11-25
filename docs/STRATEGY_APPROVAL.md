# Host strategy approval authority

## Status

Implemented as a host-only HMAC grant issuer/verifier. It is not exposed as a model tool and does not activate a strategy by itself. `SQLiteStrategyStore` remains responsible for principal scoping, one-use grant consumption, generation compare-and-swap, target config/evaluation binding, and append-only activation history.

## Composition

Construct `HostStrategyApprovalAuthority` only in trusted host startup code. Supply:

- A host-held `ApprovalMacProvider` (prefer a non-exportable secret-manager/KMS/HSM adapter; the existing `HmacApprovalKeyRing` is suitable for local tests).
- An authenticator that derives both principal and approver identity from a trusted credential. It must not trust a principal or approver string from model input.
- An authorization callback that returns the literal boolean `True` only when the exact requested transition is permitted.

Pass `authority.verify` as the strategy store's `approval_verifier` callback. Keep the authority object and its credential path outside the model/tool registry.

## Cryptographic binding

The versioned canonical HMAC payload binds the key ID, grant ID, principal, strategy class/ID/version, evaluation fingerprint, config fingerprint, expected active generation, action, issue/expiry timestamps, and authenticated approver. The signature string carries the key ID so retained verification keys can validate grants across key rotation. Unknown keys, malformed tags, callback errors, and non-boolean authorization results fail closed.

The grant lifetime is host-bounded to at most 900 seconds and defaults to 300 seconds. The store independently checks timestamps and consumes each grant ID once. This authority does not replace the store's one-use check.

## Important limits

- A valid HMAC proves that this host authority signed the exact grant. It does not prove the evidence is genuine or that a statistical assessment is correct.
- A production host must still authenticate evidence manifests, classify task families, independently revalidate the promotion assessment, enforce the 5% canary router, monitor hard gates, and implement automatic rollback before any autonomous live activation.
- No live strategy activation, routing, automatic rollout, permission change, provider call, or model-weight modification is performed by this module.
