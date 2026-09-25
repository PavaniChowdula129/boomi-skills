#!/usr/bin/env bash
# BDI variable operations: environment-scoped variables and per-river variables.

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-variable.sh <subcommand> [args]

Environment variables (environment-scoped):
  env-list                       list the environment's variables
  env-set --body <file.json>     add or update environment variables
  env-delete <variable-key>      delete one environment variable by key

River variables (per flow):
  river-get <flow-id> [paging]   fetch a flow's variables
  river-set <flow-id> --body <file.json>   update a flow's variables

env-list isn't paginated — one response holds every variable.

[paging] (river-get) = --all | --page N | --items N | --max-pages N. Default: first page
(20) with a stderr NOTE when more exist; --all follows every page into a JSON array of
page envelopes.

Body shapes (raw JSON, passed through as-is):
  env-set    {"variables": {"NAME": "value", ...}}
  river-set  {"items": [{"name": "NAME", "settings": {...}, "value": ...}]}  (settings required per item)

env-set adds or updates only the keys sent. river-set replaces the flow's entire
variable set: read-modify-write (river-get --all, merge every envelope's items into one
body, river-set), resending each item's full settings — an omitted settings flag resets
to its default. A bare river-get reads one page only; replacing from a partial read
destroys the rest.

The flow-id is the river cross_id (from bdi-flow.sh list/get). Reads BDI_* from
.env. Emits the API's raw response on stdout.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID BDI_ENVIRONMENT_ID

case "$sub" in
  env-list)
    # This endpoint carries no page fields and ignores items_per_page.
    [[ -n "${1:-}" ]] && { echo "ERROR: env-list takes no arguments — it returns the environment's complete variable set in one response." >&2; exit 1; }
    bdi_api "$(bdi_env_url variables)"
    ;;
  env-set)
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    [[ -f "$2" ]] || { echo "File not found: $2" >&2; exit 1; }
    bdi_api -X PUT --data-binary @"$2" "$(bdi_env_url variables)"
    ;;
  env-delete)
    [[ -n "${1:-}" ]] || { echo "Need <variable-key>" >&2; exit 1; }
    bdi_api -G --data-urlencode "variable_key=$1" -X DELETE "$(bdi_env_url variables)"
    ;;
  river-get)
    [[ -n "${1:-}" ]] || { echo "Need <flow-id>" >&2; exit 1; }
    id="$1"; shift
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      echo "ERROR: unexpected argument '$1'" >&2; exit 1
    done
    pg_validate
    paginate_get "$(bdi_env_url "rivers/$id/variables")"
    exit 0
    ;;
  river-set)
    [[ -n "${1:-}" ]] || { echo "Need <flow-id>" >&2; exit 1; }
    id="$1"; shift
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    [[ -f "$2" ]] || { echo "File not found: $2" >&2; exit 1; }
    # river-get --all emits one envelope per page; PUTting that array would wipe the variable set.
    if [[ "$(tr -d '[:space:]' < "$2" | cut -c1)" == "[" ]]; then
      echo "ERROR: the body is a JSON array. river-get --all returns one envelope per page — merge every envelope's items into a single {\"items\":[...]} body before sending." >&2
      exit 1
    fi
    bdi_api -X PUT --data-binary @"$2" "$(bdi_env_url "rivers/$id/variables")"
    ;;
  *) usage >&2; exit 1 ;;
esac

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "ERROR: HTTP $RESPONSE_CODE" >&2
  echo "$RESPONSE_BODY" >&2
  exit 1
fi
echo "$RESPONSE_BODY"
