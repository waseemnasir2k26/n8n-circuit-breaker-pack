# Changelog

All notable changes to this project are documented in this file.

## [2026.09] - 2026-09-16

- Maintenance review of n8n-circuit-breaker-pack — drop-in n8n sub-workflows that put a spend cap, an iteration budget, an error-rate circuit breaker and a manual kill switch in front of any AI-agent workflow, with every limit stored in Postgres or an env var rather than in the agent's prompt.
- Contents: four importable modules plus a worked example in `workflows/` (`spend-cap.json`, `iteration-budget.json`, `error-rate-breaker.json`, `kill-switch.json`, `example-protected-agent.json`), `sql/schema.sql` for the counter tables, `config/caps.example.yaml`, and three Python checks in `tests/` (workflow JSON validator, cost-math unit tests, validator self-test). MIT licensed.
- Status: v1, committed September 2026 in a single commit. Targets n8n 1.x; workflows import with placeholder credential and workflow ids that the user replaces by hand.
- Reviewed September 2026: docs refreshed, CHANGELOG started, versioned as v2026.09. No workflow JSON, SQL or tests changed.
- Known gaps (stated in the README's own Limitations section): cost is estimated from a hand-written table, not billed; the user must map token counts in or the cap silently charges zero; the spend cap is evaluated after the call that crosses it; breaker reset is manual by design; the kill switch only stops work at workflow entry, not in flight. Repo-level: no CI workflow, so the validators run only by hand; no CHANGELOG before this release; no package manifest to version.
