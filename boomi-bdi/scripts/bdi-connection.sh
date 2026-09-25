#!/usr/bin/env bash
# BDI connection operations (BDI-native source/target credentials).

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-connection.sh <subcommand> [args]

Connections (environment-scoped; id = cross_id from list/get):
  list [paging]                 list connections
  get <id>                      fetch one connection
  tables <id> [paging]          list a DB source's tables + their cursor-eligible columns
  columns <id> --datasource <api-name> (--schema S… | --all-schemas)
                                a DB source's FULL column schema, via an async metadata pull
  create --body <file.json>     create from a complete JSON body
  edit <id> --body <file.json>  update in place (full-body PUT)
  add-file <type> --file <p>    upload a connection file, e.g. a .pem (3/min); returns its file_path
Catalog discovery (read-only; needs only BDI_API_URL/BDI_API_TOKEN):
  connection-types [paging]               list connection types
  type <type>                             fetch one connection type
  source-types    [paging] [--segment S]  list data source types
  target-types    [paging]                list target types
  source-sections [paging] [--segment S]  list source sections and their types
[paging] = --all | --page N | --items N | --max-pages N. Default: first page (200) with
a stderr NOTE when more exist; --all follows every page into a JSON array of envelopes
(cap --max-pages, default 100); --all/--page are exclusive. An environment can hold far more
connections than one page — pass --all before concluding a connection isn't there. Deleting
isn't supported — use the BDI console. Reads BDI_* from .env; emits the raw API response on stdout.

columns is asynchronous: it triggers a metadata pull and polls the operation to a terminal
state, emitting the settled operation (its `result` is keyed by schema, then table, with a
full `columns[]` per table). --datasource takes the source `api_name`, which is not the
connection's type slug — resolve it from `source-types` (see the connector-discriminator
rule in references/source_to_target_authoring.md). Name a schema with --schema (repeatable)
or pass --all-schemas; naming one keeps the response small, while --all-schemas returns every
schema including `information_schema`. A pull that doesn't settle in 180s leaves the operation
running server-side; re-check it with bdi-flow.sh operation.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift
load_env
require_env BDI_API_URL BDI_API_TOKEN
case "$sub" in list|get|tables|columns|create|edit|add-file) require_env BDI_ACCOUNT_ID BDI_ENVIRONMENT_ID ;; esac

case "$sub" in
  get)
    [[ -n "${1:-}" ]] || { echo "Need <connection-id>" >&2; exit 1; }
    bdi_api "$(bdi_env_url "connections/$1")" ;;
  type)
    [[ -n "${1:-}" ]] || { echo "Need <connection-type>" >&2; exit 1; }
    bdi_api "$(bdi_root_url "connections_types/$1")" ;;
  create)
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X POST --data-binary @"$2" "$(bdi_env_url connections)" ;;
  edit)
    [[ -n "${1:-}" ]] || { echo "Need <connection-id>" >&2; exit 1; }
    id="$1"; shift
    [[ "${1:-}" == "--body" ]] || { echo "Need --body <file.json>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    bdi_api -X PUT --data-binary @"$2" "$(bdi_env_url "connections/$id")" ;;
  columns)
    [[ -n "${1:-}" ]] || { echo "Need <connection-id>" >&2; exit 1; }
    conn="$1"; shift
    datasource=""; all_schemas=""; schemas=()
    # Poll backstop for the async metadata pull; healthy sources settle in under a minute.
    timeout=180 interval=5
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --datasource)   need_val "$1" "${2:-}"; datasource="$2"; shift 2 ;;
        --schema)       need_val "$1" "${2:-}"; schemas+=("$2"); shift 2 ;;
        --all-schemas)  all_schemas=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
      esac
    done
    [[ -n "$datasource" ]] || { echo "ERROR: --datasource <api-name> is required — the source api_name from source-types, not the connection's type slug." >&2; exit 1; }
    [[ -n "$all_schemas" && ${#schemas[@]} -gt 0 ]] && { echo "ERROR: --schema and --all-schemas are mutually exclusive" >&2; exit 1; }
    [[ -z "$all_schemas" && ${#schemas[@]} -eq 0 ]] && { echo "ERROR: name a schema with --schema, or pass --all-schemas to pull every schema" >&2; exit 1; }

    inputs="\"connection_id\":\"$conn\""
    if [[ ${#schemas[@]} -gt 0 ]]; then
      schema_list=""
      for s in "${schemas[@]}"; do
        [[ -n "$schema_list" ]] && schema_list="$schema_list,"
        schema_list="$schema_list\"$s\""
      done
      inputs="$inputs,\"schemas\":[$schema_list]"
    fi
    bdi_api -X POST -d "{\"pull_request_inputs\":{$inputs},\"task\":\"get_db_metadata\",\"task_type\":\"source\",\"datasource_id\":\"$datasource\"}" \
      "$(bdi_env_url pull_requests)"
    if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
      echo "ERROR: HTTP $RESPONSE_CODE" >&2; echo "$RESPONSE_BODY" >&2; exit 1
    fi
    op_id=$(printf '%s' "$RESPONSE_BODY" \
      | grep -oE '"operation_id"[[:space:]]*:[[:space:]]*"[^"]+"' \
      | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
    [[ -n "$op_id" ]] || { echo "ERROR: no operation_id in the trigger response; cannot poll." >&2; echo "$RESPONSE_BODY" >&2; exit 1; }
    echo "metadata pull accepted (HTTP $RESPONSE_CODE); polling operation '$op_id' (up to ${timeout}s)..." >&2
    rc=0
    poll_operation "$op_id" "$timeout" "$interval" || rc=$?
    if (( rc == 2 )); then
      echo "ERROR: could not read operation status while polling. The pull keeps running server-side as operation '$op_id' — re-check it with 'bdi-flow.sh operation $op_id'." >&2
      echo "$RESPONSE_BODY" >&2; exit 1
    fi
    if (( rc == 1 )); then
      echo "ERROR: the pull did not settle within ${timeout}s. It keeps running server-side as operation '$op_id' — an unreachable source can sit for tens of minutes before failing. Re-check it later with 'bdi-flow.sh operation $op_id'." >&2
      echo "$RESPONSE_BODY" >&2
      exit 1
    fi
    status=$(printf '%s' "$RESPONSE_BODY" \
      | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' \
      | head -1 | sed -E 's/.*"([^"]+)"$/\1/') || true
    # error_message may contain escaped quotes.
    msg=$(printf '%s' "$RESPONSE_BODY" \
      | grep -oE '"error_message"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' \
      | head -1 | sed -E 's/^"error_message"[[:space:]]*:[[:space:]]*"//; s/"$//; s/\\"/"/g') || true
    if [[ "$status" == "E" ]]; then
      echo "ERROR: the metadata pull failed (status E): ${msg:-no message}" >&2
      echo "$RESPONSE_BODY" >&2; exit 1
    fi
    # A settled pull can report a per-object problem while still returning the data.
    [[ -n "$msg" ]] && echo "WARNING: the pull settled but reported: $msg" >&2
    echo "$RESPONSE_BODY"
    exit 0 ;;
  add-file)
    [[ -n "${1:-}" ]] || { echo "Need <connection-type>" >&2; exit 1; }
    type="$1"; shift
    [[ "${1:-}" == "--file" ]] || { echo "Need --file <path>" >&2; exit 1; }
    need_val "$1" "${2:-}"
    [[ -f "$2" ]] || { echo "File not found: $2" >&2; exit 1; }
    bdi_api -X POST -F "file=@$2" "$(bdi_env_url "connections/$type/files")" ;;
  list|tables|connection-types|source-types|target-types|source-sections)
    case "$sub" in
      list) url="$(bdi_env_url connections)" ;;
      tables)
        [[ -n "${1:-}" ]] || { echo "Need <connection-id>" >&2; exit 1; }
        url="$(bdi_env_url "connections/$1/tables")"; shift ;;
      connection-types) url="$(bdi_root_url connections_types)" ;;
      source-types)     url="$(bdi_root_url data_source_types)" ;;
      target-types)     url="$(bdi_root_url target_types)" ;;
      source-sections)  url="$(bdi_root_url data_source_sections)" ;;
    esac
    q=()
    while [[ $# -gt 0 ]]; do
      if pg_flag "$@"; then shift "$PG_SHIFT"; continue; fi
      case "$1" in
        --segment)
          [[ "$sub" == source-types || "$sub" == source-sections ]] || { echo "--segment is only valid for source-types/source-sections" >&2; exit 1; }
          need_val "$1" "${2:-}"
          q+=(--data-urlencode "segment=$2"); shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
      esac
    done
    pg_validate
    [[ -z "$PG_ITEMS" ]] && PG_ITEMS=200
    paginate_get "$url" ${q[@]+"${q[@]}"}
    exit 0 ;;
  *) usage >&2; exit 1 ;;
esac

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "ERROR: HTTP $RESPONSE_CODE" >&2
  echo "$RESPONSE_BODY" >&2
  exit 1
fi
echo "$RESPONSE_BODY"
