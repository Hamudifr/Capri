# Execution budgets

Capri's optional `SQLiteBudgetStore` enforces conservative per-principal quotas before provider, tool, and durable task-step execution. Pass one shared store to `CapriHostRuntime(budget_store=...)`; the host wires that same ledger into the orchestrator, tool executor, and task engine. Supplying different ledgers is rejected.

## Default policy

The default policy is persisted in the budget database so a restart cannot silently change the active window or reset limits.

| Dimension | Default per principal per 24-hour UTC window |
|---|---:|
| Provider calls | 40 |
| Provider input bytes | 2 MiB |
| Tool handler calls | 80 |
| Task steps | 100 |
| Task input bytes | 2 MiB |

A trusted host can set a principal-specific `BudgetPolicy` with `set_policy_for_principal`. Policies can be tightened or raised deliberately. The host exposes only the authenticated principal's current usage through `get_budget_usage`.

## Enforcement behavior

- **Provider:** reserve one provider call and the serialized transcript/tool-schema/memory/knowledge input-byte measure before every adapter invocation, including each tool-loop round. A denied reservation prevents the adapter call.
- **Tools:** reserve one tool call after permission/approval checks and before handler dispatch. A denied reservation prevents the handler from running.
- **Tasks:** reserve one task step and its JSON input bytes before invoking a principal handler. If the current window is exhausted, the claim moves to `budget_wait` until the next window. It does not consume a task attempt. An unbudgeted worker cannot claim `budget_wait` tasks. If one input alone exceeds the policy maximum, the task fails closed without invoking the handler.
- Reservations are atomic across all requested dimensions, append-only, and charged before execution. Failed or interrupted calls are not refunded, preventing retries from manufacturing free quota.
- The budget database is private SQLite state with integrity checks and validated, no-overwrite backups.

## Measurement limits

These are hard caps on **call counts and the bytes Capri controls**, not a financial meter. The provider input-byte figure counts the serialized conversation, tool schemas, and supplied memory/knowledge context; it is not a claim about exact HTTP wire bytes or provider tokenization. The current provider adapter contract does not expose trustworthy token usage, so this release does not claim exact input/output token or monetary-cost accounting.

Task-step quotas do not forcibly preempt a synchronous handler that is already running. A Python thread cannot be safely killed while an external side effect may be in progress. Existing leases and uncertain-outcome reconciliation remain the recovery mechanism. Per-handler wall-clock preemption is not part of this slice.

## Deployment requirement

The host must be composed with a persistent private budget database to enable enforcement. If `budget_store` is omitted, legacy unbudgeted composition remains available for compatibility. Production host composition should always provide the shared store and review per-principal policies. No paid provider or external billing API is required.
