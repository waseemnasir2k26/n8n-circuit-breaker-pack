# n8n-circuit-breaker-pack

Drop-in n8n sub-workflows that put a spend cap, an iteration budget, an error-rate circuit breaker and a manual kill switch in front of any AI-agent workflow.

## Status

Last reviewed: October 2026 · release v2026.10

## Why this exists

An n8n workflow that calls an LLM in a loop has no natural stopping point. If the exit condition never becomes true, the loop keeps calling the model. Nothing crashes. No node turns red. The execution just keeps running and every turn costs money. You find out from the provider's billing page, not from n8n.

n8n has no built-in circuit breaker. It has an Error Workflow, which runs _after_ something already failed, and per-node retry settings, which make a failing node try _harder_. Neither of those stops a workflow that is succeeding its way through your budget.

The gap has been asked about publicly. The n8n community feature request [Health-Check / Circuit-Breaker workflow](https://community.n8n.io/t/health-check-circuit-breaker-workflow/60679) (November 2024) asks for exactly this: a health-check / circuit-breaker workflow you can attach to any other workflow, the way you attach an Error workflow. It got one reply and, as of this writing, nothing in core.

So the pattern gets rebuilt badly, by hand, in every project - usually as a number in the agent's prompt. That is the thing this repo is arguing against:

> A cap in a prompt is a suggestion. A cap in a database is a control.

The model can ignore, misread, or lose a prompt instruction in a long context. It cannot argue with `SELECT cost_usd FROM spend_counter`. Every limit in this pack lives in Postgres or an environment variable, and the check happens in a node the model does not control.

![license](https://img.shields.io/badge/license-MIT-blue)
![n8n](https://img.shields.io/badge/n8n-1.x-orange)
![storage](https://img.shields.io/badge/state-Postgres-336791)
![status](https://img.shields.io/badge/status-v1-lightgrey)

## Quick start

1. **Create the tables.** Point psql at the database your n8n Postgres credential uses (a separate database is cleaner than n8n's own):
   `psql "$DATABASE_URL" -f sql/schema.sql`
2. **Import the four modules** from `workflows/` into n8n (Workflows -> Import from File): `spend-cap.json`, `iteration-budget.json`, `error-rate-breaker.json`, `kill-switch.json`. Open each one, set the Postgres credential on every Postgres node (they import with the placeholder id `REPLACE_WITH_YOUR_POSTGRES_CREDENTIAL_ID`), and save. Note each workflow's id from its URL.
3. **Set the environment variables** on your n8n instance (see [Config reference](#config-reference)):
   `N8N_CB_WORKFLOW_KEY`, `N8N_CB_SPEND_CAP_USD`, `N8N_CB_MAX_ITERATIONS`, `N8N_CB_MAX_RUNTIME_MS`.
   Code nodes read `$env` only when `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`. If you leave env access blocked, pass the caps as fields in the Execute Workflow call instead - the modules take either.
4. **Wire the gates.** Import `workflows/example-protected-agent.json`, replace the four `REPLACE_WITH_*_WORKFLOW_ID` placeholders with the ids from step 2, and copy the pattern into your own workflow: kill switch and breaker check at the entry, iteration budget before each loop turn, spend cap after each model call.
5. **Prove it stops.** Set `N8N_CB_MAX_ITERATIONS=2` and run the example. It should halt on the third turn with `CIRCUIT BREAKER: iteration budget exceeded`. Put your real value back.

Verify the JSON before importing, any time you edit it:

```
python tests/validate_workflows.py
python tests/test_cost_math.py      # needs node on PATH
python tests/test_validator.py
```

## The four modules

| Module                    | What it stops                                                                                                                                                                                                                     | What you configure                                            |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `spend-cap.json`          | A workflow spending past a dollar ceiling. Counts estimated USD per model call in a rolling hour/day/week/month window and halts at the cap.                                                                                      | `cap_usd`, `spend_window`, the per-model cost table           |
| `iteration-budget.json`   | A loop that never exits. Counts turns and wall-clock time per run and halts past either.                                                                                                                                          | `max_iterations`, `max_runtime_ms`                            |
| `error-rate-breaker.json` | A workflow that keeps starting while it is broken. Records each run's outcome, and when the error rate over the last N runs crosses the threshold it flips `breaker_state` to `open`, which blocks entry until a human resets it. | `window_size`, `min_samples`, `error_rate_threshold`          |
| `kill-switch.json`        | Everything, right now. One boolean row that every protected workflow reads first. Flip it by SQL or by POSTing to its webhook.                                                                                                    | scope (`global` or one `workflow_key`), webhook path and auth |

All four are sub-workflows with an Execute Workflow Trigger. They halt by throwing (Stop and Error), so the calling workflow stops too and the failure is visible in the executions list instead of silent. Each one writes a single alert item into a No-Op node named `... Alert Sink` - replace that node with your Slack, email or PagerDuty node.

`example-protected-agent.json` is a runnable three-turn agent loop with all four wired in, so you can see where each gate goes rather than guess.

## A protected workflow

```
                          +--------------------------+
   trigger  ------------> |  ENTRY GATE              |
                          |  1. kill-switch    (read)|--- engaged? --> STOP + alert
                          |  2. error-rate     (read)|--- open?    --> STOP + alert
                          +------------+-------------+
                                       | clear
                                       v
                          +--------------------------+
                    +---> |  iteration-budget (write)|--- over? ------> STOP + alert
                    |     |  turns++ , elapsed_ms    |
                    |     +------------+-------------+
                    |                  | within budget
                    |                  v
                    |     +--------------------------+
                    |     |  YOUR WORK               |
                    |     |  LLM call / tool / HTTP  |
                    |     +------------+-------------+
                    |                  | model, tokens
                    |                  v
                    |     +--------------------------+
                    |     |  spend-cap       (write) |--- over cap? --> STOP + alert
                    |     |  cost_usd += estimate    |                  + trip breaker
                    |     +------------+-------------+
                    |                  |
                    |            done? |
                    +----- no ---------+
                                       | yes
                                       v
                          +--------------------------+
                          |  error-rate     (write)  |   rate > threshold
                          |  log success / error     |-- over N runs ---> trip breaker
                          +------------+-------------+                    + alert
                                       v
                                     finish

  Postgres holds the state that survives an execution ending:
    spend_counter . breaker_state . kill_switch . execution_log . iteration_counter
```

Reads are cheap and go at the entry. Writes go around the expensive part. The kill switch is read first because it is the only gate a human flips mid-incident.

## Config reference

Precedence in every module: **value passed in the Execute Workflow call > environment variable > built-in default.** `config/caps.example.yaml` is the documented shape; copy it into your infra repo and render it into your n8n environment.

| Setting                | Env var                       | Default         | Meaning                                                                                              |
| ---------------------- | ----------------------------- | --------------- | ---------------------------------------------------------------------------------------------------- |
| `workflow_key`         | `N8N_CB_WORKFLOW_KEY`         | `default`       | Identity of the protected workflow across all tables. One key per workflow, or their counters merge. |
| `cap_usd`              | `N8N_CB_SPEND_CAP_USD`        | `5`             | Halt when window spend reaches this (`>=`).                                                          |
| `spend_window`         | `N8N_CB_SPEND_WINDOW`         | `day`           | `date_trunc` unit: `hour`, `day`, `week`, `month`.                                                   |
| `max_iterations`       | `N8N_CB_MAX_ITERATIONS`       | `25`            | Halt when turns for one `run_key` exceed this (`>`).                                                 |
| `max_runtime_ms`       | `N8N_CB_MAX_RUNTIME_MS`       | `300000`        | Halt when ms since the run's first charged iteration exceed this.                                    |
| `window_size`          | `N8N_CB_ERROR_WINDOW`         | `20`            | How many recent runs form the error-rate window.                                                     |
| `min_samples`          | `N8N_CB_ERROR_MIN_SAMPLES`    | = `window_size` | Do not trip before this many runs exist. Stops one early failure reading as 100%.                    |
| `error_rate_threshold` | `N8N_CB_ERROR_RATE_THRESHOLD` | `0.5`           | Trip when `errors / samples` exceeds this.                                                           |
| `cost_table`           | (call field only)             | see below       | `{ "<model prefix>": { "input": <usd per 1M>, "output": <usd per 1M> } }`                            |

Per-call fields the modules accept, beyond the table above: `model`, `input_tokens`, `output_tokens` (spend-cap); `run_key` (iteration-budget, defaults to the n8n execution id); `mode` (`check` or `record`), `status` (`success` or `error`), `error_message`, `execution_id` (error-rate-breaker).

**Cost table.** Model names match longest-prefix-first and case-insensitively, so `gpt-4o-mini-2024-07-18` prices as `gpt-4o-mini`, not `gpt-4o`. Anything that matches nothing uses the `default` entry - keep that entry pessimistic, so an unrecognised model costs more than you expect rather than nothing. The prices shipped in the Code node are defaults, not a maintained price feed. Check them against your provider before you rely on the cap.

**Resetting a tripped breaker** (deliberately manual):

```sql
UPDATE breaker_state
   SET state = 'closed', reset_at = now(), updated_at = now()
 WHERE workflow_key = 'your-workflow-key';
```

**Engaging the kill switch** by SQL, or by POST to the webhook (header auth is on by default):

```sql
UPDATE kill_switch
   SET engaged = true, reason = 'runaway agent', engaged_at = now(),
       engaged_by = 'you', updated_at = now()
 WHERE scope = 'global';
```

```
curl -X POST https://your-n8n/webhook/circuit-breaker/kill-switch \
  -H "Content-Type: application/json" -H "X-CB-Token: <your header auth value>" \
  -d '{"scope":"global","engaged":true,"reason":"runaway agent","by":"you"}'
```

## Limitations

Read these before you trust it with real money.

- **Cost is estimated, not billed.** The spend cap multiplies your token counts by your cost table. It does not read your provider's billing API. Cached tokens, batch discounts, image and audio pricing, and any price change you have not copied into the table will all make the estimate wrong. Treat the cap as a tripwire, not an invoice.
- **You must supply token counts.** The module cannot see inside your LLM node. If you do not map the response's usage fields into `input_tokens` / `output_tokens`, it charges zero and the cap never fires. This is the most likely way to mis-wire the pack.
- **Postgres is required for cross-execution state.** n8n's workflow static data is per-workflow and not safe under concurrent executions, so it is not a real substitute. If you genuinely cannot run Postgres, you can swap the Postgres nodes for SQLite or Redis equivalents - the SQL is plain and the modules only need atomic upsert-and-return. That variant is not shipped here and is not tested.
- **The spend cap is checked after the call, not before it.** It increments and then evaluates, so the call that crosses the cap has already happened. You are protected from the next hundred calls, not from the one that tipped you over.
- **Breaker reset is manual on purpose.** There is no half-open state, no automatic retry after a cooldown. A breaker that resets itself will trip, reset, and burn the same budget again while you sleep. Someone has to look at why it tripped.
- **The kill switch is only as fast as your check.** It is read at workflow entry. An execution already past the entry gate keeps running until its next iteration-budget check. It stops new work immediately, not work in flight.
- **Concurrency is handled by Postgres, not by n8n.** The counters use `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, which is atomic, so parallel executions cannot lose increments. But two executions can both read "under cap" in the same instant and both proceed. Expect the cap to be accurate to roughly one in-flight call per concurrent execution.
- **v1.** This is a first release. It is tested structurally (see `tests/`) and the cost math has unit tests, but it has not been running in production estates for a year. Read the SQL before you run it.

## Contributing

Issues and pull requests welcome, particularly: a Redis or SQLite state backend, cost-table updates with a source link, a Slack alert node wired into the alert sinks, and a Docker Compose example that stands up n8n plus Postgres plus this schema.

Before opening a PR:

1. Edit the workflow JSON, or edit it in n8n and re-export it into `workflows/`.
2. Run all three checks and paste the output in the PR:
   `python tests/validate_workflows.py && python tests/test_cost_math.py && python tests/test_validator.py`
3. Keep every Code node ASCII-only. The n8n public API rejects non-ASCII `jsCode`, and the validator will fail you for a smart quote pasted in from a document.
4. No credentials, no instance URLs, no client names in exported JSON. Exports carry a credential id; the placeholder `REPLACE_WITH_YOUR_POSTGRES_CREDENTIAL_ID` is what should be in the file.

---

Built by SkynetLabs (Waseem Nasir) - we build and monitor n8n estates for clients.
https://skynetjoe.com - https://calendly.com/skynetlabs/schedule-a-free-consultation

## License

MIT. See [LICENSE](LICENSE).

## Work with SkynetLabs

Built by [Waseem Nasir](https://www.skynetjoe.com/?utm_source=github&utm_medium=readme&utm_campaign=n8n-circuit-breaker-pack) at SkynetLabs — n8n + AI automation for small businesses.

- Hire on Fiverr: https://www.fiverr.com/agencies/skynetjoellc
- Hire on Upwork: https://www.upwork.com/freelancers/muhammadwaseemnasir
- Book a free call: https://calendly.com/skynetlabs/schedule-a-free-consultation
