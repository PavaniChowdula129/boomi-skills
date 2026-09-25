#!/usr/bin/env bash
# BDI change-data-capture (CDC) offset and lifecycle operations on log-based data flows.

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-cdc.sh <subcommand> [args]

CDC offset/lifecycle operations on log-based (extract_method:"log") data flows.
Flow ids are the river cross_id (from bdi-flow.sh list/get).

  enable  <flow-id> [--no-wait]      turn the CDC log on  (async; waits for the operation to settle)
  disable <flow-id> [--no-wait]      turn the CDC log off (waits for an operation if the API returns one)
  get     <flow-id>                  read the stored CDC offset
  set     <flow-id> --body <file.json>  write the CDC offset cursor (full config body)
  delete  <flow-id>                  clear the stored CDC offset (does not turn the log off)

get requires the CDC log enabled; with it off the API returns HTTP 400 "Enable log is off", and
with it on but no offset captured yet a different 400. get exits non-zero on both — read which
one, don't assume failure.
set/delete are accepted either way (HTTP 200), so the log state does not protect the cursor —
a wrong or cleared offset silently skips or replays change records; confirm before writing.
enable is asynchronous: the POST returns 202 with an operation that validates the source
connection and target file zone and may settle to an error (e.g. an unreachable target) —
a 202 is acceptance, not success. This script polls that operation to a terminal state and
exits non-zero if it errors, or if the response carries no operation at all.
disable may return 204 with an empty body and no operation: nothing to poll, so it is treated
as complete on return. When it returns an operation, that operation is polled the same way.
--no-wait skips polling for either verb and returns the API's response as-is.
Override the poll window with BDI_CDC_TIMEOUT (default 300s) / BDI_CDC_INTERVAL (default 10s).
Reads BDI_* from .env. Emits the API's raw response on stdout.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID BDI_ENVIRONMENT_ID

: "${BDI_CDC_TIMEOUT:=300}"
: "${BDI_CDC_INTERVAL:=10}"

no_wait=""

# POST enable_cdc/disable_cdc, then poll any returned operation to a terminal state.
# args: <flow-id> <endpoint> <verb>
do_cdc_toggle() {
  local flow_id="$1" endpoint="$2" verb="$3"
  bdi_api -X POST -d '{}' "$(bdi_env_url "rivers/$flow_id/$endpoint")"
  if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
    echo "ERROR: HTTP $RESPONSE_CODE" >&2; echo "$RESPONSE_BODY" >&2; exit 1
  fi
  local op_id
  op_id=$(printf '%s' "$RESPONSE_BODY" \
    | grep -oE '"operation_id"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
  if [[ -n "$no_wait" ]]; then
    echo "$verb acknowledged (HTTP $RESPONSE_CODE); not waiting (--no-wait). operation_id: ${op_id:-unknown}" >&2
    echo "$RESPONSE_BODY"; exit 0
  fi
  if [[ -z "$op_id" ]]; then
    if [[ "$verb" == "disable" ]]; then
      echo "disable acknowledged (HTTP $RESPONSE_CODE); no operation to poll — treating as complete. Confirm with 'get': once the log is off it answers HTTP 400 \"Enable log is off\" and exits non-zero — that is the expected result, not a failure." >&2
      echo "$RESPONSE_BODY"; exit 0
    fi
    echo "ERROR: $verb returned HTTP $RESPONSE_CODE with no operation_id; cannot poll. Check the log state with 'get'." >&2
    echo "$RESPONSE_BODY" >&2; exit 1
  fi
  echo "$verb acknowledged (HTTP $RESPONSE_CODE); polling operation '$op_id' (up to ${BDI_CDC_TIMEOUT}s)..." >&2
  local rc=0
  poll_operation "$op_id" "$BDI_CDC_TIMEOUT" "$BDI_CDC_INTERVAL" || rc=$?
  if (( rc == 2 )); then echo "ERROR: could not read operation status while polling." >&2; echo "$RESPONSE_BODY" >&2; exit 1; fi
  if (( rc == 1 )); then echo "ERROR: $verb operation did not settle within ${BDI_CDC_TIMEOUT}s." >&2; echo "$RESPONSE_BODY" >&2; exit 1; fi
  local status
  status=$(printf '%s' "$RESPONSE_BODY" \
    | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
  if [[ "$status" == "E" ]]; then
    echo "ERROR: $verb operation failed (status E) — enabling CDC validates the source connection and target file zone; check the BDI console." >&2
    echo "$RESPONSE_BODY" >&2; exit 1
  fi
  echo "$verb operation settled (status ${status:-unknown})." >&2
  echo "$RESPONSE_BODY"; exit 0
}

case "$sub" in
  enable|disable)
    [[ -n "${1:-}" ]] || { echo "Need <flow-id>" >&2; exit 1; }
    flow_id="$1"; shift
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --no-wait) no_wait=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
      esac
    done
    if [[ "$sub" == enable ]]; then
      do_cdc_toggle "$flow_id" enable_cdc "enable"
    else
      do_cdc_toggle "$flow_id" disable_cdc "disable"
    fi
    ;;
  get)
    [[ -n "${1:-}" ]] || { echo "Need <flow-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "rivers/$1/cdc_config")"
    ;;
  set)
    [[ -n "${1:-}" ]] || { echo "Need <flow-id>" >&2; exit 1; }
    flow_id="$1"; shift
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X POST --data-binary @"$2" "$(bdi_env_url "rivers/$flow_id/cdc_config")"
    ;;
  delete)
    [[ -n "${1:-}" ]] || { echo "Need <flow-id>" >&2; exit 1; }
    bdi_api -X DELETE "$(bdi_env_url "rivers/$1/cdc_config")"
    ;;
  *) usage >&2; exit 1 ;;
esac

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "ERROR: HTTP $RESPONSE_CODE" >&2
  echo "$RESPONSE_BODY" >&2
  exit 1
fi
echo "$RESPONSE_BODY"
