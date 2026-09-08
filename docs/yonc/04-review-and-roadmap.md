# Specification Review and Implementation Roadmap

## Review findings

This review compares the “Handoff declined” design conversation with the repository state on 2026-09-08.

| Finding | Evidence | Required resolution |
| --- | --- | --- |
| Request commit and rollback already have one owner. | [API session dependency](../../graph_app/api.py#L104) | Preserve it; services flush and raise but never commit. |
| Graph version is incremented when a batch begins. | [begin_batch](../../graph_app/v2_service.py#L95) | Replace check-then-set with an atomic guarded version claim. |
| New operations have inverse payloads, but several forward payloads are incomplete for replay. | [operation recording](../../graph_app/v2_service.py#L112), [create node/edge](../../graph_app/v2_service.py#L250) | Persist complete changed values in both directions. |
| Whole-node snapshot undo can overwrite later unrelated edits. | [restore_node](../../graph_app/v2_service.py#L1116) | Store field-level patches and use conflict-aware revert. |
| Current undo advances graph version without creating a new commit. | [undo_batch](../../graph_app/v2_service.py#L1075) | Make undo a compatibility route to a new REVERT commit. |
| Agent-channel `DONE` is rejected regardless of decision owner. | [transition rule](../../graph_app/v2_service.py#L402), [test](../../tests/test_graph_app_v2.py#L68) | Authorize user-commanded completion using decision provenance. |
| Schema version is hard-coded in API projections. | [health](../../graph_app/api_v2.py#L180), [graph projection](../../graph_app/v2_service.py#L825) | Read it from `GraphMeta`. |
| Startup can add schema objects but has no specified backup/recovery contract. | [startup upgrade](../../graph_app/api.py#L97), [schema upgrader](../../graph_app/schema_v2.py#L151) | Add pre-upgrade backup, shared migration logic, and post-upgrade verification. |
| v1 and v2 expose multiple mutation paths. | [v1 routes](../../graph_app/api.py#L147), [v2 routes](../../graph_app/api_v2.py#L191) | Adapt every Project Graph writer to one write service. |

## Complete writer inventory

The following routes or flows must be classified and covered before unified writes are complete.

### Project Graph truth writers

| Current entry point | Current behavior | Target |
| --- | --- | --- |
| v1 node create, patch, lifecycle | Uses legacy operations; patch may also call v2 reparent | One semantic commit per request |
| v1 edge create/delete | Uses legacy operation history | `EDGE_CREATE` / `EDGE_REMOVE` commit |
| v1 proposal accept | Applies each accepted item through legacy services | One `USER_APPROVED_PROPOSAL` commit |
| v1 legacy import | Imports graph state | One import commit containing semantic operations |
| v1 operation undo | Legacy operation or batch undo | Compatibility adapter to revert where replayable |
| v2 node create/patch/reparent/transition/schedule | Creates operation batches | Route adapters to `write_service` |
| v2 agent transition | Creates a batch but blocks all agent `DONE` | Require decision provenance; permit user-commanded `DONE` |
| v2 edge create and resource add | Creates operation batches | Route adapters with replayable payloads |
| v2 split commit | One existing batch containing created nodes and edges | Preserve atomicity and label source `split_commit` |
| v2 batch undo | Mutates original batch and version | Compatibility adapter to new REVERT commit |
| v2 legacy import apply | Applies imported graph data | One import commit containing semantic operations |

The v1 endpoint locations are visible in [api.py](../../graph_app/api.py#L147); v2 endpoints are registered in [api_v2.py](../../graph_app/api_v2.py#L191). Any direct service, startup, command-line, scheduled, or test-only graph mutation discovered during implementation must be added here and migrated. An unlisted bypass blocks release.

### Operational and workflow state

These changes do not advance Project Graph version:

- Canvas position and v2 view state are UI state.
- Focus start and stop are activity state and emit History when History exists.
- Proposal submission or rejection and split start, message, validation, or discard are workflow state.
- Proposal acceptance and split commit cross the boundary and therefore use Project WRITE.

## Prioritized milestones

### M1 — Compatibility and foundation

Dependencies: current Graph v1.1 tests and a representative production-style database fixture.

Deliver additive migration 0002, backup and recovery, shared Alembic/startup migration logic, new models, baseline snapshot, reliable HEAD, dynamic schema reporting, and this writer inventory as an enforced checklist.

Acceptance evidence:

- Migration test output for a fresh database and the existing 551-node fixture.
- Before and after counts plus representative field checks.
- Backup path plus a forced-failure recovery test.
- Two consecutive startups showing an unchanged 1.2 database.
- Health and graph responses reporting `GraphMeta.schema_version`.

### M2 — Unified writes

Dependencies: M1.

Deliver `ProjectWriteRequest`, guarded version claim, candidate-graph validation, one transaction and batch per intent, write receipts, provenance, semantic no-op behavior, portfolio validation, and adapters for every truth writer.

Acceptance evidence:

- Route-to-service coverage table with no bypass.
- Two concurrent writes using one expected version: one succeeds and one returns `GRAPH_VERSION_CONFLICT`.
- A multi-operation failure leaves graph, version, batch, receipt, and History unchanged.
- Duplicate request returns its original response; changed content with the same ID returns `REQUEST_ID_REUSED`.
- No-op returns `changed: false` without a commit.
- User-commanded completion through Yonc succeeds with user decision owner, while a worker-originated completion is rejected.
- MAIN/SUPPORT swaps succeed atomically and invalid role or reparent operations leave no changes.

### M3 — Reliable history

Dependencies: M2 has produced replayable commits.

Deliver commit list, detail, and diff; complete forward and inverse records; conflict-aware revert; baseline-forward reconstruction; restore preview and apply; and compatibility undo routes.

Acceptance evidence:

- Reverting an earlier title change after a later deadline change restores only the title.
- Reverting that title after a later title edit returns `REVERT_CONFLICT` and writes nothing.
- Supported versions reconstruct exactly from the baseline and commits.
- Pre-baseline or incomplete legacy ranges return `HISTORY_UNAVAILABLE` with the earliest supported version.
- Stale restore previews fail and valid previews create one `RESTORE` commit.
- Reverting a split restores graph structure and split workflow state without deleting audit history.

### M4 — History and AgentRun

Dependencies: M2 transaction path and M3 identifiers for commit references.

Deliver append, search, get, recent, and redact History APIs; graph-change event emission in the graph transaction; AgentRun lifecycle and review APIs; rework linkage; and explicit artifact promotion through Project WRITE.

Acceptance evidence:

- Graph mutation and `PROJECT_GRAPH_CHANGED` event commit or roll back together.
- History filters work by time and scope under FTS5 and fallback search modes.
- Redaction preserves event identity and audit metadata while removing protected content.
- Worker result or review does not change node completion.
- Rework creates a linked run and preserves the earlier result.
- Artifact promotion creates one resource commit and duplicate promotion is a no-op.

### M5 — Integration

Dependencies: M2 through M4 acceptance suites.

Deliver bounded Context Kernel retrieval, Project search and context reads, Hermes `yonc-runtime`, and worker connectors. Add background scanning and Notion projection only after authority and write/history suites remain green.

Acceptance evidence:

- Context Kernel includes current Graph context and selected History without loading all records.
- Hermes reads and writes through the public semantic contracts.
- Worker delegation always creates or updates AgentRun and cannot bypass Project WRITE.
- Integration failures leave accepted Project Graph truth unchanged.

## Cross-milestone verification matrix

| Scenario | Expected result | Milestone |
| --- | --- | --- |
| Two writes share expected version | Exactly one commit; loser receives 409 | M2 |
| Second operation in a batch fails | No partial state, commit, receipt, or event | M2 |
| Same request retried | Original response, no extra commit | M2 |
| Semantic no-op | Success with unchanged graph version | M2 |
| Explicit user says “done” through Yonc | `DONE` commit with user decision owner and Yonc executor | M2 |
| Worker reports completion | AgentRun and History update only | M4 |
| Revert old title after deadline edit | Title restored; deadline preserved | M3 |
| Revert old title after newer title edit | Atomic `REVERT_CONFLICT` | M3 |
| Read supported historical version | Exact reconstructed graph | M3 |
| Read unsupported legacy version | `HISTORY_UNAVAILABLE` plus boundary | M3 |
| Migration repeated | No duplicate rows, snapshots, or rewrites | M1 |
| Any truth-writing route succeeds | One version increment, one commit, consistent History event | M2/M4 |

## Release rule

Update `implementation/features.json` only with evidence from end-to-end tests. A milestone remains incomplete while any acceptance scenario fails, any Graph writer bypasses `write_service`, schema reports disagree, or migration recovery is unverified.
