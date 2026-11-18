#!/usr/bin/env bash
# One-time setup of a Vault for AXoR (D-033): the secrets engine, the audit device, AXoR's policy, the token role for runs, and
# AXoR's own token. Run by the Owner (or for the Owner) with a token that may configure Vault; AXoR itself never has such a token.
# Used as it is against the throwaway test server in staging. NOT a deployment: it creates no cluster object and stores no secret.
#
#   VAULT_ADDR=http://… VAULT_TOKEN=<an administrator's token> k8s/vault/bootstrap.sh [AUDIT_FILE]
#   prints AXoR's token on the last line (give it to AXoR as VAULT_TOKEN_FILE's content; it can't read any secret's value)
#
# Secrets are then written by the Owner with Vault's own tools, never through AXoR:
#   vault kv put axor/teams/<team id>/<NAME> value=…          a team's credential
#   vault kv put axor/missions/<mission>/<NAME> value=…       one mission's (it wins over the team's)
#   vault kv metadata put -custom-metadata=agents="2,5" axor/teams/<team id>/<NAME>      optional: only these agents
set -euo pipefail
: "${VAULT_ADDR:?}" "${VAULT_TOKEN:?}"
here=$(cd "$(dirname "$0")" && pwd)
audit=${1:-/vault/logs/audit.log}
curl -fsS -m 10 -o /dev/null "$VAULT_ADDR/v1/sys/health" || { echo "Vault doesn't answer at $VAULT_ADDR (or is sealed or not initialized)" >&2; exit 1; }
v() { curl -fsS -H "X-Vault-Token: $VAULT_TOKEN" -H "Content-Type: application/json" -X "$1" "$VAULT_ADDR/v1/$2" ${3:+-d "$3"}; }
v POST sys/mounts/axor '{"type": "kv", "options": {"version": "2"}}' >/dev/null 2>&1 || echo "(the axor secrets engine exists already)" >&2
v PUT sys/audit/file "{\"type\": \"file\", \"options\": {\"file_path\": \"$audit\"}}" >/dev/null 2>&1 || echo "(the file audit device exists already)" >&2
python3 - "$here/policy-axor-web.hcl" <<'PY' | v PUT sys/policies/acl/axor-web "$(cat)" >/dev/null
import json, sys
print(json.dumps({"policy": open(sys.argv[1]).read()}))
PY
# runs' tokens: only axor-run-* policies, never the default policy, never renewable past an hour, orphans (they end with their own
# lifetime or AXoR's revocation, not with AXoR's token)
v POST auth/token/roles/axor-run '{"allowed_policies_glob": ["axor-run-*"], "disallowed_policies": ["root", "default", "axor-web"], "orphan": true, "renewable": false, "token_explicit_max_ttl": "3600", "token_no_default_policy": true, "token_type": "service"}' >/dev/null
v POST auth/token/create '{"policies": ["axor-web"], "no_default_policy": true, "display_name": "axor-web", "renewable": true, "ttl": "768h"}' | python3 -c 'import json, sys; print(json.load(sys.stdin)["auth"]["client_token"])'
