# Source-to-target (ELT) flow authoring

Body fields for a `source_to_target` (`river_type`) data flow — the source→warehouse/lake ELT pattern. This reference carries the field grammar to author a body from scratch; you do not need an existing flow to copy. Assemble the JSON and create it with `bdi-flow.sh create --body <file.json>`. The body requires a top-level `metadata` object (e.g. `description`) — omitting it fails with HTTP 422 (`missing body.metadata`); its `river_status` is ignored here, since a new source-to-target flow is forced `disabled` at create (see Create-time behavior). Keep first creations bare-bones and confirm the result in the BDI console before building on them.

## Contents

- Choosing extraction and load modes
- Load-shaping patterns
- Source schema discovery
- Connector discriminator
- Source run type
- Load-mode fields
- `extract_method` (extraction)
- `merge_method` (load strategy)
- Incremental extraction
- Match/merge keys
- Target types
- File-zone (S3) targets
- Rivery metadata columns
- Schema drift
- PostgreSQL RDS load mechanism
- Create-time behavior
- Recipe (Blueprint) REST sources
- Before you create or activate
- Worked examples

## Choosing extraction and load modes

Decide the flow's shape before filling fields.

Extraction follows the source table. No column that reliably marks when a row last changed → full extract (`extract_method: all`) every run; incremental is not available. A reliable high-water column — an `updated_at`/`modified` timestamp, or a monotonic id — → incremental (`extract_method: incremental`) keyed on it. Where the source exposes a change stream, log-based CDC (`extract_method: log`) is the real-time option (see `cdc.md`).

Change volume tempers that choice, because incremental carries per-run overhead. As rough guidelines, not platform thresholds: below ~5% of rows changing per run, incremental with a keyed merge; ~5–30%, incremental extraction rebuilding the affected partitions; above ~30%, a full reload is usually cheaper than incremental.

Load mode follows intent: a current-state table → `merge` on a key (upsert); an immutable event or log stream → `append`; a disposable full refresh → `overwrite`. Field-level mechanics for each are below.

Schedule via the top-level `schedulers[]` array — each entry `{cron_expression, is_enabled}`, a 5-field cron interpreted in UTC. Schedule off-peak for periodic loads (e.g. `0 2 * * *`) to avoid warehouse contention; reserve minute-level frequency for CDC. Since a new source-to-target flow is created `disabled` (below), an enabled schedule only begins firing once the flow is activated.

## Load-shaping patterns

Common target-shaping patterns and what each requires. If the target lacks a pattern's required columns, flag the gap to the user rather than silently applying the pattern.

| Pattern | Use when | Requires on the target |
|---|---|---|
| SCD Type 1 (latest only) | keep only each row's current value | natural key |
| SCD Type 2 (history) | prior versions must be preserved | natural key + `valid_from` + `valid_to` + `is_current` |
| Deduplication | source delivers duplicate rows | a dedup key |
| Late-arriving updates | source revises rows after first load | `updated_at` + merge predicate on the key |
| Merge by `updated_at` | high-volume incremental current-state | `updated_at` + natural key |
| Idempotency | source can redeliver the same event | a dedup/event key |

SCD-1, deduplication, late-arriving, and merge-by-`updated_at` are expressed through the keyed `merge` load below. SCD-2 additionally needs the flow to populate the history columns on the target — confirm they exist before choosing it.

If your agent platform supports subagents and the user prefers that workflow, you may offer to run this design step in one. It is optional — authoring is interactive, and the surrounding session context is usually an advantage, so default to reasoning through it inline.

## Source schema discovery

`tables[].details.modified_columns[]` carries the source table's columns. Read them from the source with `bdi-connection.sh columns <connection-id> --datasource <api-name> --schema <schema>`, which returns every column of every table in the schema — see `references/data_discovery.md` for its inputs and the fields it returns. `bdi-connection.sh tables` is not a substitute: it returns only cursor-eligible columns (see Incremental extraction), so text and boolean columns never appear. Where `columns` doesn't cover a source, take the column names from the user or the source's DDL, or build that source in the console once and pull the flow with `bdi-flow.sh get` to operate from here (the console-then-pull fallback Blueprint sources use, below).

## Connector discriminator

The source and target connector types are set by a discriminator `name` — `properties.source_to_target.source.name` and `.target.name` — which must be the lowercase `api_name`, not the title-cased label `bdi-connection.sh list` shows (e.g. `mysql`, not `MySQL`). A non-canonical value is rejected with HTTP 422 `union_tag_invalid`. The top-level `source.name` propagates into the per-table discriminator at `schemas[].tables[].details.additional_source_settings.source_type`, so a bad top-level value surfaces as a per-table error there. Take the canonical name from `bdi-connection.sh source-types`/`target-types` (which return `api_name`s), not from the connection `list` label.

To resolve the discriminator for a specific connection, match its `connection_type` (the machine slug from `bdi-connection.sh get`, or `connection_type_id` from `list`) against the `connection_type` of a `source-types` entry whose `segment` includes `source`, and take that entry's `api_name`. The slug is frequently not the `api_name` — `snowflake_src` resolves to `snowflake` — and one slug can carry both a source and a target entry (a `postgres` connection resolves to the source entry's `postgresql`, not the target-only `postgres_rds`), which the `source` segment filter disambiguates. A slug whose only entries lack the `source` segment is target-only and has no source discriminator.

The source name for PostgreSQL is `postgresql`, spelled out — distinct from the target-side `postgres_rds`. The two run types accept different, barely-overlapping source-name sets, so resolve the name for the run type you are authoring (see Source run type); a name from the wrong set is rejected with HTTP 422 listing the supported one. An entry with a null `api_name` (Treasure Data, Firebolt) has no discriminator and cannot be named in a flow body.

## Source run type

A native database source uses `source.run_type: multi_tables` (the common case). Custom-report SaaS and file sources (Shopify, S3, GCS, email, FTP/SFTP and many more) use `run_type: regular` — any unrecognized value collapses to `regular` — and in that mode `source.additional_settings` must omit `cdc_override`, `connection_id`, `datasource_id`, and `run_type`; any of them there is rejected with HTTP 422 (`Fields: '…' should not be in additional_settings for run_type='regular'`, naming the offending keys present). Keep it `{}`. A `regular` source loads into a single output table named by `target.table_name` on the target block and has no per-table `schemas[]` selection — where a `multi_tables` source enumerates its tables under `schemas[]`, a `regular` source names its one table on the target.

The top-level `run_type` propagates to the per-table discriminator `run_type_and_datasource`, whose valid tags are `multi_tables` and `predefined_report`: a native table block is tagged `multi_tables`, a custom-report table block `predefined_report`.

## Load-mode fields

Three distinct fields carry the load configuration; they are not interchangeable, and the older `load_type` / `full_load` / `incremental` / `append` vocabulary does not appear in these bodies:

- `extract_method` — how rows are read from the source.
- `loading_method` — how rows are written to the target: `overwrite`, `append`, or `merge`.
- `merge_method` — the merge/load strategy when `loading_method` is `merge`.

An insert-only (append) load paired with incremental extraction never updates existing rows — each changed source row lands as an additional row, so the target retains every historical version and grows without bound. That is correct for an append-only event/log table; for a current-state table use `merge` with a key column instead.

## `extract_method` (extraction)

Enum: `all`, `incremental`, `log`, `change_tracking`, `system_versioning`. Any other value is rejected with HTTP 422 (it is not silently demoted). `log` selects log-based CDC — see `cdc.md`.

`extract_method` appears in two places in the flow body: per table in `tables[].details` (alongside the cursor containers below), and at source level in `properties.source.additional_settings`. The two are stored independently — writing one does not change the other — and the source-level field can read back as `increment` rather than `incremental` after a write. Set and read the per-table field. Exception: for `extract_method: log`, the source-level and per-table values must both be `log` at create — a per-table `log` with the source-level field unset is rejected with HTTP 422 (see `cdc.md`).

Switching a table to `extract_method: all` requires clearing its `incremental_field` in the same body — leaving both is rejected with HTTP 422 (`Incremental field cannot be set if extract method is 'all'`).

## `merge_method` (load strategy)

`merge_method` is **target-type-specific**; the valid set depends on the target:

- Snowflake: `switch_tables`, `delete_insert`, `merge`.
- PostgreSQL (`postgres_rds`): `delete_insert`, `insert_on_conflict`.

Other targets (e.g. Redshift) carry their own set. For a target other than Snowflake or PostgreSQL, confirm its accepted `merge_method` before relying on one — a wrong value is rejected at create with HTTP 422.

## Incremental extraction

For a database source, discover a table's cursor candidates with `bdi-connection.sh tables <connection-id>`: each table lists its cursor-eligible columns in `increment_columns[]` (name, type, `incremental_type`).

When `extract_method` is `incremental`, the cursor type is one of `datetime`, `runningnumber`, `epoch`, `row_version`. The type is **not** a directly settable field — sending an `incremental_type` field is rejected (`extra_forbidden`). Instead the type is implied by which interval container is populated in the table details: `date_range` (datetime), `running_number`, or `epoch`.

- A `running_number` container carries `start_value`, `end_value`, `rows_in_chunk`, and `include_end_value`; sending just `{"start_value": 0}` is accepted, and the API fills in the remaining fields.
- A `datetime` incremental requires an explicit `start_date`. A null start activates but fails at run time ("no start date/time set") — the cursor does not self-seed. The `date_range` container also accepts `days_back` (a rolling N-day window) and `include_end_value` (end-inclusive window).
- The cursor auto-advances: each run's start value becomes the prior run's end value. The high-water mark for a datetime cursor persists in `date_range.start_date`.
- By default a failed run does **not** advance the cursor, so a rerun re-covers the same window. Setting `update_increment_on_failures: true` (in `date_range`, default `false`) advances the cursor even on failure, which can skip the failed window's data — leave it off unless you specifically want that.
- The extraction window is half-open `[start, end)` — start-inclusive, end-exclusive.
- `extract_method: incremental` with an `incremental_field` set but **none** of the interval containers populated is rejected at create/edit with HTTP 422 (`Missing interval details of date_range / running_number / epoch...`) — not accepted-and-idle. Populate one of the containers above, or switch `extract_method` to `all` or `log`.

## Match/merge keys

Per-table column metadata lives under `tables[].details.modified_columns[]`. The match/merge-key flag on a column is `is_key` (snake_case), uniformly — there is no camelCase `isKey` variant. Columns may also carry `is_rivery_metadata` and `cluster_key` (merge-key ordering).

A `merge` load with no column flagged `is_key` is accepted silently — no error at create and none at run — and what happens next depends on how `modified_columns` was authored. Populated columns with no `is_key` flag load INSERT-only on an incremental extract — even when the source table has a primary key — so each run re-appends the extracted rows and duplicates accumulate silently. An entirely empty `modified_columns` instead has the loader auto-map the table and derive the merge key from the source's primary key (observed on MSSQL), upserting correctly — the generated MERGE and its `key_columns` are visible in the run log. When populating columns, always flag a key: use a NOT NULL column — typically the primary key — or a composite whose columns are all NOT NULL, since a nullable key can't reliably match (NULL never equals NULL).

## Target types

The available target types are account- and region-scoped. Enumerate the live set with `bdi-connection.sh target-types` rather than relying on a frozen list. The target discriminator value for PostgreSQL RDS is `postgres_rds` (see Connector discriminator).

Each target requires specific fields at the top level of the target block. The validator keys these off `target.name` before it checks the connection, so a missing field returns a precise `Field <X> is required for <target>`:

| Target (`name`) | Required top-level target fields |
|---|---|
| `snowflake` | `database_name` + `schema_name` |
| `bigquery` | `dataset_id` |
| `redshift`, `databricks`, `azure_synapse_analytics`, `azure_sql`, `postgres_rds` | `schema_name` |
| `athena` | `schema_name` + `bucket_name` |
| `onelake` | `workspace_name` + `lakehouse_name` |

## File-zone (S3) targets

An S3 file-zone target's keys are flat siblings on the target block — there is no `settings`/`file_zone_settings` sub-object. `path` is required (omitting it → HTTP 422 `Field required` at `target.s3.path`). Other siblings: `bucket_name` (string), `partitioned_kind` (partition granularity), `fz_loading_mode` (`auto-period` or `custom`), and `convert_file_type`.

`partitioned_kind` accepts `by_day`, `by_hour`, or `by_minute`; other values are rejected with HTTP 422. The partition suffix (e.g. `date=YYYYMMDD/` for `by_day`) is applied at runtime when data is written — `path` is stored verbatim, and the API appends neither the granularity token nor a trailing slash on save.

The default platform-managed file zone may not satisfy data-residency rules — when a requirement names GDPR, HIPAA, SOC 2, or a specific region, point the target at your own S3/GCS/Azure Blob in that region rather than the default zone.

## Rivery metadata columns

`properties.target.additional_settings.use_rivery_metadata` (boolean) controls whether per-row lineage columns are appended to the target table. When on, the loader appends three columns: `_rivery_last_update` (load timestamp), `_rivery_river_id` (flow cross_id), `_rivery_run_id` (run id). These are loader-generated — they never appear in `modified_columns`, and per-column `is_rivery_metadata` stays null.

Caveat: the column names/types above apply to a PostgreSQL warehouse target. Do not assume identical names on Snowflake/BigQuery/Redshift — verify per target. On an S3 append target (no warehouse loader) the `_rivery_*` columns do not apply.

## Schema drift

On a merge load, source schema changes are handled additively by default:

- A new source column is added to the target; rows that predate it are back-filled with NULL.
- A dropped source column is retained in the target and back-filled with NULL from then on — it is not deleted.
- A renamed source column is handled as drop-plus-add: the new name is added and the old name is retained, so both columns persist.
- A dot (`.`) in a source column name is unsupported and can cause errors or unexpected behavior — remove or replace dots in column names before loading.

## PostgreSQL RDS load mechanism

BDI loads a PostgreSQL RDS target via S3-staged `aws_s3.table_import_from_s3`. The only target-side prerequisite is `CREATE EXTENSION aws_s3` on the target database; BDI supplies the managed-bucket credentials. There is no direct/JDBC load mode for this target.

## Create-time behavior

A newly created source-to-target (and CDC) flow is forced to `disabled` regardless of the body — activate it with `bdi-flow.sh activate` once the source/target connections are reachable.

An edit to an `active` flow leaves it active and immediately runnable — no re-activation is needed after an edit. `last_activated` reads back null after an edit (it tracks which version was activated, and an edit mints a new version); that is cosmetic — the run gate keys off `river_status`.

## Recipe (Blueprint) REST sources

A Blueprint REST source is authored as a **console recipe**, not through the river body. The river references the recipe by a `recipe_id` that the BDI console mints (`source_type: blueprint`); the recipe's own configuration — pagination, authentication, and break/stop conditions — lives in the console and is not reachable from the river API. So this source kind can't be authored end-to-end from JSON here: have the user build the recipe in the console and supply its `recipe_id`, then reference it in the flow body and operate the flow from here.

## Before you create or activate

A quick pass over the body catches the silent-failure cases documented above:

- A `merge` load has a merge key: at least one NOT NULL column flagged `is_key` when `modified_columns` is populated, or `modified_columns` left entirely empty so the loader derives the key from the source primary key — a populated-but-keyless merge re-appends rows on every incremental run with no error.
- An incremental extract has both an `incremental_field` and one populated interval container — otherwise the write is rejected with HTTP 422.
- CDC uses `extract_method: log` — configured any other way it silently degrades to a full or incremental extract.
- `append` is paired with incremental extraction only for a genuinely append-only target — otherwise the table grows without bound.
- OAuth / browser-consent sources already exist in the console — they can't be created through the flow API.
- Target string columns are sized to fit the longest source value they'll receive.
- Target numeric columns keep the source's precision — use `DECIMAL`/`NUMERIC`, not `FLOAT`/`DOUBLE`, for money and other exact values.
- Source and target discriminator names are the lowercase `api_name` (see Connector discriminator).

## Worked examples

Two minimal bodies to mirror. Both create `disabled` (a source-to-target flow is forced disabled at create); activate with `bdi-flow.sh activate` once the source and target connections are reachable. Replace the `<...>` placeholders with real connection ids and names.

### Native database source → Snowflake (full extract)

A PostgreSQL table loaded whole into Snowflake on each run — `run_type: multi_tables`, per-table `extract_method: all`, `loading_method: overwrite`. The source table is selected under `schemas[]`; `modified_columns` is left empty to take the table's full column set. The `source.additional_settings` block shown is optional — the API derives it from `source.name` and the connection when omitted.

```json
{
  "name": "Postgres to Snowflake — orders",
  "type": "source_to_target",
  "metadata": {
    "description": "Full load of orders into Snowflake"
  },
  "settings": {
    "run_timeout_seconds": 43200
  },
  "schedulers": [],
  "properties": {
    "properties_type": "source_to_target",
    "source": {
      "name": "postgresql",
      "connection_id": "<postgresql connection id>",
      "run_type": "multi_tables",
      "additional_settings": {
        "datasource_id": "postgresql",
        "connection_type": "postgresql"
      }
    },
    "target": {
      "name": "snowflake",
      "connection_id": "<snowflake connection id>",
      "loading_method": "overwrite",
      "database_name": "DEMO_DB",
      "schema_name": "PUBLIC",
      "additional_settings": {}
    },
    "schemas": [
      {
        "name": "public",
        "tables": [
          {
            "run_type_and_datasource": "multi_tables",
            "details": {
              "is_selected": true,
              "name": "orders",
              "target_table": "orders",
              "extract_method": "all",
              "incremental_field": null,
              "date_range": null,
              "running_number": null,
              "epoch": null,
              "modified_columns": [],
              "additional_source_settings": { "source_type": "postgresql" },
              "additional_target_settings": { "target_loading": "overwrite", "target_type": "snowflake" }
            }
          }
        ]
      }
    ]
  }
}
```

### Custom-report (SaaS) source → Snowflake

A Shopify custom-report source appending into a single Snowflake table — `run_type: regular`. The one output table is named by `target.table_name`; `source.additional_settings` stays empty (its otherwise-mapped keys are forbidden here) and there is no `schemas[]` table selection.

```json
{
  "name": "Shopify to Snowflake — customers",
  "type": "source_to_target",
  "metadata": {
    "description": "Append Shopify customers into Snowflake"
  },
  "settings": {
    "run_timeout_seconds": 43200
  },
  "schedulers": [],
  "properties": {
    "properties_type": "source_to_target",
    "source": {
      "name": "shopify",
      "connection_id": "<shopify connection id>",
      "run_type": "regular",
      "additional_settings": {}
    },
    "target": {
      "name": "snowflake",
      "connection_id": "<snowflake connection id>",
      "loading_method": "append",
      "table_name": "shopify_customers",
      "database_name": "DEMO_DB",
      "schema_name": "PUBLIC",
      "additional_settings": {}
    },
    "schemas": []
  }
}
```
