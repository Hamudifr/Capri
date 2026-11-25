# Contributing to Capri

Thanks for helping improve Capri. Keep changes small, evidence-backed, secure by default, and easy to review.

## Project boundaries

Capri is an evolving agent-runtime project, not a production-ready multi-tenant service or a sandbox. The host application remains responsible for identity-provider integration, current resource-level authorization, secret custody, provider budgets, process supervision, and deployment.

Important invariants:

- Model output, retrieved memory, Notion records, and knowledge-graph results are untrusted data. They never grant identity, permission, policy, approval, or tool authority.
- Principal-owned sessions and tasks must remain owner-scoped. Do not expose unscoped store methods to untrusted callers.
- Principal task handlers must use the explicit principal-handler registry and re-check resource authorization at the side-effect boundary.
- Unknown handler failures, invalid results, and expired running leases are uncertain outcomes. Quarantine them; do not automatically replay them.
- Raise `RetryableTaskError` only when the handler can guarantee that no external side effect occurred. `fail_step()` is nonretryable by default.
- Keep optional live integrations opt-in. Ordinary tests must not require network access, paid services, API keys, or user secrets.

## Development setup

Python 3.15.x is the only supported runtime. CI runs one Python version, 3.15, rather than a multi-version matrix.

```bash
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install --upgrade pip
python -m pip install --no-deps .
```

Run the same core checks used by CI:

```bash
python -m compileall -q capri_core capri_runtime tests
capri doctor --json
python -m unittest discover -s tests -v
```

The optional live Notion REST smoke test is disabled by default. Do not add credentials to test fixtures, source files, logs, or pull-request descriptions.

## Engineering standards

- Prefer standard-library implementations unless an external dependency has a clear, documented benefit.
- Validate exact input types and bounds at trust boundaries; reject malformed or ambiguous data.
- Use parameterized SQL, explicit transactions, owner-scoped APIs, and fail-closed filesystem operations.
- Treat SQLite backups as plaintext unless an encryption layer is explicitly configured by the host. Preserve no-overwrite publication and restore validation.
- Add regression tests for every bug fix, especially authorization failures, stale claims, uncertain side effects, malformed inputs, backup corruption, and path traversal.
- Update the relevant documentation whenever behavior, security boundaries, configuration, or operational procedures change.
- Do not silently broaden permissions, introduce background execution, or add live external calls.

## Branches, commits, and pull requests

1. Branch from the current `main`.
2. Keep each pull request focused on one coherent change. Avoid duplicate or unnecessarily stacked pull requests.
3. Use draft status while work is incomplete. Mark ready only when the diff, tests, and documentation are reviewable.
4. Use descriptive Conventional Commit subjects, for example `feat:`, `fix:`, `security:`, `test:`, `docs:`, `ci:`, or `refactor:`. Prefer imperative wording and explain the user-visible or technical outcome.
5. Never force-push or rewrite shared history on `main`. Preserve historical branches when their commits provide useful provenance.
6. Before merging, verify the exact pull-request head has green CI, review the changed-file list, and confirm no unrelated changes are included.
7. Prefer squash merges for focused integration pull requests so `main` has a readable, outcome-oriented history.

## Licensing

This repository currently has no `LICENSE` file. Public visibility does not itself grant permission to reuse or redistribute the code. Do not add third-party code or assume an open-source license; ask the repository owner to clarify licensing before reuse or redistribution.
