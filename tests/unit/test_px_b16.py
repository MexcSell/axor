"""PX-B16 end to end on the integrated tree (W7 mission_ops + W8 vault; kept by the integration owner from b3's merge check): the gate's record (mission_ops, orchestrator.risk_verify)
against the Vault stream's real vault.fingerprint / vault.verified, with a client double in vault._CLIENT. No Vault server."""
import json, os, tempfile, types, unittest
from unittest import mock
from fastapi import HTTPException
from app import mission_ops as mo, orchestrator as o, vault
from app.auth import AuthDB

ME = {"id": 1, "username": "owner", "role": "admin"}


class Double:
    def __init__(self): self.held, self.down, self.calls = {}, False, 0
    def meta(self, path):
        self.calls += 1
        if self.down: raise vault.VaultError("Vault is sealed")
        v = self.held.get(path)
        return {"version": v[0], "created": v[1], "custom": {}} if v else None


class RotationVoidsTheVerification(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, mission TEXT, title TEXT, detail TEXT, needs TEXT)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER)"); q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER)")
        q("INSERT INTO mh_campaigns VALUES (2, 1)"); q("INSERT INTO mw_comps VALUES (23, 2)")
        self.o = o.init(self.db)
        self.ch = types.SimpleNamespace(db=self.db, w=None, _has=lambda t: bool(q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        mo._written.clear(); mo._probe_cache.clear(); mo._fp_cache.clear()
        self.v = Double()
        for p in (mock.patch.object(vault, "ADDR", "http://vault.test:8200"), mock.patch.object(vault, "_CLIENT", [self.v])):
            p.start(); self.addCleanup(p.stop)
        q("INSERT INTO mw_tasks (id, comp_id, title, detail, needs) VALUES (1, 23, 'Task 1', 'Call the API', ?)", (json.dumps(["credential:MX_TEST_KEY"]),))
        self.t = dict(q("SELECT * FROM mw_tasks WHERE id=1", one=True))

    def tearDown(self):
        o._orc = None; self.dir.cleanup()

    def ready(self): return mo.task_readiness(self.ch, 1, {"id": 23}, self.t, "comp:23", "mw_task:1")["state"]
    def granted(self): return vault.verified(self.db, 23, "comp:23", 1, "MX_TEST_KEY")[0]
    def later(self): mo._fp_cache.clear()      # as if mission_ops.UNREADABLE_HOLD had passed

    def verify(self):
        self.assertEqual(self.ready(), "BLOCKED")
        rid = next(r for r in self.o.risks(1) if r["source_ref"] == "probe:credential")["id"]
        return self.o.risk_verify(ME, rid, "the API answered 200 with it")["verification"]

    def test_rotation_new_path_recreation_and_outage(self):
        self.v.held["teams/23/MX_TEST_KEY"] = (1, "2026-11-13T10:00:00Z")
        self.assertFalse(self.granted())                                              # nobody verified it yet
        v = self.verify()
        self.assertEqual(v["fingerprint"], "vault:teams/23/MX_TEST_KEY@v1@2026-11-13T10:00:00Z")
        self.assertEqual(v["fingerprint"], vault.fingerprint(23, "comp:23", "MX_TEST_KEY"))
        self.assertAlmostEqual(v["expires"] - v["at"], 24 * 3600, delta=5)
        self.assertEqual(self.ready(), "READY"); self.assertTrue(self.granted())
        self.v.held["teams/23/MX_TEST_KEY"] = (2, "2026-11-13T12:00:00Z")      # rotated: seen at once, nothing is cleared
        self.assertFalse(self.granted()); self.assertEqual(self.ready(), "BLOCKED")
        v = self.verify(); self.assertIn("@v2@", v["fingerprint"]); self.assertTrue(self.granted())
        self.v.held["teams/23/MX_TEST_KEY"] = (1, "2026-11-13T13:00:00Z")      # deleted and written again: version 1 once more
        self.assertFalse(self.granted())
        v = self.verify(); self.assertTrue(self.granted())
        self.v.held["missions/comp_23/MX_TEST_KEY"] = (1, "2026-11-13T13:00:00Z")   # a mission secret over the team's
        self.assertFalse(self.granted()); self.assertEqual(self.ready(), "BLOCKED")
        v = self.verify(); self.assertIn("missions/comp_23/", v["fingerprint"]); self.assertTrue(self.granted())
        self.v.down = True                                                # sealed
        self.assertFalse(self.granted()); self.assertEqual(self.ready(), "BLOCKED")
        rid = next(r for r in self.o.risks(1) if r["source_ref"] == "probe:credential")["id"]
        with self.assertRaises(HTTPException) as e: self.o.risk_verify(ME, rid, "checked")
        self.assertEqual(e.exception.status_code, 503)
        self.v.down = False; self.later()
        self.assertTrue(self.granted())                                                 # the record was never replaced by an "absent" one

    def test_a_record_under_another_account_doesnt_count(self):
        self.v.held["teams/23/MX_TEST_KEY"] = (1, "2026-11-13T10:00:00Z")
        self.verify(); self.assertTrue(self.granted())
        self.db.q("UPDATE mh_campaigns SET user_id=9 WHERE id=2")
        self.assertFalse(self.granted())

    def test_a_run_starting_right_after_a_rotation_is_not_given_the_new_secret(self):
        self.v.held["teams/23/MX_TEST_KEY"] = (1, "2026-11-13T10:00:00Z")
        self.verify()
        self.assertEqual(self.ready(), "READY")                                        # the dispatch gate has just asked Vault
        self.v.held["teams/23/MX_TEST_KEY"] = (2, "2026-11-13T12:00:00Z")              # rotated between the gate and the run's start
        self.assertFalse(self.granted())                                               # the grant reads Vault itself, at that moment

    def test_an_outage_is_held_a_few_seconds_not_asked_per_credential(self):
        self.v.held["teams/23/MX_TEST_KEY"] = (1, "2026-11-13T10:00:00Z")
        self.verify(); self.v.down = True
        self.assertFalse(self.granted()); n = self.v.calls
        for _ in range(5): self.assertFalse(self.granted())
        self.assertEqual(self.v.calls, n)


class TheGrantRestsOnOneReadingOfVault(unittest.TestCase):
    """PX-B16's residual, with both sides real: vault.broker locates the secret once, hands mission_ops._verified the identity
    of what it located, and reads the value at that version. Vault here is the Vault stream's own stand-in (test_vault.FakeVault)."""
    def setUp(self):
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from test_vault import FakeVault
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, mission TEXT, title TEXT, detail TEXT, needs TEXT)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER)"); q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER)")
        q("INSERT INTO mh_campaigns VALUES (2, 1)"); q("INSERT INTO mw_comps VALUES (23, 2)")
        self.o = o.init(self.db)
        self.ch = types.SimpleNamespace(db=self.db, w=None, _has=lambda t: bool(q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        mo._written.clear(); mo._probe_cache.clear(); mo._fp_cache.clear()
        self.v = FakeVault({"teams/23/MX_TEST_KEY": {"value": "first value"}})
        self.metas = []
        real_meta = self.v.meta
        def meta(path): self.metas.append(path); return real_meta(path)
        self.v.meta = meta
        for p in (mock.patch.object(vault, "ADDR", "http://vault.test:8200"), mock.patch.object(vault, "_CLIENT", [self.v])):
            p.start(); self.addCleanup(p.stop)
        q("INSERT INTO mw_tasks (id, comp_id, title, detail, needs) VALUES (1, 23, 'Task 1', 'Call the API', ?)", (json.dumps(["credential:MX_TEST_KEY"]),))
        self.t = dict(q("SELECT * FROM mw_tasks WHERE id=1", one=True))
        self.broker = vault.broker(self.v, self.db, 1800)
        self.assertEqual(mo.task_readiness(self.ch, 1, {"id": 23}, self.t, "comp:23", "mw_task:1")["state"], "BLOCKED")
        rid = next(r for r in self.o.risks(1) if r["source_ref"] == "probe:credential")["id"]
        self.fp = self.o.risk_verify(ME, rid, "the API answered 200 with it")["verification"]["fingerprint"]   # a person verified version 1

    def tearDown(self):
        o._orc = None
        try: self.db.db.close()
        except Exception: pass   # noqa: BLE001
        self.dir.cleanup()

    def grant(self, sid): return self.broker(self.t, "comp:23", sid, {"id": 2})

    def test_unchanged_since_verified_is_granted_from_one_reading(self):
        self.assertEqual(self.fp, vault.identity("teams/23/MX_TEST_KEY", self.v.meta("teams/23/MX_TEST_KEY")))
        self.metas.clear()
        with mock.patch.object(mo, "_verified", autospec=True, side_effect=mo._verified) as gate:   # autospec: the broker reads the gate's signature
            rs = self.grant(101)
        self.assertEqual((rs.names, rs.versions), ({"MX_TEST_KEY"}, {"MX_TEST_KEY": 1}))
        self.assertEqual(gate.call_args.kwargs.get("identity"), self.fp)              # the gate was handed what the broker located
        self.assertEqual(self.metas, ["missions/comp_23/MX_TEST_KEY", "teams/23/MX_TEST_KEY"])   # the broker's one lookup; the gate made none

    def test_a_rotation_that_lands_before_the_brokers_lookup_is_not_granted(self):
        self.v.rotate("teams/23/MX_TEST_KEY", "second value")
        self.metas.clear()
        with mock.patch.object(mo, "_verified", autospec=True, side_effect=mo._verified) as gate:   # autospec: the broker reads the gate's signature
            self.assertIsNone(self.grant(102))
        self.assertIn("@v2@", gate.call_args.kwargs.get("identity"))
        self.assertEqual(self.v.children, []); self.assertEqual(self.v.reads, [])     # no token was made, nothing was read
        self.assertEqual(len(self.metas), 2)

    def test_the_gate_alone_refuses_it_whatever_the_broker_checks_besides(self):
        """The negative control's other half: the gate's own answer for the located identity, without the broker's second comparison."""
        key = mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY")
        v2 = "vault:teams/23/MX_TEST_KEY@v2@2026-11-13T11:00:00Z"
        self.metas.clear()
        self.assertIsNone(mo._verified(self.ch, 1, key, "MX_TEST_KEY", identity=v2))                # Vault itself still says version 1 here
        self.assertIsNotNone(mo._verified(self.ch, 1, key, "MX_TEST_KEY", identity=self.fp))
        self.assertEqual(self.metas, [])
        with mock.patch.object(mo, "vault_fp", lambda ident: self.fp):                             # control: a gate that ignores what it is handed would pass v2
            self.assertIsNotNone(mo._verified(self.ch, 1, key, "MX_TEST_KEY", identity=v2))

    def test_a_rotation_after_the_grant_doesnt_reach_the_run(self):
        rs = self.grant(103)
        self.v.rotate("teams/23/MX_TEST_KEY", "second value")
        self.assertEqual(rs.fetch("MX_TEST_KEY"), "first value")                       # read at the verified version
        self.assertEqual(self.v.reads, [("teams/23/MX_TEST_KEY", 1)])
        rs.close()
        self.assertIsNone(self.grant(104))                                             # the next run needs a new verification


if __name__ == "__main__":
    unittest.main()
