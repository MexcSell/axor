"""Credentials for runs (vault.py; D-033, approved for development against a test server): what is granted and why not, the
per-run token's life, the audit rows, and the client's handling of Vault's answers. A stand-in Vault is used here; the real
one is exercised in staging (owner-decisions/g5-plan/aef/evidence/vault-run1)."""
import json, os, socket, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app import exec_env as ex, vault
from app.auth import AuthDB


class FakeVault:
    """What vault.broker and RunSecrets ask of a Vault, recorded."""
    enabled = True
    def __init__(self, secrets):
        self.secrets, self.children, self.dropped, self.reads = secrets, [], [], []   # {path: {"value", "custom"}}
    def meta(self, path):
        s = self.secrets.get(path)
        return {"version": s.get("version", 1), "created": s.get("created", "2026-11-13T10:00:00Z"), "updated": "now", "custom": s.get("custom") or {}} if s else None
    def child(self, name, paths, ttl, uses, meta):
        c = {"token": f"tok-{name}", "accessor": f"acc-{name}", "policy": f"axor-run-{name}", "paths": paths, "ttl": ttl, "uses": uses, "meta": meta}
        self.children.append(c); return c
    def read(self, path, token, version=None):
        c = next(c for c in self.children if c["token"] == token)
        if path not in c["paths"]: raise vault.VaultError("Vault answered 403")
        self.reads.append((path, version) if version else path)
        s = self.secrets[path]
        return s.get("old", {}).get(version, s["value"]) if version and version != s.get("version", 1) else s["value"]

    def rotate(self, path, value, created="2026-11-13T11:00:00Z"):
        """The Owner writes a new version: the earlier one stays readable by its number, as in Vault's KV v2."""
        s = self.secrets[path]
        s.setdefault("old", {})[s.get("version", 1)] = s["value"]
        s.update(value=value, version=s.get("version", 1) + 1, created=created)
    def drop(self, accessor, policy): self.dropped.append((accessor, policy))


class Grants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        self.db.q("CREATE TABLE io_risks (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, rkey TEXT, status TEXT, verification TEXT, resolved_at REAL)")
        self.db.q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER)"); self.db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER)")
        self.db.q("INSERT INTO mh_campaigns (id, user_id) VALUES (1, 41), (2, 42)"); self.db.q("INSERT INTO mw_comps (id, campaign_id) VALUES (7, 1), (8, 2)")
        self.v = FakeVault({"teams/7/API_KEY": {"value": "team-value"}, "missions/mx_4/API_KEY": {"value": "mission-value"}, "teams/7/ONLY_AGENT_5": {"value": "x", "custom": {"agents": "5, 9"}},
                            "teams/7/ONLY_MX9": {"value": "y", "custom": {"missions": "mx:9"}}, "teams/8/API_KEY": {"value": "other team's"}})
        self.broker = vault.broker(self.v, self.db, 1800)

    def tearDown(self):
        try: self.db.db.close()   # on Postgres every AuthDB holds a connection for as long as it lives
        except Exception: pass    # noqa: BLE001
        self.tmp.cleanup()

    def verify(self, mission, task, name, expires=None, status="resolved", owner=41, **v):
        """What a person's verification leaves on the readiness gate's record (mission_ops): under the team owner's account."""
        import inspect
        from app import mission_ops as mo
        fp = "absent"
        if "identity" in inspect.signature(mo._verified).parameters:   # a gate that ties a verification to Vault's identity records that identity
            found = vault.locate(self.v, {41: 7, 42: 8}.get(owner), mission, name)
            if found: fp = vault.identity(*found)
        self.db.q("INSERT INTO io_risks (owner_id, rkey, status, verification) VALUES (?,?,?,?)",
                  (owner, f"readiness:{mission}:mw_task:{task}:credential:{name}", status,
                   json.dumps({"by": "owner", "kind": "credential", "expires": expires or time.time() + 3600, "fingerprint": fp, **v})))

    def task(self, tid=11, needs=("credential:API_KEY",), comp=7): return {"id": tid, "comp_id": comp, "needs": json.dumps(list(needs))}

    def refusals(self): return [(r["target"], r["detail"].split("; ", 1)[1]) for r in self.db.q("SELECT target, detail FROM audit WHERE action='secret.refused' ORDER BY ts")]

    def test_declared_verified_and_held_is_granted_and_the_missions_own_wins(self):
        self.verify("mx:4", 11, "API_KEY")
        rs = self.broker(self.task(), "mx:4", 301, {"id": 2})
        self.assertEqual((rs.names, rs.paths), ({"API_KEY"}, {"API_KEY": "missions/mx_4/API_KEY"}))
        self.verify("mx:5", 11, "API_KEY")
        self.assertEqual(self.broker(self.task(), "mx:5", 302, {"id": 2}).paths, {"API_KEY": "teams/7/API_KEY"})

    def test_each_missing_condition_refuses_with_its_reason(self):
        self.assertIsNone(self.broker(self.task(), "mx:4", 1, {"id": 2}))                                      # nobody verified it
        self.verify("mx:4", 12, "API_KEY", expires=time.time() - 1)
        self.assertIsNone(self.broker(self.task(12), "mx:4", 2, {"id": 2}))                                    # the verification expired
        self.verify("mx:4", 13, "API_KEY", status="open")
        self.assertIsNone(self.broker(self.task(13), "mx:4", 3, {"id": 2}))                                    # the gate's item isn't resolved
        self.verify("mx:4", 14, "API_KEY", kind="approval")
        self.assertIsNone(self.broker(self.task(14), "mx:4", 4, {"id": 2}))                                    # an approval isn't a verification of the credential
        self.verify("mx:4", 15, "API_KEY")
        self.assertIsNone(self.broker(self.task(16), "mx:4", 5, {"id": 2}))                                    # verified for another task
        self.verify("mx:4", 19, "API_KEY", owner=42)
        self.assertIsNone(self.broker(self.task(19), "mx:4", 5, {"id": 2}))                                    # a record under another account doesn't count
        self.verify("mx:4", 20, "API_KEY", fingerprint="0123456789abcdef")
        self.assertIsNone(self.broker(self.task(20), "mx:4", 5, {"id": 2}))                                    # verified for another value of the credential
        self.assertIsNone(self.broker(self.task(21, comp=99), "mx:4", 5, {"id": 2}))                           # a team nobody owns
        self.verify("mx:4", 17, "NOT_HELD")
        self.assertIsNone(self.broker(self.task(17, ["credential:NOT_HELD"]), "mx:4", 6, {"id": 2}))
        self.verify("mx:4", 18, "ONLY_AGENT_5"); self.verify("mx:4", 18, "ONLY_MX9")
        self.assertIsNone(self.broker(self.task(18, ["credential:ONLY_AGENT_5", "credential:ONLY_MX9"]), "mx:4", 7, {"id": 2}))
        self.assertEqual(self.broker(self.task(18, ["credential:ONLY_AGENT_5"]), "mx:4", 8, {"id": 5}).names, {"ONLY_AGENT_5"})   # the control: the named agent gets it
        why = self.refusals()
        self.assertEqual([w for _, w in why[:7]], ["no person's current verification of it is recorded for this task"] * 7)
        self.assertEqual(why[7], ("API_KEY", "the team's owner couldn't be found, so no verification can be read"))
        self.assertEqual(why[8:], [("NOT_HELD", "Vault holds no such secret for this team or mission"), ("ONLY_AGENT_5", "the secret's own policy doesn't name this agent"),
                                   ("ONLY_MX9", "the secret's own policy doesn't name this mission")])
        self.assertEqual(self.v.children, [])                                                                   # no token was ever made for a refusal

    def test_undeclared_or_malformed_needs_ask_vault_nothing(self):
        self.verify("mx:4", 11, "API_KEY")
        for needs in ([], ["internet"], ["credential:"], ["credential:lower_case"], ["credential:../../x"], ["credential:A B"]):
            self.assertIsNone(self.broker(self.task(needs=needs), "mx:4", 1, {"id": 2}), needs)
        self.assertIsNone(vault.broker(None, self.db)(self.task(), "mx:4", 1, None))
        off = FakeVault({}); off.enabled = False
        self.assertIsNone(vault.broker(off, self.db)(self.task(), "mx:4", 1, None))

    def test_another_teams_secret_of_the_same_name_is_never_reached(self):
        self.verify("mx:1", 11, "API_KEY", owner=42)
        rs = self.broker(self.task(comp=8), "mx:1", 9, {"id": 2})
        self.assertEqual(rs.paths, {"API_KEY": "teams/8/API_KEY"}); self.assertEqual(rs.fetch("API_KEY"), "other team's")

    def test_one_token_per_run_made_on_first_use_scoped_counted_and_revoked(self):
        self.verify("mx:5", 11, "API_KEY")
        rs = self.broker(self.task(), "mx:5", 77, {"id": 2})
        self.assertEqual(self.v.children, [])                                    # granted isn't used: nothing exists in Vault until the run asks
        self.assertEqual(rs.fetch("API_KEY"), "team-value"); self.assertEqual(rs.fetch("API_KEY"), "team-value")
        c = self.v.children
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["paths"], c[0]["ttl"], c[0]["uses"]), (["teams/7/API_KEY"], 1800, 2))
        self.assertEqual(self.v.reads, [("teams/7/API_KEY", 1)] * 2)                    # read by version, both times
        self.assertEqual(c[0]["meta"], {"mission": "mx:5", "team": 7, "run": 77, "task": 11, "agent": 2})
        with self.assertRaises(vault.VaultError): rs.fetch("OTHER")
        rs.close(); rs.close()
        self.assertEqual(self.v.dropped, [(c[0]["accessor"], c[0]["policy"])])
        acts = [(r["action"], r["actor"], r["target"]) for r in self.db.q("SELECT action, actor, target FROM audit WHERE action LIKE 'secret.%' ORDER BY ts")]
        self.assertEqual(acts, [("secret.read", "run:77", "API_KEY"), ("secret.read", "run:77", "API_KEY"), ("secret.closed", "run:77", "API_KEY")])
        dumped = json.dumps([dict(r) for r in self.db.q("SELECT * FROM audit")])
        self.assertNotIn("team-value", dumped); self.assertNotIn("tok-", dumped)   # neither the value nor a token is ever in AXoR's audit log

    def test_a_rotation_after_the_grant_doesnt_put_an_unverified_version_in_the_runs_hands(self):
        """The window between "verified" and "read": the run is given exactly the version that was located and verified."""
        self.verify("mx:5", 11, "API_KEY")
        rs = self.broker(self.task(), "mx:5", 90, {"id": 2})
        self.assertEqual(rs.versions, {"API_KEY": 1})
        self.v.rotate("teams/7/API_KEY", "written after the grant, verified by nobody")
        self.assertEqual(rs.fetch("API_KEY"), "team-value")                              # version 1, the verified one
        self.assertEqual(self.v.reads, [("teams/7/API_KEY", 1)])
        self.assertIn("version 1", self.db.q("SELECT detail FROM audit WHERE action='secret.read'", one=True)["detail"])
        rs.versions.clear()                                                              # the control: without the pin the same read returns the new value
        self.assertEqual(rs.fetch("API_KEY"), "written after the grant, verified by nobody")

    def test_a_rotation_between_the_verification_and_the_grant_is_refused(self):
        """With a gate that ties a verification to Vault's identity of the secret (the access stream's side): the broker locates the
        secret once, and the verification must be for exactly that identity. Both forms of such a gate are covered."""
        from app import mission_ops as mo
        v1 = vault.identity("teams/7/API_KEY", self.v.meta("teams/7/API_KEY"))
        self.verify("mx:5", 11, "API_KEY", fingerprint=v1)
        record = lambda ch, uid, rkey: json.loads(ch.db.q("SELECT verification FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)["verification"])
        asked = []
        def gate_with_identity(ch, uid, rkey, value=None, live=True, identity=None):    # compares the identity it is handed; makes no lookup of its own
            asked.append(identity); r = record(ch, uid, rkey)
            return r if r["fingerprint"] == identity else None
        def gate_without(ch, uid, rkey, value=None):                                     # an aware gate that made its own lookup a moment ago and still saw v1
            return record(ch, uid, rkey)
        aware_fp = lambda name, team=None, mission=None, live=True: "x"
        for gate in (gate_with_identity, gate_without):
            self.db.q("DELETE FROM audit"); self.v.secrets["teams/7/API_KEY"].update(value="team-value", version=1, created="2026-11-13T10:00:00Z")
            with mock.patch.object(mo, "_verified", gate), mock.patch.object(mo, "credential_fingerprint", aware_fp):
                self.assertEqual(self.broker(self.task(), "mx:5", 91, {"id": 2}).versions, {"API_KEY": 1}, gate.__name__)   # the control: unchanged since verified → granted
                self.v.rotate("teams/7/API_KEY", "rotated after a person verified version 1")
                self.assertIsNone(self.broker(self.task(), "mx:5", 92, {"id": 2}), gate.__name__)                         # located v2; the verification is for v1
            why = [w for _, w in self.refusals()]
            self.assertEqual(len(why), 1, gate.__name__)
            self.assertIn(why[0], ("no person's current verification of it is recorded for this task", "the credential changed since it was verified: a person has to verify it again"))
        self.assertEqual(len(asked), 2)
        self.assertTrue(asked[0] == v1 and "@v2@" in asked[1])                          # the gate was handed the identity of what was located, each time
        self.assertEqual(self.v.children, [])                                            # and nothing was read for the refused grant

    def test_fingerprint_names_the_secret_a_run_would_get_and_changes_when_it_does(self):
        """What the readiness gate stores with a verification: the same lookup as the broker's, so the two can't disagree."""
        fp = lambda team, mission, name: vault.fingerprint(team, mission, name)
        with mock.patch.object(vault, "ADDR", ""), mock.patch.object(vault, "_CLIENT", [self.v]):
            self.assertIsNone(fp(7, "mx:4", "API_KEY"))                                   # no Vault set for the server: nothing asked, nothing claimed
        with mock.patch.object(vault, "ADDR", "http://vault:8200"), mock.patch.object(vault, "_CLIENT", [self.v]):
            self.assertEqual(fp(7, "mx:5", "API_KEY"), "vault:teams/7/API_KEY@v1@2026-11-13T10:00:00Z")
            self.assertEqual(fp(7, "mx:4", "API_KEY"), "vault:missions/mx_4/API_KEY@v1@2026-11-13T10:00:00Z")   # the mission's own wins, as in the broker; same version, another identity
            self.assertEqual(self.broker.__closure__ is not None and vault.locate(self.v, 7, "mx:4", "API_KEY")[0], "missions/mx_4/API_KEY")
            before = fp(7, "mx:5", "API_KEY")
            self.v.secrets["teams/7/API_KEY"]["version"] = 2                                # the Owner rotates it
            self.assertNotEqual(fp(7, "mx:5", "API_KEY"), before)
            self.v.secrets["teams/7/API_KEY"].update(version=1, created="2026-11-14T08:00:00Z")   # deleted and written again: version 1 once more
            self.assertNotEqual(fp(7, "mx:5", "API_KEY"), before)
            self.assertIsNone(fp(7, "mx:5", "NOT_HELD")); self.assertIsNone(fp(8, "mx:5", "ONLY_AGENT_5")); self.assertIsNone(fp(7, "mx:5", "lower-case"))
            self.assertIsNotNone(fp(7, "mx:5", "ONLY_AGENT_5"))                             # the secret's own agent policy isn't part of its identity
            def down(path): raise vault.VaultError("Vault is sealed")
            with mock.patch.object(self.v, "meta", down):
                with self.assertRaises(vault.VaultError): fp(7, "mx:5", "API_KEY")          # unreadable is not absent

    def test_a_run_never_opened_leaves_nothing_in_vault(self):
        self.verify("mx:5", 11, "API_KEY")
        self.broker(self.task(), "mx:5", 78, {"id": 2}).close()
        self.assertEqual((self.v.children, self.v.dropped), ([], []))


class Client(unittest.TestCase):
    """vault.Vault against a small HTTP server that answers as Vault does."""
    @classmethod
    def setUpClass(cls):
        cls.seen = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _go(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                cls.seen.append((self.command, self.path, self.headers.get("X-Vault-Token"), body))
                code, out = cls.answer(self.command, self.path, self.headers.get("X-Vault-Token"), body)
                raw = json.dumps(out).encode() if out is not None else b""
                self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            do_GET = do_POST = do_PUT = do_DELETE = _go

        with socket.socket() as s: s.bind(("127.0.0.1", 0)); cls.port = s.getsockname()[1]
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close()

    @staticmethod
    def answer(method, path, token, body):
        if path.startswith("/v1/sys/health"): return 200, {"initialized": True, "sealed": False}
        if token not in ("axor", "child"): return 403, {"errors": ["permission denied"]}
        if path == "/v1/auth/token/lookup-self": return 200, {"data": {}}
        if path == "/v1/axor/metadata/teams/7/API_KEY": return 200, {"data": {"current_version": 3, "updated_time": "t", "custom_metadata": {"agents": "2"}, "versions": {"3": {"deletion_time": "", "created_time": "2026-11-13T09:00:00Z"}}}}
        if path == "/v1/axor/metadata/teams/7/DELETED": return 200, {"data": {"current_version": 1, "versions": {"1": {"deletion_time": "2026-11-13T00:00:00Z"}}}}
        if path.startswith("/v1/axor/metadata/"): return 404, {"errors": []}
        if path.startswith("/v1/sys/policies/acl/"): return 204, None
        if path == "/v1/auth/token/create/axor-run": return 200, {"auth": {"client_token": "child", "accessor": "acc1"}}
        if path == "/v1/auth/token/revoke-accessor": return (204, None) if body == {"accessor": "acc1"} else (400, {"errors": ["invalid accessor"]})
        if path == "/v1/axor/data/teams/7/API_KEY": return (200, {"data": {"data": {"value": "v3"}}}) if token == "child" else (403, {"errors": ["permission denied"]})
        if path == "/v1/axor/data/teams/7/API_KEY?version=2": return 200, {"data": {"data": {"value": "v2"}}}
        if path == "/v1/axor/data/teams/7/NO_VALUE": return 200, {"data": {"data": {"password": "x"}}}
        return 404, {"errors": ["no handler"]}

    def v(self, token="axor"): return vault.Vault(f"http://127.0.0.1:{self.port}", token)

    def test_ready(self):
        self.assertEqual(self.v().ready(), (True, ""))
        ok, why = self.v("wrong").ready()
        self.assertFalse(ok); self.assertIn("403", why)
        self.assertEqual(vault.Vault("").ready()[0], False)
        ok, why = vault.Vault("http://127.0.0.1:9", "x").ready()
        self.assertFalse(ok); self.assertIn("didn't answer", why)

    def test_metadata_never_a_value(self):
        self.assertEqual(self.v().meta("teams/7/API_KEY"), {"version": 3, "created": "2026-11-13T09:00:00Z", "updated": "t", "custom": {"agents": "2"}})
        self.assertIsNone(self.v().meta("teams/7/NOPE")); self.assertIsNone(self.v().meta("teams/7/DELETED"))

    def test_child_token_request_is_exact_and_axors_own_token_is_never_used_to_read(self):
        del self.seen[:]
        c = self.v().child("s9-1", ["teams/7/API_KEY"], 1800, 2, {"run": 9, "mission": "mx:4", "agent": None})
        pol = next(b for m, p, t, b in self.seen if p == "/v1/sys/policies/acl/axor-run-s9-1")
        self.assertEqual(pol, {"policy": 'path "axor/data/teams/7/API_KEY" { capabilities = ["read"] }'})
        req = next(b for m, p, t, b in self.seen if p == "/v1/auth/token/create/axor-run")
        self.assertEqual(req, {"policies": ["axor-run-s9-1"], "ttl": "1800s", "explicit_max_ttl": "1800s", "num_uses": 2, "renewable": False, "no_default_policy": True,
                               "display_name": "s9-1", "meta": {"run": "9", "mission": "mx:4"}})
        self.assertEqual(self.v().read("teams/7/API_KEY", c["token"]), "v3")
        self.assertEqual(self.v().read("teams/7/API_KEY", c["token"], version=2), "v2")   # one exact version, when a grant names it
        read = next((m, p, t) for m, p, t, b in self.seen if p == "/v1/axor/data/teams/7/API_KEY")
        self.assertEqual(read[2], "child")
        with self.assertRaisesRegex(vault.VaultError, "403"): self.v().read("teams/7/API_KEY", "axor")
        with self.assertRaisesRegex(vault.VaultError, "no `value` field"): self.v().read("teams/7/NO_VALUE", "child")
        self.v().drop(c["accessor"], c["policy"])
        self.v().drop("already-gone", c["policy"])                                # a token that is used up or expired is the wanted end state: no error

    def test_the_environments_proxy_is_never_used_for_vault(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}):
            self.assertEqual(self.v().ready(), (True, ""))


class Wiring(unittest.TestCase):
    def test_no_vault_set_no_broker(self):
        with mock.patch.object(vault, "ADDR", ""): self.assertIsNone(ex._vault_broker(object()))
        with mock.patch.object(vault, "ADDR", "http://vault:8200"):
            ex._BROKERS.clear(); db = object()
            b = ex._vault_broker(db)
            self.assertTrue(callable(b)); self.assertIs(ex._vault_broker(db), b)
        ex._BROKERS.clear()


if __name__ == "__main__":
    unittest.main()
