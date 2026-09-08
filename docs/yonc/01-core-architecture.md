# Yonc Core Architecture

## System boundary

**Planned.** Yonc is the user’s secretary and dispatcher. It may advise, record an explicit user decision, and delegate bounded work. It may not turn its own suggestion or a worker result into accepted project truth.

```text
                         User
                          |
                          v
                    Yonc Secretary
             /            |            \
         Advise         Record       Delegate
             \            |            /
              -------- User decision ---
                          |
                          v
                    Accepted truth
```

The v1 runtime has three core domains:

| Domain | Question it answers | Status |
| --- | --- | --- |
| Project Graph | What work exists, how is it related, and what is its accepted state? | **Implemented**, to be extended |
| History | What observable events occurred? | **Planned** |
| AgentRun | What work was delegated, returned, and reviewed? | **Planned** |

The current repository already models graph nodes, edges, operations, batches, proposals, focus sessions, resources, view state, and split sessions in [models.py](../../graph_app/models.py#L28). `HistoryEvent` and `AgentRun` are not present yet.

## Truth, observations, and projections

**Planned.** The local SQLite Project Graph is the source of accepted project truth. Canvas and Hermes/Yonc are clients. Notion is a future projection surface.

History stores observable records, including user statements, tool results, graph commits, agent activity, approvals, and rejections. A History record is evidence that something occurred; it does not automatically change the Graph. An AgentRun result is work output; it becomes a Project Resource only through an explicit promotion write.

```text
Observable event -----> History
User decision --------> validated Graph Commit -----> Project Graph
Worker output --------> AgentRun --explicit promotion--> ResourceReference
```

The existing `ResourceReference` model is the destination for accepted artifacts ([models.py](../../graph_app/models.py#L189)).

## Decision ownership and execution

**Decision.** Project truth changes only when:

1. the user gives an explicit, unambiguous instruction; or
2. the user explicitly accepts a proposal.

Every commit records these roles independently:

- `decision_actor_type` and `decision_actor_id`: who owns the decision;
- `executor_type` and `executor_id`: which client carried it out.

When the user tells Yonc “this is done,” the decision actor is `user` and the executor is `yonc`. Yonc may record `DONE` in that case. A worker finishing, returning a result, or receiving an acceptable review never completes a Graph node.

**Gap.** The current agent transition rejects every `DONE` request unless its channel is `user_ui` ([v2_service.py](../../graph_app/v2_service.py#L402), [test](../../tests/test_graph_app_v2.py#L68)). The unified write contract replaces channel-based authority with recorded decision ownership.

| Trigger | Project Graph behavior |
| --- | --- |
| Explicit user instruction with one clear interpretation | Apply through Project WRITE. |
| Ambiguous target or value | Ask; write nothing. |
| Yonc suggestion | Save/present a proposal; await acceptance. |
| Worker result or review | Update AgentRun/History only. |
| Derived forecast or warning | Present and record as observation; change no user-decided field. |

## History-first memory and Today

**Planned.** Use **record broadly, retrieve selectively**. Store observable data rather than model hidden reasoning. Retrieval filters History for the current need; it does not inject the entire archive into context.

Initial retrieval uses SQLite scope/time filters and FTS5 when available. Summarization, importance scoring, embeddings, policy extraction, and memory decay are **deferred**.

Today is initially a view over:

```text
today’s History events
+ current or selected Action, when available
+ relevant Project Graph context
```

The current code already has `FocusSession` and `ViewState` ([models.py](../../graph_app/models.py#L86), [models.py](../../graph_app/models.py#L203)). These are operational/UI state, not versioned Project Graph truth.

## Portfolio

**Planned.** Add nullable `portfolio_role` to `GraphNode` with values `MAIN`, `SUPPORT`, `PARKED`, or `null`.

- Only root nodes with `work_type = GOAL` may hold a portfolio role.
- At most one root is `MAIN` and at most one is `SUPPORT`; `PARKED` is unlimited.
- A single Project WRITE may atomically swap roles between roots.
- Reparenting a role-bearing root is rejected. The caller must explicitly clear its role in the same atomic request before making it a child.
- Status and portfolio role remain independent; `PARKED` does not mean cancelled.

These rules reduce the candidate set for recommendations and future background scans. Portfolio is a Graph field and uses ordinary Graph history; it is not a separate subsystem.

## AgentRun lifecycle

**Planned.** An AgentRun has a run state and a review state. They change independently:

```text
QUEUED -> RUNNING -> RESULT_READY
                    |           \
                    v            v
              review state    FAILED / CANCELLED
```

Review states are `UNREVIEWED`, `ACCEPTABLE`, `PARTIAL`, `NEEDS_REWORK`, and `REJECTED`. Rework creates a new AgentRun with `supersedes_run_id` pointing to the prior attempt. The prior assignment, result, artifacts, and review remain immutable audit evidence.

Initial workers remain Brainstormer, Scholar, Forge-Lab-Bot, and Wisdom-Oldman. Worker integration follows the History and Project WRITE milestones.

## Deferred surfaces

**Deferred.** Heavy Daily Runtime tables, policy learning, vector memory, autonomous strategic delegation, mobile/今日 redesign, and Notion’s bidirectional editing rules remain outside Runtime Foundation v1.2.

Notion remains a required future projection. Its information architecture and sync policy will be specified after the Project WRITE authority and history contracts pass verification.
