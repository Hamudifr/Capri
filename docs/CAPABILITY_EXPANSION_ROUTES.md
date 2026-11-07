# Capri capability expansion: alternative implementation routes

**Research date:** 2026-11-07  
**Status:** Research completed; two remote-tool integrations are saved in the private plugin. ChatGPT-side MCP handshakes remain pending.

## Executive finding

Do not treat skills as the only way to improve Capri. Use a layered capability model:

1. Skills teach task-specific procedures and quality standards.
2. Remote MCP tools give ChatGPT callable external capabilities.
3. Local MCP tools give desktop/Codex agents access to local processes, files, Git, Python and databases.
4. Public APIs and source registries provide domain data without vendor accounts.
5. Evaluation harnesses test whether a skill/tool actually improves outcomes.

The best route depends on the user's host. Remote MCP servers can be used from ChatGPT when connected as plugins. Local stdio MCP servers require a local runtime and are suitable for desktop/Codex, not an Android-only ChatGPT session.

## Implemented: remote mathematical computation

Updated the existing private **Capri Engineering Lab** plugin to v0.3.0.

- Plugin ID: `plugins_6aef721e946c81918014a2c04ff4476f`
- Release ID: `pluginrel_6aef763b9f1c81919d84ad5952a3c9d1`
- Added Streamable HTTP servers `calculator` and `noodle` in `mcp.json`.
- Added `calculator-computation` and `biomedical-literature-discovery` skills with privacy boundaries and validation procedures.
- Preserved the original seven domain skills and private audience.

### Verification

The endpoint's public health metadata returned:

- `status=ok`
- Server `calculator-mcp-server`, version `0.5.3`
- `transport=http`, `sessionMode=stateless`
- `auth.mode=none`
- MCP tools/resources advertised as available

The upstream project is Apache-2.0: https://github.com/cyanheads/calculator-mcp-server

The upstream README describes a `calculate` tool for numeric evaluation, symbolic simplification and differentiation, with validation, execution timeouts, result-size limits, and read-only stateless behavior.

**Not yet verified:** a ChatGPT-side MCP initialize/list-tools handshake and a live `calculate` invocation. Plugin source read-back confirms the configuration and skill were saved; that is not proof the host has connected successfully.

**Privacy boundary:** this is a third-party public service. Expressions are sent to its operator. Do not send private, confidential, identifying or sensitive data.

## Route A: public remote MCP tools (ChatGPT web)

Use only when the endpoint is verified, HTTPS, no-auth or has an acceptable auth model, has a narrow tool surface, and has a credible source/maintainer.

### Candidate: mathematical computation — integrated

- Project: https://github.com/cyanheads/calculator-mcp-server
- Endpoint: https://calculator.caseyjhand.com/mcp
- Transport: Streamable HTTP
- Auth: none reported by the live health endpoint
- License: Apache-2.0
- Purpose: expression evaluation, simplification, differentiation
- Decision: integrated in Capri Engineering Lab v0.2.0; host-side handshake pending.

### Candidate: biomedical literature graph — integrated, host handshake pending

- Project: https://github.com/helena-bioinformatics/noodle-mcp
- Endpoint: https://api.helena.bio/noodle/v1/mcp
- Transport: Streamable HTTP; official MCP Server Card version 0.2.1 declares `authentication.required=false`.
- Official MCP Registry identity: `io.github.helena-bioinformatics/noodle`, active latest version 0.2.1.
- License: Apache-2.0.
- Scope: read-only public PubMed-derived corpus search, PMID/DOI/PMCID publication lookup, bounded citation and semantic graph exploration, corpus freshness/coverage metadata.
- Added to Capri Engineering Lab v0.3.0 with a dedicated task-first skill.
- Privacy restriction: public, non-sensitive queries and identifiers only; never send patient records or private case data. Graph edges are discovery signals, not causality or clinical evidence. Do not call the unrelated `support_helena` action unless the user explicitly asks.
- Verification: source README, official Server Card, registry record and privacy policy inspected. The endpoint returned HTTP 405 to a GET-style page fetch; this is not an MCP handshake test. ChatGPT-side initialize/list-tools and tool invocation remain pending.

### Candidate: hosted academic bibliography search — do not connect yet

- Project: https://github.com/xeophon/bibtex-mcp
- Advertises public SSE endpoint: https://mcp.florianbrand.de/sse
- License: MIT; README says no authentication.
- Scope: arXiv, DBLP, Semantic Scholar and OpenAlex search with BibTeX generation.
- A fetch attempt reported an SSL error for the public endpoint. Its advertised legacy SSE transport is supported by some clients, but client support is optional.
- Decision: do not connect until endpoint availability, TLS and tool schema are independently verified.

## Route B: local MCP servers (desktop/Codex)

These add actual executable capabilities without a vendor account, but they require a local machine, runtime and installation. They will not run on an Android-only ChatGPT session.

### Academic search

- https://github.com/Moreti2002/polymath-mcp
- MIT-licensed Python MCP server; README advertises 17 public research/data sources without API keys.
- Tools include paper search/deduplication, paper resolution, code search, model/dataset search, trend search, standards search and component datasheets.
- Requires Python 3.11+. Optional email improves Unpaywall/Crossref access; core sources remain keyless.
- Repository currently has very low adoption and was created recently. Treat as experimental; inspect source, test provider failures and verify license before installing.

### Unified academic search

- https://github.com/raktim-mondol/academic-search
- README advertises SDK, CLI, REST, MCP and Agent Skill interfaces across 24+ scholarly sources with a zero-API-key core.
- Repository is extremely new and has no established adoption signal in the search snapshot.
- Decision: promising architecture, but do not install as trusted production tooling without source review and reproducible tests.

### Local databases and analytics

- https://github.com/Fashad-Ahmed/universal-db-mcp
- MIT-licensed Python MCP server for SQLite, DuckDB, PostgreSQL and MySQL.
- Local SQLite/DuckDB can run without a cloud account; DuckDB can query CSV/Parquet/JSON.
- README describes read-only defaults and multiple query validation layers, including injection checks and result limits.
- Very low adoption at time of research. Inspect implementation and test the security controls before granting access to any real database. Start with an empty or disposable database.

### Python computation

- https://github.com/Ajaja/mcp_python_sandbox
- Local stdio MCP server for calculations, statistics, linear algebra, calculus and symbolic math.
- README explicitly warns that its Python-level deny-list is not a hardened security boundary and may be bypassable.
- Decision: do not expose to untrusted input or remote users; prefer OS/container isolation or a constrained expression calculator. The integrated remote calculator is narrower and safer for basic math.

### Official reference servers

- https://github.com/modelcontextprotocol/servers
- Reference implementations include fetch, filesystem and Git server patterns. These can be run locally with `uvx`/Node where appropriate.
- Keep filesystem roots narrow; keep Git scoped to the selected repository; use read-only access unless writes are explicitly needed.
- Treat reference implementations as starting points, not automatic security approvals.

## Route C: open Agent Skills ecosystem

### Standards and discovery

- Agent Skills specification: https://agentskills.io/specification
- Skills directory: https://skills.sh/
- CLI repository: https://github.com/vercel-labs/skills
- NVIDIA skill catalog: https://github.com/NVIDIA/skills

The Agent Skills format supports `SKILL.md`, optional scripts, references and assets, and progressive disclosure. The skills CLI can discover/install skills for Codex and many other coding agents. It is not itself a ChatGPT runtime tool.

The skills CLI docs state that anonymous telemetry is enabled by default and can be disabled with `DISABLE_TELEMETRY=1`. If Capri uses the CLI, disable telemetry unless the user explicitly opts in.

NVIDIA's catalog is especially useful for GPU/CUDA, CUDA-X, NeMo, NIM, robotics, simulation and accelerated computing workflows. Its README says skills are mirrored from product repositories via automated sync, so the owning upstream repository should be checked before importing.

### Research and security skill candidates

- https://github.com/KalarisLabs/research-agent-skills — MIT literature-review skill with search, screening, extraction, synthesis and citation verification workflow. Some optional LLM steps may use an OpenRouter API key; do not import a requirement for it.
- https://github.com/yigityildiz0/scientific-agent-skills — MIT scientific literature review workflow with explicit review-mode distinctions, reproducible search logs and human screening requirements.
- https://github.com/agamm/claude-code-owasp — OWASP security review skill; inspect current version, license and scripts before importing.

### Safe import policy

Never blindly import a skill because it is popular or appears in a directory. For each candidate:

1. Record repository, exact path, author, license, commit SHA, last update and dependencies.
2. Read the full skill, all referenced files, scripts and install hooks.
3. Flag shell execution, network calls, credential access, file writes, telemetry and prompt-injection-like instructions.
4. Check whether any workflow requires paid APIs, OAuth, a user account or private data.
5. Rewrite into Capri's own workflow where licensing or quality warrants it; retain provenance and attribution.
6. Add deterministic test prompts and expected behavior before inclusion.
7. Preserve source/version information so updates can be reviewed rather than silently pulled.

## Route D: use existing ChatGPT-connected research tools directly

Already available in this ChatGPT environment:

- Exa: web and technical-source discovery.
- Firecrawl: web search and page extraction/research.
- Context.dev: live web search, scraping, crawling and document parsing.
- TinyFish: browser/content retrieval tools; a content fetch attempt in this research returned no usable result records.

These tools already provide a substantial amount of external research capability. A new plugin should not duplicate them unless it adds a materially better workflow, source coverage, or structured output.

## Route E: evaluation and tool orchestration

Build a benchmark suite with one task per capability:

- Research: source coverage, DOI correctness, citation validity, evidence/claim alignment.
- CUDA/ML: version correctness, profiling-first recommendations, reproducible benchmark design.
- Security: true-positive findings, false-positive rate, severity calibration, safe remediation.
- Architecture/debugging: root-cause accuracy, minimal patch quality, regression coverage.
- Databases: query correctness, EXPLAIN interpretation, migration safety, injection resistance.
- Math/data science: numeric correctness, uncertainty, reproducibility, edge-case coverage.
- MCP integrations: initialize/list-tools success, schema correctness, timeout/error handling, no-auth assumptions and data minimization.

Measure baseline vs skill-only vs skill+tool. Keep a tool only if it improves quality enough to justify its attack surface and maintenance cost.

## Recommended next steps

1. Refresh/install Capri Engineering Lab v0.3.0 and verify both remote MCP handshakes and one harmless tool call per server.
2. Build a separate local desktop/Codex toolkit later: Polymath MCP + scoped Git/Fetch + DuckDB/SQLite, with read-only defaults.
3. Curate NVIDIA and high-quality research/security skills through a provenance-and-license review; do not bulk-import unknown skills.
4. Find a reliable, no-login, hosted general CS/engineering academic MCP endpoint beyond the biomedical corpus; current candidates are either local-only, too new, or failed endpoint verification.
5. Create and run the capability benchmark before declaring any skill or integration validated.

## Non-goals

- No purchases, paid services, API-key acquisition or external-account signups.
- No public plugin listing or workspace-wide sharing.
- No broad filesystem, shell or database write access by default.
- No sending private user data to third-party MCP servers.


## Plugin v0.4.0: citation integrity — 2026-11-07

The private Capri Engineering Lab plugin now has three configured remote MCP servers and ten skills. Release: pluginrel_6aef770eadc48191a82b293aefce6c4a.

### Third remote MCP integration

- Project: https://github.com/mlava/scholar-sidekick-mcp
- Endpoint: https://scholar-sidekick.com/api/mcp
- Transport: Streamable HTTP.
- License: MIT; v0.8.13 was the latest release surfaced in this review.
- Anonymous, rate-limited free access is documented. No API key, RapidAPI route, or paid service is configured.
- Seven documented read-only tools: citation verification, bibliography audit (up to 25 records), retraction/correction checks, legal open-access discovery, identifier resolution, citation formatting, and bibliography export.
- Security policy states that the MCP server makes HTTPS calls only to its configured API host, accepts citation identifiers/metadata rather than arbitrary URLs, and does not write files or execute shell commands. Operator engineering notes state raw citation inputs are not retained as application data; lookups can be forwarded to upstream resolvers such as Crossref and PubMed.
- Privacy: send only public bibliographic metadata. Never send confidential manuscripts, private/unpublished bibliographies, patient/personal data, credentials, or private research records.
- Interpretation: a match verifies identifier-to-record identity, not whether the paper supports a claim. Mismatch and not-found are discrepancies requiring review, not proof of fraud or non-existence. Retraction status is separate from citation identity. Optional LLM screening requires authentication and is not enabled.
- The plugin source readback confirms the endpoint, skill and README. ChatGPT-side MCP handshake/tool execution remains pending.

Details: [citation-integrity integration record](https://github.com/Hamudifr/Capri/blob/main/docs/CITATION_INTEGRITY_MCP.md). GitHub PR #128 merged as 51a2bf5a0559a1d9b4222d38d522f97537caadd3.

### Current capability inventory

- 10 skills: capability routing; scientific literature; AI/ML-GPU; defensive security; software engineering; database engineering; mathematics/data science; safe calculator use; biomedical literature discovery; citation integrity.
- 3 remote MCP server configurations: calculator, Noodle, Scholar Sidekick.
- No MCP integration is considered runtime-verified until the ChatGPT host completes initialize/tools-list and at least one harmless tool call. Static configuration and upstream health/card evidence are not sufficient.

### Evaluation work

A repeatable benchmark plan is now tracked in [PLUGIN_CAPABILITY_EVALUATION.md](https://github.com/Hamudifr/Capri/blob/main/docs/PLUGIN_CAPABILITY_EVALUATION.md). It distinguishes structural checks, source-contract checks, live transport tests, and behavioral skill evaluation. Do not label a skill validated merely because its package parses or a remote endpoint is documented.


## Plugin v0.5.0: API integration and test engineering — 2026-11-07

The same private plugin advanced to v0.5.0, adding two dedicated skills: api-integration and testing-validation. The capability router now routes API/GraphQL/MCP/webhook/OAuth/external data-source work to api-integration, and acceptance criteria, regression, CI, release gates and integration verification to testing-validation. These separate concerns from the general software-engineering skill.

- Plugin ID: plugins_6aef721e946c81918014a2c04ff4476f
- Release ID: pluginrel_6aef786d631881919e50282b20102edc
- Total skills: 12.
- Both root mcp.json and Codex .mcp.json retain the three configured servers: calculator, Noodle and Scholar Sidekick.
- No API keys, credentials, paid subscriptions or external accounts were added.
- Plugin Creator readback confirms both new skill files, router changes, both MCP manifests, and v0.5.0 metadata.
- Runtime skill activation and all three ChatGPT-side MCP handshakes/tool calls remain pending.

The evaluation plan was extended from ten to twelve skill cases; the two new cases test integration correctness/security and evidence-based test/release validation.
