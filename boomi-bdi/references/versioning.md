# Managing data flow versions

Every save of a data flow (river) appends a version. This covers working with that history — list the versions, view any one in full, compare two, and (only on the user's explicit approval) restore the flow to a prior version. Reads are pure; restore is a mutation with potentially high data consequences: it is mechanically reversible, but that is not license to make such changes lightly.

The shape: resolve the flow → list versions → view or compare as needed → restore on approval.

## Contents

- Resolve the flow
- List versions
- View a single version
- Compare two versions (the risk rubric)
- Restore (on approval)
- Discipline

## 1. Resolve the flow

Resolve the user's name to a flow with `bdi-flow.sh search` (server-side `--name`/`--query` filter; prefer it over `list`). If the match is ambiguous, confirm the specific flow with the user before continuing.

## 2. List versions

```
bdi-flow.sh versions <flow-id> [paging]
```

Returns the saved versions newest-first, each carrying its `version_id`, author, timestamp, and a per-item `bookmarked` boolean (distinct from the envelope's `statistics.bookmarked_versions` count). Which version is *current* comes from the flow itself — `bdi-flow.sh get <flow-id>` exposes it as `metadata.current_version_id`. Like other listings, `versions` returns the first page only; page through it if the flow has a long history.

The response envelope's `statistics` reports usage against per-flow caps — `total_versions`/`versions_allowed` and `bookmarked_versions`/`bookmarks_allowed` — so saved versions and bookmarks are finite; read it when a user asks about retention limits.

Talk to the user in flow titles; version ids appear only where they're unavoidable (a diff header, a restore).

Expect the user to name a version loosely — a short id-prefix (`@abc12345`), or by recency or author ("yesterday's version", "Dana's last change"). Resolve it yourself against this listing: match a prefix to the full `version_id`, and if a prefix matches more than one version, show the candidates and ask which.

## 3. View a single version

```
bdi-flow.sh version <flow-id> <version-id>
```

Fetches one saved version with the full flow snapshot embedded — the flow's entire config as of that save. The snapshot nests that body under a `river` key, so in a version snapshot every config path below reads as `river.properties.…` (a plain `get` returns the same body at the top level, as `properties.…`). Use it to show what a version contained, and as the input to a comparison.

## 4. Compare two versions

There's no diff subcommand — fetch both snapshots with `version` and compare them yourself. Two hygiene rules keep the comparison meaningful:

- **Ignore ambient fields that change on every save** — the metadata timestamps (`metadata.created_at`, `metadata.last_updated_at`), the attribution fields (`created_by`, `last_updated_by`), and `metadata.current_version_id`. Diffing these makes every save look like a change.
- **Compare list elements by stable key, not by position** — schedulers by `cron_expression`; schemas and tables by name (`source_to_target` flows put a table's identity in `details.name`, falling back to `details.target_table`). Otherwise a reordering masquerades as a change.

Lead with a plain-English summary of what changed — a reader shouldn't need to know the config schema to follow it — then offer the field-level detail for anyone who wants it.

Classify the overall change by its **highest-risk** field, using the rubric below. Paths are literal config paths within the flow body — `properties.…` here, `river.properties.…` when read from a `version` snapshot (§3):

| Risk | Field / change | Why it matters |
|---|---|---|
| **HIGH** | `properties.target.loading_method` | Loading-mode change can mix or duplicate prior rows if the table isn't reconciled |
| **HIGH** | `properties.target.merge_method` | Alters how records are deduplicated on write |
| **HIGH** | `properties.target.table_name` / `schema_name` / `database_name` | Writes redirect to a different table / schema / database; downstream queries on the old name stop receiving data |
| **HIGH** | `properties.source.connection_id` | Reads now come from a different source system |
| **HIGH** | `properties.source.additional_settings.extract_method` | Source-contract change (log-based CDC vs incremental key vs full load) |
| **HIGH** | a table's `details.is_selected` → `false` | Replication stops for that table |
| **HIGH** | a table's `details.target_table` renamed | The table's destination name changed; downstream queries break |
| **HIGH** | a table added to / removed from the replication set | A table entry appeared in or disappeared from `properties.schemas[].tables[]` (both are arrays; a table's identity is `details.name`) |
| **MEDIUM** | `properties.source.cdc_settings` | CDC replication slot / publication change |
| **MEDIUM** | `properties.source.additional_settings.fz_*` | File-zone path or partitioning change |
| **MEDIUM** | a table's `details.cdc_settings` (e.g. `initiate_table`) | Per-table CDC tuning; affects backfill behavior |
| **MEDIUM** | `properties.schedulers` | Schedule turned on/off, or cron expression changed |
| **MEDIUM** | `properties.schemas` (other schema-level config) | Schema-level configuration change |
| **LOW** | everything else — description, name, `river_status`, run timeout | Cosmetic / operational only |

Reading the rubric: several fields are conditional — `loading_method`, `merge_method`, `schema_name`, and `database_name` appear only on warehouse targets; `source.cdc_settings` only on log-CDC flows; and `target.table_name` is empty on multi-table flows (the real per-table destination is `details.target_table`). Treat a field that's simply absent on a given flow as not-applicable, not a change to empty. And `fz_path` is platform-normalized on save, so an `fz_*` delta can be a normalization artifact rather than a user edit — confirm it reflects a real change before scoring it.

Close the comparison by offering the restore follow-up when it's relevant: to roll back to the older version, run `restore` (next section).

## 5. Restore — mutation, explicit approval only

`bdi-flow.sh restore <flow-id> <version-id>` rolls the flow back to a version **synchronously** and **append-only**: rather than rewinding, it creates a *new* version whose content equals the chosen snapshot and points the flow at it. So restore is itself reversible — the pre-restore state remains an earlier version you can restore back to — and after a restore the flow's `current_version_id` is the new version's id, not the target's.

A restore may be rejected on an `active` flow with HTTP 400 — `"Please disable the data flow before running a restore version operation"`. When that happens, disable the flow for the restore and re-activate it afterward: **disable → restore → re-activate**. That takes the flow briefly offline (it won't run, scheduled or manual, until re-activated), and `restore` does not re-activate for you — a restored flow stays `disabled` until you turn it back on.

Do not make consequential changes autonomously — they must be reviewed with the user. Since restoring an active flow may briefly take it offline, tell the user that up front, not only that the config will change.

Steps:

- Read the flow first with `bdi-flow.sh get`: it reports `river_status` and `metadata.current_version_id`. If the target is already the current version, say so and skip — no restore needed.
- Show the diff between the current version and the target (§4, with its risk level), and state plainly that restore is reversible, and that restoring an active flow may briefly disable it (offline until re-enabled). Then **wait for the user's explicit approval**.
- On approval, run `restore`. If it returns the "please disable" 400 above, do the sequence instead: `bdi-flow.sh disable` (the script waits for it to settle) → `restore` → `bdi-flow.sh activate`, then `get` to confirm `river_status` returned to `active`. If the flow was already `disabled`, `restore` runs directly — leave it disabled, as you found it.
- `activate` re-validates the source/target connections and can take minutes or fail; a failed re-activation leaves the flow disabled (offline). If it fails, surface the activation error and tell the user the flow is still disabled — never leave it silently down.
- If a `restore` fails after you disabled an active flow, re-activate it (or explicitly tell the user it is disabled) before stopping — don't strand it offline. Render the API `detail` on any 4xx; don't retry blindly.
- On success, report the flow's new current version id and offer a rerun to validate (`bdi-flow.sh run <flow-id>`) if the user wants one.

## Discipline

- Flow **titles** to the user; **ids** in script calls. Version ids surface only in a diff header or a restore, by necessity.
- Reads (`versions`, `version`) are pure. `restore` is the only write here, and it's reversible — but still show the change and get approval first.
- Restore is reversible *config* history, not a data undo — it changes what the next run does, not rows already written to the target.
- A version saved shortly before a failure is context, not proven cause — see `references/troubleshooting.md` §5 before implying one changed a run's outcome.
