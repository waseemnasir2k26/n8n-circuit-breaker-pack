# Changelog

All notable changes to this project are documented in this file.

## [2026.10] - 2026-10-12

- n8n-circuit-breaker-pack is a public, MIT-licensed set of n8n sub-workflows (spend cap, iteration budget, error-rate breaker, kill switch, plus an example protected agent) with a Postgres schema, an example caps config and three Python validators in tests/.
- State: v1, unchanged since the September 2026 initial commit; targets n8n 1.x and imports with placeholder credential and workflow ids.
- Re-reviewed October 2026: README, file tree and commit history re-read; documentation and version metadata only, no code changes. External links (skynetjoe.com, the Calendly page, the n8n community thread) returned HTTP 200.
- Known gaps (from the README's Limitations): cost is estimated from a hand-written table; token counts must be mapped in or the cap charges zero; the cap is checked after the crossing call; breaker reset is manual; the kill switch only stops work at workflow entry. Repo-level: no CI workflow, so validators run by hand.

## [2026.09] - 2026-09-16

- Maintenance review of n8n-circuit-breaker-pack — drop-in n8n sub-workflows that put a spend cap, an iteration budget, an error-rate circuit breaker and a manual kill switch in front of any AI-agent workflow, with every limit stored in Postgres or an env var rather than in the agent's prompt.
- Contents: four importable modules plus a worked example in `workflows/` (`spend-cap.json`, `iteration-budget.json`, `error-rate-breaker.json`, `kill-switch.json`, `example-protected-agent.json`), `sql/schema.sql` for the counter tables, `config/caps.example.yaml`, and three Python checks in `tests/` (workflow JSON validator, cost-math unit tests, validator self-test). MIT licensed.
- Status: v1, committed September 2026 in a single commit. Targets n8n 1.x; workflows import with placeholder credential and workflow ids that the user replaces by hand.
- Reviewed September 2026: docs refreshed, CHANGELOG started, versioned as v2026.09. No workflow JSON, SQL or tests changed.
- Known gaps (stated in the README's own Limitations section): cost is estimated from a hand-written table, not billed; the user must map token counts in or the cap silently charges zero; the spend cap is evaluated after the call that crosses it; breaker reset is manual by design; the kill switch only stops work at workflow entry, not in flight. Repo-level: no CI workflow, so the validators run only by hand; no CHANGELOG before this release; no package manifest to version.
