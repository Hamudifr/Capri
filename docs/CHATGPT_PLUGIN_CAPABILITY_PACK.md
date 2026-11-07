# Capri Engineering Lab — ChatGPT capability plugin

**Status:** Created as a private ChatGPT plugin; runtime activation and behavioral evaluation remain pending.  
**Version:** 0.1.0  
**Plugin ID:** `plugins_6aef721e946c81918014a2c04ff4476f`  
**Release ID:** `pluginrel_6aef721fde548191ba4561353dec13e5`  
**Plugin URL:** https://chatgpt.com/plugins/plugins_6aef721e946c81918014a2c04ff4476f

## Purpose

Add reusable, account-independent specialist workflows for scientific research and technical engineering. The plugin is skills-only: it adds guidance and routing, not hosted APIs, runtime execution, GPU hardware, or new external tool permissions.

## Included skills

1. **Capability Router** — routes requests to the relevant specialist workflow.
2. **Research Literature** — literature discovery, screening, appraisal, evidence synthesis, and reproducibility.
3. **AI/ML & GPU** — model lifecycle, CUDA kernels, profiling, NCCL, and distributed training/inference.
4. **Defensive Security** — STRIDE threat modeling, OWASP ASVS, NIST SSDF, secure code review, and supply-chain controls.
5. **Software Engineering** — architecture, debugging, testing, reliability, and performance diagnosis.
6. **Database Engineering** — relational modeling, SQL, query plans, migrations, transactions, and database security.
7. **Math & Data Science** — mathematical reasoning, statistics, experiment design, ML evaluation, and numerical computing.

## Constraints

- No external app binding, MCP server, Gmail connection, API key, paid subscription, or external account is required.
- The plugin does not grant permission to test systems without authorization.
- It does not imply that CUDA, a GPU, code execution, or external network access is available in every session.
- Upstream documents are referenced, not copied wholesale. Check each upstream license before redistributing source files.

## Research sources

- NVIDIA Agent Skills catalog: https://github.com/NVIDIA/skills
- NVIDIA skills documentation and governance: https://docs.nvidia.com/skills
- Agent skills for compute: https://github.com/dtunai/agent-skills-for-compute
- CUDA kernel skills (repository declares MIT): https://github.com/xingjinglu/kernel-skills
- CUDA Best Practices Guide: https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/
- NCCL documentation: https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/
- OWASP ASVS: https://asvs.org/
- NIST SSDF SP 800-218: https://csrc.nist.gov/pubs/sp/800/218/final
- PRISMA 2020: https://www.prisma-statement.org/prisma-2020
- Cochrane Handbook: https://www.cochrane.org/handbook
- PostgreSQL performance tips: https://www.postgresql.org/docs/current/performance-tips.html

## Verification record

- The generated archive passed ZIP integrity checks.
- The root manifest parsed as JSON; category and short-description length passed package constraints.
- Seven skill files had unique names and non-empty YAML frontmatter.
- Plugin creation returned `status=created`, `scope=USER`, and `discoverability=PRIVATE`.
- A post-creation skill-catalog lookup did not show the new skills in the currently loaded runtime catalog. Therefore plugin creation is confirmed, but runtime activation is not yet confirmed.
- No behavioral benchmark was run against a no-skill baseline. Structural validation must not be described as behavioral proof.

## Next validation

1. Open the plugin URL and confirm it is connected/available in ChatGPT.
2. In a fresh conversation, test one representative prompt per skill.
3. Score activation, correctness, evidence quality, security boundaries, reproducibility, and efficiency against a baseline without the plugin.
4. Fix any activation or quality failures before treating the pack as validated.
