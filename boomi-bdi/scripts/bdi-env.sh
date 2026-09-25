#!/usr/bin/env bash
# BDI environment CRUD (account-scoped) and audit-event reads (environment-scoped).

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-env.sh <subcommand> [args]

Environments (account-scoped; need BDI_ACCOUNT_ID, not BDI_ENVIRONMENT_ID):
  list [--include-deleted] [--deployable] [paging]
                                            list the account's environments (discover environment ids here);
                                            each environment's variables map is replaced with "[omitted]" --
                                            read one environment's variables with bdi-variable.sh env-list
  get <env-id>                              fetch one environment
  create --body <file.json>                 create an environment (body: name required; color, description, is_default)
  edit <env-id> --body <file.json>          update an environment (full-body PUT; body: environment_name, color, description, is_default)

Audit events (environment-scoped; use BDI_ENVIRONMENT_ID):
  audit [--from <ts>] [--to <ts>] [--user-id <id>] [--event-type <t>]
        [--entity-type <t>] [--entity-key <k>] [paging]
                                            list audit events in the environment (filters repeatable; combine to narrow)
  audit-get <event-id>                      fetch one audit event

[paging] = --all | --page N | --items N | --max-pages N. The first page is returned by default and a
stderr NOTE fires when more pages exist. --all follows every page and emits a JSON array of page
envelopes (capped by --max-pages, default 100). --page N fetches one page; --items N sets the page
size. --all and --page are mutually exclusive. (audit pages by opaque cursor: only --all advances
it; --page/--items have no effect.)

Env ids are the environment _id (from list). Timestamps are yyyy-mm-ddThh:mm:ss (UTC).
create/edit bodies differ: create uses name, edit uses environment_name. Deleting environments isn't
supported here; have the user delete them in the BDI console. Reads BDI_* from .env. Emits the API's raw response
on stdout.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID

# Account-scoped environments collection (not under a single environment).
envs_url() { bdi_root_url "accounts/${BDI_ACCOUNT_ID}/environments${1:+/$1}"; }

case "$sub" in
  list)
    q=()
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --include-deleted) q+=(--data-urlencode "include_deleted=true"); shift ;;
        --deployable)      q+=(--data-urlencode "is_deployable_environments=true"); shift ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    pg_validate
    BDI_DROP_VARIABLES=1 paginate_get "$(envs_url)" ${q[@]+"${q[@]}"}
    exit 0
    ;;
  get)
    [[ -n "${1:-}" ]] || { echo "Need <env-id>" >&2; exit 1; }
    bdi_api "$(envs_url "$1")"
    ;;
  create)
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    [[ -f "$2" ]] || { echo "File not found: $2" >&2; exit 1; }
    bdi_api -X POST --data-binary @"$2" "$(envs_url)"
    ;;
  edit)
    [[ -n "${1:-}" ]] || { echo "Need <env-id>" >&2; exit 1; }
    id="$1"; shift
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    [[ -f "$2" ]] || { echo "File not found: $2" >&2; exit 1; }
    bdi_api -X PUT --data-binary @"$2" "$(envs_url "$id")"
    ;;
  audit)
    require_env BDI_ENVIRONMENT_ID
    q=()
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --from)        need_val "$1" "${2:-}"; q+=(--data-urlencode "start_time=$2"); shift 2 ;;
        --to)          need_val "$1" "${2:-}"; q+=(--data-urlencode "end_time=$2"); shift 2 ;;
        --user-id)     need_val "$1" "${2:-}"; q+=(--data-urlencode "user_id=$2"); shift 2 ;;
        --event-type)  need_val "$1" "${2:-}"; q+=(--data-urlencode "event_type=$2"); shift 2 ;;
        --entity-type) need_val "$1" "${2:-}"; q+=(--data-urlencode "entity_type=$2"); shift 2 ;;
        --entity-key)  need_val "$1" "${2:-}"; q+=(--data-urlencode "entity_logical_key=$2"); shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    pg_validate
    paginate_get "$(bdi_env_url audit_events)" ${q[@]+"${q[@]}"}
    exit 0
    ;;
  audit-get)
    require_env BDI_ENVIRONMENT_ID
    [[ -n "${1:-}" ]] || { echo "Need <event-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "audit_events/$1")"
    ;;
  *) usage >&2; exit 1 ;;
esac

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "ERROR: HTTP $RESPONSE_CODE" >&2
  echo "$RESPONSE_BODY" >&2
  exit 1
fi
echo "$RESPONSE_BODY"
