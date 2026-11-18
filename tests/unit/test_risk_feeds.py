"""G5-3 R3.1: the diagnosis feeds of the risk register (D-012).

io_diag and io_sbx feed orchestrator.io_risks: a failure class that isn't the work's own, seen RISK_RECUR times in one scope
within RISK_WINDOW, is one register row. The scope is never invented (mission only from an mx: corr, else the run's team, else
the owner's own work). Re-running a feed changes nothing; a quiet window resolves the row; a new burst reopens it. A feed
touches only its own rows and never holds a task (T-9)."""
import os, sys, tempfile, time, unittest

from app import orchestrator as o
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_readiness_gate import Base as GateBase  # noqa: E402

CRED = "Claude Code on the server isn't signed in."  # canon credential (legacy cls task)
QUOTA = "plan rate limit reached"                    # canon quota
T8 = ("title", "description", "root_cause", "probability", "impact", "severity", "priority", "detection", "countermeasure", "responsible", "approval")


class FeedBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("""CREATE TABLE ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, system TEXT, kind TEXT, ref TEXT, corr TEXT, team TEXT,
             agent_key TEXT, status TEXT, error TEXT, score REAL, tokens INTEGER, started REAL, finished REAL)""")
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, netuid INTEGER, status TEXT)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, name TEXT)")
        q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, status TEXT, error TEXT,
             started REAL, finished REAL)""")
        q("INSERT INTO mh_campaigns (id, user_id, netuid, status) VALUES (1, 7, 61, 'live')")
        q("INSERT INTO mw_comps (id, campaign_id, name) VALUES (5, 1, 'SN61'), (6, 99, 'orphan')")
        self.o = o.Orchestrator(self.db)
        self.now = time.time()

    def tearDown(self): self.dir.cleanup()

    def fail(self, err, n=1, owner=7, corr=None, team="comp:5", ref="mw:1", at=None):
        for _ in range(n):
            self.db.q("INSERT INTO ac_runs (owner_id, system, kind, ref, corr, team, status, error, started) VALUES (?,?,?,?,?,?,?,?,?)",
                      (owner, "teams", "task", ref, corr, team, "failed", err, at or self.now))
        self.o.diagnose()

    def sbx(self, err, n=1, comp=5, status="error"):
        for _ in range(n):
            self.db.q("INSERT INTO mw_sbx (comp_id, task_id, status, error, started) VALUES (?,?,?,?,?)", (comp, 1, status, err, self.now))
        self.o.diagnose_sandbox()

    def rows(self, source=None):
        return [r for r in self.o.risks(7) if source is None or r["source"] == source]

    def row(self, rkey):
        return next(r for r in self.o.risks(7, limit=500) if r["rkey"] == rkey)


class Feeds(FeedBase):
    # ---------- io_diag ----------
    def test_under_the_threshold_is_not_a_risk(self):
        self.fail(CRED, 2)
        self.assertEqual(self.o.risk_feeds(self.now), 0)
        self.assertEqual(self.rows(), [])

    def test_recurring_class_is_one_row_with_every_field(self):
        self.fail(CRED, 3)
        self.assertEqual(self.o.risk_feeds(self.now), 1)
        [r] = self.rows()
        self.assertEqual((r["rkey"], r["mission"], r["source"], r["layer"], r["status"], r["critical"]),
                         ("diag:comp:5:credential", "comp:5", "diagnosis", "workforce", "open", False))
        for f in T8: self.assertTrue(r[f], f)                      # T-8: the 11 fields
        self.assertEqual((r["evidence"]["n"], len(r["evidence"]["runs"])), (3, 3))
        self.assertIsNone(r["task_ref"])

    def test_rerunning_changes_nothing(self):
        self.fail(CRED, 3)
        self.o.risk_feeds(self.now)
        before = self.row("diag:comp:5:credential")
        self.assertEqual(self.o.risk_feeds(self.now), 0)
        self.assertEqual(self.o.risk_feeds(self.now + 60), 0)
        after = self.row("diag:comp:5:credential")
        self.assertEqual((after["seen"], after["updated"], after["evidence"]), (before["seen"], before["updated"], before["evidence"]))

    def test_new_failure_updates_quiet_window_resolves_new_burst_reopens(self):
        self.fail(CRED, 3)
        self.o.risk_feeds(self.now)
        self.fail(CRED, 1)
        self.assertEqual(self.o.risk_feeds(self.now), 1)
        r = self.row("diag:comp:5:credential")
        self.assertEqual((r["seen"], r["evidence"]["n"]), (2, 4))
        later = self.now + o.RISK_WINDOW + 60
        self.assertEqual(self.o.risk_feeds(later), 1)
        r = self.row("diag:comp:5:credential")
        self.assertEqual((r["status"], r["verification"]["feed"], r["verification"]["n"]), ("resolved", "diagnosis", 0))
        self.assertEqual(self.o.risk_feeds(later), 0)               # resolved stays resolved
        self.fail(CRED, 3, at=later)
        self.o.risk_feeds(later)
        self.assertEqual(self.row("diag:comp:5:credential")["status"], "open")

    def test_open_row_stays_open_while_its_class_still_shows_under_the_threshold(self):
        self.fail(CRED, 3)
        self.o.risk_feeds(self.now)
        t = self.now + o.RISK_WINDOW - 600
        self.fail(CRED, 1, at=t)                                    # the first three age out, one is still in the window
        self.o.risk_feeds(t + 1200)
        r = self.row("diag:comp:5:credential")
        self.assertEqual((r["status"], r["evidence"]["n"]), ("open", 1))

    def test_failures_ageing_out_without_a_new_one_write_nothing(self):
        for h in (0, 2, 4, 6):                                      # four failures, two hours apart
            self.fail(CRED, 1, at=self.now + h * 3600)
        t = self.now + 6 * 3600
        self.o.risk_feeds(t)
        before = self.row("diag:comp:5:credential")
        self.assertEqual(self.o.risk_feeds(t + o.RISK_WINDOW - 3600), 0)   # the first one aged out, nothing new
        self.assertEqual(self.row("diag:comp:5:credential")["seen"], before["seen"])

    def test_a_fed_row_is_never_verified_or_approved_as_a_readiness_item(self):
        self.fail(CRED, 3)
        self.o.risk_feeds(self.now)
        rid = self.row("diag:comp:5:credential")["id"]
        me = {"id": 7, "username": "owner", "role": "admin"}
        for call in (lambda: self.o.risk_verify(me, rid, "works"), lambda: self.o.risk_approve(me, rid, "go", None)):
            with self.assertRaises(o.HTTPException) as e: call()
            self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(self.row("diag:comp:5:credential")["status"], "open")

    def test_scope_is_never_invented(self):
        self.fail(CRED, 3, corr="mx:9")                             # a mission's run
        self.fail(QUOTA, 3, corr="mw:1", team=None)                 # corr is the run's own ref: no mission, no team
        self.fail(QUOTA, 3, team="co-team:2")                       # a Company team
        self.o.risk_feeds(self.now)
        got = {r["rkey"]: r["mission"] for r in self.rows()}
        self.assertEqual(got, {"diag:mx:9:credential": "mx:9", "diag:owner:quota": None, "diag:co-team:2:quota": "co-team:2"})

    def test_own_and_elsewhere_fed_classes_stay_out(self):
        self.fail("boom", 3)                                        # task: the work's own
        self.fail("Interrupted: the server restarted", 3)           # restart: a deploy
        self.fail("token budget reached", 3)                        # budget: the ac_alerts feed (R3.2)
        got = {r["k"] for r in self.db.q("SELECT DISTINCT COALESCE(canon, cls) AS k FROM io_diag")}
        self.assertEqual(got, {"task", "restart", "budget"})        # the errors really are those classes
        self.o.risk_feeds(self.now)
        self.assertEqual(self.rows("diagnosis"), [])

    def test_owners_are_kept_apart(self):
        self.fail(CRED, 3, owner=7)
        self.fail(CRED, 3, owner=8)
        self.o.risk_feeds(self.now)
        self.assertEqual(len(self.o.risks(7)), 1)
        self.assertEqual(len(self.o.risks(8)), 1)

    def test_accepted_row_stays_accepted_until_it_resolves(self):
        self.fail(CRED, 3)
        self.o.risk_feeds(self.now)
        rid = self.row("diag:comp:5:credential")["id"]
        self.o.risk_accept({"id": 7, "username": "owner"}, rid)
        self.fail(CRED, 1)
        self.o.risk_feeds(self.now)
        self.assertEqual(self.row("diag:comp:5:credential")["status"], "accepted")
        self.o.risk_feeds(self.now + o.RISK_WINDOW + 60)
        self.assertEqual(self.row("diag:comp:5:credential")["status"], "resolved")

    def test_a_feed_never_touches_a_readiness_row(self):
        self.o.risk_upsert(7, "readiness:comp:5:mw_task:1:docker:", {"state": "FAIL"}, title="docker not ready", mission="comp:5", source="readiness")
        self.fail(CRED, 3)
        self.o.risk_feeds(self.now)
        self.o.risk_feeds(self.now + o.RISK_WINDOW + 60)
        r = self.row("readiness:comp:5:mw_task:1:docker:")
        self.assertEqual((r["status"], r["seen"]), ("open", 1))

    def test_tick_runs_the_feeds_at_most_every_few_minutes(self):
        self.fail(CRED, 3)
        out = self.o.tick()
        self.assertEqual(out["risks"], 1)
        self.fail(CRED, 1)
        self.assertEqual(self.o.tick()["risks"], 0)                 # throttled: RISK_FEED_EVERY
        self.o._last_feeds -= o.RISK_FEED_EVERY + 1
        self.assertEqual(self.o.tick()["risks"], 1)

    # ---------- io_sbx ----------
    def test_sandbox_class_recurring_in_a_team_is_one_row_owned_by_the_team_account(self):
        self.sbx("The sandbox is busy (2 runs at once)", 3)
        self.o.risk_feeds(self.now)
        [r] = self.rows("sandbox")
        self.assertEqual((r["rkey"], r["mission"], r["layer"], r["owner_id"]), ("sbx:comp:5:busy", "comp:5", "execution", 7))
        for f in T8: self.assertTrue(r[f], f)
        self.assertEqual(r["evidence"]["n"], 3)
        self.assertEqual(self.o.risk_feeds(self.now), 0)
        self.o.risk_feeds(self.now + o.RISK_WINDOW + 60)
        self.assertEqual(self.row("sbx:comp:5:busy")["status"], "resolved")

    def test_sandbox_own_classes_and_orphans_stay_out(self):
        self.sbx("files come to 900 MB", 3)                         # too_large: the run's own input
        self.sbx("x", 3, status="timeout")                          # timeout: the run's own time
        self.sbx("The sandbox is busy", 3, comp=6)                  # team whose campaign is gone: no owner
        self.o.risk_feeds(self.now)
        self.assertEqual(self.rows("sandbox"), [])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_risks", one=True)["n"], 0)


    def test_axor_readiness_check_runs_are_not_team_sandbox_failures(self):
        """C3 (wave 2): AXoR's own check runs (W7) failing in the sandbox don't become the team's recurring sandbox failure; the team's
        own runs failing the same way still do (positive control). The name matches the one W7's probe writes."""
        from app import mission_ops
        self.assertIn(mission_ops.NET_CHECK_USER, o.RISK_SBX_NOT_TEAM)
        self.db.q("ALTER TABLE mw_sbx ADD COLUMN by_user TEXT")
        for _ in range(4):
            self.db.q("INSERT INTO mw_sbx (comp_id, task_id, status, error, started, by_user) VALUES (5, NULL, 'error', 'The sandbox is busy', ?, ?)",
                      (self.now, mission_ops.NET_CHECK_USER))
        self.o.diagnose_sandbox()
        self.o.risk_feeds(self.now)
        self.assertEqual(self.rows("sandbox"), [])
        for _ in range(3):
            self.db.q("INSERT INTO mw_sbx (comp_id, task_id, status, error, started, by_user) VALUES (5, 1, 'error', 'The sandbox is busy', ?, 'Morgan')", (self.now,))
        self.o.diagnose_sandbox()
        self.o.risk_feeds(self.now)
        [r] = self.rows("sandbox")
        self.assertEqual((r["rkey"], r["evidence"]["n"]), ("sbx:comp:5:busy", 3))


class Sources(FeedBase):
    """R3.2: hq_issues, ac_alerts, mo_alerts, mh_alerts. A row is open exactly while its source item is, so open counts per
    source equal direct SQL; organization rows have no owner of their own (ORG_OWNER) and no mission."""

    def setUp(self):
        super().setUp()
        q = self.db.q
        q("""CREATE TABLE hq_issues (id INTEGER PRIMARY KEY, key TEXT, agent TEXT, team TEXT, severity TEXT, title TEXT, detail TEXT, target TEXT,
             status TEXT DEFAULT 'open', seen INTEGER DEFAULT 1, last_seen REAL, resolved REAL, resolution TEXT, verdict TEXT, cause TEXT, recommendation TEXT)""")
        q("""CREATE TABLE ac_limits (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, scope TEXT, key TEXT, label TEXT, tokens INTEGER,
             period TEXT, mode TEXT DEFAULT 'stop')""")
        q("""CREATE TABLE ac_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, ref TEXT, label TEXT, period TEXT, level TEXT,
             spent INTEGER, tokens INTEGER, ts REAL)""")
        q("""CREATE TABLE mo_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, key TEXT, level TEXT, kind TEXT, title TEXT,
             detail TEXT, go TEXT, status TEXT DEFAULT 'open', first_seen REAL, last_seen REAL, resolved REAL)""")
        q("""CREATE TABLE mh_alerts (id INTEGER PRIMARY KEY, campaign_id INTEGER, key TEXT, level TEXT, title TEXT, detail TEXT,
             status TEXT DEFAULT 'open', once INTEGER DEFAULT 0, first_seen REAL, last_seen REAL, resolved REAL)""")
        self.admin = {"id": 7, "username": "owner", "role": "admin"}

    def open_by_source(self, uid=7, org=True):
        got = {}
        for r in self.o.risks(uid, status="open", org=org, limit=500): got[r["source"]] = got.get(r["source"], 0) + 1
        return got

    def test_hq_issues_are_organization_rows_open_while_the_issue_is(self):
        q = self.db.q
        q("INSERT INTO hq_issues (key, agent, team, severity, title, detail, status, seen) VALUES ('disk', 'server', 'infra', 'critical', 'Disk 95%', 'd', 'open', 2)")
        q("INSERT INTO hq_issues (key, agent, team, severity, title, detail, status) VALUES ('tls', 'edge', 'infra', 'warning', 'TLS expires', 'd', 'open')")
        q("INSERT INTO hq_issues (key, agent, team, severity, title, detail, status) VALUES ('old', 'edge', 'infra', 'warning', 'Old', 'd', 'resolved')")
        self.o.risk_feeds(self.now)
        rows = [r for r in self.o.risks(7, org=True) if r["source"] == "hq"]
        self.assertEqual(len(rows), q("SELECT COUNT(*) n FROM hq_issues WHERE status='open'", one=True)["n"])  # equals direct SQL
        for r in rows:
            self.assertEqual((r["owner_id"], r["mission"], r["layer"]), (o.ORG_OWNER, None, "execution"))
            for f in T8: self.assertTrue(r[f], f)
        self.assertEqual([r for r in self.o.risks(8) if r["source"] == "hq"], [])          # a member doesn't see them
        self.assertEqual(self.o.risk_feeds(self.now), 0)                                   # idempotent
        q("UPDATE hq_issues SET status='resolved', resolution='Cleaned /var/log', verdict='fixed' WHERE key='disk'")
        self.assertEqual(self.o.risk_feeds(self.now), 1)
        r = next(r for r in self.o.risks(7, org=True) if r["rkey"] == "hq:disk")
        self.assertEqual((r["status"], r["verification"]["source"]["resolution"]), ("resolved", "Cleaned /var/log"))

    def test_a_resolved_row_carries_its_own_issue_s_resolution_not_an_older_one_s(self):
        q = self.db.q
        q("INSERT INTO hq_issues (key, agent, team, severity, title, detail, status, resolution) VALUES ('disk', 'server', 'infra', 'warning', 'Disk', 'd', 'resolved', 'Cleared on its own.')")
        q("INSERT INTO hq_issues (key, agent, team, severity, title, detail, status) VALUES ('disk', 'server', 'infra', 'warning', 'Disk', 'd', 'open')")
        q("INSERT INTO hq_issues (key, agent, team, severity, title, detail, status, resolution) VALUES ('disk', 'server', 'infra', 'warning', 'Disk', 'd', 'resolved', 'A later one.')")
        self.o.risk_feeds(self.now)
        q("UPDATE hq_issues SET status='resolved', resolution='Cleaned /var/log' WHERE status='open'")
        self.o.risk_feeds(self.now)
        r = next(r for r in self.o.risks(7, org=True) if r["rkey"] == "hq:disk")
        self.assertEqual((r["status"], r["verification"]["source"]["resolution"]), ("resolved", "Cleaned /var/log"))

    def test_an_administrator_accepts_an_organization_row_a_member_cannot(self):
        self.db.q("INSERT INTO hq_issues (key, agent, team, severity, title, detail) VALUES ('tls', 'edge', 'infra', 'warning', 'TLS expires', 'd')")
        self.o.risk_feeds(self.now)
        rid = next(r["id"] for r in self.o.risks(7, org=True) if r["rkey"] == "hq:tls")
        with self.assertRaises(o.HTTPException) as e: self.o.risk_accept({"id": 8, "username": "m", "role": "user"}, rid)
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(self.o.risk_accept(self.admin, rid)["status"], "accepted")

    def test_budget_alerts_open_for_their_period_at_the_highest_level(self):
        q, today = self.db.q, __import__("datetime").date.fromtimestamp(self.now).isoformat()
        q("INSERT INTO ac_limits (id, owner_id, scope, key, label, tokens, period) VALUES (3, 7, 'team', 'comp:5', 'SN61', 1000, 'total')")
        q("INSERT INTO ac_alerts (owner_id, ref, label, period, level, spent, tokens) VALUES (7, 'cap', 'Daily cap', ?, 'warn', 800, 1000)", (today,))
        q("INSERT INTO ac_alerts (owner_id, ref, label, period, level, spent, tokens) VALUES (7, 'cap', 'Daily cap', ?, 'limit', 1000, 1000)", (today,))
        q("INSERT INTO ac_alerts (owner_id, ref, label, period, level, spent, tokens) VALUES (7, 'cap', 'Daily cap', '2020-01-01', 'limit', 1, 1)")
        q("INSERT INTO ac_alerts (owner_id, ref, label, period, level, spent, tokens) VALUES (7, 'limit:3', 'SN61', 'total', 'limit', 1000, 1000)")
        self.o.risk_feeds(self.now)
        got = {r["rkey"]: r for r in self.o.risks(7) if r["source"] == "budget"}
        self.assertEqual(set(got), {f"budget:cap:{today}", "budget:limit:3:total"})
        self.assertEqual(got[f"budget:cap:{today}"]["evidence"]["level"], "limit")
        self.assertEqual(self.o.risk_feeds(self.now), 0)
        q("UPDATE ac_limits SET tokens=5000 WHERE id=3")                                   # raised above the use that crossed it
        tomorrow = self.now + 86400 + 60
        self.o.risk_feeds(tomorrow)                                                        # and the day's period is over
        self.assertEqual([r for r in self.o.risks(7, status="open") if r["source"] == "budget"], [])

    def test_ops_and_campaign_alerts_follow_their_status(self):
        q = self.db.q
        q("INSERT INTO mo_alerts (user_id, key, level, kind, title, detail) VALUES (7, 'budget:5', 'stop', 'budget', 'SN61 out of budget', 'd')")
        q("INSERT INTO mo_alerts (user_id, key, level, kind, title, detail) VALUES (7, 'usd', 'info', 'budget', 'Spend note', 'd')")
        q("INSERT INTO mh_alerts (id, campaign_id, key, level, title, detail, status) VALUES (1, 1, 'app', 'critical', 'Miner failing', 'd', 'acked')")
        q("INSERT INTO mh_alerts (id, campaign_id, key, level, title, detail, status) VALUES (2, 1, 'leader:x', 'info', 'New leader', 'd', 'open')")
        q("INSERT INTO mh_alerts (id, campaign_id, key, level, title, detail, status) VALUES (3, 99, 'app', 'critical', 'Orphan', 'd', 'open')")
        self.o.risk_feeds(self.now)
        self.assertEqual(self.open_by_source(org=False), {"ops": 1, "campaign": 1})
        self.assertEqual(next(r for r in self.o.risks(7) if r["source"] == "ops")["mission"], "comp:5")   # budget:5 names team 5
        r = next(r for r in self.o.risks(7) if r["source"] == "campaign")
        self.assertEqual((r["rkey"], r["mission"], r["layer"], r["title"]), ("mh:1:app", None, "mission", "SN61: Miner failing"))
        for f in T8: self.assertTrue(r[f], f)
        q("UPDATE mo_alerts SET status='resolved' WHERE key='budget:5'")
        q("UPDATE mh_alerts SET status='resolved' WHERE id=1")
        self.assertEqual(self.o.risk_feeds(self.now), 2)
        self.assertEqual(self.open_by_source(org=False), {})
        q("INSERT INTO mo_alerts (user_id, key, level, kind, title, detail, first_seen) VALUES (7, 'budget:5', 'warn', 'budget', 'SN61 at 85%', 'd', 2)")
        self.o.risk_feeds(self.now)
        self.assertEqual(next(r for r in self.o.risks(7) if r["rkey"] == "mo:budget:5")["status"], "open")   # the same key again reopens

    def test_filters_by_source_and_scope(self):
        self.fail(CRED, 3)                                                                 # team row
        self.fail(QUOTA, 3, team=None)                                                     # owner row
        self.db.q("INSERT INTO hq_issues (key, agent, team, severity, title, detail) VALUES ('tls', 'edge', 'infra', 'warning', 'TLS', 'd')")
        self.o.risk_feeds(self.now)
        rk = lambda **kw: sorted(r["rkey"] for r in self.o.risks(7, org=True, **kw))
        self.assertEqual(rk(scope="organization"), ["hq:tls"])
        self.assertEqual(rk(scope="team"), ["diag:comp:5:credential"])
        self.assertEqual(rk(scope="owner"), ["diag:owner:quota"])
        self.assertEqual(rk(source="hq"), ["hq:tls"])
        self.assertEqual(rk(source="diagnosis"), ["diag:comp:5:credential", "diag:owner:quota"])


class NeverHolds(GateBase):
    """T-9: a feed's open row on a team doesn't change that team's readiness."""

    def test_open_feed_row_does_not_block_a_task(self):
        before = self.ready(["docker"], {})["state"]
        self.o.risk_upsert(self.ME_ID, "diag:comp:23:credential", {"n": 9}, mission="comp:23", source="diagnosis", title="x", critical=0)
        self.o.risk_upsert(self.ME_ID, "sbx:comp:23:image", {"n": 9}, mission="comp:23", source="sandbox", title="y", critical=0)
        self.assertEqual(self.ready(["docker"], {})["state"], before)
        self.assertEqual(before, "READY")

    @property
    def ME_ID(self):
        from test_mission_ref import ME
        return ME["id"]


if __name__ == "__main__":
    unittest.main()
