#!/usr/bin/env bash
# BDI logicode (Python) code files for logic-flow `logicode` steps.

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-logicode.sh <subcommand> [args]

Logicode (Python) code files that logic-flow `logicode` steps reference by file_id:
  upload <file> [--name <n>]   upload a Python file; prints its file_id
  read <file_id>               print an uploaded file's stored source
  template                     print the Python logic-step template
  requirements                 print the generic requirements file

upload is two hops: it requests an upload slot from the API (returns a file_id and a presigned URL),
then PUTs the file bytes to that URL. Wire the printed file_id into a logicode step's `file_id`.
--name sets the stored file name (default: the file's basename).

read/template/requirements each follow a short-lived presigned URL and print the content to stdout.

Reads BDI_* from .env. upload emits {"file_id":"..."} on stdout; the others emit file content.
EOF
}
[[ -z "${1:-}" ]] && { usage; exit 0; }
help_requested "$@"

sub="$1"; shift

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID BDI_ENVIRONMENT_ID

# Extract a top-level JSON string field (grep+sed, matching bdi-common's paginate_* style).
json_str() {
  printf '%s' "$1" \
    | grep -oE "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
    | head -1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/' || true
}

# Follow a presigned URL with no auth (it is pre-signed) and print the fetched body.
# args: <presigned-url>
fetch_presigned() {
  local tmp code rc
  tmp=$(mktemp)
  set +e
  code=$(curl_cfg url "$1" | curl -s --max-time 60 -K - -o "$tmp" -w "%{http_code}")
  rc=$?
  set -e
  local body; body=$(cat "$tmp"); rm -f "$tmp"
  if (( rc != 0 )) || [[ "$code" != 2?? ]]; then
    echo "ERROR: fetching presigned URL failed (curl exit $rc, HTTP $code)." >&2
    echo "$body" >&2
    exit 1
  fi
  printf '%s\n' "$body"
}

# GET a {url,...} envelope from the API, then follow url and print the content.
# args: <api-url>
print_presigned_content() {
  bdi_api "$1"
  if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
    echo "ERROR: HTTP $RESPONSE_CODE" >&2; echo "$RESPONSE_BODY" >&2; exit 1
  fi
  local url; url=$(json_str "$RESPONSE_BODY" url)
  [[ -n "$url" ]] || { echo "ERROR: no presigned url in response." >&2; echo "$RESPONSE_BODY" >&2; exit 1; }
  fetch_presigned "$url"
}

case "$sub" in
  upload)
    [[ -n "${1:-}" ]] || { echo "Need <file> [--name <n>]" >&2; exit 1; }
    file="$1"; shift
    name=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --name) need_val "$1" "${2:-}"; name="$2"; shift 2 ;;
        *) echo "ERROR: unexpected argument '$1'" >&2; exit 1 ;;
      esac
    done
    [[ -f "$file" ]] || { echo "ERROR: file not found: $file" >&2; exit 1; }
    [[ -n "$name" ]] || name="$(basename "$file")"

    # Hop 1: request an upload slot -> {file_id, url (presigned S3 PUT)}.
    bdi_api -X POST -d "{\"file_name\":\"$name\"}" "$(bdi_env_url logicode_file)"
    if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
      echo "ERROR: HTTP $RESPONSE_CODE requesting upload slot." >&2; echo "$RESPONSE_BODY" >&2; exit 1
    fi
    file_id=$(json_str "$RESPONSE_BODY" file_id)
    put_url=$(json_str "$RESPONSE_BODY" url)
    [[ -n "$file_id" && -n "$put_url" ]] || { echo "ERROR: upload-slot response missing file_id or url." >&2; echo "$RESPONSE_BODY" >&2; exit 1; }

    # Hop 2: PUT the bytes to the presigned URL. NO auth — the URL carries its own signature.
    echo "upload slot acquired (file_id=$file_id); uploading bytes..." >&2
    set +e
    put_code=$(curl_cfg url "$put_url" | curl -s --max-time 120 -o /dev/null -w "%{http_code}" -K - --upload-file "$file")
    put_rc=$?
    set -e
    if (( put_rc != 0 )) || [[ "$put_code" != 2?? ]]; then
      echo "ERROR: presigned PUT failed (curl exit $put_rc, HTTP $put_code) for file_id=$file_id." >&2
      exit 1
    fi
    printf '{"file_id":"%s"}\n' "$file_id"
    exit 0
    ;;
  read)
    [[ -n "${1:-}" ]] || { echo "Need <file_id>" >&2; exit 1; }
    print_presigned_content "$(bdi_env_url "logicode_file/$1")"
    exit 0
    ;;
  template)
    print_presigned_content "$(bdi_root_url "logicode_file/template")"
    exit 0
    ;;
  requirements)
    print_presigned_content "$(bdi_root_url "logicode_file/requirements")"
    exit 0
    ;;
  *) usage >&2; exit 1 ;;
esac
