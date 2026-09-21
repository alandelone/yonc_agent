# Hermes deployment implementation progress

Updated: 2026-09-21

- P0: integration contract and explicit database identity health response added.
- P1: additive authorization schema, immutable proposal versions, graph version checks,
  operation receipts, and history-preserving explicit removals added.
- P2: UI edits now autosave drafts only. Formal writes require the visible
  **Accept & Commit** action. Submission no longer invents missing action fields.
- P3: bounded `yonc-project` stdio MCP added. Agent commits require both the
  process-owned service token and a proposal-bound, expiring, single-use user grant.
- P4: `yonc` UuMA identity, Worker allowlist, guard preflight, profile, skill, and
  Hermes config generation added in the sibling UuMA repository.
- P5: split tabs remain session-bound; draft and formal-write states are separate.
- P6: install/start/check/rollback scripts and runbook added.

Automated evidence is recorded by repository tests and frontend build. A live Hermes
gateway probe remains environment-dependent and must not be marked successful unless
the deployment script and direct-chat acceptance are actually run.
