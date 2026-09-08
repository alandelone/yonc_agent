# Project WRITE and Git-like Graph History

## Current state

**Implemented.** Graph v1.1 has optimistic-version inputs, `OperationBatch`, ordered `Operation` records, inverse payloads, atomic request commit/rollback, split commit, and batch undo. See [batch creation](../../graph_app/v2_service.py#L95), [operation recording](../../graph_app/v2_service.py#L112), and [request transaction handling](../../graph_app/api.py#L104).

**Gap.** Several current forward payloads store only IDs or field names, so they cannot reconstruct historical state ([node/edge recording](../../graph_app/v2_service.py#L250)). Node update undo restores a whole snapshot and may overwrite unrelated later edits ([undo implementation](../../graph_app/v2_service.py#L1116)). Batch undo marks the original batch as undone and advances the version without creating a new Graph Commit ([undo implementation](../../graph_app/v2_service.py#L1075)). These behaviors support local undo but do not satisfy auditable revert or time travel.

## Unified write contract

**Planned.** One explicit user intent becomes one atomic Graph Commit. All operations succeed or the request leaves Graph, commit, receipt, and History state unchanged.

```text
User language
    -> Yonc resolves intent and targets
    -> ProjectWriteRequest
    -> backend claims expected graph version
    -> validate all operations against one candidate graph
    -> apply operations and emit one Graph Commit + HistoryEvent
```

The session dependency in [api.py](../../graph_app/api.py#L104) remains the sole commit/rollback owner. Domain services flush when IDs or constraints must be observed and never call `commit()`.

### Request

```json
{
  "request_id": "01JY...",
  "expected_graph_version": 105,
  "intent_source": "USER_COMMANDED",
  "intent_summary": "Mark literature search complete",
  "conversation_turn_id": "turn_x",
  "decision_actor": {"type": "user", "id": "local-user"},
  "executor": {"type": "yonc", "id": "yonc"},
  "operations": [
    {"op": "NODE_TRANSITION", "node_id": "node_search", "action": "done"}
  ]
}
```

`request_id`, `expected_graph_version`, `intent_source`, `intent_summary`, both actors, and at least one operation are required on the new agent endpoint. `conversation_turn_id` is nullable for non-conversation clients. Existing endpoints may generate a request ID at the adapter boundary during migration.

The backend claims the version with a guarded update equivalent to `UPDATE graph_meta SET graph_version = expected + 1 WHERE graph_version = expected`. A zero-row update returns `409 GRAPH_VERSION_CONFLICT`; this prevents two concurrent requests from both accepting the same version.

### Response

```json
{
  "ok": true,
  "changed": true,
  "graph_version": 106,
  "operation_batch_id": "commit_106",
  "request_id": "01JY..."
}
```

A semantic no-op returns `changed: false`, keeps version `105`, and creates no `OperationBatch` or graph-change History event.

## Retry deduplication

**Proposed decision.** Add `write_receipts` because no-op requests also require reliable retry behavior and therefore cannot use `OperationBatch` alone.

```text
request_id          primary key
request_fingerprint SHA-256 of canonical request semantics, excluding request_id
result_json         original successful/no-op response
operation_batch_id  nullable foreign key
created_at
```

The receipt is written in the same transaction as the Graph Commit. A repeated `request_id` with the same fingerprint returns the stored result and performs no work. Reuse with different content returns `409 REQUEST_ID_REUSED`. Failed or rolled-back requests leave no receipt and may be retried.

## Semantic operation vocabulary

**Planned.** Use these names at the unified boundary and in new operation records:

| Operation | Minimum persisted before/after data |
| --- | --- |
| `NODE_CREATE` | Complete created node plus initial parent edge, if any |
| `NODE_PATCH` | Node ID and only changed fields with before/after values |
| `NODE_REMOVE` | Complete node, all incident edges, and resource references |
| `EDGE_CREATE` | Complete created edge |
| `EDGE_REMOVE` | Complete removed edge |
| `NODE_REPARENT` | Node ID and complete old/new `contains` edges |
| `NODE_TRANSITION` | Stage/status and associated reason/closure fields before/after |
| `NODE_SCHEDULE` | Schedule and placement fields before/after |
| `PORTFOLIO_SET` | Affected root IDs and roles before/after |
| `RESOURCE_ADD` | Complete resource reference |
| `RESOURCE_REMOVE` | Complete removed resource reference |

`SPLIT_COMMIT` is a commit source/summary, not a primitive operation. It expands to `NODE_CREATE` and `EDGE_CREATE` operations within one batch. Imports likewise record their actual semantic operations.

New operations must be replayable both forward and backward. Store only changed fields for patches so reverting an old title change cannot overwrite a later deadline change.

## Provenance

**Decision.** Keep `OperationBatch.source` for the backend path such as `create_node`, `transition_node`, or `split_commit`. Store decision provenance separately:

```text
intent_source = USER_COMMANDED | USER_APPROVED_PROPOSAL | SYSTEM_MAINTENANCE | LEGACY
```

The earlier conversation also used `AGENT_PROPOSED` and `SYSTEM_DERIVED`. This review resolves the conflict as follows:

- `AGENT_PROPOSED` belongs to proposal/History state; an accepted write uses `USER_APPROVED_PROPOSAL`.
- `SYSTEM_DERIVED` is an observation in History and does not create a graph commit.
- A system repair that genuinely changes stored graph structure uses `SYSTEM_MAINTENANCE` and must identify its maintenance rule.

Runtime v1.2 keeps one linear history and one HEAD. Every new non-baseline commit has one `parent_batch_id`; branching, merging, rebasing, and detached writes remain deferred.

## Revert

**Planned.** Revert always creates a new commit. It never edits `undone_at` as the authoritative history mechanism and never removes the original commit.

Before applying an inverse operation, compare each field or relationship written by the target commit with its expected “after” value:

- If it still matches, restore that item’s “before” value.
- If an unrelated field changed later, preserve it.
- If the same field or relationship changed later, return `409 REVERT_CONFLICT` with the conflicting entity/field list.

All checks run before mutation; one conflict rejects the entire revert. A revert commit records `commit_type = REVERT` and `reverts_batch_id`. Reverting a revert is allowed through the same algorithm and produces another new commit.

Example: C10 changes title A→B and C11 changes deadline. Reverting C10 restores title A and preserves C11’s deadline. If C11 changed title B→C, reverting C10 conflicts.

The existing `/api/v2/operation-batches/{id}/undo` endpoint becomes a compatibility adapter to this revert behavior. The v1 operation undo endpoint routes to its batch when available; an unbatched legacy operation retains only its currently supported legacy undo behavior and is excluded from replay guarantees.

## Historical reconstruction and restore

**Proposed decision.** Migration 0002 records a full `graph_snapshots` baseline at the current graph version and stores that version in `GraphMeta.history_base_version`. Historical reconstruction is supported from that baseline forward only when every intervening commit has replayable operations.

Requests older than the baseline, or across an incomplete legacy commit, return `409 HISTORY_UNAVAILABLE` with the earliest supported version. Existing records remain queryable as audit metadata without a false replay guarantee.

Restore is a two-step operation:

1. `POST /api/v2/graph-history/restore-preview` receives target and expected current versions and returns a deterministic semantic diff plus `preview_id`.
2. `POST /api/v2/graph-history/restore` receives `preview_id`, a request ID, and the same expected current version. Any HEAD change invalidates the preview.

Restore applies the previewed diff as a new `RESTORE` commit with `restores_graph_version`; it never moves HEAD backward.

Restore previews are persisted in `restore_previews` with `id`, `target_graph_version`, `expected_head_version`, canonical operations JSON, `created_at`, and nullable `consumed_at`. A preview can be applied once and only while HEAD equals `expected_head_version`; successful application marks it consumed in the restore transaction.

## Endpoint and state boundary

All Project Graph mutations listed in [04 Review and roadmap](04-review-and-roadmap.md) must pass through the unified service before the milestone is complete.

Canvas positions, view state, and focus sessions are mutable local state but do not advance Project Graph version. Proposal drafting, split messages, validation, discard, and rejection are workflow records; only acceptance or commit changes Project Graph truth. These actions may emit History events without creating Graph Commits.
