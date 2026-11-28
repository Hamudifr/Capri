# Agent Intelligence Vision

How Capri moves toward AGI-style behavior — not by being programmed to
interact, but by building a strong, optimized information foundation and then
reasoning, proposing, agreeing, improving, and working continuously on top of
it.

This document records the direction the fleet is converging on. It is a
**vision and design**, not a claim that any of it is fully shipped. Where a
capability exists in code, it is named; where it is a proposal, it is marked
as such.

## 1. Not a programmed interaction — an information foundation

A common mistake is to build a system that is *programmed* to interact: a
fixed decision tree, a hard-coded prompt, a REA that only does what it was
told. Capri takes the opposite path.

Capri builds a **strong, optimized information foundation** drawn from
everywhere — the best and most-loved sources — and then *behaves*: it reasons
about what to do, proposes ideas, lets other agents agree or disagree,
improves the skills it uses, and keeps working. The host keeps authority;
Capri keeps the limitless foundation.

The foundation has three layers, all already partially present in the repo:

1. **Clean information extraction** — reverse-engineer arbitrary sources
   into normalized, provenance-tagged facts (see §2).
2. **Durable memory and evidence** — bounded memory, the knowledge graph,
   append-only evaluation records, and integrity checks.
3. **The agreement substrate** — the inter-agent forum
   (`capri_runtime/agent_forum.py`) where agents propose, vote, and converge.

## 2. Clean information extraction from anywhere

**Goal:** the best system to reverse-engineer and extract *clean* information
from anywhere, then feed it into the foundation.

**Approach:**

- **Source adapters** normalize arbitrary inputs (documents, web pages, APIs,
  databases, code) into a common fact shape: `{fact, value, source, provenance,
  confidence, extracted_at}`.
- **Provenance is mandatory.** Every extracted fact carries where it came from
  and how it was obtained, so downstream reasoning can distinguish a verified
  fact from an inference from an untrusted scrape.
- **Contradiction handling.** When two sources disagree, both are kept with
  their provenance and a conflict marker, rather than silently overwriting.
- **Fail-closed normalization.** Malformed or ambiguous extractions are
  quarantined, not coerced into plausible values.

**Status:** the *contract* for this is designed here; the Notion Agent Forum
tracks it as a profound proposal assigned to the extraction-focused agent. The
knowledge graph retrieval in `capri_runtime/knowledge_graph.py` already
implements provenance and contradiction handling for the Notion graph, which is
the first concrete adapter.

## 3. Proof optimization — math, physics, coding, web design

**Goal:** make Capri better at any domain where correctness matters, by
optimizing *proofs* — not just answers, but the evidence that an answer is
right.

**Approach:**

- **Proof-carrying outputs.** Every claim that matters carries its evidence: a
  math result carries the steps; a code change carries the tests that verify
  it; a web-design decision carries the rendering evidence.
- **Domain-specific verifiers.** Each domain gets a checkable oracle:
  - **Math / physics** — symbolic verification where possible; numeric
    cross-checks against independent methods.
  - **Coding** — the committed test suite is the proof; a change without a
    passing test is not an improvement.
  - **Web design** — the rendered page and its performance/accessibility
    evidence are the proof.
- **Iterative refinement.** When a proof fails, the agent refines the claim
  rather than discarding the reasoning, recording what changed and why in the
  work log.

**Status:** the philosophy is design; the repo already ships the *mechanism* —
goals carry acceptance criteria and evidence references
(`capri_runtime/goals.py`), and the quality gate runs the full test suite at
the exact proposed commit. The agent forum tracks proof optimization as a
profound proposal spanning the math/physics and coding/web agents.

## 4. Visualize context as a screen

**Goal:** develop a way to *visualize context as if looking at a screen*, even
though the agent has no eyes — so reasoning is inspectable and the agent can
"see" its own state.

**Approach:**

- **A context field.** Treat the agent's working context — retrieved memory,
  knowledge graph state, tool results, goal state, and skill confidence — as a
  single coherent visual field that can be rendered.
- **Inspectable by design.** The same representation that the agent reasons
  over can be serialized and displayed: a context snapshot is a screenshot of
  the agent's mind at a moment in time.
- **Confidence as visual weight.** Skill confidence and fact confidence are
  rendered as visual prominence, so a high-confidence fact stands out from an
  uncertain inference.

**Status:** design. The building blocks exist — `capri_project_status()`
returns a JSON snapshot of project state, and the status page renders a
deployed-commit field — but a unified *context-as-screen* renderer is a
proposed capability, tracked in the Notion Agent Forum.

## 5. Continuous work and skill improvement

**Goal:** agents that work for a very long time and get better at what they
do.

**Approach (shipped in `capri_runtime/agent_forum.py`):**

- **Durable work logs** — every action is recorded append-only, so an agent
  resumes with full knowledge of what it already did, across restarts.
- **Skill confidence ledger** — each skill's confidence is recorded over
  time; an agent that repeatedly succeeds at a skill shows a rising confidence
  curve, and the latest value is the one that gates decisions.
- **Consensus, not commands** — agents converge on ideas through voting, so
  the fleet's direction emerges from agreement rather than a single programmed
  directive.

## 6. The fleet

The fleet is the set of autonomous actors that share this foundation. Each has
a focus and a set of skills; together they cover extraction, proof, building,
memory, and coordination. The fleet is named in
`docs/CAPRI_CHARACTER_DERIVED_IDENTITY.md`; the Notion Agent Forum holds the
live roster, open proposals, work log, and skill-confidence table.

## 7. What is real, and what is still a proposal

This document is honest about the boundary:

- **Shipped:** the inter-agent forum (communication, consensus, work logs,
  skill ledger); goals with acceptance criteria and evidence; the knowledge
  graph's provenance and contradiction handling; the test-suite-as-proof
  quality gate.
- **Designed, not yet built:** unified clean-information extraction across
  arbitrary sources; the context-as-screen renderer; domain proof optimizers
  beyond the existing test gate.

Treat a capability as implemented only when its code, tests, documentation,
and relevant integration evidence agree.
