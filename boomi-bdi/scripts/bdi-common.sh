#!/usr/bin/env bash
# Shared utilities for boomi-bdi CLI tools; sourced, not executed directly.

set -euo pipefail

# A schemeless host makes curl fail in a way that looks like a network fault, and a trailing
# slash builds //v1/... and 404s. Both are silent otherwise, so catch them at load time.
normalize_api_url() {
  [[ -n "${BDI_API_URL:-}" ]] || return 0
  case "$BDI_API_URL" in
    [hH][tT][tT][pP][sS]://*) ;;
    *)
      echo "ERROR: BDI_API_URL must start with https:// (got '$BDI_API_URL')." >&2
      echo "You can't edit .env -- ask the user to set the API host, e.g. BDI_API_URL=https://api.rivery.io" >&2
      echo "(the API host, not the console address; SKILL.md has the four regional hosts)." >&2
      exit 1
      ;;
  esac
  while [[ "$BDI_API_URL" == */ ]]; do BDI_API_URL="${BDI_API_URL%/}"; done
}

# The leading ./ is required: a bare `source .env` searches $PATH before the current directory.
load_env() {
  if [[ -f .env ]]; then
    source ./.env
  else
    echo "ERROR: .env file not found in $(pwd)" >&2
    exit 1
  fi
  normalize_api_url
}

require_env() {
  local missing=()
  for var in "$@"; do
    [[ -z "${!var:-}" ]] && missing+=("$var")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing required environment variables: ${missing[*]}" >&2
    echo "Check your .env file." >&2
    exit 1
  fi
}

# Pass the full arg vector before load_env so --help works after the subcommand.
help_requested() {
  local arg
  for arg in "$@"; do
    case "$arg" in --help|-h) usage; exit 0 ;; esac
  done
}

# Guard a value-taking option flag's argument, which scripts run under `set -u`
# would otherwise dereference unbound. args: <flag-name> <value>, e.g. need_val "$1" "${2:-}"
need_val() {
  [[ -n "${2:-}" ]] || { echo "ERROR: $1 needs a value" >&2; exit 1; }
}

BDI_USER_AGENT="boomi-companion/boomi-bdi/$(cat "$(dirname "${BASH_SOURCE[0]}")/../VERSION" 2>/dev/null || echo unknown)"

bdi_env_url() {
  echo "${BDI_API_URL}/v1/accounts/${BDI_ACCOUNT_ID}/environments/${BDI_ENVIRONMENT_ID}/$1"
}

# Root-level endpoints (e.g. catalog/discovery) that are not account/environment-scoped.
bdi_root_url() {
  echo "${BDI_API_URL}/v1/$1"
}

RESPONSE_BODY=""
RESPONSE_CODE=""

# Emits a curl config file on stdout for `curl -K -`, keeping credentials out of argv.
# Usage: curl_cfg header "Authorization: Bearer t" url "https://..." | curl -K - ...
curl_cfg() {
  (( $# % 2 == 0 )) || { echo "ERROR: curl_cfg needs directive/value pairs" >&2; return 1; }
  local val
  while [[ $# -gt 1 ]]; do
    val="$2"
    val="${val//\\/\\\\}"
    val="${val//\"/\\\"}"
    printf '%s = "%s"\n' "$1" "$val"
    shift 2
  done
}

# Replace each "variables" object with a placeholder. Quote- and depth-aware: a value may hold a brace or a nested object.
drop_variables() {
  awk '{ s = s (NR > 1 ? "\n" : "") $0 }
  END {
    if (substr(s,1,1) != "{" && substr(s,1,1) != "[") { printf "%s", s; exit }
    out=""; q=0; esc=0; d=0; vd=-1
    for (i=1; i<=length(s); i++) {
      c=substr(s,i,1)
      if (q) { if (vd<0) out=out c
               if (esc) esc=0; else if (c=="\\") esc=1; else if (c=="\"") q=0
               continue }
      if (c=="\"") { q=1; if (vd<0) out=out c; continue }
      if (c=="{") { d++
        if (vd<0 && out ~ /"variables":$/) { vd=d; out=out "\"[omitted]\"" } else if (vd<0) out=out c
        continue }
      if (c=="}") { if (d==vd) vd=-1; else if (vd<0) out=out c; d--; continue }
      if (vd<0) out=out c
    }
    printf "%s", out
  }'
}

bdi_api() {
  # Disable xtrace so a caller's set -x can't leak the token.
  local _xtrace_enabled=0
  case $- in *x*) _xtrace_enabled=1 ;; esac
  set +x

  # Send JSON content type by default; omit it for -F/--form uploads so curl sets its own multipart boundary.
  local ct_header=(-H "Content-Type: application/json") _a
  for _a in "$@"; do
    case "$_a" in -F|--form) ct_header=() ; break ;; esac
  done

  local tmpfile rc
  tmpfile=$(mktemp)
  set +e
  RESPONSE_CODE=$(curl_cfg header "Authorization: Bearer ${BDI_API_TOKEN}" \
    | curl -s \
        --max-time 60 \
        -A "$BDI_USER_AGENT" \
        -K - \
        ${ct_header[@]+"${ct_header[@]}"} \
        -o "$tmpfile" -w "%{http_code}" \
        "$@")
  rc=$?
  set -e
  RESPONSE_BODY=$(cat "$tmpfile")
  [[ -n "${BDI_DROP_VARIABLES:-}" ]] && RESPONSE_BODY=$(printf '%s' "$RESPONSE_BODY" | drop_variables)
  rm -f "$tmpfile"

  (( _xtrace_enabled )) && set -x

  if (( rc != 0 )) || [[ -z "$RESPONSE_CODE" || "$RESPONSE_CODE" == "000" ]]; then
    echo "ERROR: no HTTP response from the BDI API within 60s (curl exit ${rc}; timeout, DNS, or no network)." >&2
    return 1
  fi
  return 0
}

# Extract the next_page URL from a list envelope (empty if null/absent/empty-string).
# Trailing `|| true`: a no-match must yield empty, not fail under set -e/pipefail.
paginate_next() {
  printf '%s' "$1" \
    | grep -oE '"next_page"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/' || true
}

# Extract a top-level numeric scalar (e.g. total_items, page, current_page_size).
paginate_num() {
  printf '%s' "$1" \
    | grep -oE "\"$2\"[[:space:]]*:[[:space:]]*[0-9]+" \
    | head -1 \
    | sed -E 's/.*:[[:space:]]*([0-9]+).*/\1/' || true
}

# Pagination levers consumed by paginate_get; subcommands set these via pg_flag.
PG_ALL="" PG_PAGE="" PG_ITEMS="" PG_MAX_PAGES=100

# Parse a shared pagination flag; returns 0 (and sets how many args to shift in PG_SHIFT) when matched.
pg_flag() {
  PG_SHIFT=0
  case "$1" in
    --all)       PG_ALL=1; PG_SHIFT=1 ;;
    --page)      need_val "$1" "${2:-}"; PG_PAGE="$2"; PG_SHIFT=2 ;;
    --items)     need_val "$1" "${2:-}"; PG_ITEMS="$2"; PG_SHIFT=2 ;;
    --max-pages) need_val "$1" "${2:-}"; PG_MAX_PAGES="$2"; PG_SHIFT=2 ;;
    *) return 1 ;;
  esac
  return 0
}

# Reject contradictory paging flags once a subcommand has parsed its args.
pg_validate() {
  [[ -n "$PG_ALL" && -n "$PG_PAGE" ]] && { echo "ERROR: --all and --page are mutually exclusive" >&2; exit 1; }
  for v in PG_PAGE PG_ITEMS PG_MAX_PAGES; do
    [[ -n "${!v}" && ! "${!v}" =~ ^[0-9]+$ ]] && { echo "ERROR: ${v#PG_} must be a positive integer" >&2; exit 1; }
  done
  return 0
}

# Pagination-aware GET for page-based list endpoints. Emits to stdout; exits 1 on HTTP error.
#   args: <base-url> [extra -G query args...]
#   honors these vars (caller sets after flag-parsing; all optional):
#     PG_ALL=1        traverse next_page to the end -> emit a JSON array of page envelopes
#     PG_PAGE=N       fetch only page N (single envelope)
#     PG_ITEMS=N      items_per_page (omitted -> server default)
#     PG_MAX_PAGES=N  --all traversal cap (default 100)
# Default (no PG_ALL/PG_PAGE): page 1, single envelope, with a stderr NOTE if more pages exist.
paginate_get() {
  local url="$1"; shift
  local q=("$@")
  local max="${PG_MAX_PAGES:-100}"
  [[ -n "${PG_ITEMS:-}" ]] && q+=(--data-urlencode "items_per_page=$PG_ITEMS")

  if [[ -n "${PG_ALL:-}" ]]; then
    bdi_api -G ${q[@]+"${q[@]}"} "$url"; _paginate_check || exit 1
    printf '[%s' "$RESPONSE_BODY"
    local count=1 next; next=$(paginate_next "$RESPONSE_BODY")
    while [[ -n "$next" && "$count" -lt "$max" ]]; do
      # next_page is a full URL; if it omits items_per_page, later pages use the server default size (traversal still complete).
      bdi_api "$next"; _paginate_check || { printf ']\n'; exit 1; }
      printf ',%s' "$RESPONSE_BODY"
      count=$((count + 1)); next=$(paginate_next "$RESPONSE_BODY")
    done
    printf ']\n'
    [[ -n "$next" ]] && echo "WARNING: stopped at --max-pages=$max; more pages remain. Raise --max-pages or narrow the window." >&2
    return 0
  fi

  [[ -n "${PG_PAGE:-}" ]] && q+=(--data-urlencode "page=$PG_PAGE")
  bdi_api -G ${q[@]+"${q[@]}"} "$url"; _paginate_check || exit 1
  printf '%s\n' "$RESPONSE_BODY"
  local next; next=$(paginate_next "$RESPONSE_BODY")
  if [[ -n "$next" ]]; then
    # Cursor endpoints (e.g. audit) lack page/total/size; use the detailed NOTE only when present.
    local pg tot sz
    pg=$(paginate_num "$RESPONSE_BODY" page)
    tot=$(paginate_num "$RESPONSE_BODY" total_items)
    sz=$(paginate_num "$RESPONSE_BODY" current_page_size)
    if [[ -n "$pg" && -n "$tot" && -n "$sz" ]]; then
      echo "NOTE: page $pg of $tot total_items (page size $sz); more pages exist. Use --all, or --page N / --items N." >&2
    else
      echo "NOTE: more results exist. Use --all to fetch them all." >&2
    fi
  fi
  return 0
}

_paginate_check() {
  if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
    echo "ERROR: HTTP $RESPONSE_CODE" >&2
    echo "$RESPONSE_BODY" >&2
    return 1
  fi
  return 0
}

# Poll GET operations/{op_id} until status is terminal. RESPONSE_BODY/RESPONSE_CODE hold the last
# successful response.
#   args: <op-id> <timeout-secs> <interval-secs>
#   returns: 0 terminal · 1 timed out · 2 the get call failed POLL_MAX_FAILS times in a row
# Only transport failures count toward POLL_MAX_FAILS; an HTTP error response carries no status,
# so it just polls again until the timeout.
POLL_MAX_FAILS=3
poll_operation() {
  local op_id="$1" timeout="$2" interval="$3"
  local elapsed=0 status fails=0 last_body="" last_code=""
  while :; do
    if bdi_api "$(bdi_env_url "operations/$op_id")"; then
      fails=0
      last_body="$RESPONSE_BODY" last_code="$RESPONSE_CODE"
      status=$(printf '%s' "$RESPONSE_BODY" \
        | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' \
        | head -1 \
        | sed -E 's/.*"([^"]+)"$/\1/') || true
      case "$status" in E|D) return 0 ;; esac  # E=error, D=done — both terminal
    else
      # a failed call empties both; keep the last real pair for the caller
      RESPONSE_BODY="$last_body" RESPONSE_CODE="$last_code"
      (( fails += 1 ))
      (( fails >= POLL_MAX_FAILS )) && return 2
    fi
    (( elapsed >= timeout )) && return 1
    (( fails > 0 )) && echo "NOTE: operation poll failed ($fails of $POLL_MAX_FAILS consecutive); the operation may still be running — retrying in ${interval}s." >&2
    sleep "$interval"
    (( elapsed += interval ))
  done
}
