<div align="center">

<img src="docs/assets/hero.jpg" alt="Gojo Satoru — Capri, the strongest agent runtime" width="100%" />

<h1>
<span style="color:#5b8cff;">⚡</span> <span style="color:#7aa2ff;">Capri</span>
<span style="color:#9d7bff;">·</span> <span style="color:#22d3ee;">Limitless</span>
</h1>

<p>
<span style="color:#a9b4d4;">A provider-neutral runtime for building reliable, evidence-driven AI workflows —</span><br/>
<span style="color:#e8ecff;"><b>durable state · permissioned execution · bounded orchestration · project memory</b></span>
</p>

[![Python quality](https://github.com/Hamudifr/Capri/actions/workflows/quality.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/quality.yml)
[![Rust quality](https://github.com/Hamudifr/Capri/actions/workflows/rust.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/rust.yml)
[![CodeQL](https://github.com/Hamudifr/Capri/actions/workflows/codeql.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/codeql.yml)
[![Keep-alive](https://github.com/Hamudifr/Capri/actions/workflows/keep-alive.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/keep-alive.yml)
[![Workflow lint](https://github.com/Hamudifr/Capri/actions/workflows/workflow-lint.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/workflow-lint.yml)

</div>

---

## <span style="color:#7aa2ff;">Profile</span>

> <span style="color:#c9d3f5;">Capri is the <b style="color:#22d3ee;">strongest</b> substrate for delegated agent work — it doesn't hide uncertainty behind an autonomous-agent label. It makes every step <b style="color:#5b8cff;">inspectable</b>, every outcome <b style="color:#5b8cff;">recoverable</b>, and every decision <b style="color:#9d7bff;">evidence-bound</b>. The host keeps the authority; Capri provides the limitless foundation.</span>

Capri is an experimental, provider-neutral Python runtime with durable state, bounded
orchestration, permissioned tool execution, project memory, and optional model-provider
integrations. It ships as the `capri` CLI and runs under a host that owns identity, secrets,
budgets, and lifecycle — Capri provides the trustworthy substrate, the host keeps the power.

<div align="center">

**[Repository](https://github.com/Hamudifr/Capri) · [Capability roadmap](docs/CAPABILITY_ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Operating model](docs/OPERATING_MODEL.md)**

</div>

---

## <span style="color:#22d3ee;">Table of contents</span>

- [What Capri provides](#what-capri-provides)
- [Quick start](#quick-start)
- [Architecture at a glance](#architecture-at-a-glance)
- [Security and operational boundaries](#security-and-operational-boundaries)
- [Project direction](#project-direction)
- [Engineering standards](#engineering-standards)
- [Project maturity](#project-maturity)

---

## <span style="color:#5b8cff;">What Capri provides</span>

| Capability | What it gives you |
| --- | --- |
| 🌀 **Bounded orchestration** | Structured model/tool rounds with explicit limits on messages, results, and transcript size. |
| 🛡️ **Permissioned execution** | Tool proposals pass through trusted host authority, argument validation, optional approvals, and audit recording before handlers run. |
| 💾 **Durable state** | Principal-owned SQLite sessions and task plans, worker leases, step checkpoints, and security records. Uncertain outcomes are quarantined, never blindly replayed. |
| 🧠 **Project memory** | Bounded local memory, a Notion REST adapter, retention and provenance rules, and a separate untrusted-memory context boundary. |
| 🕸️ **Evidence-aware knowledge graph** | Read-only Notion Neurons/Synapses retrieval with deterministic lexical ranking, bounded traversal, provenance, and contradiction handling. Retrieved content stays untrusted data. |
| 🔌 **Provider integration** | An optional standard-library OpenAI Responses API adapter. Provider calls are explicit and require host-supplied configuration. |
| 📜 **Evidence and recovery** | Append-only evaluation records, integrity checks, operational diagnostics, and documented backup/recovery procedures. |
| 🔬 **Research components** | An experimental Rust CCEL implementation, kept distinct from the Python orchestration runtime. |

These are reusable engineering components. Their presence does not mean Capri is deployed as a
continuously running service or that every host-side integration is complete.

---

## <span style="color:#9d7bff;">Quick start</span>

Capri currently supports **Python 3.15.x only**. Older and newer minor versions are
intentionally outside the supported range until the support policy is updated. The Python
package declares no runtime dependencies.

### <span style="color:#22d3ee;">Install</span>

```bash
python -m pip install .
```

### <span style="color:#22d3ee;">Verify</span>

```bash
capri doctor
capri doctor --json
```

Validate repository-local Agent Skills packages:

```bash
capri skills validate --root .
```

See [Skill authoring and validation](docs/SKILL_AUTHORING.md) for the format, limits, and
workflow. The validator is static and never executes skill instructions or scripts.

### <span style="color:#22d3ee;">Test</span>

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

See the workflow definitions in [`.github/workflows/`](.github/workflows/) for the CI checks.
The optional live Notion smoke test is disabled unless its host-side configuration is
explicitly enabled.

---

## <span style="color:#7aa2ff;">Architecture at a glance</span>

<img src="docs/assets/architecture.jpg" alt="Capri runtime architecture — interconnected pathways" width="65%" />

| Area | Location | Responsibility |
| --- | --- | --- |
| Core records and integrity | `capri_core/` | Immutable records, validation, learning/evaluation primitives, and the diagnostic CLI |
| Runtime and orchestration | `capri_runtime/` | Sessions, model adapters, tool orchestration, execution, tasks, approvals, memory, evidence-aware graph retrieval, and SQLite stores |
| Tests | `tests/` | Offline contract, regression, security-boundary, and runtime tests |
| Documentation | `docs/` | Architecture, operating rules, security assumptions, integration contracts, and recovery procedures |
| Rust research | `rust/ccel-core/` | Experimental bounded synthesis and causal-compression research |
| Benchmarks | `benchmarks/` | Reproducible, scoped experiments; results are not generalized beyond their measured workloads |

### <span style="color:#5b8cff;">Trust flow</span>

1. The host authenticates the caller and resolves current authority.
2. The model adapter proposes structured tool calls; **model output is not authority**.
3. Capri validates the request and routes it through the trusted execution boundary.
4. The host supplies any required approval and resource-level authorization.
5. Capri records bounded outcomes and audit evidence; uncertain side effects remain uncertain
   and must not be blindly replayed.

The host remains responsible for identity-provider integration, secret custody, resource ACLs,
provider budgets, scheduling, process supervision, and deployment.

---

## <span style="color:#9d7bff;">Security and operational boundaries</span>

Capri is an **engineering prototype**, not a production-ready multi-tenant service, sandbox,
identity provider, or hosted agent.

- Keep credentials and signing keys in host-managed secret storage. Never commit them.
- Treat model output, retrieved memory, external documents, and tool results as untrusted data.
- Do not expose lower-level execution primitives directly to untrusted callers; expose a
  narrowly configured host facade.
- A successful tool call is not proof that an external side effect happened exactly once. Hosts
  must use idempotency at the side-effect boundary and reconcile uncertain outcomes.
- SQLite backups are private snapshots, not encryption. Hosts must provide protected storage,
  retention, off-site backup, and restore drills.
- Live provider requests and live Notion REST tests are opt-in. Offline tests do not establish
  live-provider behavior or end-to-end prompt-injection resistance.
- Capri does not run in the background between sessions unless an embedding host explicitly
  starts and supervises it.

Read [`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md),
[`docs/TOOL_EXECUTION.md`](docs/TOOL_EXECUTION.md), and
[`docs/HOST_RUNTIME.md`](docs/HOST_RUNTIME.md) before integrating consequential tools.

---

## <span style="color:#22d3ee;">Project direction</span>

The capability roadmap separates implemented foundations from work still required for reliable
autonomous operations and evidence-based adaptation.

**Foundations**

- [Capability roadmap](docs/CAPABILITY_ROADMAP.md)
- [Runtime architecture](docs/RUNTIME_CORE.md)
- [Host runtime contract](docs/HOST_RUNTIME.md)
- [Task execution semantics](docs/TASK_EXECUTION.md)

**Memory and retrieval**

- [Memory contract](docs/MEMORY_STORE.md)
- [Knowledge graph runtime](docs/KNOWLEDGE_GRAPH_RUNTIME.md)
- [Notion memory adapter](docs/NOTION_MEMORY_ADAPTER.md)

**Integrations**

- [OpenAI Responses adapter](docs/OPENAI_RESPONSES_ADAPTER.md)

**Operations and measurement**

- [SQLite persistence profiling](docs/PERSISTENCE_BENCHMARKS.md)
- [Runtime performance baseline](docs/RUNTIME_BENCHMARKS.md)
- [Backup and recovery operations](docs/LEDGER_OPERATIONS.md)
- [Free-plan operations (Vercel + Supabase)](docs/FREE_PLAN_OPTIMIZATION.md)

**Contributing**

- [Contributing and development workflow](CONTRIBUTING.md)
- [Security reporting policy](SECURITY.md)

A roadmap item is not a shipped capability. Treat a feature as implemented only when its code,
tests, documentation, and relevant integration evidence agree.

---

## <span style="color:#5b8cff;">Engineering standards</span>

Changes should be small enough to review, tested at the exact proposed commit, and explicit
about their trust boundaries.

- Prefer standard-library implementations unless a dependency has a clear, measured benefit.
- Preserve useful history; do not rewrite published commits to make the graph look cleaner.
- Add regression tests for corrected behavior, especially around authorization, persistence,
  retries, and malformed inputs.
- Keep CI permissions minimal and pin third-party Actions to immutable commit SHAs.
- Document operational assumptions and distinguish offline tests, CI verification, live
  integration, and independent review.
- Use benchmarks to answer a specific question; do not turn one workload into a universal
  performance claim.

---

## <span style="color:#9d7bff;">Project maturity</span>

Capri is under active development. The repository contains useful runtime and security
primitives, but production deployment still requires host-specific authentication and
authorization, complete resource isolation, hard provider budgets, operational observability,
supervised lifecycle management, protected secret storage, and tested recovery procedures.

Contributions and experiments should preserve this distinction between what exists, what has
passed automated checks, and what remains a proposal.

---

<div align="center">

<span style="color:#7aa2ff;">⚡</span> <span style="color:#a9b4d4;">Capri</span> <span style="color:#9d7bff;">—</span> <span style="color:#22d3ee;">the limitless foundation for inspectable, evidence-driven agent workflows.</span>

<br/><br/>

[Capability roadmap](docs/CAPABILITY_ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Python support policy](docs/PYTHON_SUPPORT_POLICY.md)

</div>
