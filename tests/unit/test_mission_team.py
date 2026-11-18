"""missions.py + mission_link.py: a mission that belongs on a Competition team asks for one instead of falling back silently;
the hash-bound team request (approve creates exactly that team, a team of yours, or go on without), its expiry, and the command map."""
import hashlib, json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import mission_link, missions
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
U = {"title": "Improve the SN62 miner", "objective": "Raise the miner's score.", "targets": ["Score up"], "criteria": ["A benchmark against the baseline"],
     "questions": [], "engine": "mining", "engine_why": "Miner work.", "mining_team": 0, "mining_target": {"netuid": 0, "competition": 0},
     "gated_actions": [], "complexity": "medium", "hours": 2, "success": 60}


class FakeMining:
    def __init__(self, db): self.db, self.created = db, []
    def create(self, me, b, ip):
        cid = self.db.q("INSERT INTO mh_campaigns (user_id, netuid, mech) VALUES (?,?,?) RETURNING id", (me["id"], b.netuid, b.mechs[0]), one=True)["id"]
        self.created.append(b.netuid)
        return {"id": cid, "ids": [cid]}


class FakeWork:
    """The bits of mining_work.Work the mission uses: the user's teams, creating one, owning one."""
    def __init__(self, db): self.db, self.m, self.made = db, FakeMining(db), []
    def all(self, me):
        rows = self.db.q("""SELECT w.id, w.number, w.name, w.status, c.netuid FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id
                            WHERE c.user_id=? ORDER BY w.id""", (me["id"],))
        return {"comps": [{"id": r["id"], "label": r["name"] or f"Competition {r['number']}", "netuid": r["netuid"], "number": r["number"],
                           "subnet": "Ridges", "agents": 3, "status": r["status"]} for r in rows]}
    def create(self, me, cid, b, ip):
        wid = self.db.q("INSERT INTO mw_comps (campaign_id, number, name, status) VALUES (?,?,?,'active') RETURNING id", (cid, b.number, b.name), one=True)["id"]
        self.made.append((cid, b.number, b.team))
        return {"comp": {"id": wid}}
    def _own(self, me, wid):
        w = self.db.q("SELECT w.* FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE w.id=? AND c.user_id=?", (wid, me["id"]), one=True)
        if not w: raise HTTPException(404, "no such team")
        return w, None


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, netuid INTEGER, mech INTEGER)")
        q("""CREATE TABLE mw_comps (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT,
             autopilot INTEGER DEFAULT 0, paused INTEGER DEFAULT 0, relay INTEGER DEFAULT 1)""")
        q("""CREATE TABLE mw_agents (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, name TEXT, title TEXT, role TEXT, lead INTEGER DEFAULT 0,
             active INTEGER DEFAULT 1, squad TEXT, head INTEGER DEFAULT 0)""")
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, status TEXT, agent_id INTEGER, created REAL)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, agent_id INTEGER, kind TEXT, status TEXT, started REAL, tokens INTEGER DEFAULT 0)")
        self.work = FakeWork(self.db)
        self.mx = missions.Missions(self.db, hub=None, wf=object(), ia=None, mw=self.work)
        self.submitted = []
        self.mx._submit = self.submitted.append
        self.u = dict(U)
        self.mx._ask = lambda m, stage, schema, name, prompt, **kw: (json.loads(json.dumps(self.u)), "fake")

    def tearDown(self): self.dir.cleanup()

    def mission(self, goal="Improve my SN62 competition 28 miner and benchmark it", **kw):
        now = time.time()
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, constraints, status, stage, forced, team, created, updated)
                           VALUES (?,?,?,?,?,'running','understand',?,?,?,?) RETURNING id""",
                        (ME["id"], goal[:60], goal, 5.0, "", kw.get("forced"), kw.get("team"), now, now), one=True)["id"]
        self.mx._understand(self.mx._m(mid))
        return mid

    def team(self, netuid, number):
        c = self.db.q("INSERT INTO mh_campaigns (user_id, netuid, mech) VALUES (?,?,0) RETURNING id", (ME["id"], netuid), one=True)["id"]
        return self.db.q("INSERT INTO mw_comps (campaign_id, number, name, status) VALUES (?,?,?,'active') RETURNING id", (c, number, ""), one=True)["id"]

    def req(self, mid): return self.db.q("SELECT * FROM mx_requests WHERE mission_id=? ORDER BY id DESC", (mid,), one=True)

    def decide(self, mid, approve, **kw):
        r = self.req(mid)
        return self.mx.decide(ME, r["id"], missions.DecideIn(approve=approve, hash=kw.pop("hash", r["hash"]), **kw))

    def events(self, mid): return [e["text"] for e in self.db.q("SELECT text FROM mx_events WHERE mission_id=? ORDER BY id", (mid,))]


class Target(unittest.TestCase):
    def test_goal_words_first_then_model(self):
        self.assertEqual(mission_link.target("Improve my SN62 competition 28 miner"), {"netuid": 62, "number": 28})
        self.assertEqual(mission_link.target("subnet 8 work", {"mining_target": {"netuid": 3, "competition": 4}}), {"netuid": 8, "number": 4})
        self.assertEqual(mission_link.target("my miner", {"mining_target": {"netuid": 0, "competition": 0}}), {"netuid": None, "number": None})

    def test_match(self):
        teams = [{"id": 1, "netuid": 62, "number": 27}, {"id": 2, "netuid": 8, "number": None}]
        self.assertIsNone(mission_link.match(teams, {"netuid": 62, "number": 28}))   # another competition: not that team
        self.assertEqual(mission_link.match(teams, {"netuid": 62, "number": 27}), 1)
        self.assertEqual(mission_link.match(teams, {"netuid": 8, "number": None}), 2)
        self.assertIsNone(mission_link.match(teams, {"netuid": None, "number": None}))  # two teams, nothing named
        self.assertEqual(mission_link.match(teams[:1], {"netuid": None, "number": None}), 1)


class TeamRequest(Base):
    def test_no_team_asks_instead_of_falling_back(self):
        mid = self.mission()
        m, r = self.mx._m(mid), self.req(mid)
        self.assertEqual(m["status"], "needs_input")
        self.assertEqual(m["engine"], "mining")
        self.assertEqual(r["kind"], "team")
        self.assertEqual(r["status"], "pending")
        prop = m["understanding"]["team_request"]
        self.assertEqual((prop["netuid"], prop["number"], prop["campaign"]), (62, 28, None))
        self.assertIn("kickoff", r["action"])  # starting a campaign spends: the request says so up front
        self.assertEqual(r["artifact"], hashlib.sha256(missions._j(prop).encode()).hexdigest())
        self.assertIn("create a Competition team", self.mx._card(m)["doing"])
        with self.assertRaises(HTTPException) as e: self.mx.answer(ME, mid, missions.AnswerIn(answers=[]))
        self.assertEqual(e.exception.status_code, 409)

    def test_approve_creates_that_team_and_goes_on(self):
        mid = self.mission()
        self.decide(mid, True)
        m = self.mx._m(mid)
        self.assertEqual(self.work.m.created, [62])               # no SN62 campaign: one was started
        self.assertEqual(self.work.made[0][1:], (28, "auto"))     # competition 28, the pack Work picks
        self.assertEqual((m["engine"], m["status"], m["stage"]), ("mining", "running", "discover"))
        self.assertEqual(m["team"], self.db.q("SELECT id FROM mw_comps WHERE number=28", one=True)["id"])
        self.assertNotIn("team_request", m["understanding"])
        self.assertEqual(self.req(mid)["status"], "approved")
        self.assertEqual(self.submitted, [mid])
        self.assertTrue(any("created the Competition team" in t for t in self.events(mid)))

    def test_existing_campaign_is_reused(self):
        self.db.q("INSERT INTO mh_campaigns (user_id, netuid, mech) VALUES (?,?,0)", (ME["id"], 62))
        mid = self.mission()
        r = self.req(mid)
        self.assertNotIn("kickoff", r["action"])
        self.decide(mid, True)
        self.assertEqual(self.work.m.created, [])

    def test_decision_is_single_use_and_hash_bound(self):
        mid = self.mission()
        with self.assertRaises(HTTPException) as e: self.decide(mid, True, hash="0" * 64)
        self.assertEqual(e.exception.status_code, 409)
        self.decide(mid, False)
        with self.assertRaises(HTTPException) as e: self.decide(mid, True)
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(self.work.made, [])

    def test_tampered_proposal_is_refused(self):
        mid = self.mission()
        m = self.mx._m(mid)
        u = m["understanding"]; u["team_request"]["netuid"] = 1
        self.mx._set(mid, understanding=u)
        with self.assertRaises(HTTPException) as e: self.decide(mid, True)
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(self.req(mid)["status"], "pending")      # put back: still decidable once fixed
        self.assertEqual(self.work.made, [])

    def test_reject_runs_on_workforce_and_says_so(self):
        mid = self.mission()
        self.decide(mid, False)
        m = self.mx._m(mid)
        self.assertEqual((m["engine"], m["team"], m["status"]), ("workforce", None, "running"))
        self.assertTrue(any("declined the Competition team" in t and "Workforce" in t for t in self.events(mid)))
        self.assertEqual(self.work.made, [])

    def test_use_an_existing_team(self):
        other = self.team(62, 27)
        mid = self.mission()                                     # comp 28 named: the comp 27 team doesn't fit by itself
        self.assertEqual(self.req(mid)["kind"], "team")
        self.assertIn("already have 1 team on SN62", self.req(mid)["action"])
        self.decide(mid, False, team=other)
        m = self.mx._m(mid)
        self.assertEqual((m["engine"], m["team"]), ("mining", other))
        self.assertEqual(self.work.made, [])

    def test_model_pick_must_fit_what_the_goal_names(self):
        comp28 = self.team(62, 28)
        self.u["mining_team"] = comp28                            # the model picks the team it was shown
        mid = self.mission("Research how top miners score on SN62 competition 29")
        self.assertEqual(self.req(mid)["kind"], "team")           # not comp 28's team: comp 29 needs its own
        mid = self.mission("Improve my SN8 miner's latency")
        self.assertEqual(self.mx._m(mid)["understanding"]["team_request"]["netuid"], 8)
        mid = self.mission("Improve my miner")                    # nothing named: the model's pick stands
        self.assertEqual(self.mx._m(mid)["team"], comp28)

    def test_users_own_team_choice_stands(self):
        comp28 = self.team(62, 28)
        mid = self.mission("Research SN62 competition 29", team=comp28)
        self.assertEqual((self.mx._m(mid)["team"], self.req(mid)), (comp28, None))

    def test_matching_team_needs_no_request(self):
        wid = self.team(62, 28)
        mid = self.mission()
        m = self.mx._m(mid)
        self.assertEqual((m["engine"], m["team"], m["status"]), ("mining", wid, "running"))
        self.assertIsNone(self.req(mid))

    def test_no_subnet_named_falls_back_with_a_reason(self):
        mid = self.mission("Make my miner better than the top ones")
        m = self.mx._m(mid)
        self.assertEqual(m["engine"], "workforce")
        self.assertIsNone(self.req(mid))
        self.assertTrue(any("Name the subnet" in t for t in self.events(mid)))

    def test_questions_come_after_the_team(self):
        self.u["questions"] = ["Which baseline?"]
        mid = self.mission()
        self.decide(mid, True)
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["engine"]), ("needs_input", "mining"))
        self.assertEqual(self.submitted, [])
        self.mx.answer(ME, mid, missions.AnswerIn(answers=["The current one"]))
        self.assertEqual(self.mx._m(mid)["stage"], "discover")

    def test_expired_request_goes_on_without_a_team(self):
        mid = self.mission()
        self.db.q("UPDATE mx_requests SET expires=? WHERE mission_id=?", (time.time() - 1, mid))
        self.mx.tick()
        m = self.mx._m(mid)
        self.assertEqual((m["engine"], m["status"]), ("workforce", "running"))
        self.assertEqual(self.req(mid)["status"], "lapsed")
        self.assertTrue(any("Nobody decided" in t for t in self.events(mid)))
        self.mx.tick()                                            # only once
        self.assertEqual(sum("Nobody decided" in t for t in self.events(mid)), 1)


class CommandMap(Base):
    def test_chain_with_director_squads_and_states(self):
        wid = self.team(62, 28)
        q = self.db.q
        q("INSERT INTO mw_agents (comp_id, name, title, lead, squad, head) VALUES (?, 'Dara', 'Director', 1, 'command', 0)", (wid,))
        head = q("INSERT INTO mw_agents (comp_id, name, title, squad, head) VALUES (?, 'Eli', 'Eval lead', 'eval', 1) RETURNING id", (wid,), one=True)["id"]
        busy = q("INSERT INTO mw_agents (comp_id, name, title, squad) VALUES (?, 'Ivo', 'Tester', 'eval') RETURNING id", (wid,), one=True)["id"]
        q("INSERT INTO mw_agents (comp_id, name, title, squad, active) VALUES (?, 'Off', 'Spare', 'eval', 0)", (wid,))
        t = q("INSERT INTO mw_tasks (comp_id, title, status, agent_id) VALUES (?, 'Benchmark v2', 'working', ?) RETURNING id", (wid, busy), one=True)["id"]
        q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status) VALUES (?,?,?,'task','running')", (wid, t, busy))
        mid = self.mission()
        out = mission_link.command_map(self.mx, ME, mission=mid)
        self.assertEqual([x["id"] for x in out["missions"]], [mid])
        self.assertEqual(out["teams"][0]["director"]["name"], "Dara")
        eval_sq = next(s for s in out["teams"][0]["squads"] if s["key"] == "eval")
        self.assertEqual(eval_sq["head"]["id"], head)
        states = {a["name"]: a["state"] for a in eval_sq["agents"]}
        self.assertEqual(states, {"Ivo": "working", "Off": "off"})
        self.assertEqual(next(a for a in eval_sq["agents"] if a["name"] == "Ivo")["doing"], "Benchmark v2")
        self.assertEqual(next(e for e in out["engines"] if e["key"] == "mining")["missions"], [mid])

    def test_wanted_team_shows_and_others_teams_dont(self):
        mid = self.mission()
        out = mission_link.command_map(self.mx, ME)
        self.assertEqual(out["wanted"][0]["mission"], mid)
        self.assertEqual(out["wanted"][0]["netuid"], 62)
        self.assertEqual(out["you"]["requests"], 1)
        c = self.db.q("INSERT INTO mh_campaigns (user_id, netuid, mech) VALUES (99, 62, 0) RETURNING id", one=True)["id"]
        theirs = self.db.q("INSERT INTO mw_comps (campaign_id, number, name, status) VALUES (?, 1, 'x', 'active') RETURNING id", (c,), one=True)["id"]
        with self.assertRaises(HTTPException): mission_link.command_map(self.mx, ME, team=theirs)

    def test_a_teams_predefined_mission_is_drawn_without_a_custom_one(self):
        """The map read "No mission running" over a team at work: a predefined mission runs on the team's board, not in Mission Control."""
        wid, shut = self.team(62, 30), self.team(62, 29)
        q = self.db.q
        q("UPDATE mw_comps SET status='closed' WHERE id=?", (shut,))
        q("""CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission TEXT, kind TEXT, status TEXT, template TEXT)""")
        for kind, st in (("fixed", "todo"), ("fixed", "running"), ("dynamic", "review"), ("fixed", "done")):
            q("INSERT INTO ctl_tasks (user_id, mission, kind, status) VALUES (?,?,?,?)", (ME["id"], f"comp:{wid}", kind, st))
        q("CREATE TABLE ctl_briefs (task_id INTEGER PRIMARY KEY, user_id INTEGER, mission TEXT, state TEXT)")
        q("INSERT INTO ctl_briefs VALUES (1, ?, ?, 'running')", (ME["id"], f"comp:{wid}"))
        out = mission_link.command_map(self.mx, ME)
        self.assertEqual(out["missions"], [])
        self.assertEqual([p["ref"] for p in out["predefined"]], [f"comp:{wid}"])                  # the closed team's isn't drawn
        p = out["predefined"][0]
        self.assertEqual((p["open"], p["fixed"], p["dynamic"], p["running"], p["waiting"], p["researching"]), (3, 2, 1, 1, 1, 1))
        self.assertEqual(next(t for t in out["teams"] if t["id"] == wid)["predefined"], f"comp:{wid}")
        self.assertEqual(mission_link.command_map(self.mx, ME, team=wid)["predefined"][0]["team"], wid)


if __name__ == "__main__":
    unittest.main()
