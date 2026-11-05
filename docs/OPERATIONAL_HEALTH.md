# Operational health model

Capri Doctor reports local repository health, not general system or production health.

## Health states

- `healthy`: the component's required local observation passed.
- `degraded`: an observed check failed, or a dependency is degraded.
- `unavailable`: an observation explicitly reports that a component cannot be reached or used; this is distinct from a failed assertion.
- `unknown`: no observation exists. Unknown is never treated as healthy.

## Dependency propagation

The current graph covers the Python environment, repository structure, CI workflow, action pinning, CI permissions, recovery-branch CI coverage, and an aggregate developer baseline. Recovery coverage is checked separately under the top-level `push` and `pull_request` event mappings; unrelated `branches` lists elsewhere in the workflow do not count. The checker supports explicit inline and block branch lists and fails closed when those filters are missing or use unsupported YAML constructs. It is a deliberately narrow syntax check, not a general YAML parser. A component inherits the most severe state among its own observation and its dependencies.

Each component includes a stable ID, dependency IDs, observation timestamp, and evidence reference to the diagnostic check when one exists. The aggregate baseline has no direct check; it derives its state from dependencies.

## Scope and limitations

The graph is deliberately limited to local static repository checks. It does not claim to monitor deployed services, providers, credentials, runtime sessions, Notion, GitHub availability, or user data. A successful local report is not a production-readiness or security certification.

Use:

```bash
python -m capri_core doctor
python -m capri_core doctor --json
```

The JSON output includes `health.schema_version`, `health.scope`, `health.status`, `health.summary`, and `health.components`.
