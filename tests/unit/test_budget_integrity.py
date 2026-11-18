"""Codex budget integrity (D-025): unmetered use is never read as zero and never lets work past a budget control.

A run whose tokens are unknown (a Codex session that ended without reporting usage, or one a restart cut off) makes every
stopping limit over its scope, and the owner's daily cap, answer UNKNOWN (the work waits) until a person records an estimate.
Alert-only limits and scopes without limits are unaffected. An estimate is audited and counted."""
import os, sys, tempfile, time, unittest

from app import agent_core
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_budget_safety import OWNER, spend  # noqa: E402


def unmetered(db, *, team="comp:1", system="teams", model="codex:gpt-6", started=None, tokens=0):
    return db.q("""INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, finished, team, model, metering)
                   VALUES (?,?,'task','done',?,?,?,?,?,'unmetered') RETURNING id""",
                (system, OWNER, tokens, started or time.time(), started or time.time(), team, model), one=True)["id"]


class FailClosed(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db) or agent_core._core

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core = None
        self.dir.cleanup()

    def pf(self, team="comp:1"): return agent_core.preflight(OWNER, "teams", team=team, ref=f"mwt:{team}")

    def test_no_limit_no_hold(self):
        unmetered(self.db)
        self.assertIsNone(self.pf())                                         # nothing to check against: nothing held

    def test_a_stopping_limit_over_unmetered_use_is_unknown_not_allow(self):
        self.core.set_limit(OWNER, "team", "comp:1", 1_000_000, period="day", label="team")
        unmetered(self.db)
        r = self.pf()
        self.assertEqual(r["decision"], "UNKNOWN")
        self.assertIn("unknown token use", r["error"])
        self.assertIsNone(self.pf(team="comp:2"))                            # another team's limit scope is unaffected

    def test_the_gateway_holds_the_run_itself(self):
        self.core.set_limit(OWNER, "team", "comp:1", 1_000_000, period="day", label="team")
        agent_core.begin("teams", OWNER, "task", ref="mw:1")
        rid = agent_core._local.run["id"]
        self.db.q("UPDATE ac_runs SET team='comp:1' WHERE id=?", (rid,)); agent_core._local.run["team"] = "comp:1"
        self.assertIsNone(agent_core.over())
        agent_core.unmetered("a Codex session reported no usage")
        self.assertEqual(agent_core.over(), agent_core.VERIFY_STOP)          # its next model call waits
        agent_core.end("done")

    def test_alert_only_limits_and_old_periods_do_not_hold(self):
        self.core.set_limit(OWNER, "team", "comp:1", 1_000_000, period="day", mode="alert", label="team")
        unmetered(self.db)
        self.assertIsNone(self.pf())
        self.core.set_limit(OWNER, "team", "comp:1", 1_000_000, period="day", mode="stop", label="team")
        self.db.q("UPDATE ac_runs SET started=? WHERE metering='unmetered'", (time.time() - 3 * 86400,))  # before today
        self.assertIsNone(self.pf())

    def test_the_daily_cap_too(self):
        self.core.set_cap(OWNER, 5_000_000, "boss")
        unmetered(self.db)
        self.assertEqual(self.pf()["decision"], "UNKNOWN")

    def test_an_estimate_releases_the_hold_and_is_counted(self):
        self.core.set_limit(OWNER, "team", "comp:1", 10_000, period="day", label="team")
        spend(self.db, 4_000, team="comp:1")
        rid = unmetered(self.db, tokens=0)
        self.assertEqual(self.pf()["decision"], "UNKNOWN")
        with self.assertRaises(ValueError): self.core.estimate(OWNER, rid, 0, "boss")       # never zero
        with self.assertRaises(ValueError): self.core.estimate(OWNER, rid, 1, "boss")       # nor zero in all but name: the floor
        with self.assertRaises(LookupError): self.core.estimate(OWNER + 1, rid, 50_000, "x")   # not someone else's
        self.core.estimate(OWNER, rid, 12_000, "boss")
        r = self.pf()
        self.assertEqual(r["decision"], "REFUSE")                            # 4,000 + 12,000 is over 10,000: counted, refused
        self.assertEqual(self.db.q("SELECT metering, tokens FROM ac_runs WHERE id=?", (rid,), one=True), {"metering": "estimated", "tokens": 12_000})
        with self.assertRaises(LookupError): self.core.estimate(OWNER, rid, 20_000, "boss")  # once

    def test_the_floor_follows_the_models_metered_runs(self):
        for t in (40_000, 60_000):
            self.db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, model) VALUES ('teams',?,'task','done',?,?,'codex:gpt-6')", (OWNER, t, time.time()))
        rid = unmetered(self.db)
        self.assertEqual(self.core.estimate_floor(rid), 50_000)
        with self.assertRaises(ValueError): self.core.estimate(OWNER, rid, 20_000, "boss")

    def test_a_restart_marks_a_codex_run_in_flight_unmetered(self):
        live = self.db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, model) VALUES ('teams',?,'task','running',0,?,'codex:gpt-6') RETURNING id", (OWNER, time.time()), one=True)["id"]
        claude = self.db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, model) VALUES ('teams',?,'task','running',0,?,'terminal:opus') RETURNING id", (OWNER, time.time()), one=True)["id"]
        agent_core._core = None
        agent_core.init(self.db)                                             # the server restarts
        row = lambda i: self.db.q("SELECT status, metering FROM ac_runs WHERE id=?", (i,), one=True)
        self.assertEqual(row(live), {"status": "lost", "metering": "unmetered"})
        self.assertEqual(row(claude), {"status": "lost", "metering": "unmetered"})  # Milestone 2: its message in flight is unknown too


if __name__ == "__main__":
    unittest.main()


class TeamGuard(unittest.TestCase):
    """The team 24-hour budget (mining_work's gateway guard) fails closed over unmetered runs of the team too."""
    def test_unmetered_team_run_makes_the_guard_unknown(self):
        from app import mining_work
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        core = agent_core.init(db) or agent_core._core
        self.addCleanup(lambda: setattr(agent_core, "_core", None))
        db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, name TEXT, number INTEGER, budget INTEGER)")
        db.q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, tokens INTEGER, started REAL, status TEXT)")
        db.q("INSERT INTO mw_comps VALUES (1, 'T', 1, 150000), (2, 'U', 2, 0)")
        w = object.__new__(mining_work.Work); w.db, w._guarded = db, {}
        w._flying = lambda wid: 0
        run = lambda team: {"id": None, "system": "teams", "team": team, "owner": OWNER}
        self.assertIsNone(w._budget_guard(run("comp:1")))
        db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, started, team, metering) VALUES ('teams',?,'task','done',0,?,'comp:1','unmetered')", (OWNER, time.time()))
        with self.assertRaises(agent_core.UnmeteredSpend): w._budget_guard(run("comp:1"))   # the gateway turns it into UNKNOWN
        self.assertIsNone(w._budget_guard(run("comp:2")))                                    # a team without a budget: nothing to check
