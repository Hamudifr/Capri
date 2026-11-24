# Capri

**A research and execution-assistance runtime for building reliable, evidence-driven AI workflows.**

Capri is an experimental, provider-neutral Python runtime with durable state, bounded orchestration, permissioned tool execution, project memory, and optional model-provider integrations. It is designed to make delegated work inspectable and recoverable, not to hide uncertainty behind an autonomous-agent label.

[Repository](https://github.com/Hamudifr/Capri) · [Capability roadmap](docs/CAPABILITY_ROADMAP.md) · [Security review](docs/SECURITY_REVIEW.md) · [Operating model](docs/OPERATING_MODEL.md)

---

## What Capri provides

- **Bounded orchestration:** structured model/tool rounds with explicit limits on messages, results, and transcript size.
- **Permissioned execution:** tool proposals pass through trusted host authority, argument validation, optional approvals, and audit recording before handlers run.
- **Durable state:** SQLite-backed sessions, task plans, worker leases, checkpoints, and security records.
- **Project memory:** bounded local memory, a Notion REST adapter, retention and provenance rules, and a separate untrusted-memory context boundary.
- **Provider integration:** an optional standard-library OpenAI Responses API adapter. Provider calls are explicit and require host-supplied configuration.
- **Evidence and recovery:** append-only evaluation records, integrity checks, operational diagnostics, and documented backup/recovery procedures.
- **Research components:** an experimental Rust CCEL implementation, kept distinct from the Python orchestration runtime.

These are reusable engineering components. Their presence does not mean Capri is deployed as a continuously running service or that every host-side integration is complete.

## Quick start

Capri supports Python 3.11 and newer. The Python package declares no runtime dependencies.

Install from a checkout:

```bash
python -m pip install .
```

Run the read-only diagnostic:

```bash
capri doctor
capri doctor --json
```

Run the Python test suite:

```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
```

The optional Rust research crate has its own toolchain and checks:

```bash
cargo fmt --manifest-path rust/ccel-core/Cargo.toml --all -- --check
cargo clippy --manifest-path rust/ccel-core/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path rust/ccel-core/Cargo.toml
```

See the workflow definitions in [`.github/workflows/`](.github/workflows/) for the CI checks. The optional live Notion smoke test is disabled unless its host-side configuration is explicitly enabled.

## Architecture at a glance

| Area | Location | Responsibility |
| --- | --- | --- |
| Core records and integrity | `capri_core/` | Immutable records, validation, learning/evaluation primitives, and the diagnostic CLI |
| Runtime and orchestration | `capri_runtime/` | Sessions, model adapters, tool orchestration, execution, tasks, approvals, memory, and SQLite stores |
| Tests | `tests/` | Offline contract, regression, security-boundary, and runtime tests |
| Documentation | `docs/` | Architecture, operating rules, security assumptions, integration contracts, and recovery procedures |
| Rust research | `rust/ccel-core/` | Experimental bounded synthesis and causal-compression research |
| Benchmarks | `benchmarks/` | Reproducible, scoped experiments; results are not generalized beyond their measured workloads |

The intended trust flow is:

1. The host authenticates the caller and resolves current authority.
2. The model adapter proposes structured tool calls; model output is not authority.
3. Capri validates the request and routes it through the trusted execution boundary.
4. The host supplies any required approval and resource-level authorization.
5. Capri records bounded outcomes and audit evidence; uncertain side effects remain uncertain and must not be blindly replayed.

The host remains responsible for identity-provider integration, secret custody, resource ACLs, provider budgets, scheduling, process supervision, and deployment.

## Security and operational boundaries

Capri is an **engineering prototype**, not a production-ready multi-tenant service, sandbox, identity provider, or hosted agent.

- Keep credentials and signing keys in host-managed secret storage. Never commit them.
- Treat model output, retrieved memory, external documents, and tool results as untrusted data.
- Do not expose lower-level execution primitives directly to untrusted callers; expose a narrowly configured host facade.
- A successful tool call is not proof that an external side effect happened exactly once. Hosts must use idempotency at the side-effect boundary and reconcile uncertain outcomes.
- SQLite backups are private snapshots, not encryption. Hosts must provide protected storage, retention, off-site backup, and restore drills.
- Live provider requests and live Notion REST tests are opt-in. Offline tests do not establish live-provider behavior or end-to-end prompt-injection resistance.
- Capri does not run in the background between sessions unless an embedding host explicitly starts and supervises it.

Read [`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md), [`docs/TOOL_EXECUTION.md`](docs/TOOL_EXECUTION.md), and [`docs/HOST_RUNTIME.md`](docs/HOST_RUNTIME.md) before integrating consequential tools.

## Project direction

The capability roadmap separates implemented foundations from work still required for reliable autonomous operations and evidence-based adaptation.

- [Capability roadmap](docs/CAPABILITY_ROADMAP.md)
- [Runtime architecture](docs/RUNTIME_CORE.md)
- [Host runtime contract](docs/HOST_RUNTIME.md)
- [Task execution semantics](docs/TASK_EXECUTION.md)
- [Memory contract](docs/MEMORY_STORE.md)
- [Notion memory adapter](docs/NOTION_MEMORY_ADAPTER.md)
- [OpenAI Responses adapter](docs/OPENAI_RESPONSES_ADAPTER.md)
- [Backup and recovery operations](docs/LEDGER_OPERATIONS.md)

A roadmap item is not a shipped capability. Treat a feature as implemented only when its code, tests, documentation, and relevant integration evidence agree.

## Engineering standards

Changes should be small enough to review, tested at the exact proposed commit, and explicit about their trust boundaries.

- Prefer standard-library implementations unless a dependency has a clear, measured benefit.
- Preserve useful history; do not rewrite published commits to make the graph look cleaner.
- Add regression tests for corrected behavior, especially around authorization, persistence, retries, and malformed inputs.
- Keep CI permissions minimal and pin third-party Actions to immutable commit SHAs.
- Document operational assumptions and distinguish offline tests, CI verification, live integration, and independent review.
- Use benchmarks to answer a specific question; do not turn one workload into a universal performance claim.

## Project maturity

Capri is under active development. The repository contains useful runtime and security primitives, but production deployment still requires host-specific authentication and authorization, complete resource isolation, hard provider budgets, operational observability, supervised lifecycle management, protected secret storage, and tested recovery procedures.

Contributions and experiments should preserve this distinction between what exists, what has passed automated checks, and what remains a proposal.
