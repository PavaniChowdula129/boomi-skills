#!/usr/bin/env bash
# Verify .env vars and reach the BDI API; lists the environments the token can see.

source "$(dirname "$0")/bdi-common.sh"

usage() {
  cat <<'EOF'
Usage: bdi-env-check.sh [--help]

Checks BDI_* vars in .env and makes a live API round-trip listing the
environments the token can access. BDI_ENVIRONMENT_ID may still be unset --
pick one from this output. Lists one page and says so if more exist;
bdi-env.sh list --all enumerates them. Each environment's variables map is
replaced with "[omitted]"; read one environment's variables with
bdi-variable.sh env-list.
EOF
}
help_requested "$@"

load_env
require_env BDI_API_URL BDI_API_TOKEN BDI_ACCOUNT_ID

url="${BDI_API_URL}/v1/accounts/${BDI_ACCOUNT_ID}/environments"
echo "  GET $url"
BDI_DROP_VARIABLES=1 bdi_api -G --data-urlencode "items_per_page=200" "$url"

if (( RESPONSE_CODE < 200 || RESPONSE_CODE >= 300 )); then
  echo "  HTTP $RESPONSE_CODE -- FAIL" >&2
  echo "  Response: $RESPONSE_BODY" >&2
  if (( RESPONSE_CODE == 401 )); then
    echo "  A bad token and the wrong region host both return this 401 -- the response can't tell them apart." >&2
    echo "  You can't read .env, so ask the user: re-paste BDI_API_TOKEN first (truncated pastes are the" >&2
    echo "  common cause), then confirm BDI_API_URL is the API host for their console's region." >&2
  elif (( RESPONSE_CODE == 403 )); then
    echo "  Token authenticated but lacks scope or environment access for this call. Listing an environment" >&2
    echo "  does not mean the token can act in it -- try another environment before changing the token." >&2
  fi
  exit 1
fi
echo "  HTTP $RESPONSE_CODE -- OK"
echo "$RESPONSE_BODY"
if [[ -n "$(paginate_next "$RESPONSE_BODY")" ]]; then
  echo "  NOTE: more environments exist beyond this page -- enumerate them with 'bdi-env.sh list --all'." >&2
fi
if [[ -z "${BDI_ENVIRONMENT_ID:-}" ]]; then
  echo "Pick an environment _id above and add to .env: BDI_ENVIRONMENT_ID=<id>" >&2
else
  echo "Selected: BDI_ENVIRONMENT_ID=${BDI_ENVIRONMENT_ID}" >&2
fi
