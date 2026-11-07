# Capri capability expansion: alternative implementation routes

**Research date:** 2026-11-07  
**Status:** Research and one remote-tool integration completed; other routes are candidates, not installed.

## Executive finding

Do not treat skills as the only way to improve Capri. Use a layered capability model:

1. Skills teach task-specific procedures and quality standards.
2. Remote MCP tools give ChatGPT callable external capabilities.
3. Local MCP tools give desktop/Codex agents access to local processes, files, Git, Python and databases.
4. Public APIs and source registries provide domain data without vendor accounts.
5. Evaluation harnesses test whether a skill/tool actually improves outcomes.

The best route depends on the user's host. Remote MCP servers can be used from ChatGPT when connected as plugins. Local stdio MCP servers require a local runtime and are suitable for desktop/Codex, not an Android-only ChatGPT session.

## Implemented: remote mathematical computation

Updated the existing private **Capri Engineering Lab** plugin to v0.2.0.

- Plugin ID: `plugins_6aef721e946c81918014a2c04ff4476f`
- Release ID: `pluginrel_6aef75bc617c8191b42ab494be51926b`
- Added `mcp.json` with Streamable HTTP server `calculator` at `https://calculator.caseyjhand.com/mcp`.
- Added `calculator-computation` skill with privacy boundaries and result-validation procedure.
- Preserved the existing seven domain skills and private audience.

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

### Candidate: biomedical literature graph — investigate, do not yet connect

- Project/service: Helena Bioinformatics Noodle
- Endpoint: https://api.helena.bio/noodle/v1/mcp
- Public description: read-only biomedical literature search, publication inspection, bounded citation/semantic graph traversal; no authentication; Streamable HTTP.
- Documentation: https://noodle.helena.bio/mcp
- The endpoint returned HTTP 405 to a GET-style page fetch; this is not an MCP handshake test and neither proves nor disproves MCP availability.
- Privacy restriction stated by provider: public, non-sensitive questions and identifiers only; never send patient records or private case data.
- Decision: potentially useful for biomedical literature only; verify repository provenance, data handling and MCP handshake before adoption.

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

1. Keep the current remote calculator as the first real tool integration, pending a ChatGPT-side tool handshake.
2. Build a separate local desktop/Codex toolkit later: Polymath MCP + scoped Git/Fetch + DuckDB/SQLite, with read-only defaults.
3. Curate NVIDIA and high-quality research/security skills through a provenance-and-license review; do not bulk-import unknown skills.
4. Find a reliable, no-login, hosted academic MCP endpoint for broad computer science/engineering research. The current candidates are either local-only, too new, or failed endpoint verification.
5. Create and run the capability benchmark before declaring any skill or integration validated.

## Non-goals

- No purchases, paid services, API-key acquisition or external-account signups.
- No public plugin listing or workspace-wide sharing.
- No broad filesystem, shell or database write access by default.
- No sending private user data to third-party MCP servers.
