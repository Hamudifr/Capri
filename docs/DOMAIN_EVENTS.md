# Domain-local event projection

## Decision boundary

Capri keeps each domain store as its own source of truth:
- goals: `goal_events` and `goal_evidence`;
- tasks: `task_events`;
- local memory: `memory_events`;
- Notion memory: current page records and their immutable creation/supersession identity, with no claim of a full Notion event log.

There is no second global event database. The common contract is a read-only in-memory projection. It does not write events, coordinate transactions, replay state, or establish a global causal order across SQLite files and Notion.

## Envelope

`capri_runtime.domain_events.DomainEvent` uses CloudEvents 1.0 identity conventions:
- `specversion`: exactly `1.0`;
- `id`: event identifier unique within its source;
- `source`: a Capri URN identifying the domain entity;
- `type`: a `com.capri.*` event type;
- `subject`: the affected goal/task/memory identifier;
- `time`: timezone-aware ISO-8601 timestamp;
- `data`: at most 12 bounded metadata fields.

The projection enforces unique `(source, id)` pairs. `project_domain_events(*streams)` sorts deterministically by time/source/id for presentation only. Timestamps from different stores do not create a reliable total order.

## Provenance and privacy

The bounded data vocabulary supports:
- `actor_id` for authenticated goal/task ownership where the source store records it;
- `supersedes_id` for correction/revision lineage;
- `derived_from` for an opaque source reference;
- evidence type/reference, task state/step/attempt, and reason/error codes.

The projection rejects arbitrary fields and nested payloads. Never put memory content, prompts, tool arguments/results, credentials, secrets, or free-form notes into event data. Evidence references are identifiers, not independent proof. Goal evidence and task events retain their own domain-local storage and ownership checks.

These fields borrow PROV-DM concepts of attribution, revision, and derivation without requiring RDF or an ontology runtime. The envelope is CloudEvents-style, not a claim of full CloudEvents transport conformance or distributed event sourcing.

## Immutability and correction rules

- Goal events/evidence retain their existing SQLite update/delete guards.
- Task events now have SQLite UPDATE/DELETE guards; task backup and integrity checks validate the guards.
- Memory events now have SQLite UPDATE/DELETE guards. SQLite memory corrections require an Active predecessor, reject an existing successor, and use a partial unique index on non-null `supersedes_id`. Backup/integrity checks validate the index and triggers.
- Notion corrections require an Active predecessor with no existing successor. Same-payload retries reuse the existing replacement; different corrections conflict. `reconcile_correction(replacement_id)` handles safe partial states after replacement creation, predecessor archival, or activation. Notion multi-page operations are not atomic; hosts must serialize cross-process writes or inject a shared correction lock.
- Notion's `domain_events()` is a read-only record-creation/supersession projection. It is not an immutable page-history log and does not invent actor attribution or status-transition events.

## Verification scope

The X8.1 tests exercise direct SQL event mutation rejection, active-head correction, separate-instance SQLite races, Notion correction retries, competing adapter instances sharing one transport, interrupted correction recovery, projection identity uniqueness, provenance bounds, and existing backup/restore behavior. Cross-process Notion locking, real Notion integration behavior, external evidence authenticity, and global causal ordering remain host-level or external limitations.
