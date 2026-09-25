# Discovering what's connected

Explore what a BDI environment already has connected — its connections, the connector-type catalog, and a database source's tables — before deciding what data flow to build. This is the read-only precursor to authoring: everything here is a pure read, no mutations. A BDI connection is a BDI-native asset holding stored source/target credentials, distinct from Boomi Integration's connection/connector components despite the shared name.

The shape: classify the question → list, resolve, or browse the catalog → drill into a source → hand off to authoring.

## Contents

- Classify the question
- List the connections
- Drill into one connection
- Browse the connector-type catalog
- Discover a source's tables
- Read a table's full column schema
- Hand off to authoring
- Discipline

## 1. Classify the question

| Bucket | Trigger | Where it goes |
|---|---|---|
| **List connections** | "what's connected?", "list our connections", "show me our sources" | §2 |
| **Drill into one** | "tell me about `prod-postgres`", "show me our Snowflake connection" | §3 |
| **Catalog** | "what connection types does BDI support?", "what sources can we connect?" | §4 |
| **Source tables** | "what tables are in `prod-postgres`?", "which columns can I use as a cursor?" | §5 |
| **Full column schema** | "what columns does `orders` have?", "show me that table's schema" | §6 |

The connections a specific environment holds (§2, §3) are different from the connector *types* the account can create (§4): the first is "what do we have," the second is "what's possible." Route "what's connected here" to the connection list, "what could we connect" to the catalog.

## 2. List the connections

`bdi-connection.sh list` returns the environment's connections. Each item carries the connection title in `connection_name`, a human-readable type in `connection_type`, and a stable machine slug in `connection_type_id`. Group by the slug (`connection_type_id`) rather than the display type — its casing and spacing vary between otherwise-identical types — and talk in connection titles (`connection_name`), never the raw ids. There is no server-side type filter — for "show me just our Postgres connections," enumerate with `bdi-connection.sh list --all` and filter the results client-side by slug. Enumerate the same way whenever you're resolving a named connection: an environment can hold hundreds, a bare `list` returns only the first page, and a first-page miss looks exactly like "that connection doesn't exist."

If the environment has no connections, say so plainly and offer the two ways to add one: create it through this skill for a non-OAuth source (see SKILL.md "Creating assets"), or set up an OAuth/browser-consent source in the BDI console first, then reference it here. Don't dead-end the user.

## 3. Drill into one connection

When the user names a single connection, resolve it *with the user* — never silently pick one (see SKILL.md "Connections: resolve with the user"). Confirm the match by title, then `bdi-connection.sh get <id>` for its detail. Field names differ from `list`: in the `get` response `connection_type` is the machine slug and the display name moves to `connection_type_name` (SKILL.md carries the full list-vs-get field map). Render the title, type, and last-modified (`connection_update_time`); stored credentials come back only as flags (`password_exists`, `is_password_encrypted`) with no raw secret, so there is nothing sensitive to display and nothing to echo. For a database source, offer to drill into its tables (§5).

## 4. Browse the connector-type catalog

The catalog is account-scoped, so enumerate it live rather than assuming a fixed list:

- `bdi-connection.sh source-types` — data source types (`api_name` machine id + display name + an `is_new_interface` boolean). `is_new_interface:true` means creatable in the current console UI — narrower than API-authorable, not `is_api_v2` eligibility: a `false` source (e.g. `snowflake_source`) can still be authored as a v2 flow via `create`.
- `bdi-connection.sh target-types` — target (warehouse/lake/…) types.
- `bdi-connection.sh connection-types` — connection types with their config sections.
- `bdi-connection.sh source-sections` — source types grouped into their catalog sections (databases, storage, analytics, marketing, …); use it when the user wants sources by category rather than a flat list.

These listings page: they return the first page by default and print a stderr NOTE when more exist — pass `--all` to enumerate everything, or `--page N` / `--items N` for a single page. Never conclude a type is unsupported from a first-page miss. Present the display names to the user; the lowercase `api_name` is what authoring needs for the connector discriminator (see `references/source_to_target_authoring.md`), so keep it for the handoff but don't lead with it.

## 5. Discover a source's tables

For a database source connection, `bdi-connection.sh tables <connection-id>` lists its tables, each with the columns eligible to drive incremental extraction — `increment_columns[]`: name, type, and an `incremental_type` (e.g. `datetime`, `runningnumber`, `epoch`). Use it to pick the incremental cursor when authoring a source-to-target flow.

It is a cursor-discovery aid, not full schema introspection: only cursor-eligible columns come back, so text and boolean columns are omitted and a table whose columns are all text lists an empty `increment_columns`. For a table's complete column list, use `columns`.

Non-database connections don't enumerate tables: most return an empty `items[]` (the same shape a database source with zero tables returns), a few error. An empty result is a legitimate "this connection exposes no tables through the API," not a failure — a real error surfaces on stderr with a non-zero exit. When a connection returns nothing, say so plainly and, if the user wants to browse its structure, point them to the connection in the BDI console.

## 6. Read a table's full column schema

`bdi-connection.sh columns <connection-id> --datasource <api-name> --schema <schema>` returns every column of every table in that schema — including the text and boolean columns `tables` omits. Use it whenever the user asks what a table actually contains, and to populate a flow's column list when authoring.

Two inputs need care. `--datasource` is the source `api_name`, not the connection's type slug; resolve it with the connector-discriminator rule in `references/source_to_target_authoring.md`, since the two frequently differ (`snowflake_src` → `snowflake`). And a schema is required: name one (or several, repeating `--schema`), or pass `--all-schemas`. Name one where you can — `--all-schemas` also returns `information_schema`, which is rarely what the user meant and can dominate the response. Read the available schema names from `tables[].schema_name` rather than pulling everything to discover them.

The call is asynchronous — it triggers a metadata pull and waits for it. A pull against a healthy source settles in well under a minute; one against an unreachable source can sit for tens of minutes before failing, so the wait is bounded at 180s and a timeout leaves the pull running server-side rather than cancelling it — re-check that operation with `bdi-flow.sh operation` instead of re-triggering the pull. A schema name that doesn't exist is not rejected up front: it costs a full round trip and then fails with an internal platform message that names neither the schema nor the problem, so check the name against `tables` first.

`result` is keyed by schema, then by table. Each table carries `columns[]` plus its cursor set, and a schema with no tables is present as a key with nothing under it. Per column, the fields worth reading:

- `name` / `original_column_name`, and `type` (BDI's normalized type) / `original_column_type` (the source's own, e.g. `VARCHAR`, `BIT`, `TIMESTAMP_LTZ`).
- `can_increment` — whether the column can drive incremental extraction. This is the flag that reproduces the cursor set `tables` returns; normalization decides it, so a scaled decimal (`SHORTDECIMAL`) is not cursor-eligible while an unscaled one (`INTEGER`) is.
- `is_key` and `autoincrement` — real primary-key and identity information on sources that report it; both read `false` on sources that don't.
- `supported` reads `false` on every column regardless of type — never filter on it, or you will select nothing. `length` is a `2147483647` sentinel on every column, not a real precision; don't surface it as one.

Two traps. The pull renames the cursor fields `tables` uses — `interval_type` here versus `incremental_type` there, `is_default_inc_col` versus `is_default`, same values — so code or reasoning carried over from one will silently find nothing in the other. And a settled pull can report a problem while still returning the data: treat a populated `error_message` on a successful pull as a warning about one object, not as failure. The script surfaces it on stderr.

The pull is authoritative for *columns*, but not for the table inventory: it and `tables` each return tables the other doesn't. Don't treat either as the complete list of what a source holds.

## 7. Hand off to authoring

Discovery feeds building. Once the user has settled on a source connection, a target, and (for incremental) a cursor column, use `references/source_to_target_authoring.md` for an ELT flow or `references/logic_flow_authoring.md` for an orchestration flow. Carry the resolved connection titles/ids and the chosen cursor column into that step so authoring doesn't re-resolve them.

## Discipline

- Connection **titles** to the user; **ids** only in script calls.
- Everything here is read-only — no mutations, no approvals needed.
- Resolve a connection *with the user*; never silently pick one for them.
- The connection catalog is account-scoped — enumerate it live, don't assume a fixed set of types.
- Where discovery hits a wall the scripts don't cross (OAuth connection setup, a non-database connection's structure), name the limit plainly and route them to the BDI console — never dead-end the user.
