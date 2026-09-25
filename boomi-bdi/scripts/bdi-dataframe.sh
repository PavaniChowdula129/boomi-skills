#!/usr/bin/env bash
# BDI dataframe operations (named, environment-scoped data stores used by logic flows).

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-dataframe.sh <subcommand> [args]

Dataframe operations (environment-scoped; keyed by dataframe name):
  list [paging]                      list dataframes in the environment
  get <name>                         fetch one dataframe
  add --body <file.json>             create a dataframe ({"name":"...", optional connection_settings})
  update <name> --body <file.json>   update a dataframe's connection_settings (full-body PUT)
  clear <name>                       clear a dataframe's values (async; waits for the operation)
  download <name>                    download a dataframe (async; waits for the operation, whose result carries the data/URL)

[paging] = --all | --page N | --items N | --max-pages N. The first page is returned by default and a
stderr NOTE fires when more pages exist. --all follows every page and emits a JSON array of page
envelopes (capped by --max-pages, default 100). --page N fetches one page; --items N sets the page
size. --all and --page are mutually exclusive.

clear/download are asynchronous: the call returns 202 with an operation that this script polls to a
terminal state, exiting non-zero on error. Deleting dataframes isn't supported here; have the user
delete them in the BDI console. Reads BDI_* from .env. Emits the API's raw response on stdout.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID BDI_ENVIRONMENT_ID

# Poll backstop for the async clear/download operations.
DF_TIMEOUT=300
DF_INTERVAL=5

# Fire an async dataframe op (202 + operation), then poll the operation to a terminal state.
# args: <verb> <bdi_api args...>
do_async_df() {
  local verb="$1"; shift
  bdi_api "$@"
  if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
    echo "ERROR: HTTP $RESPONSE_CODE" >&2; echo "$RESPONSE_BODY" >&2; exit 1
  fi
  local op_id
  op_id=$(printf '%s' "$RESPONSE_BODY" \
    | grep -oE '"operation_id"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
  [[ -n "$op_id" ]] || { echo "ERROR: no operation_id in the $verb response; cannot confirm completion." >&2; echo "$RESPONSE_BODY" >&2; exit 1; }
  echo "$verb acknowledged (HTTP $RESPONSE_CODE); polling operation '$op_id' until it settles (up to ${DF_TIMEOUT}s)..." >&2
  local rc=0
  poll_operation "$op_id" "$DF_TIMEOUT" "$DF_INTERVAL" || rc=$?
  if (( rc == 2 )); then echo "ERROR: could not read operation status while polling." >&2; echo "$RESPONSE_BODY" >&2; exit 1; fi
  if (( rc == 1 )); then echo "ERROR: $verb operation did not settle within ${DF_TIMEOUT}s." >&2; echo "$RESPONSE_BODY" >&2; exit 1; fi
  local status
  status=$(printf '%s' "$RESPONSE_BODY" \
    | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
  if [[ "$status" == "E" ]]; then
    echo "ERROR: $verb operation failed (status E)." >&2; echo "$RESPONSE_BODY" >&2; exit 1
  fi
  echo "$verb operation settled (status ${status:-unknown})." >&2
  echo "$RESPONSE_BODY"; exit 0
}

case "$sub" in
  list)
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      echo "ERROR: unexpected argument '$1'" >&2; exit 1
    done
    pg_validate
    [[ -z "$PG_ITEMS" ]] && PG_ITEMS=50   # default page size
    paginate_get "$(bdi_env_url dataframes)"
    exit 0
    ;;
  get)
    [[ -n "${1:-}" ]] || { echo "Need <name>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "dataframes/$1")"
    ;;
  add)
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X POST --data-binary @"$2" "$(bdi_env_url dataframes)"
    ;;
  update)
    [[ -n "${1:-}" ]] || { echo "Need <name>" >&2; exit 1; }
    name="$1"; shift
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X PUT --data-binary @"$2" "$(bdi_env_url "dataframes/$name")"
    ;;
  clear)
    [[ -n "${1:-}" ]] || { echo "Need <name>" >&2; exit 1; }
    do_async_df "clear" -X POST -d '{}' "$(bdi_env_url "dataframes/$1/clear")"
    ;;
  download)
    [[ -n "${1:-}" ]] || { echo "Need <name>" >&2; exit 1; }
    do_async_df "download" "$(bdi_env_url "dataframes/$1/download")"
    ;;
  *) usage >&2; exit 1 ;;
esac

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "ERROR: HTTP $RESPONSE_CODE" >&2
  echo "$RESPONSE_BODY" >&2
  exit 1
fi
echo "$RESPONSE_BODY"
