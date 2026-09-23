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

Automated evidence is recorded by repository tests and frontend build. Live evidence is
recorded separately below so repository-only checks are not confused with deployment acceptance.

## Live deployment acceptance (2026-09-21)

- Deployed the governed Hermes `yonc` profile against the explicit canonical database at
  `data/project_graph.sqlite3`; health reports schema 1.2, database identity
  `5db40e09ff89dda4`, graph version 1, and 687 imported legacy nodes.
- The profile exposes exactly `uuma-worker` and `yonc-project`. Native Hermes MCP probes
  connected and discovered 60 Worker tools plus 9 Yonc tools. Terminal, computer-use,
  delegation, Control MCP, and inherited unrelated MCP servers are not enabled.
- Real-model direct chat registered UuMA run `run_fbc107b667f84d1e80d1f3246b133cd9`,
  read the live graph through `yonc-project`, returned a grounded 687-node report, and
  submitted a `COMPLETED` result. The UuMA projection is `REVIEW`, as required before an
  independent verifier approves completion.
- Repeated deployment passed without rebuilding the database or duplicating registration.
  Latest manifest: `data/deployments/20260921-231545/manifest.json`.
- Regression evidence: 181 Yonc Python tests passed with one environment-dependent skip;
  58 frontend tests passed; frontend production build passed. The sibling UuMA repository
  passed 175 tests plus 5 subtests and focused Ruff checks.
- Windows deployment compatibility fixes use a post-binding project-root default, a
  PowerShell 5-compatible RNG, a mutable `.env` line buffer, separate Yonc/UuMA Python
  runtimes, and an MCP 1.x constraint compatible with `mcp.server.fastmcp`.
