---
name: boomi-bdi
description: "Operates BDI (Boomi Data Integration, formerly Rivery) — the ELT data-pipeline product: it ingests and CDC-replicates sources into a data warehouse or lake, transforms within it (SQL/Python), and activates data back out (reverse ETL). Use for BDI, Rivery, data flow, river, ELT, CDC, and reverse-ETL requests. Not for application integration — connecting apps, APIs, queues, or trading partners (EDI) to run a business process or keep systems in sync (use boomi-integration, the general-purpose iPaaS); not Boomi Flow's human-facing workflow/approval apps, a different product despite the shared word 'flow' (use boomi-flow); not master-data management such as golden records, matching, or stewardship (use boomi-datahub)."
---

# boomi-bdi

## Scope

BDI is the **ELT** data-pipeline product: it ingests and CDC-replicates sources *into* a **data warehouse or lake**, transforms and orchestrates *within* it (SQL pushed down to the warehouse's compute; Python on Boomi-managed servers), and activates curated data *back out* to operational tools (reverse ETL). Reach for it when the goal is consolidating or moving data through a warehouse for analytics/BI/reporting.

Targets are predominantly warehouses and lakes, but the catalog also includes an operational database (PostgreSQL RDS/Aurora) and email, and reverse-ETL targets can be apps or APIs — so "warehouse/lake" is the center of gravity, not an exclusive rule.

## Capabilities

In:

- Author `source_to_target` (ELT) and `logic` (orchestration/transformation) flows from agent-authored JSON, then run, poll, read logs, and iterate.
- Operate existing flows regardless of origin (API, console, kit) — list, inspect, run. Editability depends on format, not origin: `is_api_v2:false` (legacy) flows — e.g. kit installs and older console flows — aren't editable in place, only rebuilt as v2 (see Platform behavior).
- Inspect and create BDI connections — resolve the connection with the user (see Connections below).
- Scan an environment for failed runs.
- Environments and audit events, variables, dataframes, CDC log/offset.

Out:

- The Scripts inventory below is the exhaustive surface — if no script covers it, it's out of scope. Do not call the API directly (curl); if a task seems to require it, flag that to the user as unexpected rather than working around the scripts.
- Deleting assets, account administration (users, teams, SCIM), and token generation — console-by-design.
- Installing kits — the Kits marketplace is console-only.

Platform gaps that affect a specific workflow (what's console-only, what's not editable) are documented where they matter — Platform behavior and the references.

When the user asks an open-ended "what can you do?" / "where do I start?", orient them from Scope and Capabilities above, grouped by the goal they're pursuing — don't recite the scripts inventory.

## Terminology

- **Rivery is BDI's former name** and survives throughout the API: `river` in paths and field names, `api.rivery.io` hosts, `_rivery_*` metadata columns.
- **Data flow = river** — both the design-time asset and the runtime unit of work. The UI says "data flow"; the API says `river` (`river_cross_id`, `river_type`, …).
- **Flow types** (`river_type`): `source_to_target` (ELT, the most common), `logic` (orchestration/transformation), `actions` (REST Action flows). List responses say `river_type`; a full `get` says `type` plus `kind`.
- **Connection** — a BDI-native asset holding stored source/target credentials. Unrelated to Boomi Integration's connection/connector components despite the shared name.
- **Processing units** — the consumption/billing metric, a raw decimal the API returns under equal-valued keys `units`/`rpu` (on an `activities` row) and `total_units`/`total_rpu` (on `stats`), both window aggregates. The console labels it **Boomi Data Units (BDU)**; older material, **Rivery Pricing Units (RPU)**; the generic word is **credits** — labels only, never JSON keys, so map any of them ("RPU usage", "how many credits") onto the metric.

## Disambiguation: neighboring Boomi products

`boomi-flow` builds human-facing workflow/approval apps (a different product despite the shared word "flow").

`boomi-datahub` is master-data management (golden records, matching, stewardship). The overlap case is a request for "a central hub of data": DataHub fits named business entities (customers, products) receiving ongoing updates from multiple systems; BDI fits high-volume raw data landing in a warehouse.

`boomi-integration` — the general-purpose iPaaS — is the hard one: both it and BDI move data between systems. The test is **whether a data warehouse/lake is the epicenter**:

- **→ BDI (this skill):** data is ingested into the warehouse, transformed in it, or activated out of it; the purpose is analytics/BI/reporting (one analytical source of truth). *e.g. "replicate Postgres into Snowflake nightly", "CDC from SQL Server to Redshift", "push warehouse segments to Salesforce" (reverse ETL).*
- **→ `boomi-integration`:** apps connect directly — the purpose is running a business process or keeping operational systems in sync. *e.g. "push each new Shopify order to NetSuite", "receive an EDI 850 and route it".*

What doesn't decide it:

- Timing — both can be scheduled or near-real-time.
- Scale of data.
- The word "ETL" — transform-in-flight technically describes integration, but callers use it loosely. ("ELT" is a stronger signal: someone asking for ELT usually does specifically mean BDI.)
- A warehouse merely being in the path — an operational sync can touch one and still be `boomi-integration`.

What decides it is intent: ELT oriented around a warehouse is BDI. When it's ambiguous, ask the user.

## Credentials

BDI work involves two independent credential layers:

1. **Platform credentials** — the BDI API token and account/environment ids. They live in the workspace `.env`; scripts source them directly and never accept them as CLI arguments. By default you will be blocked from reading `.env`. `bdi-env-check.sh` verifies the platform credentials without printing the token.
2. **Connector credentials** — third-party system secrets stored inside BDI connections, configured in the BDI console. Keep them out of context by referencing connections that already exist in the platform (see Connections: resolve with the user below).

`.env` keys (all required by every script): `BDI_API_URL`, `BDI_API_TOKEN`, `BDI_ACCOUNT_ID`, `BDI_ENVIRONMENT_ID`. The token must be generated by the user in the BDI console (My Profile → API Tokens). The account and environment ids are the two 24-character hex ids in any BDI console URL: `https://console.rivery.io/dashboard/<account-id>/<environment-id>/...`.

- `BDI_API_URL` needs the `https://` scheme and no trailing slash — `https://api.rivery.io`. A token belongs to one region's API host: US `https://api.rivery.io`, EU `https://api.eu-west-1.rivery.io`, IL `https://api.il-central-1.rivery.io`, AU `https://api.ap-southeast-2.rivery.io`.
- A 401 is `{"detail":"Credentials are not valid"}` for both a bad token and the wrong region host — the response cannot tell them apart. Check the token first (a mistyped or truncated paste is the more common cause), then the host.
- Tokens carry per-area scopes and per-environment grants: a 403 means the token authenticated but lacks the scope for that call or access to that environment — a token can list every environment yet 403 inside one it wasn't granted. When one environment 403s, the answer is usually a different environment, not a different token; whoever issued the token knows which environments it was granted. Scopes and grants are changed in the BDI console.
- `BDI_ENVIRONMENT_ID` may be absent for `bdi-env-check.sh` and for `bdi-env.sh`'s account-scoped environment subcommands; everything else requires it. If the user doesn't have it, run `bdi-env-check.sh` and pick from the environments it lists. The user adds it to `.env` themselves (scripts read it from `.env` only; inline exports and empty placeholder lines don't work).

## First-run setup

The first time a workspace is used — `bdi-env-check.sh` reports no `.env` or missing/rejected credentials, or the user says they just installed the plugin, have no token yet, or ask how to get started — walk them through setup before their task. `references/getting_started.md` has the sequenced flow (fill the four keys → validate → orient) plus the environment-lookup, empty-environment-list and already-set-up cases.

## Mutations: confirm before writing

Reads run freely. Every write below needs the user's explicit go-ahead first: show the specific change, say what undoing it would take, and act one change at a time rather than batching several behind one approval. This applies whether or not you loaded a reference.

One exception: the `create` of the asset the user just asked you to build — that call is the task. It does not extend to the other writes in the same build (`bdi-dataframe.sh add`, `bdi-variable.sh river-set`, `bdi-flow.sh activate`, `bdi-flow.sh disable`).

- **Destructive — no history to roll back to.** Only flows keep saved versions (`references/versioning.md`); a write to a connection, a variable, a dataframe, or a CDC offset overwrites the previous value outright. `bdi-cdc.sh set` / `delete` (a wrong or cleared replication cursor silently skips or replays change records, with no error either way), `bdi-variable.sh river-set` (replaces a flow's entire variable set), `bdi-variable.sh env-delete`, `bdi-dataframe.sh clear`, `bdi-connection.sh edit`. Read the current value first and show it beside the new one — that read is the only rollback these have.
- **Reversible, but production-affecting.** `bdi-flow.sh edit` / `copy` / `restore` / `activate` / `disable` / `cancel`, `bdi-env.sh edit`, `bdi-cdc.sh enable` / `disable`. Reversible is not casual — a `disable` stops a live pipeline, an `edit` changes what data lands. A `copy` comes up disabled but inherits the source's scheduler and target unchanged, so activating one whose scheduler is enabled starts a second flow writing to the same destination on that schedule — read the copy back and confirm both before activating it.
- **Executes and bills.** `bdi-flow.sh run` / `run-sub` write to the target and consume processing units.

Never let an expected rejection stand in for asking. The platform accepts writes in states where reading the same object fails: `bdi-cdc.sh set` / `delete` return HTTP 200 while the CDC log is off, on a flow whose `get` returns 400.

After an approved write, read the state back and report what you observed rather than the HTTP status — this API returns 2xx for writes that did nothing (an `env-delete` of a key that was never there, a create whose mistyped nested field was dropped).

`bdi-logicode.sh upload` and `bdi-connection.sh add-file` are additive: they store a file that affects nothing until a flow or connection references it, so they need no approval.

## Scripts inventory

**Resolve `<skill-path>` at the beginning of each session.** Script invocations below use the placeholder `<skill-path>/scripts/...`; reuse the result for every later call:

- Take the absolute path of this SKILL.md you just read and drop the trailing `/SKILL.md`. That directory is `<skill-path>`.
- Verify by running `bash <skill-path>/scripts/bdi-env-check.sh`. If bash reports "No such file," stop and re-locate the skill rather than guessing the path. (Doubles as your `.env` status check.)
- Once resolved, treat `<skill-path>` as a fixed value for the session. Every subsequent invocation must re-emit the same path string verbatim — drift between calls (e.g. dropping `skills/boomi-bdi/`) produces "No such file" errors even when the first call worked.

Run scripts from the project workspace directory (so `.env` and `active-development/` resolve correctly), but always invoke them with the full absolute `<skill-path>/scripts/...` path.

All scripts support `--help` (or run with no args) for usage. They emit the API's raw response to stdout and errors to stderr — read the JSON directly rather than transforming it.

**Pipeline discipline.** Pipe script output only to standard text filters (`head`, `tail`, `wc`, `grep`). Do **not** pipe to `python3 -c`, `jq -r`, `awk`, or other interpreters with inline code — a harness that treats each piped executable as its own trust boundary prompts for approval per pipe, defeating the point of allowlisting the scripts.

**Temp files stay in the project tree.** When you need a scratch file (a JSON body for `create`), write it under `active-development/` — not `/tmp/`. A write outside the project tree commonly triggers an approval prompt.

**Write files with a file-writing tool, not bash heredocs.** Create the file in one call, then invoke the script in a separate shell call — a combined heredoc-plus-invocation command reads as new shell code and triggers an approval prompt.

- `scripts/bdi-env-check.sh` — verify `.env`, reach the API, list the environments the token can see. Use when: starting work, or choosing `BDI_ENVIRONMENT_ID`. It lists one page and says so if more exist — on an account with many environments, enumerate with `bdi-env.sh list --all` before recommending one.
- `scripts/bdi-env.sh` — `list | get | create | edit` for environments (account-scoped — needs `BDI_ACCOUNT_ID`, not `BDI_ENVIRONMENT_ID`); `audit | audit-get` for audit events (environment-scoped). Use when: discovering, creating, or editing environments, or reviewing an environment's audit-event history.
    - `list` is how you discover environment ids.
    - `edit` is a full-body PUT and its body key is `environment_name` (create's is `name`); environment `color` is an enum (e.g. `tagCyan`).
    - `audit` filters by a `--from`/`--to` time window plus repeatable `--user-id`/`--event-type`/`--entity-type`/`--entity-key`.
    - `list` and `audit` return only the first page by default (stderr NOTE when more exist); pass `--all` to enumerate everything. `list` also takes `--page N` / `--items N` for a single page; `audit` pages by opaque cursor, so only `--all` advances it — `--page`/`--items` have no effect.
- `scripts/bdi-flow.sh` — `list | search | get | run | run-sub | cancel | activate | disable | status | logs | tasks | steps | step-logs | run-vars | runs | operation | activities | run-groups | sub-rivers | copy | create | edit | versions | version | restore | stats | targets`. Use when: anything about data flows, their runs, their active/inactive schedule status, their saved-version history, or run statistics.
    - Discovery: `search` filters flows by free-text/status/type (richer than `list --name`); `list`/`search`/`activities` also filter by Data Flow Group via `--group` (`group_id`; `list` also takes `--group-name`).
    - Run listings: `run-groups` lists a flow's run groups in a window (where the `partially succeeded` aggregate surfaces) or one group's detail; `sub-rivers` lists a master flow's sub-river runs.
    - Per-run inspection takes `<flow-id> <run-id>` — `tasks` (any flow type), `steps`/`run-vars` (logic flows); `step-logs` adds a third `<step-id>` (logic flows).
    - Execution: `run-sub` runs one sub-river; `cancel` stops a run (`--run`) or run group (`--run-group`), confirm via `status`.
    - `copy` duplicates a flow synchronously, returning the new `cross_id`. `edit` is a full-body PUT — `get` the flow, change what you need, put it back (no partial/patch).
    - Versions: `versions`/`version` list and fetch a flow's saved versions (a version embeds the full flow snapshot); `restore <flow-id> <version-id>` rolls the flow back to one synchronously, appending a new version whose content equals that snapshot (so a restore is itself reversible) rather than rewinding.
    - Statistics: `stats` returns run-status counts (`succeeded`/`failed`/`canceled`/`skipped`/…) plus processing units for one flow or, with no flow-id, the whole environment. `targets` returns a per-target (table) run breakdown for a multi-table flow, filterable by `--status`/`--run-group`/`--sub-river` and sortable via `--sort-by`/`--sort-order` — "target" here means the destination table within the flow, distinct from the source/target connection sense used elsewhere in this file.
- `scripts/bdi-connection.sh` — `list | get | tables | columns | create | edit | add-file`; catalog discovery: `connection-types | type | source-types | target-types | source-sections`. Use when: inspecting, creating, or editing BDI connections, discovering a database source's tables and incremental-cursor columns, reading a source table's full column schema, uploading a connection key/cert file, or listing available connector/source/target types.
    - `list` returns only the first page by default (stderr NOTE when more exist); an environment can hold hundreds of connections, so pass `--all` to enumerate them — never conclude a connection isn't there from a first-page miss.
    - A `list` item and a `get` (or catalog) item name their fields differently: in `list`, the title is `connection_name`, the display type is `connection_type`, and the machine slug is `connection_type_id`; in `get` and the catalog subcommands, `connection_type` is instead the machine slug and the display name is `connection_type_name`. Match and group on the slug, never the display string — its casing/spacing varies between otherwise-identical types.
    - `tables <connection-id>` lists a database source connection's tables, each with its cursor-eligible columns (`increment_columns[]`: name, type, `incremental_type` — e.g. `datetime`, `runningnumber`, `epoch`) — use it to pick an incremental cursor when authoring a source-to-target flow. It is not schema introspection: non-cursorable columns (text, boolean, …) are omitted entirely, so a table whose columns are all text lists an empty `increment_columns` — use `columns` for a table's full column set. Non-database connections don't enumerate tables — most return an empty `items` set, some error — so an empty result alone doesn't distinguish an unsupported connector from a source with no tables; an actual error surfaces on stderr with a nonzero exit.
    - `columns <connection-id> --datasource <api-name> (--schema S… | --all-schemas)` returns a database source's **full** column schema — every column of every table in the named schema, including the text and boolean columns `tables` omits. `--datasource` is the source `api_name`, not the connection's type slug (resolve it per the connector-discriminator rule in `references/source_to_target_authoring.md`). It is asynchronous and waits for the pull, bounded by a 180s backstop. See `references/data_discovery.md` for the returned fields and their traps.
    - `edit` is a full-body PUT — `get` the connection, change what you need, put it back (no partial/patch); `add-file` uploads a file (e.g. a `.pem`) for a connection type and returns its stored `file_path` (rate-limited to 3/minute).
    - Catalog entries pair a lowercase machine id (`connection_type`, source `id`) with a display name (`connection_type_name`, source `name`); the available set is account-scoped, so enumerate it live rather than assuming.
    - The catalog subcommands return only the first page by default (stderr NOTE when more exist); pass `--all` to enumerate everything, or `--page N` / `--items N` for a single page — never conclude a type is unsupported from a first-page miss.
- `scripts/bdi-cdc.sh` — `enable | disable | get | set | delete`. Use when: managing log-based CDC on a data flow — turning the CDC log on/off and reading, setting, or clearing the stored offset cursor. `enable` is asynchronous (the script polls the operation to a terminal state; a 202 is acceptance, not success); `disable` may return with no operation, in which case there is nothing to poll and the script reports it complete — when it does return one, the script polls it the same way. The log state gates the read only: `get` returns HTTP 400 "Enable log is off" while the log is off, and a different 400 once it is on but no offset has been captured yet — `get` exits non-zero on both, so read which one rather than treating any 400 as failure. `set` and `delete` are accepted (HTTP 200) either way, so nothing blocks an offset write on a flow whose offset you can't read back. See `references/cdc.md`.
- `scripts/bdi-dataframe.sh` — `list | get | add | update | clear | download`. Use when: working with BDI dataframes (named, environment-scoped data stores that logic flows read/write).
    - `list` returns only the first page by default (stderr NOTE when more exist); pass `--all` to enumerate everything, or `--page N` / `--items N` for a single page.
    - `add` needs only a unique `name` (`connection_settings` is optional — it points a dataframe at external storage and requires `connection`/`datasource_id`/`storage_type`/`default_bucket`).
    - `clear`/`download` are asynchronous (the script polls the operation to a terminal state); a settled `download` carries presigned URL(s) to the dataframe's parquet data.
- `scripts/bdi-logicode.sh` — `upload | read | template | requirements`. Use when: authoring a logic-flow `logicode` (Python) step — upload a Python file to get the `file_id` the step references, read an uploaded file's source, or fetch the starter template / requirements file. See `references/logic_flow_authoring.md`.
- `scripts/bdi-variable.sh` — `env-list | env-set | env-delete | river-get | river-set`. Use when: reading or changing environment-scoped variables or a flow's own variables. Writes take `--body <file.json>` (see `--help` for shapes, e.g. `{"variables": {...}}` and `{"items": [...]}`). `env-delete <variable-key>` deletes one environment variable by key — deleting a nonexistent key returns the same silent success, so confirm removal with `env-list`. The two `set`s differ:
    - `env-set` is an upsert — it adds or updates only the keys sent and leaves all others untouched.
    - `river-set` is a full replace — it overwrites the flow's entire variable set with the list sent, so read-modify-write (`river-get`, edit, put the complete set back), resending each item's full `settings` (an omitted settings flag silently resets to its default, e.g. `clear_value_on_start` reverts to `false`).
    - Read the "read" half of that round trip with `river-get --all`, and concatenate every returned envelope's `items` into one `{"items":[...]}` body — the items go back verbatim, read-only fields (`account`, `env_id`, `river_id`) included, so nothing needs stripping. `river-get` pages at 20, so on a flow with more than 20 variables a bare read feeds `river-set` a subset, and the full replace destroys the rest — HTTP 200, exit 0, no warning. `river-set` rejects an unmerged array of envelopes rather than accepting it.
    - `env-list` is the exception: it isn't paginated and takes no paging flags, returning the environment's complete variable set as one flat name-to-value map with none of the `page`/`total_items` fields the other listings carry. It is also the only way to read those values: `bdi-env.sh list` and `bdi-env-check.sh` replace each environment's variables map with `"[omitted]"`, since a multi-environment listing carries every environment's full set.
    - Environment variables and flow variables differ in what they can safely hold. Environment variables hold configuration — connection details, schema and database names, notification recipients — and their values are stored and returned in plain text; there is no encryption option for them, and they are read-only during a flow run. Only flow variables can be encrypted, and an encrypted one is usable solely inside a logic flow's Python step: the platform cannot decrypt it, and its value cannot be read back or reassigned. Anything that must stay secret belongs in a connection, or in an encrypted flow variable — not in an environment variable.

## Platform behavior

How the BDI platform behaves, as surfaced through the scripts above — these notes are for interpreting script output and choosing subcommands, never a reason to call the API directly.

- Flows are addressed by `cross_id` (a.k.a. `river_cross_id`); runs by `run_id`. Use titles when talking to the user, ids when calling scripts.
- A flow is one monolithic config object — source/target/schemas/mapping in one body, so every `edit` re-PUTs the whole flow.
- Runs are asynchronous: `run` returns a `run_id`; poll `status` until terminal. Single-run statuses: `pending`, `running`, then terminal `succeeded`, `failed`, `canceled`, or `skipped` — treat `skipped` as terminal so polling doesn't hang. `partially succeeded` (two words) is a run-group aggregate only, never a single run — read it via `bdi-flow.sh run-groups`.
- A run can be accepted (`run` returns a `run_id`, `status:pending`) and then fail at the target — acceptance is not success. Poll to a terminal status; on failure read `error_description`.
- Run logs (`logs`) are CSV — header `timestamp,level,msg`, newest-first — not JSON. A logic `step-logs` response is different: JSON `{"logs_url": …}` holding a short-lived presigned URL you must follow to read the content — for `logicode` (code) steps only; a SQL step returns HTTP 400 `Invalid step type <block_type>`, its diagnostics in the run's `error_description`. Logic `run-vars` values are retained only briefly after a run — afterward the call 400s (`expired`), distinct from the source_to_target type-rejection (`Only logic flows…`).
- Run subcommands (`status`/`logs`/`tasks`/`steps`) return status/metadata only — **never the data rows**. To verify produced data, query the target warehouse out-of-band (row counts / sample `SELECT`s), outside this skill. In-skill exception: Logic-flow **dataframes** download as parquet via `bdi-dataframe.sh download`.
- A flow's `river_status` (`active` | `disabled`) gates running — a `disabled` flow rejects `run`.
    - Toggle it with `activate`/`disable`, which block until the underlying operation settles and exit non-zero if it fails — how a failed `activate` (e.g. an unreachable source/target connection) surfaces. Activation validation can take minutes on some flows (e.g. CDC); the toggle waits it out rather than timing out early.
    - After a `copy`, `get` the new flow and check its `river_status` — `disable` it if you want it paused.
    - `cancel` is asynchronous and best-effort: it acks an in-flight run/group (HTTP 200; completion takes a minute or two) and 400s on an already-terminal run — confirm the outcome via `status`. A cancelled run settles as `failed` with `error_description: "Run canceled"`, not `canceled` — treat that as the successful cancel.
- Activity queries require an explicit time window — both `--from` and `--to`, format `yyyy-mm-ddThh:mm:ss` (UTC). List responses wrap the rows in an `items` array; the default page size varies by subcommand (20 for runs/activities, 50 for run-groups) — read `current_page_size` rather than assuming. An `activities` row is a per-flow aggregate — per-status run counts for the window — not an individual run record; use `runs` for the run records themselves.
- The `bdi-flow.sh` listings (`list`, `search`, `runs`, `activities`, `run-groups`, `sub-rivers`) return only the first page by default and print a stderr NOTE when more pages exist — to enumerate everything (e.g. discovering all run-ids), pass `--all`, which follows `next_page` and emits a JSON array of page envelopes (capped by `--max-pages`, default 100). `--page N` / `--items N` fetch or size a single page.
- Page-size defaults differ sharply between endpoints, so how soon a bare listing truncates is not uniform: connections default to 200 per page, while environments and a flow's variables default to 20. Read `current_page_size` against `total_items` rather than assuming, and reach for `--all` whenever the answer depends on seeing every row.
- The platform rate-limits requests (roughly 15/minute overall). Flow execution has its own caps: a single flow runs at most 2 times/minute, and one user at most 15 executions/minute. For environment-wide questions ("what failed today?"), never loop run queries across flows — use `bdi-flow.sh activities`, one call for the whole environment.
- Errors: a 422 body is `{"detail":[{type,loc,msg,input,url,...}], "body":<echo>}` — `detail` is an array naming each offending field by its `loc` path; read it. On a 400, `detail` is a plain string, not the array. HTTP 400 is overloaded:
    - running a `disabled` flow (`{"detail":"Data Flow <id> is disabled"}`);
    - disabling a flow mid-run (wait for a terminal run state first);
    - `edit`/`copy` on an `is_api_v2:false` (legacy: kit-installed or older-console) flow (`"Only Data flows that were created in this API can be used in this endpoint"`) — the API writes only v2-format flows, so a legacy flow can't be edited in place. To change one, rebuild it as a new v2 flow (`get` → drop `cross_id` → `create`), which leaves the original untouched — but only when `get` can render it (next bullet);
    - a `get` blocked by the flow's source connector (`"This data flow cannot be fetched: source api_name for datasource_id '<datasource>' is not supported."`, e.g. `salesforce` or `actions`) — `get` renders the flow into the v2 shape and can't for a source the v2 API doesn't support; the flow still runs to `succeeded` and stays visible/filterable via `list`/`search`. Read its native definition with `version` (the stored snapshot, returned as-is with no rendering). The snapshot is legacy-shaped — not a v2 body — so it can't be recreated verbatim; use it as a blueprint to author an *approximate* v2 rebuild (translate its source/target/mapping into a new `create` body, swapping the unsupported source for its v2-supported equivalent, e.g. `salesforce` → `salesforce_v3`), or rebuild in the console. The rebuild path needs a v2-supported equivalent to exist — an `actions` flow has none (the API models no definition fields for action flows), so changing one is console-only.
    - `edit` changing a flow's source connector type (`"Data Flow data source cannot be changed"`) — a flow's source is fixed at creation; to use a different source, create a new flow.
- **Groups organize flows into folders** (name, color/icon, a default group) — the organizational primitive for flows; BDI has no separate "tags" concept. Managed only in the console's Groups tab: no script creates, renames, deletes, or lists groups.
    - A flow carries `group_id`/`group_name` (settable on create/edit, readable via `get`); `bdi-flow.sh list` filters on both, `search`/`activities` filter on `group_id` only (no `group_name` there).
    - To discover existing groups, derive the distinct `group_id`/`group_name` pairs from `list --all` — there's no other way to enumerate them.

## References

Load the matching reference for the task at hand:

- `references/getting_started.md` — Use when: setting up BDI in a workspace for the first time — `.env` missing or credentials rejected by `bdi-env-check.sh`, or a new user getting oriented. Triggers: "set me up", "connect my account", "I just installed this", "where do I start", "I don't have a token yet".
- `references/data_discovery.md` — Use when: exploring what's connected before building — listing an environment's connections, browsing the connector-type catalog, discovering a database source's tables and incremental-cursor columns, or reading a source table's full column schema. Triggers: "what's connected here?", "list our connections", "what data sources do we have?", "what connection types does BDI support?", "show me our sources", "what tables are in X?", "what columns does X have?", "show me that table's schema".
- `references/source_to_target_authoring.md` — Use when: building or inspecting a `source_to_target` (ELT) flow — choosing extraction/load modes and load-shaping patterns (SCD, dedup, late-arriving), extract/load/merge fields, incremental cursors, match keys, target types, schema drift, metadata columns. Triggers: "build/create a flow", "replicate X to Y", "ingest X into Y".
- `references/cdc.md` — Use when: a flow uses log-based CDC (`extract_method:"log"`) — prerequisites, the activation-gate, CDC/delete metadata columns, and the offset/lifecycle operations (enable/disable, offset cursor) exposed by `bdi-cdc.sh`.
- `references/logic_flow_authoring.md` — Use when: building, editing, or inspecting a `logic` (orchestration/transformation) flow — flow shape, step and container structure, step types, target blocks, upsert keys, variables, and the read-modify-write edit pattern. Triggers: "build a logic flow", "create a transformation pipeline", "orchestrate flows", "multi-step ETL", "aggregate/roll up X into Y in the warehouse", "add/remove/reorder a step", "rewrite the SQL in X", "run custom Python/code in a flow", "add a script step".
- `references/operations.md` — Use when: answering fleet-level run-state questions, producing a periodic health digest, or running lifecycle mutations — what ran / failed / is in flight across the environment, a success-rate/spend summary over a window, and run/rerun, activate, disable, or cancel on the user's approval. Triggers: "what ran today?", "any failures last night?", "what's running?", "how's our pipeline health?", "weekly digest", "success rate", "what's failing most?", "RPU usage this week", "rerun X", "activate/disable Y", "cancel Z".
- `references/cost_optimization.md` — Use when: finding and applying ways to reduce an environment's consumption (processing units — BDU/RPU) — ranking the biggest spenders and the cost-saving opportunities (chronically failing schedules, flows that succeed but move no data, over-frequent schedules, full loads that should be incremental), then disabling or editing one flow at a time on the user's approval. Triggers: "reduce our cost", "save money", "cut BDU/RPU usage", "what's most expensive?", "where can we cut?", and a spend spike surfaced by the health digest.
- `references/troubleshooting.md` — Use when: diagnosing why a data flow run failed — resolving the flow, finding the most recent failed run, reading logs and (for logic flows) step status, then on the user's approval applying a fix and rerunning. Triggers: "why did X fail?", "diagnose the latest failure of Y", "show me the logs for the failed run".
- `references/versioning.md` — Use when: working with a flow's saved-version history — listing versions, viewing one, comparing two (with a HIGH/MEDIUM/LOW risk rubric), or restoring a prior version on the user's approval. Triggers: "show versions of X", "who changed X?", "what changed on this flow?", "diff two versions", "roll back / restore X to a prior version".

For authoritative platform detail these references don't cover — error-code lookups, connector specifics, how a setting behaves — the BDI documentation publishes an LLM-oriented index at `https://help.boomi.com/md/docs/Atomsphere/Data_Integration/llms.txt`, and any page under `help.boomi.com/md/docs/...` returns clean markdown. It's a large corpus: consult it only when a task genuinely needs doc grounding, and fetch the specific page rather than loading it speculatively. Per-connector setup pages — required fields, auth method — sit under `Sources/` and `Targets/`; `RESTAPI/dataintegration-api-overview.md` covers the API's own token model.

## Connections: resolve with the user

Never silently pick a connection for a flow — resolve it with the user, in this order:

1. **Check `preferred_connections.md`** in the project workspace — the user may pre-specify their BDI connections there. Match by description and confirm the choice with the user if in doubt.
2. **Ask the user** to configure the connection in the BDI console and hand over its name/id — credentials stay in the platform and never enter the conversation. Confirm it with `bdi-connection.sh list`/`get`; pulled connections carry their secrets encrypted (opaque blobs, unreadable here).
3. **Proposing re-use** of a connection you discovered via `list` is fine, but it MUST be agreed with the user before building on it.
4. **Direct credentials** (`bdi-connection.sh create`) — supported, not recommended: credentials pass through the request body and the context window. If the user chooses it, use what they give; if a value looks like a production secret, mention the console path, then respect their workflow choice. Never echo credentials in plans, summaries, or confirmations.

After resolving, you may offer to record the connection in `preferred_connections.md`.

Not every connector is API-creatable: browser-consent OAuth sources (e.g. Google Ads) are console-only — set up there, then reference; OAuth types that also expose credentials (e.g. Salesforce) are creatable via that path.

No script tests a connection in isolation — the BDI console's test-connection has no equivalent here. Connectivity first surfaces when the connection is used: `bdi-flow.sh activate` validates a flow's source/target connections (failing if one is unreachable), and a run reports target-side errors in `error_description`.

## Creating assets

`create` posts an agent-authored JSON body verbatim. Author it net-new from the field grammar in the authoring references above — `source_to_target_authoring.md` and `logic_flow_authoring.md` each carry the required fields, per-warehouse target shapes, known traps, and a worked body, enough to build a working flow from scratch.

Where an authoring reference calls out a specific setup step the scripts don't currently cover — a Blueprint recipe, a browser-consent OAuth source — have the user do that one piece in the console and supply its result, then author the rest of the body here. That is a narrow, per-step fallback for those gaps, not how to start a flow.

Keep first creations bare-bones, and confirm the result in the BDI console before building on it. A 422 response names the offending field precisely — read it; a 422 also doesn't commit, so a rejected create or edit leaves the asset unchanged.
