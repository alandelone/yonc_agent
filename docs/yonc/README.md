# Yonc Design and Implementation Documents

These documents convert the ChatGPT design conversation **“Handoff declined”** (`6a9bb7cd-8514-83ec-963d-ecb11a6622f6`) into repository-local specifications. The conversation is the design source; repository links show the implementation state reviewed on 2026-09-08.

## Status vocabulary

| Label | Meaning |
| --- | --- |
| **Implemented** | Present in the current repository and supported by cited code or tests. |
| **Planned** | Approved target behavior that still requires implementation. |
| **Deferred** | Intentionally outside the current build sequence. |
| **Gap** | Current behavior conflicts with or cannot satisfy the target contract. |
| **Proposed decision** | A code-grounded clarification added during this review; it was not claimed as an original conversation decision. |

## Documents

| Document | Purpose |
| --- | --- |
| [01 Core architecture](01-core-architecture.md) | Product boundaries, authority, History, AgentRun, Today, portfolio, and Notion. |
| [02 Project WRITE and Graph History](02-project-write-and-history.md) | The complete contract for atomic graph writes, deduplication, history, revert, and restore. |
| [03 Runtime Foundation v1.2](03-runtime-foundation-v1.2.md) | Additive migration, service boundaries, compatibility, and data-model requirements. |
| [04 Review and roadmap](04-review-and-roadmap.md) | Code-backed findings, writer inventory, milestones, and release evidence. |

## Governing contract

> Yonc interprets language. The backend protects structure. The user owns decisions. The Graph records accepted project truth.

The implementation extends Graph v1.1 and keeps the current SQLite database and table names. A feature is complete only when its milestone evidence is recorded and its acceptance scenarios pass.
