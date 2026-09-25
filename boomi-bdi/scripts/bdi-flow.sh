#!/usr/bin/env bash
# BDI data-flow operations (the API calls flows "rivers").

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-flow.sh <subcommand> [args]

Subcommands:
  list [--name <text>] [--group <group-id>] [--group-name <text>] [paging]
                                                  list data flows (rivers)
  search [--query <t>] [--name <t>] [--status <s>] [--type <t>] [--group <group-id>] [paging]
                                                  richer flow search (filterable)
  get <flow-id>                                   fetch one flow's configuration
  run <flow-id>                                   trigger a run (returns run_id; poll with status)
  run-sub <flow-id> <sub-id>                      run one sub-river of a master flow
  cancel <flow-id> (--run <run-id> | --run-group <group-id>)
                                                  cancel an in-flight run/group (async, best-effort); confirm via status
  activate <flow-id>                              enable the flow's schedule (waits for river_status to settle)
  disable <flow-id>                               disable the flow's schedule (waits for river_status to settle)
  status <flow-id> <run-id>                       fetch one run
  logs <flow-id> <run-id>                         fetch a run's logs
  tasks <flow-id> <run-id>                         list a run's tasks (any flow type)
  steps <flow-id> <run-id>                         list a run's logic steps (logic flows)
  step-logs <flow-id> <run-id> <step-id> [--iteration <n>]
                                                  fetch a logic step's log URL (presigned, short-lived)
  run-vars <flow-id> <run-id>                      fetch a run's variables (logic flows; values expire soon after a run)
  runs <flow-id> --from <ts> --to <ts> [paging]   list a flow's runs in a window (discover run-ids)
  operation <op-id>                               poll an async operation until it settles
  activities --from <ts> --to <ts> [--group <group-id>] [paging]
                                                  environment-wide run scan (one call, all flows)
  run-groups <flow-id> --from <ts> --to <ts> [--group <run-group-id>] [paging]
                                                  list a flow's run groups in a window (where "partially succeeded" lives), or one group's detail
                                                  (this --group is a run_group_id — an execution-time run grouping, unrelated to the
                                                  Data Flow Group --group above)
  sub-rivers <flow-id> --from <ts> --to <ts> [paging]
                                                  list a master flow's sub-river runs in a window
  copy <flow-id>                                  copy a flow (synchronous; returns the new cross_id; the copy is created disabled regardless of the source's status, but inherits the source's
                                                  scheduler and target as-is — if that scheduler is enabled, activating the copy starts it on that schedule)
  create --body <file.json>                       create a flow from a complete JSON body
  edit <flow-id> --body <file.json>               replace a flow's body (full PUT; get it, change what you need, put it back)
  versions <flow-id> [paging]                     list a flow's saved versions (history)
  version <flow-id> <version-id>                  fetch one saved version (embeds the flow snapshot)
  restore <flow-id> <version-id>                  roll the flow back to a version (synchronous; appends a new version)
  stats [<flow-id>] --from <ts> --to <ts> [--status <s>]
                                                  run-status statistics — one flow, or environment-wide
  targets <flow-id> --from <ts> --to <ts> [--status <s>]... [--run-group <id>] [--sub-river <id>]
          [--sort-by units|last_run|table_name] [--sort-order desc|asc]
                                                  per-target (table-name) run breakdown for a multi-table flow

Flow ids are the API's river cross_id. Timestamps are yyyy-mm-ddThh:mm:ss (UTC);
--from and --to are both required. Run statuses: pending/running/succeeded/failed/canceled/skipped
(skipped is terminal). "partially succeeded" is a run-group aggregate only, never a single run.
Async operations (activate/disable/operation) carry their own status vocabulary, not run statuses:
D is done and E is an error -- both terminal -- and any other value is still in progress.
Deleting flows isn't supported here; have the user delete them in the BDI console.
Reads BDI_* from .env. Emits the API's raw response on stdout.

Groups organize flows into folders (name, color/icon, a default group); managed in the console's
Groups tab only — this API has no group create/rename/delete/list endpoint. list/search/activities
can filter by the group a flow belongs to via --group (its group_id); list can also filter by
--group-name. search and activities do not accept --group-name. To discover existing groups, derive
the distinct group_id/group_name pairs from `list --all` output.

[paging] = --all | --page N | --items N | --max-pages N. List responses are paged; by default
the first page is returned and a stderr NOTE fires when more pages exist. --all follows every page
and emits a JSON array of page envelopes (capped by --max-pages, default 100). --page N fetches one
page; --items N sets the page size. --all and --page are mutually exclusive.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID BDI_ENVIRONMENT_ID

# Backstop for the async activate/disable operation. It validates source/target connections,
# which can take minutes, so the timeout is generous; a settled operation returns as soon as it
# reaches a terminal state, well before this.
TOGGLE_TIMEOUT=600
TOGGLE_INTERVAL=5

# POST an activate_river/disable_river toggle, then poll its async operation to a terminal state.
# args: <flow-id> <endpoint> <verb>
do_toggle() {
  local flow_id="$1" endpoint="$2" verb="$3"
  bdi_api -X POST -d '{}' "$(bdi_env_url "rivers/$flow_id/$endpoint")"
  if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
    echo "ERROR: HTTP $RESPONSE_CODE" >&2
    echo "$RESPONSE_BODY" >&2
    exit 1
  fi
  local op_id
  op_id=$(printf '%s' "$RESPONSE_BODY" \
    | grep -oE '"operation_id"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 \
    | sed -E 's/.*"([^"]+)"$/\1/') || true
  if [[ -z "$op_id" ]]; then
    # No-op toggle: the flow is already in the requested state — empty 2xx, no operation to poll.
    # Confirm river_status matches and treat as success.
    local code="$RESPONSE_CODE" want=disabled
    [[ "$endpoint" == activate_river ]] && want=active
    bdi_api "$(bdi_env_url "rivers/$flow_id")"
    if printf '%s' "$RESPONSE_BODY" | grep -qE "\"river_status\"[[:space:]]*:[[:space:]]*\"$want\""; then
      echo "$verb: flow is already $want (HTTP $code, no async operation)." >&2
      echo "$RESPONSE_BODY"; exit 0
    fi
    echo "ERROR: $verb returned HTTP $code with no operation_id and the flow is not $want." >&2
    echo "$RESPONSE_BODY" >&2; exit 1
  fi
  echo "$verb acknowledged (HTTP $RESPONSE_CODE); polling operation '$op_id' until it settles (up to ${TOGGLE_TIMEOUT}s)..." >&2
  local rc=0
  poll_operation "$op_id" "$TOGGLE_TIMEOUT" "$TOGGLE_INTERVAL" || rc=$?
  if (( rc == 2 )); then echo "ERROR: could not read operation status while polling the toggle." >&2; echo "$RESPONSE_BODY" >&2; exit 1; fi
  if (( rc == 1 )); then echo "ERROR: $verb operation did not settle within ${TOGGLE_TIMEOUT}s." >&2; echo "$RESPONSE_BODY" >&2; exit 1; fi
  local status
  status=$(printf '%s' "$RESPONSE_BODY" \
    | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 \
    | sed -E 's/.*"([^"]+)"$/\1/') || true
  if [[ "$status" == "E" ]]; then
    echo "ERROR: $verb operation failed (status E)." >&2
    [[ "$endpoint" == activate_river ]] && echo "Activation validates source/target connections; an unreachable connection fails the operation. Check the BDI console." >&2
    echo "$RESPONSE_BODY" >&2
    exit 1
  fi
  echo "$verb operation settled (status ${status:-unknown})." >&2
  echo "$RESPONSE_BODY"
  exit 0
}

case "$sub" in
  list)
    q=()
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --name)       need_val "$1" "${2:-}"; q+=(--data-urlencode "name=$2"); shift 2 ;;
        --group)      need_val "$1" "${2:-}"; q+=(--data-urlencode "group_id=$2"); shift 2 ;;
        --group-name) need_val "$1" "${2:-}"; q+=(--data-urlencode "group_name=$2"); shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    pg_validate
    [[ -z "$PG_ITEMS" ]] && PG_ITEMS=50   # list/search default page size
    paginate_get "$(bdi_env_url rivers)" ${q[@]+"${q[@]}"}
    exit 0
    ;;
  search)
    # Richer than `list --name`: filter by free-text, status, and type.
    q=()
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --query)  need_val "$1" "${2:-}"; q+=(--data-urlencode "search_query=$2"); shift 2 ;;
        --name)   need_val "$1" "${2:-}"; q+=(--data-urlencode "name=$2"); shift 2 ;;
        --status) need_val "$1" "${2:-}"; q+=(--data-urlencode "river_status=$2"); shift 2 ;;
        --type)   need_val "$1" "${2:-}"; q+=(--data-urlencode "river_type=$2"); shift 2 ;;
        --group)  need_val "$1" "${2:-}"; q+=(--data-urlencode "group_id=$2"); shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    pg_validate
    [[ -z "$PG_ITEMS" ]] && PG_ITEMS=50   # list/search default page size
    paginate_get "$(bdi_env_url rivers_search)" ${q[@]+"${q[@]}"}
    exit 0
    ;;
  get)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1")"
    ;;
  run)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id>" >&2; exit 1; }
    bdi_api -X POST -d '{}' "$(bdi_env_url "rivers/$1/run")"
    ;;
  run-sub)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <sub-id>" >&2; exit 1; }
    bdi_api -X POST -d '{}' "$(bdi_env_url "rivers/$1/sub_rivers/$2/run")"
    ;;
  cancel)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id> (--run <run-id> | --run-group <group-id>)" >&2; exit 1; }
    flow_id="$1"; shift
    run_id="" group_id=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --run)       need_val "$1" "${2:-}"; run_id="$2"; shift 2 ;;
        --run-group) need_val "$1" "${2:-}"; group_id="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    # Exactly one target: run_id cancels one run, run_group_id cancels a group's members.
    if [[ -n "$run_id" && -z "$group_id" ]]; then
      body="{\"run_id\":\"$run_id\"}"
    elif [[ -z "$run_id" && -n "$group_id" ]]; then
      body="{\"run_group_id\":\"$group_id\"}"
    else
      echo "Provide exactly one of --run <run-id> or --run-group <group-id>" >&2; exit 1
    fi
    bdi_api -X POST -d "$body" "$(bdi_env_url "rivers/$flow_id/cancel_run")"
    ;;
  activate)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id>" >&2; exit 1; }
    do_toggle "$1" activate_river "activate"
    ;;
  disable)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id>" >&2; exit 1; }
    do_toggle "$1" disable_river "disable"
    ;;
  status)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <run-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/runs/$2")"
    ;;
  logs)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <run-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/runs/$2/logs")"
    ;;
  tasks)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <run-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/runs/$2/tasks")"
    ;;
  steps)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <run-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/runs/$2/logic_steps")"
    ;;
  step-logs)
    [[ -z "${1:-}" || -z "${2:-}" || -z "${3:-}" ]] && { echo "Need <flow-id> <run-id> <step-id> [--iteration <n>]" >&2; exit 1; }
    flow_id="$1"; run_id="$2"; step_id="$3"; shift 3
    iteration=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --iteration) need_val "$1" "${2:-}"; iteration="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    url="$(bdi_env_url "rivers/$flow_id/runs/$run_id/logic_steps/$step_id/logs")"
    if [[ -n "$iteration" ]]; then
      bdi_api -G --data-urlencode "iteration_number=$iteration" "$url"
    else
      bdi_api "$url"
    fi
    ;;
  run-vars)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <run-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/runs/$2/variables")"
    ;;
  runs)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id> --from <ts> --to <ts>" >&2; exit 1; }
    flow_id="$1"; shift
    from="" to=""
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --from) need_val "$1" "${2:-}"; from="$2"; shift 2 ;;
        --to)   need_val "$1" "${2:-}"; to="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    [[ -z "$from" || -z "$to" ]] && { echo "Both --from and --to are required" >&2; exit 1; }
    pg_validate
    paginate_get "$(bdi_env_url "rivers/$flow_id/runs")" \
      --data-urlencode "start_time=$from" --data-urlencode "end_time=$to"
    exit 0
    ;;
  operation)
    [[ -z "${1:-}" ]] && { echo "Need <op-id>" >&2; exit 1; }
    op_id="$1"
    # Same backstop as the toggle path so a standalone check can't time out on an operation the
    # toggle would have waited out.
    op_timeout="$TOGGLE_TIMEOUT" op_interval="$TOGGLE_INTERVAL"
    echo "polling operation '$op_id' until it settles (up to ${op_timeout}s)..." >&2
    rc=0
    poll_operation "$op_id" "$op_timeout" "$op_interval" || rc=$?
    if (( rc == 2 )); then
      echo "ERROR: could not read operation status while polling." >&2
      echo "$RESPONSE_BODY" >&2
      exit 1
    fi
    if (( rc == 1 )); then
      echo "ERROR: operation did not settle within ${op_timeout}s." >&2
      echo "$RESPONSE_BODY" >&2
      exit 1
    fi
    # poll_operation returns 0 on any terminal state, so E (error) still has to be caught here —
    # same follow-up the activate/disable, CDC and dataframe pollers do.
    status=$(printf '%s' "$RESPONSE_BODY" \
      | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' \
      | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
    if [[ "$status" == "E" ]]; then
      echo "ERROR: operation failed (status E)." >&2
      echo "$RESPONSE_BODY" >&2
      exit 1
    fi
    echo "operation settled (status ${status:-unknown})." >&2
    echo "$RESPONSE_BODY"
    exit 0
    ;;
  activities)
    from="" to="" group=""
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --from)  need_val "$1" "${2:-}"; from="$2"; shift 2 ;;
        --to)    need_val "$1" "${2:-}"; to="$2"; shift 2 ;;
        --group) need_val "$1" "${2:-}"; group="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    [[ -z "$from" || -z "$to" ]] && { echo "Both --from and --to are required" >&2; exit 1; }
    pg_validate
    q=(--data-urlencode "start_time=$from" --data-urlencode "end_time=$to")
    [[ -n "$group" ]] && q+=(--data-urlencode "group_id=$group")
    paginate_get "$(bdi_env_url activities)" "${q[@]}"
    exit 0
    ;;
  run-groups)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id> --from <ts> --to <ts> [--group <run-group-id>]" >&2; exit 1; }
    flow_id="$1"; shift
    from="" to="" group=""
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --from)  need_val "$1" "${2:-}"; from="$2"; shift 2 ;;
        --to)    need_val "$1" "${2:-}"; to="$2"; shift 2 ;;
        --group) need_val "$1" "${2:-}"; group="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    if [[ -n "$group" ]]; then
      # Single run-group detail: path-addressed, no time window, not paginated.
      bdi_api "$(bdi_env_url "rivers/$flow_id/activities_run_groups/$group")"
    else
      [[ -z "$from" || -z "$to" ]] && { echo "Both --from and --to are required (omit only with --group)" >&2; exit 1; }
      pg_validate
      paginate_get "$(bdi_env_url "rivers/$flow_id/activities_run_groups")" \
        --data-urlencode "start_time=$from" --data-urlencode "end_time=$to"
      exit 0
    fi
    ;;
  sub-rivers)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id> --from <ts> --to <ts>" >&2; exit 1; }
    flow_id="$1"; shift
    from="" to=""
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --from) need_val "$1" "${2:-}"; from="$2"; shift 2 ;;
        --to)   need_val "$1" "${2:-}"; to="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    [[ -z "$from" || -z "$to" ]] && { echo "Both --from and --to are required" >&2; exit 1; }
    pg_validate
    # activities_sub_rivers may return an unpaginated envelope (no next_page); paginate_get handles both.
    paginate_get "$(bdi_env_url "rivers/$flow_id/activities_sub_rivers")" \
      --data-urlencode "start_time=$from" --data-urlencode "end_time=$to"
    exit 0
    ;;
  copy)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id>" >&2; exit 1; }
    # Synchronous (201): the response carries the new flow's cross_id.
    bdi_api -X POST -d '{}' "$(bdi_env_url "rivers/$1/copy")"
    ;;
  create)
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X POST --data-binary @"$2" "$(bdi_env_url rivers)"
    ;;
  edit)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id> --body <file.json>" >&2; exit 1; }
    flow_id="$1"; shift
    [[ "${1:-}" == "--body" ]] || { echo "Need <flow-id> --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X PUT --data-binary @"$2" "$(bdi_env_url "rivers/$flow_id")"
    ;;
  versions)
    [[ -z "${1:-}" ]] && { echo "Need <flow-id>" >&2; exit 1; }
    flow_id="$1"; shift
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    pg_validate
    paginate_get "$(bdi_env_url "rivers/$flow_id/versions")"
    exit 0
    ;;
  version)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <version-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/versions/$2")"
    ;;
  restore)
    [[ -z "${1:-}" || -z "${2:-}" ]] && { echo "Need <flow-id> <version-id>" >&2; exit 1; }
    bdi_api -X PUT -d "{\"version_id\":\"$2\"}" "$(bdi_env_url "rivers/$1/restore")"
    ;;
  stats)
    flow_id=""; from=""; to=""; status=""
    [[ -n "${1:-}" && "${1:0:2}" != "--" ]] && { flow_id="$1"; shift; }
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --from)   need_val "$1" "${2:-}"; from="$2"; shift 2 ;;
        --to)     need_val "$1" "${2:-}"; to="$2"; shift 2 ;;
        --status) need_val "$1" "${2:-}"; status="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    [[ -z "$from" || -z "$to" ]] && { echo "Both --from and --to are required" >&2; exit 1; }
    q=(--data-urlencode "start_time=$from" --data-urlencode "end_time=$to")
    [[ -n "$status" ]] && q+=(--data-urlencode "status=$status")
    if [[ -n "$flow_id" ]]; then
      bdi_api -G "${q[@]}" "$(bdi_env_url "rivers/$flow_id/activities_statistics")"
    else
      bdi_api -G "${q[@]}" "$(bdi_env_url activities_statistics)"
    fi
    ;;
  targets)
    # No environment-wide variant of activities_targets, so a flow id is required (unlike stats).
    [[ -z "${1:-}" || "${1:0:2}" == "--" ]] && { echo "Need <flow-id> --from <ts> --to <ts> (targets requires a flow id)" >&2; exit 1; }
    flow_id="$1"; shift
    from=""; to=""; q=()   # --status is repeatable: each occurrence appends its own status= entry
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --from)       need_val "$1" "${2:-}"; from="$2"; shift 2 ;;
        --to)         need_val "$1" "${2:-}"; to="$2"; shift 2 ;;
        --run-group)  need_val "$1" "${2:-}"; q+=(--data-urlencode "run_group_id=$2"); shift 2 ;;
        --sub-river)  need_val "$1" "${2:-}"; q+=(--data-urlencode "sub_river_id=$2"); shift 2 ;;
        --status)     need_val "$1" "${2:-}"; q+=(--data-urlencode "status=$2"); shift 2 ;;
        --sort-by)    need_val "$1" "${2:-}"; q+=(--data-urlencode "sort_by=$2"); shift 2 ;;
        --sort-order) need_val "$1" "${2:-}"; q+=(--data-urlencode "sort_order=$2"); shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    [[ -z "$from" || -z "$to" ]] && { echo "Both --from and --to are required" >&2; exit 1; }
    q+=(--data-urlencode "start_time=$from" --data-urlencode "end_time=$to")
    bdi_api -G "${q[@]}" "$(bdi_env_url "rivers/$flow_id/activities_targets")"
    ;;
  *) usage >&2; exit 1 ;;
esac

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "ERROR: HTTP $RESPONSE_CODE" >&2
  echo "$RESPONSE_BODY" >&2
  exit 1
fi
echo "$RESPONSE_BODY"
