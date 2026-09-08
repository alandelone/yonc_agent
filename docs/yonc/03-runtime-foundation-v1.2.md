# Yonc Runtime Foundation v1.2

## Baseline

**Implemented.** Graph v1.1 uses SQLite and SQLAlchemy models for `GraphNode`, `GraphEdge`, `Operation`, `OperationBatch`, `GraphMeta`, resources, view state, and split sessions ([models.py](../../graph_app/models.py#L28)). Startup runs an idempotent compatibility upgrader ([api.py](../../graph_app/api.py#L97), [schema_v2.py](../../graph_app/schema_v2.py#L151)). API requests are committed or rolled back by one session dependency ([api.py](../../graph_app/api.py#L104)).

**Planned.** Runtime Foundation v1.2 preserves those tables and behaviors while adding reliable provenance, replay boundaries, History, AgentRun, portfolio roles, and retry receipts.

## Additive migration 0002

Create `alembic/versions/20260907_0002_yonc_runtime_foundation.py`. Do not edit migration 0001. Put the additive schema and backfill logic in one reusable migration routine invoked by both Alembic and the startup compatibility path so they cannot drift.

When startup detects a pre-1.2 database, it must:

1. close outstanding connections and make a timestamped sibling copy of the SQLite file;
2. run the additive upgrade and backfill in a transaction;
3. verify required columns and tables, graph counts, schema version, baseline snapshot, and HEAD consistency;
4. start the app only after verification succeeds;
5. retain the backup on success or failure and report its path on failure.

Repeated startup on 1.2 performs verification without another migration or data rewrite. Health and graph responses must read `schema_version` from `GraphMeta`; they currently return a hard-coded `1.1` ([api_v2.py](../../graph_app/api_v2.py#L180), [v2_service.py](../../graph_app/v2_service.py#L825)).

## Schema additions

### Operation batches and graph metadata

Keep the table name `operation_batches`. Add nullable fields where legacy rows cannot be safely inferred:

```text
parent_batch_id
commit_type                 WRITE | REVERT | RESTORE | SYSTEM
intent_source               USER_COMMANDED | USER_APPROVED_PROPOSAL | SYSTEM_MAINTENANCE | LEGACY
intent_summary
decision_actor_type
decision_actor_id
executor_type
executor_id
conversation_turn_id
proposal_id
reverts_batch_id
restores_graph_version
schema_version
```

Add to `graph_meta`:

```text
head_batch_id
history_base_version
schema_version = 1.2
```

Backfill legacy batches with `commit_type = WRITE`, `intent_source = LEGACY`, `schema_version = 1.1`, and actors only when `actor_channel` supports a reliable inference. Link `parent_batch_id` only across a unique, contiguous `graph_version_before -> graph_version_after` sequence. Leave uncertain values null.

Set `head_batch_id` only if exactly one batch ends at the current graph version. Otherwise leave it null; the baseline snapshot remains the reliable reconstruction root. The first new commit links to the reliable legacy HEAD when present.

### New tables and fields

- `graph_snapshots`: graph version, optional head batch, complete canonical nodes, edges, and resource references as JSON, reason, and creation time. UI/view/focus state is excluded. Migration writes one `MIGRATION_BASELINE` snapshot.
- `write_receipts`: request ID, fingerprint, stored result, optional batch ID, and creation time as defined by the WRITE contract.
- `restore_previews`: target version, expected HEAD version, canonical operations, creation time, and one-time consumption marker.
- `history_events`: event/truth type, occurred/recorded times, actor, channel, source reference, optional project/node/run/session scope, summary, structured content, searchable text, redaction time, and creation time.
- `agent_runs`: node, agent, assignment, run status, result summary, artifact references, review status/note, creator, `supersedes_run_id`, lifecycle timestamps, and audit timestamps.
- `graph_nodes.portfolio_role`: nullable `MAIN`, `SUPPORT`, or `PARKED`; partial unique indexes enforce one `MAIN` and one `SUPPORT`, while service validation enforces root `GOAL` eligibility and role clearing before reparenting.

Use SQLite filtering plus FTS5 for History when supported. If FTS5 is unavailable, fall back to bounded `LIKE` search with the same API response shape and report search mode in health diagnostics.

## Service boundaries

**Proposed decision.** The request session remains the sole transaction owner. New services never commit independently:

```text
write_service.py       claim version, deduplicate, validate candidate graph, apply, commit metadata, emit History
history_service.py     append/search/get/recent/redact observable events
agent_run_service.py   create/start/result/review/rework AgentRun records
context_service.py     assemble bounded context after the first four milestones
```

`v2_service.py` remains the graph-rule implementation during migration. Its mutation functions are called only beneath `write_service` once adapted; no function may create a second batch inside an existing write. Existing route shapes remain stable while adapters translate them into `ProjectWriteRequest`.

## Milestone order

1. **Compatibility and foundation:** migration, backup and recovery, baseline snapshot, reliable HEAD, schema reporting, and full writer inventory.
2. **Unified writes:** guarded version claim, one batch per intent, receipts, provenance, semantic no-op handling, and migration of every Graph writer.
3. **Reliable history:** replayable operations, list/detail/diff, conflict-aware revert, reconstruction, previewed restore, and undo adapters.
4. **History and AgentRun:** event retrieval/redaction, run/review/rework lifecycle, artifact promotion, and transactional graph-change emission.
5. **Integration:** Context Kernel, semantic Project READ, Hermes runtime, then worker connections.

Background scans and Notion projection start only after the authority and write/history acceptance suites pass.

## Delivery evidence

Maintain:

- `implementation/features.json`, with milestone IDs, dependencies, verification steps, and evidence links;
- `implementation/PROGRESS.md`, with completed, tested, and failed work, current database version, open issues, and next exact step.

A milestone is complete only when all acceptance scenarios in [04 Review and roadmap](04-review-and-roadmap.md) pass and every listed Graph mutation route is either migrated or explicitly removed. Any remaining bypass is a release blocker.

## Deferred

Graph branching, merge/rebase, vector memory, memory classification, policy learning, heavy Daily Runtime, routine engine, knowledge-document subsystem, mobile/今日 redesign, autonomous strategic delegation, and Notion editing/sync policy remain **deferred**.
