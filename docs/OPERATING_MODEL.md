# Capri operating model

## 1. Purpose

Provide a traceable operating framework for research, reasoning, memory, execution, and evaluation. This document describes governance and the non-X5 recovery scope; it is not a claim that a production agent runtime exists.

## 2. Evidence taxonomy

Every material statement must be labelled as one of:

- **Observed** — directly returned by a connected source or reproducible command.
- **Derived** — calculated from identified observations, with method and denominator.
- **Hypothesis** — plausible explanation that has not been verified.
- **Planned** — intended work not yet performed.
- **Verified** — a defined check was run and its result recorded with a reproducible reference.

A tool call succeeding proves only that the call succeeded. It does not prove the underlying product behavior is correct.

## 3. Evaluation integrity

- A run is an immutable historical event. Corrections and retests create new records linked to the prior run.
- A Self evaluator cannot satisfy an Independent review requirement.
- A record marked Pass must identify the scenario, dimension, evaluator type, evidence stage, run date, and evidence reference.
- Missing evidence is not a pass. An unrun scenario is Not Run, not Pass or Fail.
- Scenario coverage counts unique scenario identifiers; run counts include retests. Report both.
- Any aggregate must state its scope, filters, timestamp, and denominator.

## 4. Blind evaluation boundary

X5 is a protected blind evaluation. Until an authorized test instruction set is explicitly supplied:

- Do not execute X5.
- Do not search for, fetch, reconstruct, infer, or request protected scoring rubrics, expected answers, hidden criteria, or scoring keys.
- Do not use X5-related evidence as ordinary implementation input.
- Do not generate substitute instructions or mark X5 Pass, Fail, or complete.
- If protected content is unexpectedly surfaced, stop reading that source immediately. Record only a minimal contamination event (source identifier, time, and that inspection stopped); do not copy the content into logs, code, prompts, or reports.

This boundary applies to humans, agents, tools, repository automation, fixtures, and artifacts.

## 5. Release gate

The release gate is not met until all required non-X5 scenarios have evidence-backed outcomes, independent review requirements are satisfied by an actually independent evaluator, critical defects are resolved or explicitly accepted by an authorized owner, and the protected X5 gate is completed through its authorized process. A dashboard of self-scored Pass records alone cannot satisfy the gate.

## 6. Change control

- Use feature branches and pull requests.
- Keep changes small and reviewable.
- Preserve source records and prior decisions.
- Never store credentials, personal secrets, protected evaluation content, or private user data in the repository.
- Keep the four canonical Capri skills unchanged unless separately authorized.
