# Log-based CDC

Change-data-capture behavior for source-to-target flows. CDC is selected by `extract_method:"log"` (see `source_to_target_authoring.md` for the surrounding load-mode fields).

## Engaging CDC

- `extract_method:"log"` engages BDI's log-based CDC pipeline: a forward-only log-sequence cursor, no full snapshot. `extract_method:"cdc"` is **not** a valid value — it is rejected with HTTP 422, never silently treated as full or incremental.
- A `log` flow requires `cdc_settings` and an **enabled schedule** at create time — a `schedulers` entry with `is_enabled: true` (e.g. `[{"cron_expression": "0 6 * * *", "is_enabled": true}]`; see `source_to_target_authoring.md`). Creating or enabling one without a schedule fails with HTTP 400 ("Please schedule a CDC data flow before enabling or creating").
- `extract_method:"log"` must be set at **both** levels — `source.additional_settings.extract_method` and each selected table's `details.extract_method`. A per-table `log` with the source-level field unset is rejected at create with HTTP 422 (`Cannot run different extract methods for tables ... River extract method is: None`).
- `cdc_settings` may be sent empty (`{}`); the API fills defaults (`default_tables_migration_option: "RUN_INITIAL_MIGRATION"`, `include_snapshot_tables: true`).

## Source-database prerequisites

The source database must have CDC enabled at **both** the database and the table level. This is enforced as an **activation-gate**, not at create: a flow targeting a non-CDC-enabled table is created successfully but rejected at activation with `[RVR-ACTIVATE-503] ... CDC is not enabled for tables: [...]`, and the flow stays disabled and never runs. A table-level CDC capture instance is required; database-level CDC is a precondition.

Log-based CDC also depends on the source retaining its transaction log — MySQL binlog, PostgreSQL WAL, or SQL Server's CDC capture tables — long enough for the pipeline to consume it. If the source purges a log segment before BDI reads it, those changes are lost; keep the source's log retention comfortably longer than the flow's run interval.

When a PostgreSQL log-CDC flow fails because its replication slot lost the WAL it needed (`wal_status = 'lost'`, or a "lost required WAL files" error), recovery is console-only — no script or API toggles it: on the flow's **Source** tab, disable **Enable stream**, save, then re-enable and save. BDI drops the stale slot, creates a fresh one, and realigns to the current WAL position — the platform's "Reinitialize Sync" procedure (BDI docs, CDC point-in-time-position). To prevent recurrence, raise the source's WAL retention: on RDS/Aurora, set `rds.log_retention_period` to ~7 days (`10080` minutes) and `wal_sender_timeout` in the parameter group, then reboot the writer.

## CDC metadata columns

CDC change events land with a flattened, Debezium-style envelope of metadata columns (**lowercase**). On an S3 append target, nine columns are appended:

- `__deleted` (bool — `true` only on a delete)
- `__ts_ms` (event time, epoch ms)
- `__transaction_id` (log-sequence id)
- `__transaction_order` (monotonic within a transaction)
- `__op` (operation: `c` create / `u` update / `d` delete)
- `__table_name`
- `__db`
- `__start_lsn_date`
- `__start_lsn_hex`

A delete surfaces as `{__op:"d", __deleted:true, ...}` carrying the pre-delete row image.

## Delete handling on a warehouse merge

On a log-CDC → PostgreSQL merge target, the loader appends `__deleted` (bool) and `__ts_ms` to the target table. A source DELETE is captured and applied via a `delete_insert` delta merge that sets `__deleted=true` and **retains** the row (soft delete) — it is not physically removed.

`include_deleted_rows` is a real source-side field, but it does **not** govern reflect-vs-suppress: at its default a source delete is still reflected as a `__deleted=true` tombstone, and there is no create-path or UI lever to change this. Treat delete handling as the loader-appended `__deleted`/`__ts_ms` columns plus the `delete_insert` delta path, not a boolean toggle.

Caveat: the delete-handling behavior above covers MSSQL log-CDC → PostgreSQL `insert_on_conflict`. Snowflake-merge delete behavior may differ — verify before relying on it.

## CDC offset and lifecycle

A log-based flow has two separate levers managed through `bdi-cdc.sh`: the **CDC log** (on/off) and the **offset cursor** (the stored source position).

### Enabling and disabling the CDC log

`bdi-cdc.sh enable <flow-id>` / `disable <flow-id>` toggle the CDC log:

- `enable` is asynchronous: the API returns HTTP 202 with an operation that validates the source connection and the target file zone, and the operation can still settle to an error (e.g. an unreachable target bucket). A 202 is acceptance, not success — `bdi-cdc.sh` polls the operation to a terminal state and exits non-zero if it errors.
- `disable` may return HTTP 204 with an empty body and no operation — nothing to poll, so `bdi-cdc.sh` reports it complete and exits 0. When it returns 202 with an operation, the script polls it the same way it polls `enable`'s.

Either way, confirm the resulting log state with `get` rather than inferring it from the exit code alone — and read *which* 400 it returns rather than treating any 400 as failure: "Enable log is off" means the log is off, while "has not retrieved any changes" means the log is on with no offset captured yet, which is the expected response right after `enable` on a flow whose source hasn't changed. `get` exits non-zero on either 400, so the message is the signal, not the exit code. Both are detailed under The offset cursor below.

A settled operation diagnoses itself, so read its body before reaching for run logs: `error_message` gives the root cause in plain text (an inaccessible target bucket names the bucket and the S3 403), and `result`, keyed by the operation type, holds one entry per validation check whose `validation_status` is `success`, `failure`, or `pending` — a `pending` check never ran, so the failed check plus the pending ones show where it stopped. `bdi-cdc.sh` emits that body on stderr when it exits non-zero; `bdi-flow.sh operation <op-id>` fetches it for any operation id.

Enabling or disabling the CDC log does not change the flow's `river_status`, and works on a disabled flow. The relationship is asymmetric: `bdi-flow.sh disable` (deactivating the flow) also turns the CDC log off. CDC-on can coexist with a disabled flow, but deactivating the flow takes the CDC log down with it.

### The offset cursor

Reading the offset requires the CDC log enabled; writing it does not. `bdi-cdc.sh get <flow-id>` returns it, and two distinct HTTP 400s mark the cases where it can't (`get` exits non-zero on both — the message is the signal):

- `"Enable log is off for data flow cross id: …"` — the CDC log is disabled.
- `"…the CDC connector has not retrieved any changes. A position will become available as soon as changes occur."` — the log is enabled but no offset has been captured yet (fresh, or just cleared).

For an MSSQL source the offset is `lsn_offset_sql_server`, a single hex Log Sequence Number string (e.g. `0x0000002A000007C70004`), inside a `config` object alongside `datasource_type` and `last_updated`.

`bdi-cdc.sh set <flow-id> --body <file.json>` writes the offset from a full config body — `{"config":{"datasource_type":"mssql","lsn_offset_sql_server":"0x…"}}` — and returns HTTP 200 with a null body; the new value is reflected by the next `get`. `bdi-cdc.sh delete <flow-id>` clears the stored offset (HTTP 200, null body) while leaving the CDC log enabled; a subsequent `get` returns the "has not retrieved any changes" 400.

Both writes are accepted with the CDC log **off** as well — HTTP 200, null body, on the same flow whose `get` 400s "Enable log is off" — and with the log off there is no way to read back what was written. The body isn't validated against the flow either: `set` accepts a `datasource_type` that doesn't match the source (e.g. `mssql` on a MySQL flow) without complaint. So neither the log state nor the API protects the cursor: getting the flow and the value right is on you, and both `set` and `delete` are mutations to confirm with the user before writing (SKILL.md "Mutations: confirm before writing"). Misplacing an offset skips change records permanently or replays them; clearing one discards the pipeline's position. Neither reports an error.

What the flow does after a cleared cursor depends on its own `cdc_settings` — `default_tables_migration_option` and `include_snapshot_tables` — and on the per-table `table_status`. Read them with `bdi-flow.sh get` before writing, and tell the user what the next run will do on that flow, not in general.

A failed run (e.g. a target load error) does not advance the offset.

### Activation timing

Activating a CDC flow (`bdi-flow.sh activate`) can take minutes while it validates the source and target connections. The activate poll may report a timeout while the underlying operation is still completing — re-check with `bdi-flow.sh operation <op-id>` or by re-reading `river_status` rather than treating the timeout as a failed activation. An operation carries its own status vocabulary rather than a run status: `D` is done and `E` is an error, both terminal, and any other value is still in progress. A timeout followed by `E` is a genuinely failed activation — the flow is down, not slow.
