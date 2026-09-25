# Cutting data-flow cost

Find the highest-leverage ways to reduce a BDI environment's consumption, then — only on the user's explicit approval — apply one change at a time. The analysis is read-only; every reduction is a mutation. The metric throughout is **processing units** — labeled **Boomi Data Units (BDU)** in the console today and **Rivery Pricing Units (RPU)** in older material, and returned as the `units`/`rpu` figure on each flow (see SKILL.md terminology). Rank by it, estimate savings against it, and talk in it, mapping whichever label the user uses (BDU, RPU, "credits") onto the same metric.

The shape: scope the environment → gather the spend signal in one call → rank the opportunities → apply one, on approval, and offer the next.

## Contents

- Scope first on large environments
- Gather the spend signal
- Rank the opportunities
- Apply one at a time (on approval)
- Discipline

## 1. Scope first on large environments

On a large environment don't analyze cold — a wide read strains the rate limit (~15 requests/minute) and buries the signal. Above roughly 1000 flows, ask the user to scope first: a Data Flow Group, a name prefix, or the specific flows they care about. `activities` and `search` filter by group (`--group <group-id>`; `list` also takes `--group-name`), and `search` filters by `--name`/`--query`. Wait for the scope, then continue against that subset.

## 2. Gather the spend signal

One `activities` call carries everything the ranking needs — the same call the health digest uses (`references/operations.md` §5), no fan-out:

```
bdi-flow.sh activities --from <ts> --to <ts>
```

Use a ~30-day window (`--all` on busy environments) so a flow's spend reflects a full billing-relevant period. Each row is one flow with, for the window: per-status run counts (`failed`/`succeeded`/…), processing units (`units`/`rpu`), bytes and files moved (`total_size`/`total_files`), last-run time (`last_run`), and whether it runs on a schedule (`is_scheduled`). Rank the rows by processing units, descending — that spend ranking is where every recommendation starts. Never loop run queries flow-by-flow to build this; the one aggregate call is the whole picture.

## 3. Rank the opportunities

Which lever matters most depends on how the flow is billed. BDI's consumption model has two bases (current rates and plan differences: `https://help.boomi.com/md/docs/Atomsphere/Data_Integration/Administration/Pricing/pricing-faqs.md`):

- **Application (API) sources** bill **per execution, per output table** — including executions that find no new data. Schedule frequency is the dominant lever; per-run data volume mostly isn't (high-frequency-sync sources flip to volume billing).
- **Database and file sources** bill **by data transferred** (pro-rata, independent of frequency; log-based CDC at a higher rate). Data volume is the dominant lever — which is what makes a full reload expensive and incremental extraction the fix.
- **Logic flows** bill a flat rate **per execution**. SQL steps push down to the warehouse — BDI doesn't bill that compute; it lands on the warehouse's own bill. Python steps run on Boomi-managed servers and do bill for their compute (execution time × server size, plus network).

A run's `pricing_category` (on its `runs` record) names the rate class it was billed under (e.g. `rdbms`, `logic`).

Two red flags fall straight out of the aggregates. The other two levers need you to open a top spender's config with `bdi-flow.sh get <flow-id>` — the activity row can't see a schedule's cadence or how a flow extracts. The ranking can also surface since-deleted flows: the activity rollup keeps their history, so a ranked flow whose `get` returns 404 no longer exists — skip it, that spend can't recur. Work down the spend ranking and check each flow against these:

| Opportunity | Signal | Why it costs | Fix |
|---|---|---|---|
| **Chronically failing schedule** | scheduled, and `failed` high with `succeeded` at or near zero over the window | fires on schedule without ever landing data — whatever it consumes is pure waste | diagnose and fix (`references/troubleshooting.md`), or disable if the flow is unwanted |
| **Succeeds but moves no data** | `succeeded > 0` and `units > 0` but `total_size == 0` | spends units yet loads no rows — usually a misconfigured or pointless flow | surface only — a human has to judge it; never auto-apply |
| **Over-frequent schedule** | a high spender whose schedule (from `get`) runs far more often than its source data actually changes | on a per-execution-billed (API) source, every run bills — even one that finds nothing new | reduce the schedule frequency |
| **Full load that should be incremental** | a high spender on a sizable table whose per-table `extract_method` (`tables[].details`, from `get`) is `all` | re-transfers the whole source every run — dominant on volume-billed (database/file) sources | switch to incremental extraction, if the source supports it (`references/source_to_target_authoring.md`) |

Estimating savings: treat the observed window units as the recurring spend — disabling a flow saves roughly its window units; halving a schedule saves roughly half; moving a full load to incremental saves in proportion to how little of the source changes between runs. Keep every figure explicitly rough — it's observed spend, not a billing calculation — and say so when you present it. Present the top handful — up to five, ranked by estimated saving — and offer the rest on request rather than dumping every observation.

Per-flow drill-in: for a multi-table flow, `bdi-flow.sh targets <flow-id> --sort-by units --sort-order desc` ranks the destination tables by spend so you can see which table inside the flow drives the cost. `--sort-by` is a server-side sort applied before pagination, so it surfaces the true top table on the first page rather than only sorting what one page happened to return.

### Optional: delegate the ranking to a subagent

If your agent platform supports subagents and the activity set is large, run the ranking in one to keep the raw per-flow rows out of the main context. Gather the `activities` rows first (step 2), then hand them over with a self-contained prompt like:

> You are a read-only cost analyst for a Boomi Data Integration (BDI, formerly Rivery — the ELT/data-pipeline product, distinct from Boomi Integration) environment. You are given one row per data flow for a ~30-day window: per-status run counts, processing units consumed (`units`), bytes moved (`total_size`), last-run time, and whether it is scheduled. Rank the flows by the highest-leverage cost reductions, weighing levers by billing basis: application (API) sources bill per execution per output table (even executions that find nothing); database/file sources bill by data volume; logic flows bill per execution. Consider: chronically failing scheduled flows (high `failed`, `succeeded` near zero); flows that succeed but move no data (`total_size == 0` with `units > 0`); and — flagging them as needing the flow's config to confirm — likely over-frequent schedules and likely full loads that should be incremental, among the top spenders. For each recommendation give: the flow, the category, the rough estimated monthly units saved (from the observed window spend — state it as an estimate), the risk of applying it, and the evidence from the row you relied on. Do not invent flows or savings beyond the data. Propose only — do not edit, run, or change anything.
>
> [paste the activity rows]

The subagent only ranks; applying any change stays with you, on the user's approval (step 4).

## 4. Apply one at a time — on the user's explicit approval

Never bulk-apply, and never apply autonomously. Present one change — the flow, the lever, the rough saving, its risk, and how to reverse it — wait for the go-ahead, apply it, confirm the outcome, then offer the next. Each opportunity maps to one apply path:

- **Disable a dead or unwanted flow** — `bdi-flow.sh disable <flow-id>`. Reversible with `activate`. See `references/operations.md` §6 for the disable/activate semantics (a failed activate leaves the flow down; don't disable mid-run).
- **Reduce a schedule's frequency** — an `edit`: `get` the flow, lower the frequency in its schedule, and put the whole body back (a full-body PUT, no partial patch). Read the schedule fields from the flow's own body rather than assuming a shape.
- **Full → incremental** — an `edit`, but really an authoring change, and the most involved of these. First confirm the source connector supports incremental extraction — not every source does. Then design the change with the user, not just apply it: the cursor column and how re-extracted rows merge into the target both need their agreement, because the wrong cursor silently misses rows — worse than the cost it saves. Field shapes and mechanics live in `references/source_to_target_authoring.md` ("Incremental extraction", "Match/merge keys").
- **Succeeds but moves no data** — never auto-apply. Surface it and let the user investigate; it usually points to a misconfigured source or a flow that should be retired, and only they can decide which.

On a 4xx, render the API's `detail` and stop — a 422 names the offending field; a legacy (`is_api_v2:false`) flow rejects `edit` and must be rebuilt as v2 (see SKILL.md Platform behavior). Don't retry blindly.

## Discipline

- Processing units (`units`/`rpu` on the activities row) is the cost metric — see SKILL.md terminology; talk in it, not in raw run counts.
- One `activities` call covers the whole environment; never loop run queries per flow.
- Analysis is read-only. Every reduction is shown, approved, and applied one at a time — never in bulk, never unprompted.
- Reductions are reversible — `disable` undoes with `activate`, and an `edit` can be rolled back from version history (`references/versioning.md`) — but that reversibility is not license to apply them casually or autonomously: each stops a running pipeline or changes what data lands, with real downstream consequence. Say so when you propose one — reversible, not casual, and never without approval.
