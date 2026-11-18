"""D-006 / gap G-02 (docs/architecture/stabilization): a board task carries the mission it works for, and Mission Control reads its
work by that ref, never by "every team task made since the attempt started".

- The lead's plan for a mission stamps every task it makes; an agent's follow-ups and a left-out task added back inherit it.
- A plan that repeats an open task of the team's own adopts that task for the mission (it isn't left with nothing and failed).
- Work the team makes in the same hours (Autoloop, the Director, another mission) is never the mission's: not counted, not
  collected for review, not cancelled with it; and cancelling stops only what the mission's own attempt put on the board.
- Control Hub tasks reach the board with their mission and get back the id of the task made, not one found by its title.
"""
import json, os, tempfile, threading, time, types, unittest

from fastapi import HTTPException

from app import control_missions, mining_release, mining_work, missions
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
WID = 3


def board_schema(q):
    q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, netuid INTEGER, mech INTEGER)")
    q("""CREATE TABLE mw_comps (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT, goal TEXT,
         budget INTEGER, last_plan REAL)""")
    q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, priority TEXT,
         agent_id INTEGER, due TEXT, origin TEXT, summary TEXT, result TEXT, created REAL, updated REAL, mission TEXT, note TEXT)""")  # note: as the real table
    q("""CREATE TABLE mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, agent_id INTEGER, kind TEXT, status TEXT,
         started REAL, finished REAL, tokens INTEGER DEFAULT 0, feedback TEXT, mission TEXT)""")
    q("""CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT, lead INTEGER DEFAULT 0,
         active INTEGER DEFAULT 1, head INTEGER DEFAULT 0, squad TEXT)""")
    q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY, comp_id INTEGER, path TEXT, content TEXT)")
    q("""CREATE TABLE mw_skipped (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, priority TEXT, agent_id INTEGER,
         origin TEXT, by_name TEXT, dup_of INTEGER, ts REAL, restored REAL, restored_by TEXT, restored_task INTEGER)""")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        board_schema(self.db.q)
        self.db.q("INSERT INTO mh_campaigns (id, user_id, netuid, mech) VALUES (1, ?, 62, 0)", (ME["id"],))
        self.db.q("INSERT INTO mw_comps (id, campaign_id, number, name, status, goal) VALUES (?, 1, 28, 'Ridges 28', 'active', 'Top 10')", (WID,))
        self.agents = [{"id": 1, "name": "Gus", "lead": 1, "active": 1, "head": 0, "squad": None, "title": "Director", "job": "Leads"},
                       {"id": 2, "name": "Devon", "lead": 0, "active": 1, "head": 0, "squad": None, "title": "Engineer", "job": "Builds"}]
        for x in self.agents:
            self.db.q("INSERT INTO mw_agents (id, comp_id, name, title, job, lead, active) VALUES (?,?,?,?,?,?,1)",
                      (x["id"], WID, x["name"], x["title"], x["job"], x["lead"]))
        self.w = self.work()

    def tearDown(self): self.dir.cleanup()

    def work(self):
        """A mining_work.Work with the real board code (plan, add task, follow-ups) and stand-ins for the model and the feed."""
        w = object.__new__(mining_work.Work)
        w.db, w.lock, w.loop, w.cancels = self.db, threading.Lock(), None, set()
        w.plan_out = {"summary": "Plan", "tasks": []}
        llm = types.SimpleNamespace(structured=lambda model, system, prompt, schema, name, **kw: w.plan_out)
        w.m = types.SimpleNamespace(_campaign=lambda cid: {"id": 1, "user_id": ME["id"], "netuid": 62}, hub=types.SimpleNamespace(llm=llm),
                                    _title=lambda c: "Ridges", _owner=lambda c: ME)
        w.web = types.SimpleNamespace(lead_note=lambda w_, me: "")
        w.pool = types.SimpleNamespace(submit=lambda fn, *a: fn(*a))  # the plan runs inline
        w._own = lambda me, wid: (w._comp(wid), {"id": 1, "user_id": ME["id"]})
        w._agents = lambda wid: self.agents
        w._model = lambda c, a, *k: "fake:model"
        w._over = lambda wid: False
        w._event = lambda *a, **k: None
        w.view = lambda me, wid: {"ok": True}
        w._context = lambda w_, c: ("", None)
        w._team = lambda wid, me_id=None: ""
        w._directive = lambda w_, a=None, note="": note
        w._recall = lambda w_, a: ""
        w._said = lambda *a, **k: None
        w._span = lambda *a, **k: None
        w._enqueue = lambda tid, *a, **k: False
        w._kick = lambda wid: None
        w._end = lambda c, rid, status, *a, **k: self.db.q("UPDATE mw_runs SET status=? WHERE id=?", (status, rid))
        return w

    def task(self, title, status="todo", mission=None, created=None, origin="you"):
        now = created or time.time()
        return self.db.q("""INSERT INTO mw_tasks (comp_id, title, detail, status, priority, origin, created, updated, mission)
                            VALUES (?,?,'',?,'medium',?,?,?,?) RETURNING id""", (WID, title, status, origin, now, now, mission), one=True)["id"]

    def plan(self, titles, mission=None):
        self.w.plan_out = {"summary": "Plan", "tasks": [{"title": t, "detail": "", "assignee": "Devon", "priority": "high"} for t in titles]}
        return self.w.plan(ME, WID, mining_work.PlanIn(note="Mission note", start=True, mission=mission))

    def missions_of(self):
        return {r["title"]: r["mission"] for r in self.db.q("SELECT title, mission FROM mw_tasks ORDER BY id")}


class Stamping(Base):
    def test_a_missions_plan_stamps_its_tasks_and_the_teams_plan_doesnt(self):
        self.plan(["Profile the scorer", "Write the harness"], mission="mx:5")
        self.plan(["Rotate the logs"])  # the autopilot's or the user's plan: the team's own work
        self.assertEqual(self.missions_of(), {"Profile the scorer": "mx:5", "Write the harness": "mx:5", "Rotate the logs": None})
        self.assertEqual(self.db.q("SELECT mission FROM mw_runs WHERE kind='plan' ORDER BY id", ()), [{"mission": "mx:5"}, {"mission": None}])

    def test_the_teams_own_mission_is_stored_as_null_and_read_as_comp(self):
        self.plan(["Rotate the logs"], mission=f"comp:{WID}")
        t = self.db.q("SELECT * FROM mw_tasks", one=True)
        self.assertIsNone(t["mission"])
        self.assertEqual(mining_work.mission_ref(t), f"comp:{WID}")
        self.assertEqual(mining_work.mission_ref({"comp_id": WID, "mission": "mx:5"}), "mx:5")

    def test_follow_ups_and_restored_tasks_inherit_the_mission(self):
        self.plan(["Profile the scorer"], mission="mx:5")
        parent = self.db.q("SELECT id FROM mw_tasks", one=True)["id"]
        self.w._followups(self.w._comp(WID), self.agents[1], parent, [{"title": "Profile the tokenizer", "assignee": "Devon"}])
        self.w._followups(self.w._comp(WID), self.agents[1], None, [{"title": "Tidy the notes"}])  # not from a task: the team's
        self.assertEqual(self.missions_of()["Profile the tokenizer"], "mx:5")
        self.assertIsNone(self.missions_of()["Tidy the notes"])
        rid = self.db.q("SELECT id FROM mw_runs WHERE kind='plan'", one=True)["id"]
        sid = self.db.q("""INSERT INTO mw_skipped (comp_id, title, detail, priority, origin, dup_of, ts) VALUES (?,?,?,?,?,?,?) RETURNING id""",
                        (WID, "Profile the scorer again", "", "medium", f"plan:{rid}", parent, time.time()), one=True)["id"]
        mining_release.Release(self.w).restore(ME, WID, sid)
        self.assertEqual(self.missions_of()["Profile the scorer again"], "mx:5")

    def test_a_repeat_of_an_open_team_task_is_adopted_not_lost(self):
        own = self.task("Profile the scorer")  # the team's own, open
        other = self.task("Write the harness", mission="mx:9")  # another mission's
        self.plan(["Profile the scorer", "Write the harness"], mission="mx:5")
        rows = {r["id"]: r["mission"] for r in self.db.q("SELECT id, mission FROM mw_tasks")}
        self.assertEqual(rows, {own: "mx:5", other: "mx:9"})  # adopted; never taken from another mission

    def test_no_stamping_while_the_lead_is_already_planning(self):
        self.db.q("INSERT INTO mw_runs (comp_id, agent_id, kind, status, started) VALUES (?, 1, 'plan', 'running', ?)", (WID, time.time()))
        with self.assertRaises(HTTPException) as e: self.plan(["Profile the scorer"], mission="mx:5")
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_tasks", one=True)["n"], 0)

    def test_the_board_shows_every_tasks_mission(self):
        self.task("Team work")
        self.task("Mission work", mission="mx:5")
        rows = self.db.q("SELECT * FROM mw_tasks ORDER BY id")
        self.assertEqual([mining_work.mission_ref(t) for t in rows], [f"comp:{WID}", "mx:5"])

    def test_add_task_returns_the_task_made_with_its_mission(self):
        a = self.w._add_task(ME, WID, mining_work.TaskIn(title="Same title", mission="mx:5"))
        b = self.w._add_task(ME, WID, mining_work.TaskIn(title="Same title"))
        self.assertNotEqual(a, b)
        self.assertEqual([r["mission"] for r in self.db.q("SELECT mission FROM mw_tasks ORDER BY id")], ["mx:5", None])
        with self.assertRaises(Exception): mining_work.TaskIn(title="Bad ref", mission="mx:5; DROP TABLE")


class ToBoard(Base):
    def test_a_control_hub_task_goes_to_the_board_with_its_mission_and_its_own_id(self):
        self.task("Check validator weights")  # an older task with the same title: a title match could pick the wrong one
        ch = types.SimpleNamespace(w=self.w, _view=lambda me: {"units": [{"id": 1}]}, _comps=lambda uid: {WID: {}}, _comp_of=lambda u: WID)
        r = {"unit_id": 1, "mission": f"comp:{WID}", "title": "Check validator weights", "detail": "", "priority": "high"}
        bid = control_missions._to_board(ch, ME, r)
        self.assertEqual(bid, self.db.q("SELECT MAX(id) i FROM mw_tasks", one=True)["i"])
        self.assertIsNone(self.db.q("SELECT mission FROM mw_tasks WHERE id=?", (bid,), one=True)["mission"])  # the team's own
        bid2 = control_missions._to_board(ch, ME, dict(r, mission="mx:5", title="Benchmark the candidate"))
        self.assertEqual(self.db.q("SELECT mission FROM mw_tasks WHERE id=?", (bid2,), one=True)["mission"], "mx:5")
        bid3 = control_missions._to_board(ch, ME, dict(r, mission="none", title="Rotate the logs"))  # a standalone task: no mission ref
        self.assertIsNone(self.db.q("SELECT mission FROM mw_tasks WHERE id=?", (bid3,), one=True)["mission"])


class MissionControl(Base):
    """missions.Missions on engine "mining": what it counts, collects and cancels is the mission's own work only."""
    def setUp(self):
        super().setUp()
        self.cancelled = []
        mw = types.SimpleNamespace(cancel=lambda me, tid: self.cancelled.append(tid), plan=lambda *a, **k: None)
        self.mx = missions.Missions(self.db, hub=None, wf=None, ia=None, mw=mw)
        self.mx._owner = lambda uid: ME
        now = time.time()
        self.started = now - 600
        self.mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, status, stage, engine, team, child, child_started, created, updated)
                                VALUES (?,?,?,?,'running','execute','mining',?,?,?,?,?) RETURNING id""",
                             (ME["id"], "Raise the score", "Raise the score", 5.0, WID, WID, self.started, now, now), one=True)["id"]
        self.ref = f"mx:{self.mid}"

    def m(self): return self.mx._m(self.mid)

    def test_only_the_missions_tasks_count_and_are_collected(self):
        mine = self.task("Benchmark the candidate", status="working", mission=self.ref)
        self.task("Autoloop's follow-up", status="working")  # the team's own, made in the same window
        self.task("Another mission's task", status="done", mission="mx:99")
        st, tok, err = self.mx._child(self.m())
        self.assertEqual(st, "running")
        d = self.mx._collect(self.m())
        self.assertEqual([x["title"] for x in d["items"]], ["Benchmark the candidate"])
        self.assertEqual(self.mx._progress(self.m())["outputs"], 0)
        self.db.q("UPDATE mw_tasks SET status='done' WHERE id=?", (mine,))
        self.assertEqual(self.mx._child(self.m())[0], "done")  # the team's open task doesn't keep the mission running
        self.assertEqual(self.mx._progress(self.m())["outputs"], 1)

    def test_tokens_are_the_missions_runs_and_its_plan_only(self):
        mine = self.task("Benchmark the candidate", status="working", mission=self.ref)
        team = self.task("Autoloop's follow-up", status="working")
        now = time.time()
        for task, kind, mission, tokens in ((mine, "task", None, 100), (team, "task", None, 5000), (None, "plan", self.ref, 20), (None, "plan", None, 7000)):
            self.db.q("INSERT INTO mw_runs (comp_id, task_id, kind, status, started, tokens, mission) VALUES (?,?,?,'done',?,?,?)", (WID, task, kind, now, tokens, mission))
        self.assertEqual(self.mx._child(self.m())[1], 120)

    def test_a_plan_for_another_purpose_doesnt_count_as_the_missions_planning(self):
        self.db.q("INSERT INTO mw_runs (comp_id, kind, status, started) VALUES (?, 'plan', 'running', ?)", (WID, time.time()))  # the autopilot's
        self.db.q("UPDATE mx_missions SET child_started=? WHERE id=?", (time.time() - 3600, self.mid))
        st, _, err = self.mx._child(self.m())
        self.assertEqual(st, "failed")
        self.assertIn("planned no tasks", err)

    def test_cancelling_stops_only_what_the_missions_attempt_put_on_the_board(self):
        made = self.task("Benchmark the candidate", status="working", mission=self.ref)
        adopted = self.task("Profile the scorer", status="working", mission=self.ref, created=self.started - 3600)  # open before the mission
        self.task("Autoloop's follow-up", status="working")
        self.task("Another mission's task", status="queued", mission="mx:99")
        self.mx._stop_child(self.m())
        self.assertEqual(self.cancelled, [made])
        self.assertNotIn(adopted, self.cancelled)


class Launch(Base):
    def test_the_mission_hands_its_ref_to_the_teams_plan(self):
        got = []
        mw = types.SimpleNamespace(plan=lambda me, wid, b: got.append((wid, b.mission, b.start)))
        mx = missions.Missions(self.db, hub=None, wf=None, ia=None, mw=mw)
        mx._owner = lambda uid: ME
        mx.att = types.SimpleNamespace(digest=lambda mid, room: "", rows=lambda mid: [])
        now = time.time()
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, status, stage, engine, team, created, updated, understanding, allocation, plan)
                           VALUES (?,?,?,?,'running','execute','mining',?,?,?,?,?,?) RETURNING id""",
                        (ME["id"], "Raise the score", "Raise the score", 5.0, WID, now, now, json.dumps({"objective": "Top 10", "criteria": ["Score measured"]}),
                         json.dumps({"price": 0}), json.dumps({"brief": "Do it"})), one=True)["id"]
        self.assertEqual(mx._launch(mx._m(mid)), "running")
        self.assertEqual(got, [(WID, f"mx:{mid}", True)])


if __name__ == "__main__":
    unittest.main()
