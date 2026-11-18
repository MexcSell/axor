"""organization.py: the hierarchy over the Company, Workforce and your agents: seeding, reporting-line integrity (no cycles, one
manager), missions that never touch permanent lines, execution authority, delegation/escalation and single-use requests."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import organization
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}


def seed_sources(db):
    """A small Company (two divisions) and Workforce (CEO, Engineering, Evaluation) with the two 'Ivo's of the real data."""
    q = db.q
    q("CREATE TABLE co_company (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)")
    q("CREATE TABLE co_divisions (id INTEGER PRIMARY KEY, company_id INTEGER, key TEXT, name TEXT, description TEXT, status TEXT)")
    q("""CREATE TABLE co_agents (id INTEGER PRIMARY KEY, company_id INTEGER, key TEXT, name TEXT, title TEXT, category TEXT, division_id INTEGER,
         skills TEXT, max_load INTEGER, lead INTEGER, evaluator INTEGER, permissions TEXT, status TEXT)""")
    q("""CREATE TABLE wf_agents (id INTEGER PRIMARY KEY, user_id INTEGER, key TEXT, team TEXT, level TEXT, role TEXT, name TEXT, title TEXT,
         tools TEXT, status TEXT)""")
    q("INSERT INTO co_company VALUES (1, 7, 'Monalisa Company')")
    q("INSERT INTO co_divisions VALUES (1, 1, 'bittensor', 'Bittensor', 'Subnets', 'active'), (2, 1, 'handshake', 'Handshake', 'HNS', 'active')")
    perms = json.dumps({"execute": ["sandbox_tests"]})
    rows = [(1, "ceo", "Ada", "CEO Agent", "leadership", None, {"strategy": 5}, 3, 0, 0, "{}"),
            (2, "competition_manager", "Gus", "Competition Manager", "division", 1, {"project_management": 5}, 4, 1, 0, "{}"),
            (3, "miner_engineer", "Ivo", "Miner Engineer", "division", 1, {"python": 5}, 3, 0, 0, perms),
            (4, "hns_pm", "Noor", "Handshake Project Manager", "division", 2, {"project_management": 5}, 4, 1, 0, "{}"),
            (5, "evaluator", "Eden", "Independent Evaluator", "shared", None, {"evaluation": 5}, 6, 0, 1, "{}")]
    for i, k, n, t, c, d, sk, ml, lead, ev, pm in rows:
        q("INSERT INTO co_agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (i, 1, k, n, t, c, d, json.dumps(sk), ml, lead, ev, pm, "available"))
    staff = [(1, "ceo", "exec", "ceo", "Atlas", "CEO · Orchestrator"), (2, "engineering-lead", "engineering", "lead", "Kenji", "Engineering Lead"),
             (3, "software-engineer", "engineering", "specialist", "Lena", "Software Engineer"),
             (4, "chief-evaluator", "evaluation", "lead", "Wren", "Chief Evaluator"),
             (5, "improvement-engineer", "evaluation", "specialist", "Ivo", "Improvement Engineer")]
    for i, k, team, lvl, n, t in staff:
        q("INSERT INTO wf_agents VALUES (?,?,?,?,?,?,?,?,?,?)", (i, 7, k, team, lvl, k, n, t, "[]", "active"))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        seed_sources(self.db)
        self.o = organization.Organization(self.db)
        self.v = self.o.view(ME)

    def tearDown(self): self.dir.cleanup()

    def key(self, name, system=None):
        return next(a["key"] for a in self.o.view(ME)["agents"] if a["name"] == name and (system is None or a["system"] == system))

    def unit(self, name): return next(u["id"] for u in self.o.view(ME)["units"] if u["name"] == name)

    def mgr(self, name, system=None): return self.o.manager_of(7, self.key(name, system))

    def agent(self, name, system=None): return next(a for a in self.o.view(ME)["agents"] if a["key"] == self.key(name, system))


class Seeding(Base):
    def test_hierarchy_from_existing_systems(self):
        v = self.v
        self.assertEqual(v["org"]["name"], "Monalisa Company")
        atlas, kenji, gus = self.key("Atlas"), self.key("Kenji"), self.key("Gus")
        self.assertEqual(v["org"]["ceo"], atlas)
        kinds = {u["name"]: u["kind"] for u in v["units"]}
        self.assertEqual(kinds["Bittensor"], "division")
        for d in ("Software Engineering", "Data & Evaluation", "Research & Intelligence", "Infrastructure & DevOps", "AI & Model Intelligence", "Quality Assurance", "Security & Compliance", "Knowledge Management"): self.assertEqual(kinds[d], "department")
        self.assertIsNone(self.o.manager_of(7, atlas))                 # the CEO reports to you
        self.assertEqual(self.o.manager_of(7, gus), atlas)              # division manager → CEO
        self.assertEqual(self.o.manager_of(7, kenji), atlas)            # department manager → CEO
        self.assertEqual(self.mgr("Lena"), kenji)                       # specialist → department manager
        self.assertEqual(self.mgr("Ivo", "company"), gus)
        self.assertEqual(self.mgr("Eden"), self.key("Wren"))            # a shared specialist with a plain department
        self.assertEqual(self.mgr("Ada"), atlas)                       # the Company's leadership is the CEO's Executive staff
        self.assertEqual(self.agent("Ada")["unit_id"], self.unit("Executive staff"))
        self.assertEqual(self.agent("Ada")["title"], "Chief of Staff")  # one CEO: the Company's CEO agent is the chief of staff
        ranks = {a["name"] + a["system"]: a["rank"] for a in v["agents"]}
        self.assertEqual((ranks["Atlasworkforce"], ranks["Guscompany"], ranks["Kenjiworkforce"], ranks["Lenaworkforce"], ranks["Adacompany"]),
                         ("ceo", "division_manager", "department_manager", "specialist", "executive"))

    def test_unique_identities_and_duplicate_names_flagged(self):
        ivos = [a for a in self.v["agents"] if a["name"] == "Ivo"]
        self.assertEqual(len(ivos), 2)
        self.assertEqual(len({a["key"] for a in ivos}), 2)
        self.assertEqual(len({a["ident"] for a in self.v["agents"]}), len(self.v["agents"]))
        kinds = {i["kind"] for i in self.v["issues"]}
        self.assertIn("duplicate_name", kinds)
        self.assertNotIn("two_ceos", kinds)  # Ada is titled Chief of Staff in the organization

    def test_sync_is_idempotent_and_follows_sources(self):
        n = len(self.v["agents"])
        self.assertEqual(len(self.o.view(ME)["agents"]), n)
        self.db.q("INSERT INTO wf_agents VALUES (6, 7, 'sre', 'operations', 'specialist', 'sre', 'Bea', 'SRE', '[]', 'active')")
        self.db.q("UPDATE co_agents SET status='archived' WHERE id=5")
        v = self.o.view(ME)
        self.assertEqual(len(v["agents"]), n)  # one in, one out
        bea = next(a for a in v["agents"] if a["name"] == "Bea")
        self.assertEqual(bea["unit_id"], self.unit("Infrastructure & DevOps"))
        self.assertEqual(bea["manager"], self.key("Atlas"))  # Infrastructure & DevOps has no manager: its people report to the CEO

    def test_lines_have_one_current_row(self):
        rows = self.db.q("SELECT agent_key, COUNT(*) n FROM og_lines WHERE user_id=7 AND ended IS NULL GROUP BY agent_key")
        self.assertTrue(all(r["n"] == 1 for r in rows))
        with self.assertRaises(Exception):
            self.db.q("INSERT INTO og_lines (user_id, agent_key, manager_key, since) VALUES (7, ?, NULL, 0)", (self.key("Lena"),))


def seed_teams(db, comps=((1, 28, "active"), (2, 29, "active"))):
    """Two Competition teams on SN62 (the Director is the lead) and one campaign of another user."""
    q = db.q
    q("CREATE TABLE IF NOT EXISTS mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER, status TEXT)")
    q("CREATE TABLE IF NOT EXISTS mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT)")
    q("""CREATE TABLE IF NOT EXISTS mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, role TEXT, name TEXT, title TEXT, lead INTEGER, active INTEGER)""")
    q("CREATE TABLE IF NOT EXISTS mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, agent_id INTEGER, reviewer INTEGER, done_at REAL)")
    q("""CREATE TABLE IF NOT EXISTS mw_reports (id INTEGER PRIMARY KEY, comp_id INTEGER, headline TEXT, status TEXT, ts REAL, asks TEXT)""")
    q("INSERT INTO mh_campaigns VALUES (1, 7, 62, 'live'), (2, 99, 62, 'live')")
    for cid, num, st in comps: q("INSERT INTO mw_comps VALUES (?,?,?,?,?)", (cid, 1, num, "", st))
    q("INSERT INTO mw_comps VALUES (3, 2, 28, '', 'active')")  # someone else's team
    rows = [(1, 1, "lead", "Dora", "Lead", 1), (2, 1, "researcher", "Rex", "Researcher", 0), (3, 1, "reviewer", "Vera", "Reviewer", 0),
            (4, 2, "lead", "Dan", "Lead", 1), (5, 2, "researcher", "Rex", "Researcher", 0), (6, 3, "lead", "Other", "Lead", 1)]
    for i, c, role, n, t, lead in rows: q("INSERT INTO mw_agents VALUES (?,?,?,?,?,?,1)", (i, c, role, n, t, lead))
    q("INSERT INTO mw_tasks VALUES (1, 1, 'Benchmark the miner', 'working', 2, NULL, NULL), (2, 1, 'Old', 'done', 2, NULL, ?)", (time.time(),))
    q("INSERT INTO mw_reports VALUES (1, 1, 'Rank 4, two asks', 'new', ?, '[1,2]')", (time.time(),))


class Teams(Base):
    def setUp(self):
        super().setUp()
        seed_teams(self.db)
        self.v = self.o.view(ME)

    def team(self, link): return next(u for u in self.v["units"] if u["link"] == link)

    def test_a_team_unit_per_open_team_under_bittensor_led_by_its_director(self):
        t = self.team("mw_comp:1")
        self.assertEqual((t["kind"], t["name"], t["parent_id"]), ("team", "SN62 · Competition 28", self.unit("Bittensor")))
        dora, gus = self.key("Dora"), self.key("Gus")
        self.assertEqual(t["manager_key"], dora)
        self.assertEqual(self.o.manager_of(7, dora), gus)              # the Director reports to the division manager
        self.assertEqual(self.o.manager_of(7, "teams:2"), dora)         # the squads report to their Director
        self.assertEqual(self.o.manager_of(7, "teams:3"), dora)
        self.assertEqual(self.o.manager_of(7, "teams:5"), self.key("Dan"))
        self.assertFalse(any(u["link"] == "mw_comp:3" for u in self.v["units"]), "another user's team isn't here")
        self.assertEqual(self.agent("Dora")["rank"], "competition_director")

    def test_the_director_sees_the_board_and_the_report(self):
        t = self.team("mw_comp:1")["team"]
        self.assertEqual((t["open"], t["done_week"]), (1, 1))
        self.assertEqual((t["report"]["headline"], t["report"]["asks"]), ("Rank 4, two asks", 2))
        rex = next(a for a in self.v["agents"] if a["key"] == "teams:2")
        self.assertEqual(rex["work"][0]["what"], "Benchmark the miner")
        self.assertEqual(rex["autonomy"], 2)

    def test_names_reused_across_teams_are_not_a_warning(self):
        dup = [i for i in self.v["issues"] if i["kind"] == "duplicate_name"]
        self.assertFalse(any("Rex" in i["title"] for i in dup))
        self.assertTrue(any("Ivo" in i["title"] for i in dup), "the Company/Workforce Ivo still is")

    def test_a_new_director_takes_over_and_a_closed_team_closes(self):
        self.db.q("UPDATE mw_agents SET lead=0 WHERE id=1"); self.db.q("UPDATE mw_agents SET lead=1 WHERE id=2")
        self.v = self.o.view(ME)
        self.assertEqual(self.team("mw_comp:1")["manager_key"], "teams:2")
        self.assertEqual(self.o.manager_of(7, "teams:1"), "teams:2")
        self.db.q("UPDATE mw_comps SET status='closed' WHERE id=2")
        self.v = self.o.view(ME)
        self.assertFalse(any(u["link"] == "mw_comp:2" for u in self.v["units"]))
        self.assertFalse(any(a["key"] == "teams:4" for a in self.v["agents"]))

    def test_your_choices_stand(self):
        u = self.team("mw_comp:1")["id"]
        self.o.apply(ME, "set_manager", {"unit_id": u, "key": self.key("Ivo", "company")})
        self.o.view(ME)
        self.v = self.o.view(ME)
        self.assertEqual(self.team("mw_comp:1")["manager_key"], self.key("Ivo", "company"), "a manager you picked isn't replaced by the sync")
        self.o.apply(ME, "dissolve", {"unit_id": u})
        self.v = self.o.view(ME)
        self.assertFalse(any(x["link"] == "mw_comp:1" for x in self.v["units"]), "a team unit you dissolved isn't made again")

    def test_without_a_company_the_teams_get_a_bittensor_division_of_their_own(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "b.db"))
        seed_teams(db)
        v = organization.Organization(db).view(ME)
        div = next(u for u in v["units"] if u["link"] == "og:bittensor")
        self.assertEqual(next(u for u in v["units"] if u["link"] == "mw_comp:1")["parent_id"], div["id"])


class Integrity(Base):
    def test_cycle_refused(self):
        lena, kenji = self.key("Lena"), self.key("Kenji")
        with self.assertRaises(HTTPException) as e:
            self.o.apply(ME, "move_agent", {"key": kenji, "unit_id": self.unit("Software Engineering"), "manager": lena})
        self.assertIn("cycle", e.exception.detail)
        self.assertEqual(self.o.manager_of(7, lena), kenji)  # nothing changed
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "move_agent", {"key": lena, "unit_id": self.unit("Software Engineering"), "manager": lena})

    def test_deep_cycle_refused(self):
        atlas, kenji, lena = self.key("Atlas"), self.key("Kenji"), self.key("Lena")
        with self.assertRaises(HTTPException):  # Atlas → Lena while Lena → Kenji → Atlas
            self.o._set_line(7, atlas, lena, "test")

    def test_unit_cannot_nest_in_itself(self):
        eng = self.unit("Software Engineering")
        self.o.apply(ME, "add_unit", {"kind": "team", "name": "Miners", "parent_id": eng})
        miners = self.unit("Miners")
        self.o.apply(ME, "add_unit", {"kind": "team", "name": "Fast miners", "parent_id": miners})
        fast = self.unit("Fast miners")
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "edit_unit", {"unit_id": miners, "parent_id": fast})
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "add_unit", {"kind": "division", "name": "Sub", "parent_id": eng})

    def test_new_manager_takes_the_unit_and_keeps_its_level(self):
        lena = self.key("Lena")
        before = self.agent("Lena")["autonomy"]
        self.o.apply(ME, "add_unit", {"kind": "team", "name": "Miners", "parent_id": self.unit("Software Engineering")})
        self.o.apply(ME, "set_manager", {"unit_id": self.unit("Miners"), "key": lena})
        a = self.agent("Lena")
        self.assertEqual(a["rank"], "team_leader")
        self.assertEqual(a["autonomy"], before)                     # managers get no execution authority from position
        self.assertEqual(self.o.manager_of(7, lena), self.key("Kenji"))  # a team's leader reports to the department manager

    def test_replacing_a_manager_repoints_members(self):
        wren, eden, ivo = self.key("Wren"), self.key("Eden"), self.key("Ivo", "workforce")
        self.o.apply(ME, "set_manager", {"unit_id": self.unit("Data & Evaluation"), "key": eden})
        self.assertEqual(self.o.manager_of(7, ivo), eden)
        self.assertEqual(self.o.manager_of(7, wren), eden)           # the old manager stays, now reporting to the new one
        self.assertEqual(self.o.manager_of(7, eden), self.key("Atlas"))
        self.assertEqual(self.o.integrity(7, self.o.view(ME)["agents"], self.o.view(ME)["units"]).__class__, list)
        self.assertFalse([i for i in self.o.view(ME)["issues"] if i["kind"] == "cycle"])

    def test_one_unit_per_manager(self):
        gus = self.key("Gus")
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "set_manager", {"unit_id": self.unit("Handshake"), "key": gus})
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "move_agent", {"key": gus, "unit_id": self.unit("Handshake")})

    def test_dissolve_moves_people_up(self):
        eng = self.unit("Software Engineering")
        self.o.apply(ME, "add_unit", {"kind": "team", "name": "Miners", "parent_id": eng})
        lena = self.key("Lena")
        self.o.apply(ME, "move_agent", {"key": lena, "unit_id": self.unit("Miners")})
        self.assertEqual(self.o.manager_of(7, lena), self.key("Kenji"))  # leaderless team → up to the department's manager
        self.o.apply(ME, "dissolve", {"unit_id": self.unit("Miners")})
        a = self.agent("Lena")
        self.assertEqual(a["unit_id"], eng)
        self.assertEqual(a["manager"], self.key("Kenji"))


class Missions(Base):
    def test_assignment_never_changes_the_permanent_line(self):
        lena, gus, kenji = self.key("Lena"), self.key("Gus"), self.key("Kenji")
        mid = self.o.apply(ME, "add_mission", {"name": "Bittensor Competition 29", "manager_key": gus, "unit_id": self.unit("Bittensor"), "skills": ["python"]})["mission_id"]
        self.o.apply(ME, "assign", {"mission_id": mid, "keys": [lena]})
        a = self.agent("Lena")
        self.assertEqual(a["manager"], kenji)
        self.assertEqual([m["manager"] for m in a["missions"]], [gus])
        self.o.apply(ME, "end_mission", {"mission_id": mid})
        a = self.agent("Lena")
        self.assertEqual((a["manager"], a["missions"], a["unit_id"]), (kenji, [], self.unit("Software Engineering")))

    def test_recommendation_covers_skills_with_an_independent_evaluator(self):
        mid = self.o.apply(ME, "add_mission", {"name": "C29", "manager_key": self.key("Gus"), "skills": ["python", "project_management"]})["mission_id"]
        r = self.o.recommend(ME, mid)
        self.assertFalse(r["missing"])
        self.assertTrue(r["evaluator"])
        self.assertNotIn(r["evaluator"]["key"], [t["key"] for t in r["team"]])
        self.assertNotIn(self.key("Atlas"), [c["key"] for c in r["candidates"]])
        self.assertNotIn(self.key("Gus"), [c["key"] for c in r["candidates"]])  # the mission manager isn't staffed onto their own mission
        self.assertEqual(r["evaluator"]["name"], "Eden")


class Authority(Base):
    def test_raising_to_l3_needs_an_approved_request_once(self):
        lena = self.key("Lena")
        with self.assertRaises(HTTPException) as e:
            self.o.apply(ME, "autonomy", {"key": lena, "level": 3})
        self.assertEqual(e.exception.status_code, 403)
        rid = self.o.propose(ME, "autonomy", {"key": lena, "level": 3})["request_id"]
        self.assertEqual(self.agent("Lena")["autonomy"], 1)
        self.assertEqual(self.o.decide(ME, rid, True)["status"], "applied")
        self.assertEqual(self.agent("Lena")["autonomy"], 3)
        with self.assertRaises(HTTPException):  # single use
            self.o.decide(ME, rid, True)
        self.assertEqual(self.o.propose(ME, "autonomy", {"key": lena, "level": 1}).get("applied") is not None, True)  # lowering applies at once

    def test_tampered_request_refused(self):
        lena = self.key("Lena")
        rid = self.o.propose(ME, "autonomy", {"key": lena, "level": 4})["request_id"]
        self.db.q("UPDATE og_requests SET payload=? WHERE id=?", (json.dumps({"key": self.key("Kenji"), "level": 4}), rid))
        with self.assertRaises(HTTPException):
            self.o.decide(ME, rid, True)
        self.assertEqual(self.agent("Kenji")["autonomy"], 1)

    def test_expired_request_refused(self):
        rid = self.o.propose(ME, "autonomy", {"key": self.key("Lena"), "level": 3})["request_id"]
        self.db.q("UPDATE og_requests SET expires=? WHERE id=?", (time.time() - 1, rid))
        with self.assertRaises(HTTPException):
            self.o.decide(ME, rid, True)

    def test_allowed(self):
        ivo = self.key("Ivo", "company")  # sandbox execution → seeded L2
        self.assertEqual(self.o.level(7, ivo), 2)
        self.assertEqual(self.o.allowed(7, ivo, 2), "yes")
        self.assertEqual(self.o.allowed(7, ivo, 3), "no")
        self.assertEqual(self.o.allowed(7, ivo, 1, "production_deploy"), "approval")
        self.assertEqual(self.o.allowed(7, "company:999", 1), "yes")  # unknown: the caller keeps its own rules


class Delegation(Base):
    def test_down_the_line_only(self):
        kenji, lena, gus = self.key("Kenji"), self.key("Lena"), self.key("Gus")
        self.o.apply(ME, "delegate", {"title": "Profile the miner", "from_key": kenji, "to_key": lena, "level": 1})
        with self.assertRaises(HTTPException) as e:
            self.o.apply(ME, "delegate", {"title": "x", "from_key": gus, "to_key": lena, "level": 1})
        self.assertEqual(e.exception.status_code, 403)
        mid = self.o.apply(ME, "add_mission", {"name": "C29", "manager_key": gus})["mission_id"]
        self.o.apply(ME, "assign", {"mission_id": mid, "key": lena})
        self.o.apply(ME, "delegate", {"title": "Mission work", "from_key": gus, "to_key": lena, "mission_id": mid, "level": 1})

    def test_level_gate_and_approval_for_l3(self):
        kenji, lena = self.key("Kenji"), self.key("Lena")
        with self.assertRaises(HTTPException):  # Lena is L1; a sandbox task needs L2
            self.o.apply(ME, "delegate", {"title": "Run tests", "from_key": kenji, "to_key": lena, "level": 2})
        ivo = self.key("Ivo", "company")
        r = self.o.apply(ME, "delegate", {"title": "Deploy", "from_key": self.key("Gus"), "to_key": ivo, "level": 1, "sensitive": "production_deploy"})
        t = self.db.q("SELECT status FROM og_tasks WHERE id=?", (r["task_id"],), one=True)
        self.assertEqual(t["status"], "awaiting")
        req = self.db.q("SELECT id FROM og_requests WHERE kind='task_go'", one=True)
        self.o.decide(ME, req["id"], True)
        self.assertEqual(self.db.q("SELECT status FROM og_tasks WHERE id=?", (r["task_id"],), one=True)["status"], "open")

    def test_escalation_climbs_to_you(self):
        kenji, lena, atlas, gus = self.key("Kenji"), self.key("Lena"), self.key("Atlas"), self.key("Gus")
        tid = self.o.apply(ME, "delegate", {"title": "Blocked", "from_key": kenji, "to_key": lena})["task_id"]
        holders = []
        for _ in range(3):
            self.o.apply(ME, "task", {"task_id": tid, "action": "escalate"})
            holders.append(self.db.q("SELECT holder_key FROM og_tasks WHERE id=?", (tid,), one=True)["holder_key"])
        self.assertEqual(holders, [kenji, atlas, None])
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "task", {"task_id": tid, "action": "escalate"})
        # inside a mission: the mission manager first
        mid = self.o.apply(ME, "add_mission", {"name": "C29", "manager_key": gus})["mission_id"]
        self.o.apply(ME, "assign", {"mission_id": mid, "key": lena})
        t2 = self.o.apply(ME, "delegate", {"title": "M", "from_key": gus, "to_key": lena, "mission_id": mid})["task_id"]
        self.o.apply(ME, "task", {"task_id": t2, "action": "escalate"})
        self.assertEqual(self.db.q("SELECT holder_key FROM og_tasks WHERE id=?", (t2,), one=True)["holder_key"], gus)
        self.o.apply(ME, "task", {"task_id": t2, "action": "escalate"})
        self.assertEqual(self.db.q("SELECT holder_key FROM og_tasks WHERE id=?", (t2,), one=True)["holder_key"], atlas)

    def test_overdue_escalates_on_tick(self):
        tid = self.o.apply(ME, "delegate", {"title": "Late", "from_key": self.key("Kenji"), "to_key": self.key("Lena"), "due": time.time() - 10})["task_id"]
        self.o.tick()
        t = self.db.q("SELECT status, holder_key, due FROM og_tasks WHERE id=?", (tid,), one=True)
        self.assertEqual((t["status"], t["holder_key"]), ("escalated", self.key("Kenji")))
        self.assertGreater(t["due"], time.time())


class Performance(Base):
    def test_scores_need_evidence_and_promotion_is_a_proposal(self):
        self.db.q("""CREATE TABLE ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, system TEXT, owner_id INTEGER, agent_key TEXT, kind TEXT, ref TEXT,
                     title TEXT, status TEXT, tokens INTEGER DEFAULT 0, reported INTEGER, cost REAL, model TEXT, error TEXT, started REAL, finished REAL)""")
        lena, ivo = self.key("Lena"), self.key("Ivo", "workforce")
        now = time.time()
        for i in range(8): self.db.q("INSERT INTO ac_runs (owner_id, agent_key, kind, status, started) VALUES (7, ?, 'run', 'done', ?)", (lena, now - i))
        for i in range(2): self.db.q("INSERT INTO ac_runs (owner_id, agent_key, kind, status, started) VALUES (7, ?, 'run', 'done', ?)", (ivo, now - i))
        recs = self.o.compute_perf(ME)["recommendations"]
        self.assertIsNone(self.agent("Ivo", "workforce")["perf"]["score"])  # 2 pieces of work: no score
        self.assertEqual(self.agent("Lena")["perf"]["score"], 100.0)
        promo = next(r for r in recs if r["kind"] == "promote" and r["key"] == lena)
        self.assertEqual(self.agent("Lena")["rank"], "specialist")         # nothing applied by itself
        rid = self.o.propose(ME, "promote", promo["payload"], by="performance")["request_id"]
        self.o.decide(ME, rid, True)
        a = self.agent("Lena")
        self.assertEqual((a["rank"], a["autonomy"]), ("team_leader", 1))


if __name__ == "__main__":
    unittest.main()


def seed_squads(db):
    """Squads on the two teams (mw_agents.squad/head, as mining_work keeps them): Rex leads Research, Vera sits in it."""
    db.q("ALTER TABLE mw_agents ADD COLUMN squad TEXT"); db.q("ALTER TABLE mw_agents ADD COLUMN head INTEGER DEFAULT 0")
    db.q("UPDATE mw_agents SET squad='intel', head=1 WHERE id IN (2, 5)")
    db.q("UPDATE mw_agents SET squad='intel', head=0 WHERE id=3")


class HQ(Base):
    """Organization HQ: executive portfolios, the eight departments, squads, unit assignments, budgets, the authority ladder."""
    def setUp(self):
        super().setUp()
        q = self.db.q
        for i, k, n, t in ((6, "cto", "Cyrus", "CTO Agent"), (7, "governance", "Fern", "Governance Agent"), (8, "security_reviewer", "Abel", "Security Reviewer")):
            q("INSERT INTO co_agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (i, 1, k, n, t, "leadership" if k != "security_reviewer" else "shared", None, "{}", 3, 0, 0, "{}", "available"))
        seed_teams(self.db)
        self.v = self.o.view(ME)

    def u(self, link): return next(u for u in self.o.view(ME)["units"] if u["link"] == link)

    def test_portfolios_follow_company_roles_and_sponsor_by_dotted_line(self):
        cyrus, fern, ada = self.agent("Cyrus"), self.agent("Fern"), self.agent("Ada")
        self.assertEqual((cyrus["portfolio"], cyrus["title"], cyrus["rank"], cyrus["tier"]), ("cto", "Chief Technology Officer", "executive", "executive"))
        self.assertEqual((fern["portfolio"], ada["portfolio"], ada["title"]), ("csec", "cso", "Chief of Staff"))
        self.assertEqual(cyrus["unit_id"], self.unit("Executive staff"))
        self.assertEqual(self.u("wf_team:engineering")["sponsor_key"], cyrus["key"])
        self.assertEqual(self.mgr("Kenji"), self.key("Atlas"), "a sponsor is a dotted line: the department manager still reports to the CEO")
        self.o.apply(ME, "portfolio", {"key": self.key("Fern"), "portfolio": "cto"})  # one holder per portfolio
        self.assertEqual((self.agent("Cyrus")["portfolio"], self.agent("Fern")["portfolio"]), (None, "cto"))
        self.assertEqual(self.u("wf_team:engineering")["sponsor_key"], self.key("Fern"))

    def test_eight_departments_and_your_names_stand(self):
        depts = {u["dept"] for u in self.v["units"] if u["kind"] == "department" and u["dept"]}
        self.assertEqual(depts, {"research", "engineering", "data", "ai", "security", "qa", "infra", "knowledge"})
        self.assertEqual(self.agent("Abel")["unit_id"], self.unit("Security & Compliance"), "a shared specialist lands in its now-existing department")
        self.o.apply(ME, "edit_unit", {"unit_id": self.unit("Quality Assurance"), "name": "QA Guild"})
        self.o.apply(ME, "dissolve", {"unit_id": self.unit("Knowledge Management")})
        names = {u["name"] for u in self.o.view(ME)["units"]}
        self.assertIn("QA Guild", names); self.assertNotIn("Knowledge Management", names)
        self.assertFalse([i for i in self.o.view(ME)["issues"] if i["kind"] == "no_manager" and "AI & Model" in i["title"]], "an empty department isn't a nag")

    def test_squads_inside_teams_with_their_lead_and_your_moves_stand(self):
        team = self.u("mw_comp:1")
        self.assertEqual(self.o.manager_of(7, "teams:3"), self.key("Dora"))  # no squads yet: straight to the Director
        seed_squads(self.db)
        sq = self.u("mw_squad:1:intel")
        self.assertEqual((sq["kind"], sq["parent_id"], sq["manager_key"]), ("squad", team["id"], "teams:2"))
        vera = next(a for a in self.o.view(ME)["agents"] if a["key"] == "teams:3")
        self.assertEqual((vera["unit_id"], vera["manager"]), (sq["id"], "teams:2"))      # moved into its squad, reports to the squad lead
        self.assertEqual(self.o.manager_of(7, "teams:2"), self.key("Dora"))             # the squad lead to the Director
        rex = next(a for a in self.o.view(ME)["agents"] if a["key"] == "teams:2")
        self.assertEqual((rex["rank"], rex["tier"]), ("squad_leader", "squad"))
        self.assertIn(sq["id"], team["squads"] or self.u("mw_comp:1")["squads"])
        self.o.apply(ME, "move_agent", {"key": "teams:3", "unit_id": team["id"]})
        self.o.view(ME)
        self.assertEqual(next(a for a in self.o.view(ME)["agents"] if a["key"] == "teams:3")["unit_id"], sq["id"],
                         "a team agent back in its team unit rejoins its squad (the team's own data says so)")
        self.o.apply(ME, "move_agent", {"key": "teams:3", "unit_id": self.unit("Data & Evaluation")})
        self.assertEqual(next(a for a in self.o.view(ME)["agents"] if a["key"] == "teams:3")["unit_id"], self.unit("Data & Evaluation"), "your move elsewhere stands")
        self.o.apply(ME, "dissolve", {"unit_id": team["id"]})
        self.assertFalse(any(u["link"] == "mw_squad:1:intel" for u in self.o.view(ME)["units"]), "a squad dissolves with its team")
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "add_unit", {"kind": "squad", "name": "Loose", "parent_id": self.unit("Bittensor")})

    def test_unit_assignment_is_scoped_and_never_moves_the_home(self):
        lena, kenji, team = self.key("Lena"), self.key("Kenji"), self.u("mw_comp:1")["id"]
        with self.assertRaises(HTTPException) as e:
            self.o.apply(ME, "assign_unit", {"unit_id": team, "key": lena, "scope": 3})
        self.assertIn("never raise", e.exception.detail)
        self.o.apply(ME, "assign_unit", {"unit_id": team, "key": lena, "scope": 0, "role": "Python engineer"})
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "assign_unit", {"unit_id": team, "key": lena})
        a = self.agent("Lena")
        self.assertEqual((a["manager"], a["unit_id"], len(a["assignments"]), a["assignments"][0]["scope"]), (kenji, self.unit("Software Engineering"), 1, 0))
        self.assertTrue(self.o.may_access(7, lena, team))
        self.assertEqual(self.o.scoped_level(7, lena, team), 0)
        self.assertEqual([x["key"] for x in self.u("mw_comp:1")["loaned_in"]], [lena])
        self.o.apply(ME, "release_unit", {"unit_id": team, "key": lena})
        self.assertEqual(self.agent("Lena")["assignments"], [])
        self.assertFalse(self.o.may_access(7, lena, team))

    def test_directors_see_only_their_own_team(self):
        seed_squads(self.db); self.o.view(ME)
        t1, t2, sq = self.u("mw_comp:1")["id"], self.u("mw_comp:2")["id"], self.u("mw_squad:1:intel")["id"]
        self.assertTrue(self.o.may_access(7, self.key("Dora"), sq))
        self.assertFalse(self.o.may_access(7, self.key("Dora"), t2))
        self.assertTrue(self.o.may_access(7, "teams:3", t1), "a squad member works in its whole team's environment")
        self.assertFalse(self.o.may_access(7, "teams:3", t2))
        self.assertTrue(self.o.may_access(7, self.key("Gus"), t2), "the division's manager sees its teams")
        self.assertTrue(self.o.may_access(7, self.key("Atlas"), t2))

    def test_budgets_fit_their_parent_and_your_limit(self):
        b = self.unit("Bittensor")
        self.o.apply(ME, "budget", {"unit_id": b, "budget": 100_000})
        self.o.apply(ME, "add_unit", {"kind": "team", "name": "Miners", "parent_id": b, "budget": 60_000})
        with self.assertRaises(HTTPException) as e:
            self.o.apply(ME, "add_unit", {"kind": "team", "name": "Validators", "parent_id": b, "budget": 50_000})
        self.assertIn("40k at most", e.exception.detail)
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "budget", {"unit_id": b, "budget": 50_000})  # below what its units already get
        self.db.q("CREATE TABLE ac_budget (owner_id INTEGER PRIMARY KEY, daily_tokens INTEGER, updated REAL, by_user TEXT)")
        self.db.q("INSERT INTO ac_budget VALUES (7, 120000, 0, 'leo')")
        with self.assertRaises(HTTPException):
            self.o.apply(ME, "budget", {"unit_id": self.unit("Handshake"), "budget": 30_000})
        self.assertEqual(self.o.view(ME)["budget"]["allocated"], 100_000)
        r = self.o.propose(ME, "budget", {"unit_id": self.unit("Handshake"), "budget": 20_000}, by="atlas")
        self.assertIn("request_id", r, "a budget proposal always waits for you")

    def test_agents_cannot_grant_themselves_authority(self):
        with self.assertRaises(HTTPException) as e:
            self.o.propose(ME, "autonomy", {"key": self.key("Atlas"), "level": 3}, by="atlas")
        self.assertEqual(e.exception.status_code, 403)
        self.assertIn("request_id", self.o.propose(ME, "autonomy", {"key": self.key("Atlas"), "level": 3}))  # yours is a request as usual

    def test_specialist_request_goes_through_approvals(self):
        team, eng = self.u("mw_comp:1")["id"], self.unit("Software Engineering")
        c = self.o.specialists(ME, team, eng, ["python"])["candidates"]
        keys = [x["key"] for x in c]
        self.assertIn(self.key("Lena"), keys)                   # her home is the department
        self.assertIn(self.key("Ivo", "company"), keys)         # his profession is: Bittensor's Miner Engineer, affiliated with Software Engineering
        self.assertNotIn(self.key("Dora"), keys)
        r = self.o.propose(ME, "assign_unit", {"unit_id": team, "key": self.key("Lena"), "scope": 1, "role": "Python engineer", "title": "Lend Lena"})
        self.assertEqual(self.agent("Lena")["assignments"], [])
        self.o.decide(ME, r["request_id"], True)
        self.assertEqual(self.agent("Lena")["assignments"][0]["unit_id"], team)
        tiers = {t["tier"]: t["count"] for t in self.o.view(ME)["tiers"]}
        self.assertEqual((tiers["owner"], tiers["ceo"], tiers["director"]), (1, 1, 2))


class LateArrival(unittest.TestCase):
    """Organization opened before Workforce had made its staff: when they arrive, the org gets its CEO, a unit per team led by
    its lead, and their agents placed; a manager you cleared stays cleared."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        seed_sources(self.db)
        self.staff = self.db.q("SELECT * FROM wf_agents")
        self.db.q("DELETE FROM wf_agents")
        self.o = organization.Organization(self.db)
        self.v = self.o.view(ME)  # made from the Company alone

    def tearDown(self): self.dir.cleanup()

    def arrive(self):
        for a in self.staff:
            self.db.q("INSERT INTO wf_agents VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(a[k] for k in ("id", "user_id", "key", "team", "level", "role", "name", "title", "tools", "status")))
        return self.o.view(ME)

    def k(self, v, name, system="workforce"): return next(a["key"] for a in v["agents"] if a["name"] == name and a["system"] == system)

    def test_ceo_units_and_places_after_workforce_arrives(self):
        self.assertIsNone(self.v["org"]["ceo"])
        v = self.arrive()
        self.assertEqual(v["org"]["ceo"], self.k(v, "Atlas"))
        self.assertFalse([i for i in v["issues"] if i["kind"] in ("no_ceo", "two_ceos")], v["issues"])
        eng = next(u for u in v["units"] if u["name"] == "Software Engineering")
        self.assertEqual(self.o._unit(7, eng["id"])["manager_key"], self.k(v, "Kenji"))
        lena = next(a for a in v["agents"] if a["key"] == self.k(v, "Lena"))
        self.assertEqual(lena["unit_id"], eng["id"])
        self.assertEqual(self.o.manager_of(7, lena["key"]), self.k(v, "Kenji"))
        self.assertFalse([a["name"] for a in v["agents"] if a["system"] == "workforce" and not a["unit_id"] and a["key"] != v["org"]["ceo"]])

    def test_your_cleared_manager_and_moves_are_kept(self):
        v = self.arrive()
        eng = next(u for u in v["units"] if u["name"] == "Software Engineering")
        self.o.apply(ME, "set_manager", {"unit_id": eng["id"], "key": None})
        lena = self.k(v, "Lena")
        self.o.apply(ME, "move_agent", {"key": lena, "unit_id": None})
        self.o.view(ME); self.o.view(ME)
        self.assertIsNone(self.o._unit(7, eng["id"])["manager_key"], "a manager you cleared came back")
        self.assertIsNone(self.o._agent(7, lena)["unit_id"], "an agent you unplaced was placed again")
