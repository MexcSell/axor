"""D-004 completion, milestone D4.1: one persistent Mission Control mission per competition team.

- Only the Owner (named in the deployment, AXOR_OWNERS) or an administrator the Owner delegated creates, configures, pauses,
  resumes and cancels one; nobody else, and no internal caller, can.
- Creation needs at least one external measure, makes no model call, starts no team work and sets no gateway limit.
- One open persistent mission per team, enforced by the database even under concurrent creates.
- Its status is "monitoring": the clock's one-shot path (queued / running) never picks it up; pausing is a flag, not the
  "paused" status; the team is never touched by any mission action; a deleted or closed team fails it, a paused team never does.
- History: a persistent mission with recorded cycles can't be deleted; it's never pruned; a measures change is a new version.
"""
import json, os, tempfile, threading, time, types, unittest
from unittest import mock

from fastapi import HTTPException
from pydantic import ValidationError

from app import missions, orchestrator
from app.auth import AuthDB

OWNER, ADMIN, USER, TEAM_ACCOUNT = 11, 12, 13, 14
WID = 22


def schema(q):
    q("CREATE TABLE IF NOT EXISTS mh_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, netuid INTEGER, mech INTEGER, keys TEXT)")
    q("""CREATE TABLE IF NOT EXISTS mw_comps (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT,
         paused INTEGER DEFAULT 0, autopilot INTEGER DEFAULT 0, goal TEXT, budget INTEGER, last_plan REAL)""")
    q("""CREATE TABLE IF NOT EXISTS mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, status TEXT, mission TEXT,
         created REAL, updated REAL)""")
    q("""CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, kind TEXT, status TEXT,
         started REAL, tokens INTEGER DEFAULT 0, mission TEXT)""")


def measures(external=1, internal=0):
    out = [{"id": f"rank{i}", "text": f"Rank in the top 10 ({i})", "tier": "external", "source": "chain", "metric": "rank", "op": "<=", "target": 10}
           for i in range(external)]
    out += [{"id": f"bench{i}", "text": f"Frozen-suite score at least 0.8 ({i})", "tier": "internal", "source": "bench", "metric": "score",
             "op": ">=", "target": 0.8} for i in range(internal)]
    return out


class Forbidden:
    """A stand-in that fails the test on any use: team work (plan, cancel, start) and model calls must never happen."""
    def __init__(self, what): self.what = what
    def __getattr__(self, name): raise AssertionError(f"{self.what}.{name} was called")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "a.db")
        self.db = AuthDB(self.path)
        schema(self.db.q)
        for uid, name, role in ((OWNER, "the-owner", "admin"), (ADMIN, "admin-two", "admin"), (USER, "plain-user", "user"), (TEAM_ACCOUNT, "team-acct", "user")):
            self.db.q("INSERT INTO users (id, username, email, pw_hash, created, role) VALUES (?,?,?,?,?,?)", (uid, name, f"{name}@example.invalid", "x", time.time(), role))
        self.db.q("INSERT INTO mh_campaigns (id, user_id, netuid, mech, keys) VALUES (1, ?, 62, 0, ?)", (TEAM_ACCOUNT, json.dumps(["5Hot", "5Cold"])))
        self.db.q("INSERT INTO mw_comps (id, campaign_id, number, name, status, paused) VALUES (?, 1, 28, 'Ridges', 'active', 1)", (WID,))
        self.db.q("INSERT INTO mw_tasks (comp_id, title, status, created, updated) VALUES (?, 'Team work', 'todo', ?, ?)", (WID, time.time(), time.time()))
        self.db.q("INSERT INTO mw_runs (comp_id, kind, status, started) VALUES (?, 'report', 'done', ?)", (WID, time.time()))
        orchestrator.init(self.db)  # the real snapshot (io_datasets) and event tables; init starts no thread
        self.env = mock.patch.dict(os.environ, {"AXOR_OWNERS": "the-owner"}); self.env.start()
        self.mx = self.missions(self.db)

    def missions(self, db):
        mx = missions.Missions(db, hub=Forbidden("hub"), wf=None, ia=None, mw=Forbidden("mw"))
        mx._ask = Forbidden("model")  # no model call anywhere on these paths
        return mx

    def tearDown(self):
        self.env.stop()
        orchestrator._orc = None
        self.dir.cleanup()

    def me(self, uid): return dict(self.db.q("SELECT id, username, role FROM users WHERE id=?", (uid,), one=True))

    def team_state(self):
        return [self.db.q(f"SELECT * FROM {t} ORDER BY id") for t in ("mw_comps", "mw_tasks", "mw_runs", "mh_campaigns")]

    def create(self, uid=OWNER, **kw):
        p = {"team": WID, "objective": "Reach the top 10 on SN62 competition 28", "measures": measures(), "attested_keys": []} | kw
        return self.mx.create(self.me(uid), missions.MissionIn(goal="unused for persistent missions", persistent=missions.PersistentIn(**p)))

    def row(self, mid): return self.mx._m(mid)


class Ownership(Base):
    def test_the_owner_creates_it_under_the_teams_account_without_touching_the_team(self):
        before = self.team_state()
        st = self.create()["mission"]
        m = self.row(st["id"])
        self.assertEqual((m["status"], m["stage"], m["engine"], m["team"], m["persistent_team"]), ("monitoring", "execute", "mining", WID, WID))
        self.assertEqual(m["user_id"], TEAM_ACCOUNT)  # K-30: the team's account owns the row
        self.assertTrue(m["understanding"]["persistent"])
        self.assertEqual(self.team_state(), before)  # no plan, no task, no run, no team setting
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_links", one=True)["n"], 0)  # no correlation link: the team's runs stay the team's
        if self.mx._has_t("ac_limits"): self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_limits", one=True)["n"], 0)

    def test_nobody_else_can_create_it(self):
        for uid in (ADMIN, USER, TEAM_ACCOUNT):
            with self.assertRaises(HTTPException) as e: self.create(uid)
            self.assertEqual(e.exception.status_code, 403)

    def test_without_a_designated_owner_nobody_can(self):
        with mock.patch.dict(os.environ, {"AXOR_OWNERS": ""}):
            with self.assertRaises(HTTPException) as e: self.create(OWNER)
            self.assertEqual(e.exception.status_code, 403)

    def test_a_delegate_can_while_an_active_administrator(self):
        self.mx.set_delegates(self.me(OWNER), missions.DelegatesIn(user_ids=[ADMIN]))
        st = self.create(ADMIN)["mission"]
        self.mx.cancel(self.me(ADMIN), st["id"])
        self.db.q("UPDATE users SET role='user' WHERE id=?", (ADMIN,))  # demoted: the delegation no longer works
        with self.assertRaises(HTTPException) as e: self.create(ADMIN)
        self.assertEqual(e.exception.status_code, 403)

    def test_only_the_owner_delegates_and_only_administrators(self):
        with self.assertRaises(HTTPException) as e: self.mx.set_delegates(self.me(ADMIN), missions.DelegatesIn(user_ids=[ADMIN]))
        self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(HTTPException) as e: self.mx.set_delegates(self.me(OWNER), missions.DelegatesIn(user_ids=[USER]))
        self.assertEqual(e.exception.status_code, 400)

    def test_the_teams_account_reads_it_but_cant_change_it(self):
        mid = self.create()["mission"]["id"]
        self.assertEqual(self.mx.state(self.me(TEAM_ACCOUNT), mid)["mission"]["id"], mid)
        for act in (lambda: self.mx.pause(self.me(TEAM_ACCOUNT), mid), lambda: self.mx.cancel(self.me(TEAM_ACCOUNT), mid),
                    lambda: self.mx.patch(self.me(TEAM_ACCOUNT), mid, missions.PatchIn(cycle_hours=12))):
            with self.assertRaises(HTTPException) as e: act()
            self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(HTTPException) as e: self.mx.state(self.me(USER), mid)
        self.assertEqual(e.exception.status_code, 404)

    def test_the_owner_sees_it_on_their_home(self):
        mid = self.create()["mission"]["id"]
        self.mx._teams = lambda uid: []
        self.mx._engines = lambda uid: {k: False for k in missions.ENGINES}
        self.mx.requests = lambda me: {"requests": []}
        self.assertIn(mid, [r["id"] for r in self.mx.home(self.me(OWNER))["missions"]])

    def test_no_internal_caller_can_make_one(self):
        root = os.path.join(os.path.dirname(missions.__file__))
        for f in ("control_hub.py", "team_eval.py", "mission_link.py", "orchestrator.py"):
            with open(os.path.join(root, f)) as fh: src = fh.read()
            self.assertNotIn("persistent=", src, f)
            self.assertNotIn("PersistentIn", src, f)


class Validation(Base):
    def test_an_external_measure_is_required(self):
        with self.assertRaises(HTTPException) as e: self.create(measures=measures(external=0, internal=1))
        self.assertEqual(e.exception.status_code, 400)

    def test_at_most_six_measures(self):
        with self.assertRaises(ValidationError): missions.PersistentIn(team=WID, objective="Reach the top 10 on SN62", measures=measures(external=7))

    def test_a_source_fits_its_tier_and_ids_are_unique(self):
        bad = measures(); bad[0]["source"] = "bench"
        with self.assertRaises(HTTPException): self.create(measures=bad)
        with self.assertRaises(HTTPException): self.create(measures=measures() + measures())

    def test_attested_keys_come_from_the_teams_campaign(self):
        with self.assertRaises(HTTPException) as e: self.create(attested_keys=["5Stranger"])
        self.assertEqual(e.exception.status_code, 400)
        m = self.row(self.create(attested_keys=["5Cold"])["mission"]["id"])
        self.assertEqual([k["key"] for k in m["understanding"]["attested_keys"]], ["5Cold"])
        self.assertEqual(m["understanding"]["attested_keys"][0]["by"], "the-owner")


class Uniqueness(Base):
    def test_one_open_persistent_mission_per_team(self):
        self.create()
        with self.assertRaises(HTTPException) as e: self.create()
        self.assertEqual(e.exception.status_code, 409)

    def test_concurrent_creates_leave_exactly_one(self):
        got, gate = [], threading.Barrier(2)
        def go():
            db = AuthDB(self.path)  # one connection per thread, as two server workers would have
            mx = self.missions(db)
            me = dict(db.q("SELECT id, username, role FROM users WHERE id=?", (OWNER,), one=True))
            p = missions.PersistentIn(team=WID, objective="Reach the top 10 on SN62 competition 28", measures=measures())
            mx.db.q("SELECT 1")  # warm the connection before the race
            gate.wait()
            try: got.append(mx.create(me, missions.MissionIn(goal="unused for persistent missions", persistent=p))["mission"]["id"])
            except HTTPException as e: got.append(e.status_code)
        ts = [threading.Thread(target=go) for _ in range(2)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(sorted(type(x).__name__ for x in got), ["int", "int"])
        self.assertEqual(sum(1 for x in got if x == 409), 1, got)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_missions WHERE persistent_team=?", (WID,), one=True)["n"], 1)

    def test_a_refused_create_never_blocks_another_connections_writes(self):
        """The loser of the race must not keep a write transaction open (SQLite): the winner's follow-up writes go through."""
        other = AuthDB(self.path)
        st = self.create()["mission"]
        with self.assertRaises(Exception):  # the unique index refuses a second row for the team on the other connection
            other.q("INSERT INTO mx_missions (user_id, title, status, persistent_team, created, updated) VALUES (?,?,?,?,?,?)",
                    (TEAM_ACCOUNT, "dup", "monitoring", WID, time.time(), time.time()))
        t0 = time.time()
        self.mx._set(st["id"], updated=time.time())  # would wait the 5-second lock timeout and fail if the transaction stayed open
        self.assertLess(time.time() - t0, 1.0)

    def test_ending_it_frees_the_slot_and_the_reconcile_frees_one_an_older_release_ended(self):
        mid = self.create()["mission"]["id"]
        self.mx.cancel(self.me(OWNER), mid)
        self.assertIsNone(self.row(mid)["persistent_team"])
        mid2 = self.create()["mission"]["id"]
        self.db.q("UPDATE mx_missions SET status='cancelled' WHERE id=?", (mid2,))  # what an older release's cancel leaves
        self.mx._reconcile_persistent()
        self.assertIsNone(self.row(mid2)["persistent_team"])
        self.create()


class Lifecycle(Base):
    def test_the_one_shot_clock_never_picks_it_up(self):
        mid = self.create()["mission"]["id"]
        self.mx._submit = Forbidden("submit")
        self.mx._watch = Forbidden("_watch")  # the one-shot watch (budget, deadline, _child, _recover)
        before, row = self.team_state(), self.row(mid)
        for _ in range(3): self.mx.tick()
        after = self.row(mid)
        self.assertEqual((after["status"], after["stage"], after["attempts"], after["child"]), (row["status"], row["stage"], row["attempts"], row["child"]))
        self.assertEqual(self.team_state(), before)
        self.assertNotIn("monitoring", missions.ACTIVE)  # not counted by the per-user cap

    def test_a_paused_team_never_fails_it_a_deleted_or_closed_team_does(self):
        mid = self.create()["mission"]["id"]
        self.mx.tick()
        self.assertEqual(self.row(mid)["status"], "monitoring")  # the team is paused (paused=1): nothing happens
        self.db.q("UPDATE mw_comps SET status='closed' WHERE id=?", (WID,))
        self.mx.tick()
        m = self.row(mid)
        self.assertEqual((m["status"], m["persistent_team"]), ("failed", None))

    def test_pause_and_resume_are_a_flag_and_leave_the_team_alone(self):
        mid = self.create()["mission"]["id"]
        before = self.team_state()
        self.mx.pause(self.me(OWNER), mid)
        m = self.row(mid)
        self.assertEqual((m["status"], m["understanding"]["evaluation_paused"]), ("monitoring", True))
        self.mx.resume(self.me(OWNER), mid)
        self.assertFalse(self.row(mid)["understanding"]["evaluation_paused"])
        self.assertEqual(self.team_state(), before)

    def test_cancel_lists_its_own_tasks_but_never_cancels_team_work(self):
        mid = self.create()["mission"]["id"]
        self.db.q("INSERT INTO mw_tasks (comp_id, title, status, mission, created, updated) VALUES (?, 'Its own', 'working', ?, ?, ?)",
                  (WID, f"mx:{mid}", time.time(), time.time()))
        before = self.team_state()
        self.mx.cancel(self.me(OWNER), mid)  # mw is Forbidden: a cancel call would fail the test
        self.assertEqual(self.row(mid)["status"], "cancelled")
        self.assertEqual(self.team_state(), before)

    def test_deliver_waits_for_d44_and_delete_keeps_history(self):
        mid = self.create()["mission"]["id"]
        # D4.3 (spec A.2): "deliver now" asks for a final cycle, whose decision raises a confirmation request; delivery itself is
        # still D4.4, so the mission stays monitoring
        st = self.mx.deliver_now(self.me(OWNER), mid)["mission"]
        self.assertEqual((st["status"], st["persistent"]["final_requested"]["by"]), ("monitoring", "the-owner"))
        with self.assertRaises(HTTPException) as e: self.mx.delete(self.me(OWNER), mid)
        self.assertEqual(e.exception.status_code, 409)  # open
        self.mx.cancel(self.me(OWNER), mid)
        orchestrator.get().emit(TEAM_ACCOUNT, "mission.cycle", f"mx:{mid}:cycle:1", corr=f"mx:{mid}", status="done")
        with self.assertRaises(HTTPException) as e: self.mx.delete(self.me(OWNER), mid)
        self.assertEqual(e.exception.status_code, 409)  # cycles recorded: kept
        mid2 = self.create()["mission"]["id"]
        self.mx.cancel(self.me(OWNER), mid2)
        self.mx.delete(self.me(OWNER), mid2, "")  # no cycles yet: may go

    def test_it_is_never_pruned(self):
        mid = self.create()["mission"]["id"]
        self.mx.cancel(self.me(OWNER), mid)
        with mock.patch.object(missions, "MAX_MISSIONS", 0): self.mx._prune(TEAM_ACCOUNT)
        self.assertEqual(self.row(mid)["status"], "cancelled")


class Configuration(Base):
    def test_a_measures_change_is_a_new_version_and_the_old_one_stays(self):
        mid = self.create()["mission"]["id"]
        v1 = self.row(mid)["understanding"]["measures_version"]
        old = dict(self.db.q("SELECT * FROM io_datasets WHERE id=?", (v1["id"],), one=True))
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(measures=[missions.MeasureIn(**x) for x in measures(external=1, internal=1)]))
        v2 = self.row(mid)["understanding"]["measures_version"]
        self.assertGreater(v2["version"], v1["version"])
        self.assertEqual(dict(self.db.q("SELECT * FROM io_datasets WHERE id=?", (v1["id"],), one=True)), old)

    def test_no_gateway_budget_or_autonomy_on_a_persistent_mission(self):
        mid = self.create()["mission"]["id"]
        with self.assertRaises(HTTPException) as e: self.mx.patch(self.me(OWNER), mid, missions.PatchIn(budget=5))
        self.assertEqual(e.exception.status_code, 400)

    def test_one_shot_missions_refuse_persistent_fields(self):
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, status, stage, created, updated) VALUES (?, 't', 'g', 3, 'running', 'plan', ?, ?)
                           RETURNING id""", (OWNER, time.time(), time.time()), one=True)["id"]
        with self.assertRaises(HTTPException) as e: self.mx.patch(self.me(OWNER), mid, missions.PatchIn(cycle_hours=12))
        self.assertEqual(e.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
