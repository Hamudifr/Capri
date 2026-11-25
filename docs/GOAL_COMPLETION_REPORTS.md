# Goal completion and evidence reports

`CapriHostRuntime.get_goal_report(credential, goal_id)` returns a stable, owner-scoped `GoalCompletionReport`. It is a read-only view; it does not execute tools, reconcile tasks, accept goals, or change lifecycle state.

## Report contents

The JSON-safe `as_dict()` output includes:
- goal outcome, state, version and acceptance criteria;
- overall acceptance status and completion status;
- next action and whether owner action is required;
- linked task state, current step, total/completed step counts, current-step attempts and sanitized failure code;
- append-only goal evidence references and goal/task event histories.

Raw task results, tool arguments, provider outputs, and goal constraints are deliberately omitted. Task-step result evidence is represented by its persisted SHA-256 reference. Owner-supplied acceptance evidence references are visible only through the authenticated owner's report and must be treated as data, not automatically opened or executed.

## Status semantics

| Completion status | Meaning | Next action |
|---|---|---|
| `not_started` | No task is linked yet | None |
| `in_progress` | A linked task is queued, waiting, or running | Execution continues |
| `activation_pending` | A linked task is still blocked after a recoverable interruption | Host recovery |
| `reconciliation_pending` | The task is terminal but the goal has not yet been reconciled | Host reconciliation |
| `awaiting_owner_acceptance` | Task execution succeeded; the owner has not accepted the outcome | Explicit owner acceptance |
| `accepted` | The owner explicitly accepted and the goal is succeeded | None |
| `rejected` | The owner explicitly rejected the outcome | None |
| `partial` | The task failed after one or more steps completed | Owner review |
| `failed` | The task failed without completed steps | Owner review |
| `uncertain` | An external side effect may have occurred; state is quarantined | Owner/host reconciliation |
| `cancellation_pending` | Cancellation has been requested but is not final | Cancellation reconciliation |
| `cancelled` | Cancellation is complete | None |
| `paused` | The goal is paused | Owner resumes or cancels |
| `inconsistent` | A succeeded goal lacks acceptance evidence | Owner review |

Acceptance is an overall owner decision. The report lists the criteria but does not claim to evaluate each criterion independently. Only the explicit owner verification path can mark a linked goal successful.

## Consistency and access

The goal and task stores are separate SQLite databases, so report construction is not a cross-database transaction. The coordinator reads both records and their histories, then re-reads the records. If either changes during construction, it raises `GoalConflictError`; callers should retry rather than display a mixed snapshot.

The host authenticates the credential before the owner-scoped goal/task reads. A foreign principal receives the same not-found behavior as other owner-scoped reads. The report method is read-only and requires both goal and task stores, but does not require a running worker.

No raw execution output is included. Evidence references and event histories are still owner data; do not expose reports to other principals.
