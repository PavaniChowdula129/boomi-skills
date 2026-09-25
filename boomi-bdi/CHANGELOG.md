# Changelog

## 0.2.3

- Keep credentials and presigned URLs out of curl's command line


## 0.2.2

- Skill folder now ships the changelog


## 0.2.1

- `bdi-cdc.sh disable` reports its no-operation response as success, not failure
- Async operation polling tolerates 3 consecutive transport failures
- Documented `bdi-cdc.sh get`'s two HTTP 400s and its non-zero exit on each


## 0.2.0

- State the tooling and approval-prompt guidance host-neutrally


## 0.1.80

- Connector discriminators now enumerated live, not from a frozen list
- `bdi-flow.sh operation` exits non-zero on a failed operation
- Documented operation statuses, CDC failure diagnosis, and copy inheritance


## 0.1.79

- Improved onboarding setup instructions
- BDI_API_URL now reports a missing https:// scheme directly, and tolerates a trailing slash


## 0.1.78

- Gitignore support for non-Claude agent tooling at development time


## 0.1.77

- Improved agent instruction and improved tool response context utilization related to environment variables


## 0.1.76

- Gate mutations in SKILL.md
- Correct the CDC offset claim: only `get` requires the log enabled


## 0.1.75

- Paginate the connection, flow-variable, and environment-check listings; stop the flow-variable round trip from dropping unread pages


## 0.1.74

- Load `.env` with `source ./.env`, bypassing `$PATH` lookup
- Stop exporting `.env` contents to child processes


## 0.1.73

- Link the BDI product and API docs from the README; point the skill at the per-connector and API-auth pages


## 0.1.72

- Note kit installation as console-only


## 0.1.71

- Correct Scope: Python transforms run on Boomi-managed servers, not warehouse push-down


## 0.1.70

- `bdi-connection.sh columns` returns a database source's full column schema


## 0.1.69

- Logicode (Python) steps: upload and read code files from the CLI.


## 0.1.68

- Doc and help-text corrections from E2E testing: merge-key derivation, `river-set` body shape, `copy` created disabled, connections paging


## 0.1.67

- Source-to-target: resolve the source discriminator `api_name` from the catalog.


## 0.1.66

- Document that action-flow definitions are console-authored — the flows API models no fields for them; reference by `action_id`.


## 0.1.65

- Source-to-target: add worked example bodies; correct OneLake fields, `regular` forbidden keys, and the per-table source path.
- CDC: note both-level `extract_method: log` and `cdc_settings` defaults.


## 0.1.64

- CDC: console recovery for a lost PostgreSQL WAL slot.


## 0.1.63

- Refine authoring notes with runtime-validated logic-flow and incremental-extraction details.


## 0.1.62

- Correct the schema-drift and `disable_errors` notes to documented behavior.
- Add authoring guardrails: cron runs in UTC, chain dependent flows, ensure CDC source log retention, size target columns to the source, and treat a throttled source's success as possibly partial.


## 0.1.61

- Improved instructions for net-new flow authoring

## 0.1.60

- Documented the required top-level `metadata` field in `source_to_target_authoring.md`
- Refined instructions about authoring net new assets


## 0.1.59

- Added option to use subagents to some workflows


## 0.1.58

- Document the `schedulers[]` payload (`{cron_expression, is_enabled}`) for source-to-target and CDC flows.


## 0.1.57

- `edit` rejects a source-connector change (400 `Data Flow data source cannot be changed`).
- `activities` rows are per-flow aggregates, not run records.


## 0.1.56

- Note the `is_new_interface` flag on `source-types` (new-UI-creatable, narrower than API-authorable).


## 0.1.55

- Expanded the logic flow authoring reference to enable greenfield builds, without expectation of valid reference assets being made available by the account.

## 0.1.54

- Add a first-run setup guide: region → token → validate → pick an environment, with empty-environment-list and already-set-up handling.


## 0.1.53

- Source-to-target authoring: mode selection, load-shaping patterns, and a pre-write checklist.


## 0.1.52

- Add a data-discovery reference: explore an environment's connections, the connector-type catalog, and a database source's cursor columns before building.


## 0.1.51

- `bdi-connection.sh tables <id>` lists a DB source's tables and incremental-cursor candidate columns.


## 0.1.50

- Expanded the source-to-target flow authoring reference.


## 0.1.49

- Document that `step-logs` serves `logicode` steps only; SQL steps return HTTP 400.


## 0.1.48

- Troubleshooting: note the `succeeded`-but-zero-row trap when a source table is already tracked as loading.


## 0.1.47

- SKILL.md: orient "what can you do?" asks by goal.


## 0.1.46

- `bdi-flow.sh activate`/`disable`: treat a no-op toggle (flow already in the requested state) as success.
- `bdi-flow.sh operation`: poll up to 600s (was 90s), matching the toggle backstop.


## 0.1.45

- Restore `env-delete` (single environment-variable deletion) to bdi-variable.sh


## 0.1.44

- Logic dataframe steps use `target_properties`, not `target_settings`.
- Keyless `upsert_merge` steps create but fail at run.


## 0.1.43

- Added `references/cost_optimization.md` for cost-reduction analysis.


## 0.1.42

- Added a periodic health-digest section to `references/operations.md`.
- Defined "processing units" in SKILL.md.

## 0.1.41

- Added `references/operations.md` — fleet-level run-state questions and run/activate/disable/cancel lifecycle actions.
- Noted that a cancelled run surfaces as `failed` with `error_description: "Run canceled"`.


## 0.1.40

- Added `references/versioning.md` — for version management.
- Reflowed `references/troubleshooting.md` to single-line paragraphs, matching the other skill files (no content change).


## 0.1.39

- Clarify legacy (`is_api_v2:false`) flow guidance


## 0.1.38

- Added `references/troubleshooting.md` — diagnosing a failed data flow run and applying a fix.
- Linked the Boomi Data Integration documentation index for on-demand grounding.


## 0.1.37

- Restructured and tightened SKILL.md


## 0.1.36

- Cleaned line breaks in references/*.md files

## 0.1.35

- Added info about `group_id` omission behavior

## 0.1.34

- Split SKILL.md mega-bullets into sub-bullets (no content change)


## 0.1.33

- Reframed skill positioning as ELT-first
- Noted pushdown-to-warehouse compute
- Added ETL/ELT routing caveat
- Standardized "REST Action" terminology

## 0.1.32

- Fix SKILL.md scripts inventory to show `step-logs` takes a third `<step-id>` arg


## 0.1.31

- Document `get` 400 for datasource_id salesforce/actions flows as a get-endpoint-only limitation


## 0.1.30

- Remove the `delete` subcommands from cli tools; users should delete assets via the BDI GUI


## 0.1.29

- Correct the `is_api_v2` 400 note: `edit`/`copy` are gated (not `get`), and note the recreate-to-edit path


## 0.1.28

- Add `targets` (per-target run breakdown for multi-table flows) to `bdi-flow.sh`


## 0.1.27

- `bdi-flow.sh`: add group filter handling


## 0.1.26

- Add changes/.gitkeep so the fragment directory persists across releases


## 0.1.25

- `bdi-*.sh`: guard option-flag values via shared `need_val`


## 0.1.24

- Note the monolithic-river design (no component model)


## 0.1.23

- Note that the API returns no data rows; verify data warehouse-side


## 0.1.22

- Note that browser-consent OAuth connectors are console-only


## 0.1.21

- Note the missing connection-test endpoint + workaround


## 0.1.20

- Document the no-source-schema-discovery limitation + workarounds


## 0.1.19

- Consolidate pagination handling across scripts


## 0.1.18

- Paginate `bdi-connection.sh` catalog subcommands


## 0.1.17

- SKILL.md: scope out the admin surface as console-only


## 0.1.16

- New `bdi-env.sh`: environment CRUD and audit-event reads


## 0.1.15

- Add `bdi-dataframe.sh` for dataframe ops


## 0.1.14

- `bdi-flow.sh` listings: paging (`--all`/`--page`/`--items`); warn instead of silently truncating at page 1


## 0.1.13

- Add bdi-variable.sh for environment and per-flow (river) variables


## 0.1.12

- Add `versions`/`version`/`restore` (history + rollback) to `bdi-flow.sh`
- Add `stats` (run statistics, per-flow or env-wide) to `bdi-flow.sh`


## 0.1.11

- Poll the activate/disable operation to completion instead of a fixed `river_status` window
- Drop the `BDI_TOGGLE_TIMEOUT`/`BDI_TOGGLE_INTERVAL` knobs from `activate`/`disable`


## 0.1.10

- Add `bdi-cdc.sh` for CDC offset and lifecycle operations
- Document CDC offset/lifecycle behavior in `cdc.md`


## 0.1.9

- Add `bdi-flow.sh runs <flow-id> --from <ts> --to <ts>` to list a flow's runs in a time window (run-id discovery).
- Add `bdi-flow.sh operation <op-id>` to poll an async operation (`GET operations/{id}`) until it settles.
- Add a reusable `poll_operation` helper to `bdi-common.sh`.
- Surface the async `operation_id` from `activate`/`disable` so it can be polled with `operation`.
- Add additional `bdi-flow.sh' capabilities


## 0.1.8

- Add `edit`, `delete`, `add-file` to `bdi-connection.sh`
- Add `type <connection-type>` to `bdi-connection.sh`


## 0.1.7

- Add `edit <flow-id> --body <file.json>` to `bdi-flow.sh`


## 0.1.6

- Add SKILL.md guidance on connection re-use vs. authoring and keeping credentials out of context


## 0.1.5

- Add flow-authoring references: `source_to_target_authoring.md`, `cdc.md`, `logic_flow_authoring.md`
- Expand scope to authoring `source_to_target` and `logic` flows from agent-authored JSON
- Document `skipped` run status (terminal) and `partially succeeded` as a run-group-only aggregate
- Document CSV run logs, overloaded 400 causes, and the 422 error-body shape
- Document execution rate caps (2/min per flow, 15/min per user), the list pagination envelope, and regional API hosts
- Note `river_type`/`type`/`is_api_v2` field placement and account-scoped catalog id/name pairing


## 0.1.4

- Refined scope, frontmatter, and disambiguations


## 0.1.3

- Add `activate` and `disable` subcommands to `bdi-flow.sh`; both poll until `river_status` settles.
- Document the `river_status` run gate and async-toggle behavior in SKILL.md.


## 0.1.2

- Correct run terminal success status `succeed` → `succeeded` in `SKILL.md` and the `bdi-flow.sh` usage text.
- Correct source-to-target flow type `src_to_trgt` → `source_to_target` in `SKILL.md` terminology.
- Add read-only catalog discovery subcommands to `bdi-connection.sh` — `connection-types`, `source-types`, `target-types`, `source-sections` — for enumerating the connector/source/target types available to the account without a selected environment.


## 0.1.1

- Initial bc-bdi plugin scaffold
