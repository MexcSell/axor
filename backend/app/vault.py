"""Credentials for runs, from HashiCorp Vault (decision D-033: Vault as a platform service approved in principle on 2026-11-13;
this injection design approved the same day for development against a throwaway test server only. Placement, unseal method,
key custody and any production deployment are the Owner's and open: owner-decisions/g5-plan/aef/AEF_02 §7).

Off unless VAULT_ADDR is set. AXoR adds no secret store of its own: this is a client and a gate.

The rule the design rests on: **a run never holds a Vault token, and AXoR's own Vault identity can't read a secret's value.**
- AXoR's token (VAULT_TOKEN_FILE, or VAULT_TOKEN in staging) may list and read secret *metadata*, write policies named
  axor-run-*, create tokens through the token role axor-run, and revoke them by accessor. Nothing else (k8s/vault/policy-axor-web.hcl).
- For one run, and only when that run asks for a credential it was granted, AXoR writes a policy that can read exactly the
  granted paths, creates a child token with it (it lives as long as the run may, can be used a counted number of times, isn't
  renewable, carries the mission, team, run, task and agent as metadata), reads the value with that token, and hands the value
  to the run over the run's own endpoint (exec_env.Session). The token and the policy are revoked when the run ends.
  Vault's audit device therefore shows each read under a token that names its run.

What is granted (grants): a credential is given to a run only when all of these hold, and every refusal has its reason:
  1. the run's board task declares it (`credential:<NAME>` in the task's needs);
  2. a person verified that need for this exact task and the verification still counts by the readiness gate's own rule
     (mission_ops._verified, asked here and never copied: the team owner's record, not expired, same credential fingerprint);
  3. Vault holds it for this team (`teams/<team id>/<NAME>`) or this mission (`missions/<mission>/<NAME>`, which wins);
  4. the secret's own custom metadata, when the Owner set any, allows this agent (`agents`: ids) and this mission (`missions`).

Stated plainly, as the design says: a value given to a run is readable by that run's code. So exec_env gives such a run an
allowlist for its internet or none, masks the value in its output, and refuses any workspace file that contains it."""
import hashlib, json, logging, os, re, time, urllib.error, urllib.request

log = logging.getLogger("vault")
ADDR = os.getenv("VAULT_ADDR", "").rstrip("/")
MOUNT = os.getenv("VAULT_MOUNT", "axor")
ROLE = os.getenv("VAULT_RUN_ROLE", "axor-run")
NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,60}$")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # Vault is reached directly, never through a proxy from the environment


class VaultError(Exception):
    """Vault refused or didn't answer; the message never holds a secret's value."""


def _mission_key(mission): return re.sub(r"[^A-Za-z0-9_.-]", "_", mission or "")


class Vault:
    def __init__(self, addr=None, token=None, token_file=None):
        self.addr = (addr if addr is not None else ADDR).rstrip("/")
        self._token, self._file = token or os.getenv("VAULT_TOKEN", ""), token_file or os.getenv("VAULT_TOKEN_FILE", "")

    @property
    def enabled(self): return bool(self.addr)

    def token(self):
        if self._file:
            try: return open(self._file).read().strip()
            except OSError as e: raise VaultError(f"AXoR's Vault token can't be read ({e.strerror})")
        return self._token

    def call(self, method, path, body=None, token=None, timeout=10):
        req = urllib.request.Request(f"{self.addr}/v1/{path.lstrip('/')}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Vault-Token": token if token is not None else self.token(), "Content-Type": "application/json"})
        try:
            with OPENER.open(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try: errs = "; ".join(json.loads(e.read() or b"{}").get("errors") or [])
            except ValueError: errs = ""
            err = VaultError(f"Vault answered {e.code}" + (f": {errs[:200]}" if errs else ""))
            err.status = e.code
            raise err
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = VaultError(f"Vault didn't answer: {getattr(e, 'reason', e)}")
            err.status = 0
            raise err

    def ready(self):
        """(True, "") when Vault is initialized, unsealed and takes AXoR's token; else (False, why)."""
        if not self.enabled: return False, "No Vault is set for this server (VAULT_ADDR)."
        try:
            h = self.call("GET", "sys/health?standbyok=true&sealedcode=200&uninitcode=200", token="")
            if not h.get("initialized"): return False, "Vault isn't initialized."
            if h.get("sealed"): return False, "Vault is sealed: a key holder has to unseal it."
            self.call("GET", "auth/token/lookup-self")
        except VaultError as e: return False, str(e)
        return True, ""

    def meta(self, path):
        """A secret's metadata (never its value), or None when there is no such secret."""
        try: d = self.call("GET", f"{MOUNT}/metadata/{path}").get("data") or {}
        except VaultError as e:
            if getattr(e, "status", 0) == 404: return None
            raise
        ver = (d.get("versions") or {}).get(str(d.get("current_version")), {})
        if not d.get("current_version") or ver.get("deletion_time") or ver.get("destroyed"): return None
        return {"version": d["current_version"], "created": ver.get("created_time") or "", "updated": d.get("updated_time"), "custom": d.get("custom_metadata") or {}}

    def child(self, name, paths, ttl, uses, meta):
        """A token that can read exactly `paths` (data paths under the mount): {"token", "accessor", "policy"}."""
        policy = f"{ROLE}-{name}"
        rules = "\n".join(f'path "{MOUNT}/data/{p}" {{ capabilities = ["read"] }}' for p in paths)
        self.call("PUT", f"sys/policies/acl/{policy}", {"policy": rules})
        try:
            a = self.call("POST", f"auth/token/create/{ROLE}", {"policies": [policy], "ttl": f"{int(ttl)}s", "explicit_max_ttl": f"{int(ttl)}s", "num_uses": int(uses),
                                                                "renewable": False, "no_default_policy": True, "display_name": name,
                                                                "meta": {k: str(v) for k, v in meta.items() if v is not None}})["auth"]
        except VaultError:
            self.drop(None, policy); raise
        return {"token": a["client_token"], "accessor": a["accessor"], "policy": policy}

    def read(self, path, token, version=None):
        """The secret's value. version: exactly that version (the one a grant located and a person's verification names), so a
        rotation after the grant can't put an unverified value in the run's hands; None is the current one."""
        d = (self.call("GET", f"{MOUNT}/data/{path}" + (f"?version={int(version)}" if version else ""), token=token).get("data") or {}).get("data") or {}
        if "value" not in d or not isinstance(d["value"], str): raise VaultError("the secret has no `value` field")
        return d["value"]

    def drop(self, accessor, policy):
        """Revokes a run's token and deletes its policy. Each is tried even when the other fails."""
        errs = []
        for method, path, body in ((("POST", "auth/token/revoke-accessor", {"accessor": accessor}),) if accessor else ()) + (("DELETE", f"sys/policies/acl/{policy}", None),):
            try: self.call(method, path, body)
            except VaultError as e:
                if getattr(e, "status", 0) not in (400, 404): errs.append(str(e))   # a token already used up or expired is gone: that is the wanted end state
        if errs: raise VaultError("; ".join(errs))


def locate(vault, team, mission, name):
    """(path, metadata) of the secret a run of this team and mission would be given under that name: the mission's own when
    there is one, else the team's; None when Vault holds neither. The one lookup: the broker and fingerprint() both use it."""
    for path in (f"missions/{_mission_key(mission)}/{name}", f"teams/{team}/{name}"):
        m = vault.meta(path)
        if m: return path, m
    return None


_CLIENT = []


def fingerprint(team, mission, name):
    """What identifies the credential a run would be given, without its value: `vault:<path>@v<version>@<that version's creation
    time>`. The readiness gate stores it with a person's verification and compares it later (mission_ops.credential_fingerprint),
    so a rotation, a mission secret added over the team's, or a secret deleted and written again all void the verification: the
    path, the version and the time each differ. None when no Vault is set for the server (no call is made) or it holds no such
    secret for this team or mission. Raises VaultError when Vault is set but sealed, unreachable or refusing: "unreadable" is
    not "absent". The secret's own agents / missions policy is not part of it: that refusal stays the broker's."""
    if not ADDR or not NAME.match(name or ""): return None
    if not _CLIENT: _CLIENT.append(Vault())
    found = locate(_CLIENT[0], team, mission, name)
    return identity(*found) if found else None


def identity(path, meta):
    """The identity string of one located secret: fingerprint() and the broker both build it here, from the same locate() result."""
    return f"vault:{path}@v{meta['version']}@{meta['created']}"


def team_owner(db, comp_id):
    """The account a team belongs to (its campaign's), or None: the readiness gate keeps its records under that account."""
    try: r = db.q("SELECT c.user_id FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE w.id=?", (comp_id,), one=True)
    except Exception: return None   # noqa: BLE001 - no such tables here: nothing can be verified
    return r["user_id"] if r else None


def verified(db, comp_id, mission, task_id, name, ident=None):
    """(True, who) when the readiness gate holds a person's verification of `credential:<name>` for this exact board task that
    still counts; else (False, why). The rule is the gate's own and is asked, not copied (mission_ops._verified): the record is
    the team owner's, resolved by a person, not an approval, not expired, and for the credential's current fingerprint. Reads only.

    ident: the identity of the secret the caller has just located and is about to hand over (identity()). The verification must
    then be for exactly that identity, so there is no moment between "verified" and "located" in which a rotation could slip an
    unverified secret through: the gate is given the identity to compare (its `identity` argument, where it has one), and the
    record's own fingerprint is compared here as well. A gate that doesn't yet tie verifications to Vault's identities (it has no
    notion of them) is asked its own rule only; the version handed over is still the one located (RunSecrets reads it by version)."""
    import inspect, types
    from . import mission_ops as mo
    owner = team_owner(db, comp_id)
    if owner is None: return False, "the team's owner couldn't be found, so no verification can be read"
    ch = types.SimpleNamespace(db=db, _has=lambda t: bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
    rkey = mo._rkey(mission, f"mw_task:{task_id}", "credential", name)
    takes = "identity" in inspect.signature(mo._verified).parameters
    v = mo._verified(ch, owner, rkey, name, identity=ident) if ident and takes else mo._verified(ch, owner, rkey, name)
    if not v: return False, "no person's current verification of it is recorded for this task"
    aware = takes or "team" in inspect.signature(mo.credential_fingerprint).parameters   # the gate stores Vault's identity with a verification
    if ident and aware and v.get("fingerprint") != ident: return False, "the credential changed since it was verified: a person has to verify it again"
    return True, str(v["by"])


class RunSecrets:
    """The credentials one run was granted. exec_env.Session asks it: .names, .fetch(name), .close()."""
    def __init__(self, vault, db, *, team, mission, sid, task, agent, granted, ttl):
        self.vault, self.db, self.team, self.mission, self.sid, self.task, self.agent = vault, db, team, mission, sid, task, agent
        self.paths, self.ttl, self.child, self.reads = dict(granted), ttl, None, 0   # {NAME: path}
        self.versions = {}                                                             # {NAME: the version that was located and verified}
        self.names = set(self.paths)

    def _audit(self, action, name, detail=""):
        try: self.db.log(action, f"run:{self.sid}", name, "", f"mission {self.mission}, team {self.team}, task {self.task}, agent {(self.agent or {}).get('id')}" + (f"; {detail}" if detail else ""))
        except Exception as e:  # noqa: BLE001
            log.warning("vault: audit %s: %s", action, e)

    def fetch(self, name):
        if name not in self.paths: raise VaultError("not granted")
        try:
            if not self.child:
                self.child = self.vault.child(f"s{self.sid}-{int(time.time())}", sorted(set(self.paths.values())), self.ttl, uses=len(self.paths) * 2,
                                              meta={"mission": self.mission, "team": self.team, "run": self.sid, "task": self.task, "agent": (self.agent or {}).get("id")})
            v = self.vault.read(self.paths[name], self.child["token"], self.versions.get(name))   # that version, whatever was written since
        except VaultError as e:
            self._audit("secret.read_failed", name, str(e)); raise
        self.reads += 1
        self._audit("secret.read", name, f"path {self.paths[name]}" + (f" version {self.versions[name]}" if name in self.versions else "") + f", run token {hashlib.sha256(self.child['accessor'].encode()).hexdigest()[:10]} (sha256 of its accessor)")   # D-019: never a piece of a token
        return v

    def close(self):
        if not self.child: return
        c, self.child = self.child, None
        try: self.vault.drop(c["accessor"], c["policy"])
        finally: self._audit("secret.closed", ",".join(sorted(self.names)), f"{self.reads} read(s); token and policy revoked")


def broker(vault, db, timeout_s=2400):
    """The function exec_env.begin calls for a run of a board task: (task_row, mission, sid, agent) -> RunSecrets or None.
    None when Vault is off or the task declares no credential. A declared credential that isn't granted is audited with its reason
    and left out: the run then starts without it and is told so when it asks."""
    def for_run(t, mission, sid, agent):
        if not vault or not vault.enabled: return None
        try: needs = [str(s) for s in json.loads(t.get("needs") or "[]")]
        except ValueError: needs = []
        names = sorted({s.split(":", 1)[1] for s in needs if s.startswith("credential:") and NAME.match(s.split(":", 1)[1])})
        if not names: return None
        granted, team = {}, t.get("comp_id")
        rs = RunSecrets(vault, db, team=team, mission=mission, sid=sid, task=t.get("id"), agent=agent, granted={}, ttl=timeout_s)
        versions = {}
        for name in names:
            # Locate first, then ask whether THAT secret is verified, then hand over THAT version: one located result runs through all
            # three, so nothing written to Vault in between can be granted without a person having verified it.
            ok, why, path = False, "", None
            try: found = locate(vault, team, mission, name)
            except VaultError as e: found, why = None, str(e)
            if found:
                c = found[1]["custom"]
                ok, why = verified(db, team, mission, t.get("id"), name, identity(*found))
                if ok and c.get("agents") and str((agent or {}).get("id")) not in re.split(r"[,\s]+", c["agents"].strip()): ok, why = False, "the secret's own policy doesn't name this agent"
                elif ok and c.get("missions") and mission not in re.split(r"[,\s]+", c["missions"].strip()): ok, why = False, "the secret's own policy doesn't name this mission"
                elif ok: path = found[0]; versions[name] = found[1]["version"]
            elif not why:
                ok, why = verified(db, team, mission, t.get("id"), name)   # the reason a person needs: not verified, or verified and not held
                why = "Vault holds no such secret for this team or mission" if ok else why
                ok = False
            if ok and path: granted[name] = path
            else: rs._audit("secret.refused", name, why)
        if not granted: return None
        rs.paths, rs.names, rs.versions = granted, set(granted), versions
        return rs
    return for_run
