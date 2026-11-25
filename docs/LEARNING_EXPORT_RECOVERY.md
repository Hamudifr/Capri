# Learning Engine export recovery: legacy pathless staging records

## Current behavior

Learning Engine export publication registers an export before final publication and stores both `artifact_path` and `staging_path`. Reconciliation validates known artifacts and only removes a staging file when its intended artifact path proves the staging file is a private sibling with the expected name.

A legacy `publishing` row with an empty `artifact_path` is marked `failed`. If it has a non-empty `staging_path`, reconciliation deliberately preserves that path in the registry and leaves the file untouched. The cleanup helper cannot prove that the file belongs to this export without the intended artifact path. Repeated reconciliation remains fail-closed.

This behavior is intentional. A path stored in an old or corrupted database row is not, by itself, authority to unlink or move a filesystem object.

## Safe operator procedure

1. **Stop concurrent export writers** for the affected Learning Engine store. Do not investigate a moving target.
2. **Preserve evidence first.** Take a consistent backup of the SQLite registry and a filesystem-level snapshot of the configured export area using the normal host backup procedure. Keep backup files private.
3. **Identify the registry row by export ID.** Use `LearningStore.get_export_status(export_id)`. Confirm `status == "failed"`, `artifact_path == ""`, and `staging_path` is non-empty. Do not paste raw paths or learning contents into shared tickets or logs.
4. **Inspect without following links.** In the trusted host environment, inspect the candidate with `lstat`, not a call that follows symlinks. Confirm the parent is within the configured export root, the parent and file are owned by the expected service account, the object is a regular file and not a symlink, and its permissions/link count meet the deployment's private-file policy. Do not read or publish the file contents as part of routine inventory.
5. **Stop on any ambiguity.** If the path is outside the export root, contains traversal, is a symlink, is not a regular file, has unexpected ownership or permissions, or cannot be tied to the expected host and export store, leave it untouched and escalate to the repository/service owner.
6. **Do not manually clear `staging_path`.** The current public API has no audited quarantine transition for a pathless legacy row. Clearing the field would erase the pointer to retained evidence. Do not use SQL edits to make reconciliation appear complete.
7. **Do not delete or move the file using a guessed relationship.** A future quarantine tool must establish root containment, object identity, ownership, no-overwrite destination semantics, durable rename/fsync behavior, and an append-only audit record before changing either the filesystem or registry.

## What is and is not verified

- Verified in code: `reconcile_pending_exports()` marks pathless publishing rows failed; it preserves a non-empty staging path when the artifact path is absent.
- Verified in code: `_cleanup_staging_file()` returns false when no artifact path is available and does not unlink the candidate.
- Regression test: `test_pathless_legacy_staging_path_is_retained_for_operator_review` creates a synthetic staging file and confirms the first and repeated reconciliation attempts retain both the file and registry path.
- Not provided: automatic cleanup, automatic quarantine, or a supported operator mutation API for this legacy state.

## Future implementation gate

Do not add automatic deletion. If an operator workflow is later required, design it as a separate explicit quarantine operation with a configured trusted root, no-follow filesystem checks, service-account ownership checks, a private quarantine destination, atomic no-overwrite movement, directory fsync, a durable audit event, and a recoverable registry transition. Add adversarial tests for symlink swaps, traversal, hard links, cross-device moves, destination collisions, concurrent writers, and interrupted operations before enabling it.
