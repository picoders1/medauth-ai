#!/usr/bin/env bash
# Bootstrap the NON-PRODUCTION Keycloak realm MEDAUTH authenticates against.
#
#     docker compose -f compose.idp.yaml up -d
#     set -a; . ./.env; set +a
#     bash scripts/bootstrap_nonprod_idp.sh
#
# Idempotent: re-running it reconciles rather than duplicating.
#
# ## What this creates, and what it deliberately does not
#
# Three groups, matching `_PERMISSION_FOR_ROLE` in `app/identity/authenticator.py`
# exactly. The mapping lives in MEDAUTH, not here - the provider says which groups a
# person is in and nothing about what those groups may do. A provider that could
# grant a MEDAUTH permission directly would be a second authorization system.
#
# Four users. Three carry one group each; the fourth carries none, because
# "authenticated but authorised for nothing" is the case most worth being able to
# test and the one an all-users-are-reviewers fixture never covers.
#
# **No secret is written by this script.** Every password is read from the
# environment (see `.env.example`), and `.env` is gitignored. Nothing here is a real
# person, and no clinical identity is used.
set -euo pipefail

IDP="${MEDAUTH_IDP_URL:-http://localhost:8090}"
REALM="${MEDAUTH_IDP_REALM:-medauth-nonprod}"
CLIENT="${MEDAUTH_OIDC_AUDIENCE:-medauth-api}"

: "${MEDAUTH_IDP_ADMIN_USER:?set it in .env}"
: "${MEDAUTH_IDP_ADMIN_PASSWORD:?set it in .env}"
: "${MEDAUTH_IDP_TEST_REVIEWER_PASSWORD:?set it in .env}"
: "${MEDAUTH_IDP_TEST_SENIOR_PASSWORD:?set it in .env}"
: "${MEDAUTH_IDP_TEST_OUTSIDER_PASSWORD:?set it in .env}"
: "${MEDAUTH_IDP_TEST_READONLY_PASSWORD:?set it in .env}"

say() { printf '  %s\n' "$*"; }

TOKEN=$(curl -sS -X POST "$IDP/realms/master/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=admin-cli \
  --data-urlencode "username=$MEDAUTH_IDP_ADMIN_USER" \
  --data-urlencode "password=$MEDAUTH_IDP_ADMIN_PASSWORD" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
say "admin session obtained"

api() { # method path [body]
  local m=$1 p=$2
  if [ $# -ge 3 ]; then
    curl -sS -o /dev/null -w '%{http_code}' -X "$m" "$IDP/admin/realms$p" \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$3"
  else
    curl -sS -X "$m" "$IDP/admin/realms$p" -H "Authorization: Bearer $TOKEN"
  fi
}

# --- realm -----------------------------------------------------------------
code=$(api POST "" "$(printf '{"realm":"%s","enabled":true,"displayName":"MEDAUTH non-production","sslRequired":"none","accessTokenLifespan":900}' "$REALM")")
say "realm $REALM -> HTTP $code (409 = already present)"

# --- client, with an audience mapper ---------------------------------------
# Without the mapper Keycloak stamps `aud: account` and MEDAUTH rejects the token.
# The audience is not decoration: it is what stops a token minted for another
# application in this realm from being replayed against this one.
read -r -d '' CLIENT_JSON <<JSON || true
{"clientId":"$CLIENT","enabled":true,"publicClient":true,
 "directAccessGrantsEnabled":true,"standardFlowEnabled":true,
 "protocolMappers":[
  {"name":"audience","protocol":"openid-connect",
   "protocolMapper":"oidc-audience-mapper",
   "config":{"included.client.audience":"$CLIENT","access.token.claim":"true"}},
  {"name":"groups","protocol":"openid-connect",
   "protocolMapper":"oidc-group-membership-mapper",
   "config":{"claim.name":"groups","full.path":"false",
             "access.token.claim":"true","id.token.claim":"true","userinfo.token.claim":"true"}}]}
JSON
code=$(api POST "/$REALM/clients" "$CLIENT_JSON")
say "client $CLIENT -> HTTP $code (409 = already present)"

# --- groups ----------------------------------------------------------------
# These three names are the keys of `_PERMISSION_FOR_ROLE`. A fourth group here
# would grant nothing - unknown groups map to the empty set, by design.
for g in medauth-readonly medauth-reviewer medauth-senior-reviewer; do
  code=$(api POST "/$REALM/groups" "$(printf '{"name":"%s"}' "$g")")
  say "group $g -> HTTP $code"
done

gid() { api GET "/$REALM/groups?search=$1" | python3 -c "import sys,json;print([g['id'] for g in json.load(sys.stdin) if g['name']=='$1'][0])"; }
uid() { api GET "/$REALM/users?username=$1&exact=true" | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])'; }

# --- users -----------------------------------------------------------------
mkuser() { # username password group-or-empty
  local u=$1 p=$2 g=${3:-}
  code=$(api POST "/$REALM/users" "$(python3 -c '
import json,sys
u,p = sys.argv[1], sys.argv[2]
# `requiredActions: []` and a verified email are not conveniences. Keycloak 26
# enables a VERIFY_PROFILE required action by default, and a user carrying any
# required action cannot complete a direct grant - the token endpoint answers
# `invalid_grant: Account is not fully set up`, which reads like a credential
# failure and is not one. These are fixture identities with no interactive
# login to complete the action in.
print(json.dumps({"username":u,"enabled":True,"emailVerified":True,
  "email":f"{u}@nonprod.invalid", "firstName":"Nonprod","lastName":u,
  "requiredActions":[],
  "credentials":[{"type":"password","value":p,"temporary":False}]}))' "$u" "$p")")
  # Reconcile an existing user too, so a re-run repairs rather than reporting 409.
  if [ "$code" = "409" ]; then
    curl -sS -o /dev/null -X PUT "$IDP/admin/realms/$REALM/users/$(uid "$u")" \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d "$(python3 -c '
import json,sys
u,p = sys.argv[1], sys.argv[2]
print(json.dumps({"enabled":True,"emailVerified":True,"email":f"{u}@nonprod.invalid",
  "requiredActions":[],
  "credentials":[{"type":"password","value":p,"temporary":False}]}))' "$u" "$p")"
  fi
  if [ -n "$g" ]; then
    curl -sS -o /dev/null -X PUT "$IDP/admin/realms/$REALM/users/$(uid "$u")/groups/$(gid "$g")" \
      -H "Authorization: Bearer $TOKEN"
  fi
  say "user $u -> HTTP $code, group=${g:-<none>}"
}

mkuser nonprod-readonly "$MEDAUTH_IDP_TEST_READONLY_PASSWORD" medauth-readonly
mkuser nonprod-reviewer "$MEDAUTH_IDP_TEST_REVIEWER_PASSWORD" medauth-reviewer
mkuser nonprod-senior   "$MEDAUTH_IDP_TEST_SENIOR_PASSWORD"   medauth-senior-reviewer
mkuser nonprod-outsider "$MEDAUTH_IDP_TEST_OUTSIDER_PASSWORD" ""

say "done. issuer: $IDP/realms/$REALM"
