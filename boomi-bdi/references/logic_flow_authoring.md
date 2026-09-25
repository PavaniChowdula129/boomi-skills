# Logic flow authoring

Body fields for a `logic` (`river_type`) data flow — an orchestration/transformation flow built from ordered steps that run SQL in the warehouse, Python on Boomi-managed servers, plus sub-flows and REST actions. Author the JSON body and create it with `bdi-flow.sh create --body <file.json>`; edit an existing one with `bdi-flow.sh edit <id> --body <file.json>` (a full-body PUT — see Editing a logic flow).

This reference carries the full step grammar, the per-warehouse target shapes, and a complete worked body, so a flow can be authored from scratch — you never need an existing flow to copy. Keep first creations bare-bones and confirm the result in the BDI console before building on them.

## Contents

- Choosing the flow shape
- Flow body structure
- Steps and containers
- Step target blocks (incl. table target by warehouse, advanced options)
- SQL steps and upsert keys
- `logicode` (Python) steps
- `run-river` steps
- `action` steps
- Variables
- Before you create
- Worked example
- Editing a logic flow

## Choosing the flow shape

Decide what the flow is for before filling fields — it drives which step types you assemble:

- **Transformer** — computes or reshapes data already in the warehouse (aggregations, rollups, staging, dedup). Built from SQL steps writing to target tables. The most common logic-flow shape; when a request is ambiguous, it is usually this.
- **Orchestrator** — coordinates other flows: runs a set of sub-flows in sequence or in parallel, with no SQL of its own. Built from `run-river` steps, often inside a parallel container.
- **Mixed** — both, in one flow (e.g. run a sub-flow, then aggregate its output).

A request that names a source connector to *replicate or ingest* ("sync X into Snowflake", "CDC from Postgres") is not a logic flow — it is `source_to_target` (see `source_to_target_authoring.md`). Logic flows operate on data already landed in the warehouse or orchestrate other flows.

If your agent platform supports subagents and the user prefers that workflow, you may offer to run the shape-classification and step-decomposition in one. It is optional — authoring is interactive, and the surrounding session context is usually an advantage, so default to reasoning through it inline.

## Flow body structure

A logic-flow create body requires, at the top level: `name`, `type` (`"logic"`), `metadata`, `settings`, and `properties.logic_steps[]` with at least one entry. Omitting `metadata` fails with HTTP 422 (`missing body.metadata`).

- `kind` is optional — the server defaults it to `"main_river"`; it need not be sent.
- `metadata` carries `{description, river_status}` (`river_status`: `active` | `disabled`). A logic flow comes up `active` regardless of the `river_status` sent at create — `disabled`, `active`, and omitted all create `active` — so don't rely on `river_status` to create a paused flow; call `bdi-flow.sh disable` after create and confirm with `get`.
- `settings` carries `run_timeout_seconds` (integer; 43200 = 12h is a common default) and an optional `notification` block, whose `warning` / `failure` / `run_threshold` sub-blocks each take `{email, is_enabled, execution_time_limit_seconds}`.
- `schedulers[]` is an array of `{cron_expression, is_enabled}` — cron times are interpreted in UTC. Schedule off-peak for periodic loads (e.g. `0 6 * * *`); reserve minute-level frequency for genuinely continuous work. Because a new flow comes up `active`, a scheduler with `is_enabled: true` can begin running the moment the flow is created — leave it `false` until you have verified the flow (or `disable` the flow right after create), then enable it.
- `properties` carries `properties_type: "logic"` and `logic_steps[]`.
- Omitting top-level `group_id` is accepted and the flow runs normally. Set `group_id` explicitly when the flow needs to belong to a particular group — copy it from an existing flow (`bdi-flow.sh get <id>` → its 24-character `group_id`); which group an omitted one lands in is not something to rely on. Groups can only be created/renamed in the console (see SKILL.md → Platform behavior).

## Steps and containers

Each entry in `logic_steps[]` is either a **step** (a unit of work) or a **container** (a group of steps). Both can appear at the top level — steps need not be wrapped in a container unless you want grouping or control flow.

Every step and container carries `name`, `is_enabled` (real on/off toggle), and `disable_errors` (continue past errors — see the warning under Before you create). A step also carries a `type` discriminator; type-specific fields follow.

**Omit `step_id` and `container_id`.** The server assigns them (a 32-character id) when absent. A supplied value is persisted verbatim and **not** validated or overwritten — a hand-written, guessed, or duplicated id sticks unchanged, creating a collision risk. Always let the server assign them. (When editing an existing flow, the opposite applies — preserve the ids already present; see Editing a logic flow.)

Containers (`type`):

- `run_once` — runs its `steps[]` once. `is_parallel: true` runs them concurrently (use for orchestrator fan-out where sub-flows have no data dependency); `false` (default) runs them in order.
- `loop` — repeats its `steps[]` once per item in a list. `loop_over_value` (a string) must be a variable or expression that **resolves to a real list at run time** — an inline array literal like `["a","b"]` is not parsed, and the run fails echoing the raw value back; feed it from an upstream step that writes a variable (a SQL step with `target_type: "variable"`) or a dataframe. `loop_over_variable_name` is a **list of strings** — the variable name(s) each iteration binds to the current item. Use a loop to run the same work across dates, accounts, or regions, or to page a REST action over a list of offsets.
- `condition` — branches. Its `steps[]` are inner branches, each `{condition, action, is_else, condition_name, step}`, where `condition` is `{operator, operand_1, operand_2}`. Known `operator` values are `equals`, `greater_than`, `lower_than`, and `exists`. **The API does not validate `operator`** — an unrecognized value is accepted at create and the run still completes, but the comparison silently evaluates false and the branch never fires, so use one of the four exactly. `action` is one of `run_step` (execute the branch's step), `skip_container` (skip it), `stop_river` (halt the flow cleanly), or `fail_river` (terminate with failure); set `is_else: true` on a branch to handle the else case. Each branch runs a **single** `step` — to run several steps under one branch, make that step a `run_once` container.

Containers nest: a container's `steps[]` may itself contain containers.

## Step target blocks

The field that names where a step writes depends on the step family — this distinction is enforced server-side:

- A **SQL query** step (`*_sql_query`) writes its result through `target_settings`, keyed by a `target_type` discriminator: `table`, `variable`, `dataframe`, or `files_export` (file zone). Availability varies by warehouse — `table` and `variable` are universal and `files_export` is broadly supported; `dataframe` is Snowflake/Redshift-only (Postgres, for one, rejects it).
- A **dataframe** step (`*_dataframe`, e.g. `snowflake_dataframe`) instead uses `target_properties`. Sending `target_settings` on a dataframe step is ignored and the create fails with HTTP 422 for the missing `target_properties`. Dataframe steps exist only for Snowflake and Redshift, and their table target supports `append_only` and `overwrite` only — not `upsert_merge` (use a SQL query step to upsert).
- A **SQL script** step (`*_sql_script`) has no target block — it is free-form DDL/DML.

Every `table` target (`target_type: "table"`) carries `table_name` and `loading_mode`, plus warehouse-specific location fields (below). Note the `_name` suffixes — the wire fields are `database_name`/`schema_name`/`table_name`, not `database`/`schema`/`table`. `target_type: "variable"` writes to a variable (`variable_name`, `variable_type`: `river` | `environment`); `target_type: "dataframe"` writes to a named dataframe (`dataframe_name`) — which must already exist (create it with `bdi-dataframe.sh add`), or the step fails at run (`Dataframe name … not exist`) — and also carries `database_name`/`schema_name` for its staging table; with `schema_name` unset, staging defaults to `<database>.PUBLIC` and the run fails if that schema is absent or unauthorized, so set it to the connection's schema. A file-export target (`target_type: "files_export"`) writes to a file zone (S3 / GCS / Azure Blob) and carries `bucket_name`, `file_path`, `connection_id`, and `file_settings`.

### Table target by warehouse

The SQL step type is `<prefix>_sql_query` / `<prefix>_sql_script`, and the connection must be of the matching warehouse type. Location fields are in addition to `table_name` + `loading_mode`:

| Warehouse | Prefix | Location fields |
|---|---|---|
| Snowflake | `snowflake` | `database_name`, `schema_name` |
| BigQuery | `bigquery` | `dataset_id` |
| Redshift | `redshift` | `schema_name` |
| Postgres | `postgres` | `schema_name` |
| Azure SQL | `azure_sql` | `schema_name` |
| Azure Synapse | `azure_synapse` | `schema_name` |
| Databricks | `databricks` | `catalog`, `schema_name` |
| Athena | `athena` | `schema_name`, `bucket_name`, `file_path` |

### Advanced table-target options

All optional and warehouse-specific; omit unless the workload needs them:

- **BigQuery** — `partition_properties` (`{partition_by: "timestamp", partition_granularity: YEAR|MONTH|DAY|HOUR}`) and `split_tables_properties` (either `{split_by: "insert_timestamp", interval: YEAR|MONTH|DAY|HOUR}` or `{split_by: "expression", expression: "<sql>"}`). BigQuery also carries four query flags on the **step** (not the target): `use_standard_sql`, `query_priority`, `maximum_billing_tier`, `flatten_results`.
- **Athena** — `partition_properties` (`{partition_by: "timestamp"|"date", partition_granularity: HOUR|DAY|MONTH|YEAR}` or `{partition_by: "none"}`) and `number_of_buckets` (int).
- **Redshift** — `distribution_method`: `all` | `even` | `key`.
- **Azure Synapse** — `distribution_method`: `round_robin` | `hash` | `replicate`; `table_type`: `columnstore` | `rowstore`.
- **Databricks** — `custom_location`: `{use_custom_location, location_type: DBFS|EXTERNAL, location}`.
- **Snowflake** — `enforce_masking_policy` (bool). **Postgres** — `analyze_tables` (bool).
- **Upsert (any warehouse)** — `merge_settings`: `{merge_method, is_ordered_merge, order_expression}`; `merge_method` must be one the warehouse supports (see SQL steps and upsert keys).

## SQL steps and upsert keys

A SQL query step's `target_settings.loading_mode` is one of `append_only`, `overwrite`, or `upsert_merge`. For `append_only` and `overwrite`, no column mapping is needed — the step is complete with just the target table fields above. `upsert_merge` additionally requires a key.

An `upsert_merge` step is **accepted at create with no key column** but then **fails at run** (`"please set keys for Upsert-Merge process"` / `"no merge keys selected"`): the logic-flow auto-mapping pass does not populate a merge key. Declare `target_settings.fields[]` (non-empty) with at least one column flagged as a key. Each entry is `{"fieldName": "<column>", "type": "<TYPE>", "isKey": true|false}`. `type` is required on every entry and is emitted as a SQL cast (`<column>::<TYPE>`), so it must be a type the target warehouse recognizes — `STRING` is portable (translated to the warehouse's string type, e.g. `VARCHAR`), but warehouse-specific names do not cross over (Snowflake's `NUMBER` is not a Postgres type — use `INTEGER`/`NUMERIC` there). On Snowflake a bare `NUMBER` cast defaults to scale 0 and silently truncates decimals — type fractional values (averages, rates) as `FLOAT` or an explicit `NUMBER(p,s)`. The key flag is `isKey` (camelCase, matching the console's Column Mapping); snake-case `is_key` is also accepted. Use a NOT NULL column for the key (a nullable key can't match — NULL never equals NULL). Where the warehouse supports it, `mapping_order` lists the projected column names in order.

An upsert also needs a merge method the warehouse supports, in `target_settings.merge_settings.merge_method`: Snowflake accepts `merge` / `delete_insert` / `switch_tables`; Postgres accepts `delete_insert` / `insert_on_conflict` (not `merge`). **Always set this explicitly on a non-Snowflake upsert.** If you omit `merge_settings`, the server injects the Snowflake default `merge_method: "merge"`, which a non-Snowflake warehouse cannot run and which fails at run with `Unsupported Merge Method`. The per-target merge-method sets are in `source_to_target_authoring.md`.

A SQL **query** step (`*_sql_query`) runs a single `SELECT` — the platform manages the target table from the result shape, so no `CREATE`/`ALTER TABLE` is needed. A SQL **script** step (`*_sql_script`) runs free-form statements (`UPDATE`, `CREATE`/`ALTER`/`DROP TABLE`, `INSERT INTO`, `COPY`, multi-statement) and has no target block; on Snowflake it defaults `auto_commit: true`.

When authoring the SQL body:
- Use `/* */` block comments, not `--` line comments — a `--` comment is treated as commenting out everything after it, dropping the rest of the statement.
- Escape any colon as `\\:` (e.g. in a `::` cast or a time literal) — an unescaped `:` fails the flow.
- Snowflake SQL query steps do not support the platform's `WITH` clause (CTEs).

`bdi-flow.sh step-logs` serves `logicode` steps only; a SQL step returns HTTP 400 `Invalid step type <block_type>` — read its failure from the run's `error_description`.

## `logicode` (Python) steps

A `logicode` step runs Python. It references its code by `file_id` (an uploaded code file), and carries `code_type` (`python`), `logicode_size` (`XS`, `S`, `M`, `L`, `XL`, `XXL`), and optional `additional_packages[]` — there is no inline code in the body.

Upload the Python file with `bdi-logicode.sh upload <file>`, which prints the `file_id` to set on the step. Read an uploaded file's source with `bdi-logicode.sh read <file_id>`; fetch the starter template and generic requirements file with `bdi-logicode.sh template` / `requirements`. Point a step at an existing flow's `file_id` (from its `get`) only to reuse that same code.

## `run-river` steps

A step that runs a sub-flow is `type: "river"` and requires `name`, `type`, and `river_id`. Resolve the sub-flow's `river_id` with `bdi-flow.sh search`/`list`.

Input variables passed to the sub-flow go in `input_variables`, a flat map keyed by variable name, and each value must be **wrapped as an object** — `{"value": <actual>}`, e.g. `input_variables: {"region": {"value": "us-east"}}`. A bare value (`{"region": "us-east"}`) is accepted when the flow is created but fails at *run* (`'str' object has no attribute 'get'`) — the runtime reads each value as an object. Wrap every value.

Chaining sub-flows this way is how you enforce order between dependent flows — run the upstream source-to-target flow and the downstream logic within one orchestration so the second starts only after the first finishes. Scheduling two dependent flows independently by clock time can overlap: on any run where the upstream is still going, the downstream reads stale or partial data.

## `action` steps

A step that calls a REST Action is `type: "action"` and requires `action_id`, plus a `connection_id` and any `input_variables` / `output_variables` / `interval_variables`. The `action_id` identifies a published Action flow in the account — resolve it from the live account (Action-type flows), never invent it. The action flow's definition — the REST call itself (endpoint, method, auth, pagination) — is not modeled in the flows API in either direction, so action flows are authored in the BDI console and referenced here by `action_id`.

## Variables

- Variable references use single-brace syntax: `{name}`, and the **same** `{name}` works for every variable class — flow (river), environment, and step-output alike. When the value is a string, quote the reference in the SQL — `WHERE col = '{name}'`. Do not double-brace (`{{name}}`) and do not use the long form `{variable:name}` — neither substitutes; both stay literal in the query.
- Scope: a **flow (river) variable** passes a value between steps within one run; an **environment variable** is account-level and shared across flows; a **step-output variable** is one a SQL step publishes via `target_type: "variable"` for a later step to read (this is also how a `loop` gets its list). A variable holding a list is a multi-value variable ("Contains Multiple Values").
- Environment variables are declared as a bare `name: value` map (no sigil on the key).
- Flow-level variable *declaration* is a separate flow-variables sub-resource managed with `bdi-variable.sh river-set`, shaped `{"items": [{"name": ..., "settings": {...}, "value": ...}]}` (see `river-set --help`; the flat `{"variables": {...}}` shape belongs to `env-set`) — it is not part of the create body. `river-set` replaces the whole set, so to add one variable to an existing flow, read the current set with `river-get --all`, merge every envelope's `items` into one body, append yours, and send that.

## Before you create

A quick pass over the body catches the failure modes above — several are accepted at create (HTTP 200) and only bite at the first run, some with misleading symptoms:

- Top-level `group_id` is set explicitly when the flow must belong to a particular group (omission is accepted and runs fine).
- A dataframe step uses `target_properties`; a SQL query step uses `target_settings` (mixing them → HTTP 422 at create).
- An `upsert_merge` step declares at least one NOT NULL key column in `fields[]` (a keyless upsert creates fine but fails at run).
- Each SQL step's `connection_id` matches the step's warehouse type — a Postgres connection on a `snowflake_sql_query` step is accepted at create but fails at run with a warehouse SDK error.
- `disable_errors: true` is set only on genuinely optional steps (cleanup, notification). On a step that writes to a table it suppresses the operator-visible failure — the overall run still reports `succeeded` with no alert — while the target table is left with partial or no data, and the partial write is not rolled back. Move optional cleanup into a step that writes to a variable, not a table.
- SQL uses `/* */` comments, not `--`; colons are escaped as `\\:`; no `WITH` clause on Snowflake query steps.
- `step_id` / `container_id` are omitted (server-assigned).

A 422 names the offending field precisely (`{"detail":[{loc, msg, …}]}`) — read it; a 422 does not commit, so a rejected create leaves nothing behind.

## Worked example

A minimal single-step transformer on Snowflake — aggregate `raw_events` into `daily_counts` on a daily schedule. It will be created `active`, but the scheduler is left `is_enabled: false` so it won't run on its own; verify the flow, then enable the schedule (and `disable` the flow meanwhile if you want it fully paused):

```json
{
  "name": "Daily Counts Rollup",
  "type": "logic",
  "group_id": "<24-char group id, copied from an existing flow>",
  "metadata": {
    "description": "Aggregate raw_events into daily_counts"
  },
  "settings": {
    "run_timeout_seconds": 43200,
    "notification": {
      "failure": { "email": "you@example.com", "is_enabled": true, "execution_time_limit_seconds": null }
    }
  },
  "schedulers": [
    { "cron_expression": "0 6 * * *", "is_enabled": false }
  ],
  "properties": {
    "properties_type": "logic",
    "logic_steps": [
      {
        "name": "aggregate_daily_counts",
        "type": "snowflake_sql_query",
        "is_enabled": true,
        "disable_errors": false,
        "connection_id": "<snowflake connection id>",
        "sql_query": "/* aggregate raw_events into daily_counts */\nSELECT event_date, COUNT(*) AS event_count\nFROM DEMO_DB.PUBLIC.raw_events\nGROUP BY event_date",
        "target_settings": {
          "target_type": "table",
          "database_name": "DEMO_DB",
          "schema_name": "PUBLIC",
          "table_name": "daily_counts",
          "loading_mode": "overwrite"
        }
      }
    ]
  }
}
```

To orchestrate instead of transform, replace the SQL step with `run-river` steps (each `{name, type: "river", river_id}`) inside a `run_once` container (`is_parallel: true` for concurrent fan-out).

## Editing a logic flow

`bdi-flow.sh edit <id> --body <file.json>` is a full-body PUT with no server-side merge — the body you send replaces the flow. Read-modify-write: `bdi-flow.sh get <id>`, change only what you need, and PUT the whole body back.

- **No field-stripping needed.** A verbatim `get` → modify → PUT is accepted as-is — the server-owned fields the `get` returns (`cross_id`, `account_id`, `environment_id`, …) are valid on write. The body model is strict in the other direction: do not *add* a key the `get` didn't return — an unknown key is rejected with HTTP 422 `extra_forbidden`.
- **Preserve existing `step_id` / `container_id`.** Unlike a fresh create, an edit must keep the ids the server already assigned — changing or dropping one re-creates the step rather than editing it. Verify they survive the roundtrip.
- **One operation at a time.** Make a single change (rewrite one step's SQL, add a step, remove a step, reorder within a container), confirm it, then move to the next — rather than batching several edits into one PUT. Removing the only remaining top-level step is rejected (the flow requires at least one). Moving a step between containers is a remove-then-add, not a reorder.
- **Approval for live flows.** The `create` for a greenfield flow the user just asked for needs no separate confirmation. Everything else does — the other writes in that same build (`activate`, `disable`, `bdi-dataframe.sh add`, `bdi-variable.sh river-set`) and any `edit` to a flow already deployed and in use, since that alters something running in production: show the change and confirm before the PUT. See SKILL.md "Mutations: confirm before writing" for the full write surface.

Editing is only available on API-authored (`is_api_v2:true`) flows; a legacy or kit-installed flow must be rebuilt as a new v2 flow (see SKILL.md → Platform behavior).
