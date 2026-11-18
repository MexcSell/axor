# AXoR's own identity in Vault (D-033). It can prepare and end a run's access; it can NOT read a secret's value.
# A value is only ever read with a per-run child token (backend/app/vault.py), so Vault's audit log names the run for every read.

# Names, versions and the Owner's custom metadata of secrets: never values.
path "axor/metadata/*" {
  capabilities = ["read", "list"]
}

# One policy per run, readable paths only, written just before the run's token and deleted with it.
path "sys/policies/acl/axor-run-*" {
  capabilities = ["create", "update", "delete"]
}

# Tokens only through the role, which allows only axor-run-* policies, no default policy, a bounded lifetime.
path "auth/token/create/axor-run" {
  capabilities = ["update"]
}

path "auth/token/revoke-accessor" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
