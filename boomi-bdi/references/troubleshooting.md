# Troubleshooting a failed data flow

Diagnose why a data flow (river) run failed, then — only on the user's explicit approval — apply a fix and rerun. Diagnosis is read-only; applying a fix is a mutation. Work the failure backwards from the evidence to a root cause, present a clear verdict citing that evidence, and act only when the user says to.

The shape: resolve the flow → find the most recent failed run → read the evidence → diagnose → (optional) surface a recent config change → (optional) apply the fix and rerun.

## Contents

- Resolve the flow
- Find the most recent failed run
- Read the evidence
- Diagnose from the evidence (failure categories; optional subagent)
- Recent config change (advisory)
- Apply the fix (on approval)
- Discipline

## 1. Resolve the flow

If you were already handed a flow `cross_id` and a `run_id`, skip to step 3.

Otherwise resolve the user's name to a flow with `bdi-flow.sh search` — it filters server-side (`--name`, `--query`, `--status`, `--type`) and is the fast path; prefer it over `list`, which paginates the whole environment. If the match is ambiguous, confirm the specific flow with the user before continuing. If nothing matches, widen the search terms or ask the user to restate the name.

## 2. Find the most recent failed run

```
bdi-flow.sh runs <flow-id> --from <ts> --to <ts>
```

Timestamps are `yyyy-mm-ddThh:mm:ss` (UTC). Start with a tight recent window (e.g. the last 24h); the listing returns newest-first, first page only. Read the returned `items` and pick the newest whose status is `failed` (or otherwise error-like). Keep the window modest on high-frequency and CDC flows — they accumulate many runs, so a wide window forces pagination and on very high-frequency or CDC flows may be rejected outright; widen deliberately (`--all` or a larger window) only when a tight one turns up no failure.

If there are no failed runs in the window, don't assume — tell the user the most recent run's actual status and offer to open a wider window.

## 3. Read the evidence

- **Run logs** — `bdi-flow.sh logs <flow-id> <run-id>`. CSV, header `timestamp,level,msg`, newest-first (not JSON). Focus on the ERROR-level lines. If the logs come back empty, don't dead-end: reason from the flow config, the run history, and `error_description` (below), and point the user to the run's page in the BDI console for anything the API didn't retain.
- **Failure reason** — `bdi-flow.sh status <flow-id> <run-id>` carries `error_description`, the target-side reason a run that was accepted then failed (acceptance is not success). Read it alongside the logs.
- **Logic flows** — `bdi-flow.sh steps <flow-id> <run-id>` gives per-step records; identify the *first* step that failed (its name and error), then `bdi-flow.sh step-logs <flow-id> <run-id> <step-id>`, which returns a short-lived URL to that step's log. If every step completed but the run failed, it's an outer/envelope failure — note that. An empty step list means it isn't a logic flow.
- **Flow config** — `bdi-flow.sh get <flow-id>` for the source/target/schedule context the error has to be read against.

## 4. Diagnose from the evidence

Work backwards from what you observed — `error_description`, the ERROR log lines, and (for a logic flow) the first failed step's `error_message` — read against the flow's config. Ground every claim in something concrete: a specific log line, a config field, or a prior run's outcome. State your confidence honestly — high when the logs are clear and consistent, low when they're empty or the pattern is unclear — and say so rather than guessing.

First rule out an intentional stop: a run that shows `failed` with `error_description: "Run canceled"` was cancelled, not faulted — report it as cancelled and stop, there's no root cause to find.

Common failure categories and how they surface:

| Category | Typical evidence in the logs / `error_description` | Typical fix |
|---|---|---|
| Source unavailable | "Connection refused", "Could not resolve host", source-side timeout | Source-side fix; rerun once it's back |
| Auth | 401 / 403, "credentials invalid" | Rotate the connection's credentials in the console; rerun |
| Schema drift | "Column X not found", "Type mismatch" | Edit the flow to add the column / resync schema; rerun |
| Rate limit | 429, "rate limit exceeded" (source or target) | Reduce schedule frequency, or wait |
| Quota | "Disk full", "storage quota", "credits exceeded" | Scale up the target; rerun |
| Downstream load | Target write errors, "table locked" | Check target health; rerun |
| Timeout | "Run exceeded N seconds" | Raise the timeout, or split the workload |
| Unknown | Empty logs, unclear history pattern | Hedge; recommend inspecting the run in the console |

For a logic flow, anchor the verdict on the named step that failed ("the `aggregate_by_region` step failed because …"), not on the flow as a whole, and scope the proposed fix to that step.

Where the failure needs authoritative detail beyond the logs, ground the diagnosis in the BDI llms.txt documentation rather than in assumption — see SKILL.md for the doc index:

- **Error codes.** A BDI failure often carries an `RVR-…` code (e.g. `RVR-ACTIVATE-400`); each code has its own reference page — issue summary plus action steps — in the docs' Error Messages section. Look up the exact code rather than reasoning from the message text alone.
- **Console-side option.** When you can't resolve it here, the BDI console has its own AI troubleshooting agent ("Help Me Fix It" on a failed run in the Activity view) — a reasonable handoff for the user, subject to their account having the feature enabled.

Present the verdict as: **root cause**, the **evidence** (quote the log line or `error_description` you're relying on), a **proposed fix**, and its **rollback**.

### A `succeeded` run that loaded nothing

`succeeded` doesn't prove data moved. A `source_to_target` run can finish `succeeded` with `units: 0` / `total_rows: 0` and the log `Done With Warning: All tables are currently running…` — success reported, nothing loaded. Extraction is tracked per `(connection, schema, table)`, not per flow: if that table is already marked loading (a sibling flow, an overlapping run, or a prior run whose tracking never cleared), the run finds nothing to extract and returns an empty success — table-scoped (a different table on the same connection loads fine) and repeatable until the table clears. So when a flow "succeeds" but the target isn't updating, check `units`/`total_rows` and the logs for that warning, then look for another loader on the same `(connection, schema, table)`; if none, the tracking is stuck — clear it in the console or wait for it to release before rerunning.

A source API that throttles or rate-limits mid-extract is another cause of a `succeeded` run that loaded only part of the data — one more reason to confirm row counts rather than trust run status alone.

### Optional: delegate the diagnosis to a subagent

If your agent platform supports subagents, consider running the diagnosis in one to keep the raw logs and flow config out of the main context. Gather the evidence first (steps 1–3), then hand it over with a self-contained prompt like:

> You are a read-only diagnosis specialist for a failed Boomi Data Integration (BDI, formerly Rivery — the ELT/data-pipeline product, distinct from Boomi Integration) data-flow run. You are given the run's `error_description`, its logs (CSV rows: timestamp, level, msg), the flow's configuration, its recent run history, and — for a logic flow — the per-step records (step name, status, `error_message`). Identify the single most likely root cause. Cite specific evidence for every claim: a log line with its timestamp, a config field, or a prior run's outcome. Do not speculate beyond the evidence; if the logs are empty, say so and lower your confidence. For a logic flow, anchor on the first step that failed and name it. Return: root cause (one sentence), the evidence chain, a proposed fix, its rollback, and a confidence level. Propose only — do not edit, run, or change anything.
>
> [paste the `error_description`, the log rows, the flow config, the run history, and the logic-step records]

The subagent only diagnoses; applying any fix stays with you, on the user's explicit approval (step 6).

## 5. Recent config change — context, never cause

After diagnosing, check whether a config change landed shortly before the failure: `bdi-flow.sh versions <flow-id>` lists saved versions newest-first with their author and timestamp. If the newest version's timestamp is within ~24h *before* the failed run started, surface it as advisory only:

> A config change by `<author>` landed ~`<n>`h before this failure.

Never claim it caused the failure — you haven't compared the change against the error. Offer the user the follow-ups: `bdi-flow.sh version <flow-id> <version-id>` fetches a version's full snapshot (compare two snapshots yourself if the user wants to see what changed), and `bdi-flow.sh restore <flow-id> <version-id>` rolls back — reversible, but it requires disabling the flow first and takes it briefly offline. See `references/versioning.md` §5 for the disable → restore → re-activate workflow, and §4 for the risk rubric when reading a diff.

## 6. Apply the fix — mutation, explicit approval only

Apply nothing until the user explicitly approves. Present the concrete change and its rollback first, then act.

- **Edit** — `bdi-flow.sh edit <flow-id> --body <file.json>` is a full-body PUT: `get` the flow, change only what the fix requires, put the whole body back.
- Some existing flows reject an `edit`, and the API's `detail` explains why: a 422 body's `detail` is an array naming each offending field by its `loc` path; a 400's `detail` is a plain string. Read it. If it's a field problem, adjust the body and retry; if the flow can't be edited through the API at all, hand the fix to the user to apply in the BDI console — don't force it.
- **Rerun** — after a successful edit, ask separately before rerunning. On approval, `bdi-flow.sh run <flow-id>` returns a `run_id`; poll `bdi-flow.sh status` until it reaches a terminal state, then confirm the fix held.

## Discipline

- Use flow/run **titles** when talking to the user; use **ids** only in script calls.
- Scope every call to the single flow and run. For an environment-wide question ("what failed today?"), use `bdi-flow.sh activities --from <ts> --to <ts>` — one call across all flows — never a per-flow loop.
- The platform rate-limits (~15/min). On a rate-limit response, back off; don't retry in a tight loop.
