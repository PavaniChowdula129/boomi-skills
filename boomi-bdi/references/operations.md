# Operating data flows day to day

Answer run-state questions across the environment — what ran, what failed, what's in flight — and apply lifecycle mutations (run/rerun, activate, disable, cancel) on the user's explicit approval. Reads are pure; every mutation should be confirmed with the user first. For diagnosing *why* one specific run failed, use `references/troubleshooting.md` — this file is the fleet-level view and the lifecycle actions, not root-cause analysis.

The shape: classify the question → pick a time window → fetch → present → (mutation) approve and act.

## Contents

- Classify the question
- Pick a time window
- Fetch the run state
- Present it
- Periodic health digest
- Mutations (on approval)
- Discipline

## 1. Classify the question

| Bucket | Trigger | Where it goes |
|---|---|---|
| **What ran** | "what ran today?", any time-scoped list | §3 fetch, §4 present |
| **What failed** | "any failures?", "what broke last night?" | §3 (env-wide scan), then offer the drill-in |
| **What's running** | "what's active?", "anything in flight?" | §3, filter to non-terminal runs |
| **Health digest** | "how's our pipeline health?", "weekly digest", "success rate", "what's failing most?" | §5 |
| **Drill into one failure** | "why did X fail?" | Hand off to `references/troubleshooting.md` |
| **Mutation** | "rerun X", "activate/disable Y", "cancel Z" | §6 |

## 2. Pick a time window

Run and activity queries require an explicit window — both `--from` and `--to`, `yyyy-mm-ddThh:mm:ss` (UTC). Choose it from the user's phrasing:

- Unscoped ("what's been happening?") → last 7 days.
- "today" / "right now" → last 24h.
- "last hour" → last 1h.
- "yesterday" → the prior UTC calendar day, `00:00:00` to the next `00:00:00`.

Keep the window tight on high-frequency and CDC flows — they accumulate many runs, so a wide window just forces pagination. Widen deliberately (a larger window or `--all`) only when a tight one turns up nothing.

## 3. Fetch the run state

Match the call to the scope of the question — and know that only one of these returns individual run records:

- **Environment-wide, per-flow rollup** — `bdi-flow.sh activities --from <ts> --to <ts>`. One call, **one aggregate row per flow**: per-status run *counts* for the window (`failed`/`succeeded`/`running`/`canceled`/`pending`) plus processing units and last-run time. It tells you *which* flows failed, ran, or are in flight — not the individual runs. Page with `--all`. Use this for every env-wide question; never loop run queries flow-by-flow (rate limit ~15 requests/minute).
- **Counts and processing units** — `bdi-flow.sh stats --from <ts> --to <ts> [--status <s>]` returns run-status counts (`succeeded`/`failed`/`canceled`/`skipped`/…) plus processing units, for one flow (with a flow-id) or the whole environment (without). Use it for "how many failed?" and cost questions.
- **One flow's individual runs** — `bdi-flow.sh runs <flow-id> --from <ts> --to <ts>`, newest-first, first page only. This is the only call that returns actual run records (run ids, start/end, per-run status). There is no env-wide run-by-run listing: to reach a specific run, take the flow from `activities` and drill into its `runs`.

Interpreting status: an individual run (from `runs`) is `pending`, `running`, then a terminal `succeeded`, `failed`, `canceled`, or `skipped` (treat `skipped` as terminal). "Failed" for these questions means `failed`, and `canceled` where the user cares about non-success; "running / in flight" means `running` or `pending`. In the `activities` rollup these are counts per flow rather than a status on a row. `partially succeeded` (two words) is a run-group aggregate, never a single run — read it via `bdi-flow.sh run-groups`. If a listing ever carries a status outside this set, show it verbatim rather than forcing it into a bucket.

## 4. Present it

Lead with the totals ("3 flows with failures, 40 clean, 2 running"). For an env-wide question, list the flows from the `activities` rollup — the ones with a non-zero `failed` count first — by title, with their counts; for a single flow, group its `runs` by status. Talk in flow titles, never ids. When the user wants to know *why* a flow failed, drill from its `activities` row into that flow's `runs`, pick the failed run, and hand off to `references/troubleshooting.md` — that's where root-cause analysis lives.

## 5. Periodic health digest

When the ask is a periodic summary rather than a point-in-time check — "how's our pipeline health?", "weekly digest", "success rate", "what's failing most?", "where are processing units going?" — give a fixed-shape read-only digest. Same `activities` call and the same no-fan-out discipline as above; only the presentation is standardized.

Window as §2, plus "weekly" → 7 days and "monthly" → 30; default 7 if unscoped. Echo the window in the digest, every time.

One `activities` call over the window (`--all` on busy environments) carries everything — derive it in place, never loop run queries per flow:

- **Success rate** — sum `succeeded` and `failed` across the flows; the rate is `succeeded / (succeeded + failed)`.
- **Top failures** — the 3 flows with the highest `failed` counts.
- **Top spend** — the 3 flows that consumed the most processing units.

Lead with the window and env-wide success rate ("Last 7 days: 94% of completed runs succeeded, across 40 flows"), then the two ranked lists — top 3 by failures, top 3 by processing units — by flow title. Keep it to a 30-second read: top 3 each unless the user asks for more.

To catch a spike, run a second `activities` call over the prior equal-length window and compare. Call it out when processing-unit spend is materially higher than the prior window (roughly 1.5×+) or the failure rate is above ~10%, and offer to dig into where the spend is going — see `references/cost_optimization.md` for the cost-reduction workflow.

If no flow ran in the window, don't render an empty digest — say so plainly and offer to widen the window or check a different environment. Follow-ups: "show me more" lifts the top-3 cap; "slowest flows" drills from a flow's `activities` row into its `runs` (§3) for per-run durations.

## 6. Mutations — on the user's explicit approval

Running, activating, disabling, and canceling all change live state. Do not run any mutation autonomously: state what the action will do — and for a run, that it writes to the target and consumes processing units — then wait for the user's go-ahead before calling. 

- **Run / rerun** — `bdi-flow.sh run <flow-id>` triggers a run and returns a `run_id`; there's no separate "rerun" — rerunning is just running again. Poll `bdi-flow.sh status <flow-id> <run-id>` until it reaches a terminal state, then report the outcome. A flow runs at most twice per minute. BDI allows only one run per flow at a time: a `run` issued while one is already in flight comes back `skipped` (terminal, not a failure) with a message naming the in-flight `run_id` — `cancel` that run and run again if you need to force a fresh one.
- **A disabled flow rejects `run`** with HTTP 400 (`"Data Flow <id> is disabled"`). Don't force it — tell the user it's disabled and offer to `activate` first, then run; let them decide.
- **Activate / disable** — `bdi-flow.sh activate <flow-id>` / `disable <flow-id>` toggle `river_status` and block until the operation settles, exiting non-zero if it fails. `activate` re-validates the source/target connections and can take minutes or fail (e.g. an unreachable connection); a failed activate leaves the flow disabled — surface the error, don't leave it silently down. Disabling a flow mid-run 400s — wait for the run to reach a terminal state first.
- **Cancel** — `bdi-flow.sh cancel <flow-id> --run <run-id>` (or `--run-group <id>`) is asynchronous and best-effort: it returns HTTP 200 accepting the request (completion can take a minute or two), and 400s (`"no runs found to cancel"`) if the run is already terminal. Confirm with `status` — but a cancelled run settles as terminal **`failed`** with `error_description: "Run canceled"`, not a `canceled` status. Read that as the successful cancel, not a new fault.
- **No dry-run** — there's no dry-run/validate-run endpoint. If a user wants to preview a run, offer the flow's recent run history (`runs`) and its processing-unit cost (`stats`) instead.

On any 4xx, render the API's `detail` and stop; don't retry blindly. On a rate-limit response back off — never retry in a tight loop. On an auth failure mid-mutation, stop immediately; don't retry.

## Discipline

- Flow/run **titles** to the user; **ids** only in script calls.
- For environment-wide questions use `activities` (one call); never loop run queries across flows.
- Reads (`activities`, `stats`, `runs`, `status`) are pure. Every mutation is shown and approved first.
- This file scans and operates; it does not diagnose. Root-cause work for a single failed run lives in `references/troubleshooting.md`.
