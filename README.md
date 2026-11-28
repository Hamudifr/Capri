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

<p>
<a href="#quick-start"><span style="color:#22d3ee;">▶ Get started</span></a>
&nbsp;·&nbsp;
<a href="#what-capri-provides"><span style="color:#7aa2ff;">✦ What it gives you</span></a>
&nbsp;·&nbsp;
<a href="#see-it-in-action"><span style="color:#9d7bff;">⌨ See it in action</span></a>
&nbsp;·&nbsp;
<a href="docs/CAPABILITY_ROADMAP.md"><span style="color:#5b8cff;">↗ Roadmap</span></a>
</p>

[![Python quality](https://github.com/Hamudifr/Capri/actions/workflows/quality.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/quality.yml)
[![Rust quality](https://github.com/Hamudifr/Capri/actions/workflows/rust.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/rust.yml)
[![CodeQL](https://github.com/Hamudifr/Capri/actions/workflows/codeql.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/codeql.yml)
[![Keep-alive](https://github.com/Hamudifr/Capri/actions/workflows/keep-alive.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/keep-alive.yml)
[![Workflow lint](https://github.com/Hamudifr/Capri/actions/workflows/workflow-lint.yml/badge.svg)](https://github.com/Hamudifr/Capri/actions/workflows/workflow-lint.yml)
[![Python](https://img.shields.io/badge/python-3.15-5b8cff?logo=python&logoColor=white)](docs/PYTHON_SUPPORT_POLICY.md)
[![Runtime deps](https://img.shields.io/badge/runtime%20deps-stdlib%20only-22d3ee?logo=python&logoColor=white)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-offline%20contracts-9d7bff?logo=unittest&logoColor=white)](tests/)

</div>

<div align="center">

<span style="color:#a9b4d4;">1152 tests</span>
<span style="color:#5b8cff;">·</span>
<span style="color:#a9b4d4;">55 docs</span>
<span style="color:#5b8cff;">·</span>
<span style="color:#a9b4d4;">9 CI workflows</span>
<span style="color:#5b8cff;">·</span>
<span style="color:#a9b4d4;">stdlib-only</span>
<span style="color:#5b8cff;">·</span>
<span style="color:#a9b4d4;">provider-neutral</span>

</div>

<br/>

---

## <span style="color:#7aa2ff;">✨ Profile</span>

> <span style="color:#c9d3f5;">Capri is the <b style="color:#22d3ee;">strongest</b> substrate for delegated agent work — it doesn't hide uncertainty behind an autonomous-agent label. It makes every step <b style="color:#5b8cff;">inspectable</b>, every outcome <b style="color:#5b8cff;">recoverable</b>, and every decision <b style="color:#9d7bff;">evidence-bound</b>. The host keeps the authority; Capri provides the limitless foundation.</span>

Capri is an experimental, provider-neutral Python runtime with durable state, bounded
orchestration, permissioned tool execution, project memory, and optional model-provider
integrations. It ships as the `capri` CLI and runs under a host that owns identity, secrets,
budgets, and lifecycle — Capri provides the trustworthy substrate, the host keeps the power.

<div align="center">

**[Repository](https://github.com/Hamudifr/Capri) · [Capability roadmap](docs/CAPABILITY_ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Operating model](docs/OPERATING_MODEL.md)**

</div>

---

## <span style="color:#22d3ee;">📑 Table of contents</span>

- [What Capri provides](#what-capri-provides)
- [Quick start](#quick-start)
- [See it in action](#see-it-in-action)
- [Architecture at a glance](#architecture-at-a-glance)
- [Choose your path](#choose-your-path)
- [Security and operational boundaries](#security-and-operational-boundaries)
- [Project direction](#project-direction)
- [Engineering standards](#engineering-standards)
- [FAQ](#faq)
- [Project maturity](#project-maturity)

---

## <span style="color:#5b8cff;">✦ What Capri provides</span>

Every capability is built around one idea: **an agent's work should be provable, not just plausible.** These are reusable engineering components — their presence does not mean Capri is deployed as a continuously running service or that every host-side integration is complete.

| 🎯 Capability | What it gives you |
| --- | --- |
| 🌀 **Bounded orchestration** | Structured model/tool rounds with explicit limits on messages, results, and transcript size. No runaway loops. |
| 🛡️ **Permissioned execution** | Tool proposals pass through trusted host authority, argument validation, optional approvals, and audit recording before handlers run. Model output is never authority. |
| 💾 **Durable state** | Principal-owned SQLite sessions and task plans, worker leases, step checkpoints, and security records. Uncertain outcomes are quarantined, never blindly replayed. |
| 🧠 **Project memory** | Bounded local memory, a Notion REST adapter, retention and provenance rules, and a separate untrusted-memory context boundary. |
| 🕸️ **Evidence-aware knowledge graph** | Read-only Notion Neurons/Synapses retrieval with deterministic lexical ranking, bounded traversal, provenance, and contradiction handling. Retrieved content stays untrusted data. |
| 🔌 **Provider integration** | An optional standard-library OpenAI Responses API adapter. Provider calls are explicit and require host-supplied configuration. |
| 📜 **Evidence and recovery** | Append-only evaluation records, integrity checks, operational diagnostics, and documented backup/recovery procedures. |
| 🧠 **Inter-agent forum** | A consensus store where agents propose ideas, vote, agree or supersede, and log skill improvements — communication, not just execution. |
| 🔬 **Research components** | An experimental Rust CCEL implementation, kept distinct from the Python orchestration runtime. |

### <span style="color:#22d3ee;">Why teams reach for it</span>

- **Inspectable, not opaque** — every step, vote, and side effect is recorded and replayable.
- **Fails safely** — uncertainty is quarantined; nothing is blindly replayed.
- **Host stays in control** — identity, secrets, budgets, and lifecycle stay with the host, not the model.
- **No lock-in** — provider-neutral, standard-library-only, read-only retrieval.

---

## <span style="color:#9d7bff;">🚀 Quick start</span>

Capri currently supports **Python 3.15.x only**. Older and newer minor versions are
intentionally outside the supported range until the support policy is updated. The Python
package declares **no runtime dependencies**.

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

## <span style="color:#5b8cff;">⌨ See it in action</span>

From install to a verified, skill-validated workspace in four commands — all read-only and
offline by default:

```bash
# 1. Install the runtime (stdlib-only, no runtime dependencies)
python -m pip install .

# 2. Health-check the repository — human-readable report
capri doctor

# 3. Machine-readable report for automation
capri doctor --json

# 4. Validate local Agent Skills without executing them
capri skills validate --root .

# 5. Verify an existing ledger without modifying it
capri verify path/to/ledger.jsonl
```

Each command is **read-only and side-effect-free**. `doctor` reports repository health,
`skills validate` statically checks skill packages, and `verify` confirms ledger integrity
without rewriting it — so you can trust the report even before trusting the runtime.

---

## <span style="color:#7aa2ff;">🏛️ Architecture at a glance</span>

<img src="docs/assets/architecture.jpg" alt="Capri runtime architecture — interconnected pathways" width="65%" />

| Area | Location | Responsibility |
| --- | --- | --- |
| Core records and integrity | `capri_core/` | Immutable records, validation, learning/evaluation primitives, and the diagnostic CLI |
| Runtime and orchestration | `capri_runtime/` | Sessions, model adapters, tool orchestration, execution, tasks, approvals, memory, evidence-aware graph retrieval, inter-agent forum, and SQLite stores |
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

## <span style="color:#9d7bff;">🛤️ Choose your path</span>

<div align="center">

| 🧭 I want to… | 👉 Start here |
| --- | --- |
| **Use Capri** | [Quick start](#quick-start) → [See it in action](#see-it-in-action) |
| **Understand the design** | [Architecture](#architecture-at-a-glance) → [Capability roadmap](docs/CAPABILITY_ROADMAP.md) |
| **Integrate a host** | [Host runtime contract](docs/HOST_RUNTIME.md) → [Tool execution](docs/TOOL_EXECUTION.md) |
| **Contribute** | [Contributing](CONTRIBUTING.md) → [Engineering standards](#engineering-standards) |
| **Report a security issue** | [Security policy](SECURITY.md) → [Security review](docs/SECURITY_REVIEW.md) |

</div>

---

## <span style="color:#9d7bff;">🔒 Security and operational boundaries</span>

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

## <span style="color:#22d3ee;">🧭 Project direction</span>

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

## <span style="color:#5b8cff;">🛠️ Engineering standards</span>

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

## <span style="color:#9d7bff;">❓ FAQ</span>

**Is Capri a hosted agent service?**
No. It is an engineering prototype — a substrate that runs under a host you control. The host
owns identity, secrets, budgets, and lifecycle; Capri owns the trustworthy execution layer.

**Does it require external dependencies?**
No. The Python package declares no runtime dependencies and is standard-library-only. Provider
integrations (OpenAI, Notion) are optional and opt-in.

**What Python version is supported?**
Python 3.15.x only, per the [support policy](docs/PYTHON_SUPPORT_POLICY.md).

**Is Capri production-ready?**
Not yet. It ships useful runtime and security primitives, but production deployment still
requires host-specific authentication, resource isolation, hard budgets, observability, and
tested recovery. See [Project maturity](#project-maturity).

**How do agents communicate?**
Through the inter-agent forum: agents propose ideas, vote, reach consensus, and log skill
improvements — so work is agreed upon and visible, not just executed.

**Are the tests offline?**
Yes. The committed test suite is fully offline; live provider and Notion smoke tests are opt-in
and disabled unless explicitly configured.

---

## <span style="color:#9d7bff;">🌱 Project maturity</span>

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
