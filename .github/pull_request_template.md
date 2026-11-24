## Summary

What changes, and why?

## Scope and compatibility

- Affected components:
- User-visible or API behavior:
- Migration, compatibility, or rollback considerations:

## Verification

- [ ] Exact pull-request head passes CI.
- [ ] Relevant regression tests were added or updated.
- [ ] Package installation, CLI, and Capri Doctor checks pass where relevant.
- [ ] Optional live integrations remain disabled unless explicitly required.

## Security and data

- [ ] Authentication, principal ownership, and resource authorization boundaries were reviewed.
- [ ] Model output and retrieved context remain untrusted.
- [ ] External side effects are idempotent or have a documented uncertainty/reconciliation path.
- [ ] No uncertain outcome is automatically retried.
- [ ] No secrets, personal data, or unnecessary external calls were introduced.
- [ ] Backup, retention, and filesystem implications were considered.

## Documentation and operations

- [ ] Relevant documentation and examples are updated.
- [ ] Operational risks, monitoring, and recovery behavior are documented.
- [ ] The changed-file list contains no unrelated or generated artifacts.
