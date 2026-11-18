"""control_hub.py: the one hierarchy (Organization → Departments → Teams → Agents) over the Organization and Competition teams,
subnet = department and competition = team, recommendations with their factors, staffing by mode (manual / hybrid / auto),
fixed-task validation and activation, dynamic tasks by route, and the agent workspace chat (pictures, transcripts, web results,
proposals that run only once approved)."""
import base64, json, os, sys, tempfile, time, unittest

from fastapi import HTTPException

from app import agent_core, control_hub, mining_work, organization
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_organization import ME, seed_sources  # noqa: E402

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def seed_bittensor(db):
    """Two Competition teams on SN62 (28 and 29), one on SN19, and another user's team."""
    q = db.q
    q("""CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER, mech INTEGER DEFAULT 0, status TEXT, settings TEXT)""")
    q("""CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT, goal TEXT, budget INTEGER,
         link TEXT, starts TEXT, ends TEXT)""")
    q("""CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, role TEXT, name TEXT, title TEXT, lead INTEGER, active INTEGER,
         job TEXT, instructions TEXT, model TEXT, squad TEXT, head INTEGER)""")
    q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, priority TEXT, agent_id INTEGER, reviewer INTEGER, done_at REAL, updated REAL)")
    q("CREATE TABLE mh_briefs (id INTEGER PRIMARY KEY, campaign_id INTEGER, cycle_id INTEGER, ts REAL, headline TEXT, standing TEXT, stats TEXT)")
    q("INSERT INTO mh_campaigns VALUES (1, 7, 62, 0, 'live', '{\"target\": 10}'), (2, 99, 62, 0, 'live', '{}'), (3, 7, 19, 0, 'live', '{}')")
    for row in [(1, 1, 28, "", "active", "Top 10", 150000), (2, 1, 29, "", "active", "", 150000), (3, 2, 28, "", "active", "", 0), (4, 3, None, "Inference", "active", "", 100000)]:
        q("INSERT INTO mw_comps (id, campaign_id, number, name, status, goal, budget) VALUES (?,?,?,?,?,?,?)", row)
    rows = [(1, 1, "lead", "Dora", "Lead", 1), (2, 1, "researcher", "Rex", "Researcher", 0), (3, 2, "lead", "Dan", "Lead", 1),
            (4, 3, "lead", "Other", "Lead", 1), (5, 4, "lead", "Iris", "Lead", 1)]
    for i, c, role, n, t, lead in rows:
        q("INSERT INTO mw_agents (id, comp_id, role, name, title, lead, active, job, model) VALUES (?,?,?,?,?,?,1,?,?)", (i, c, role, n, t, lead, f"{t} of the team", "auto"))
    q("INSERT INTO mh_briefs VALUES (1, 1, 1, ?, 'Rank 14', 'amber', ?)", (time.time(), json.dumps({"rank": 14, "of": 200, "gap": 0.02, "target": 10})))


class Sync:
    def submit(self, fn, *a, **kw): fn(*a, **kw)


class FakeLLM:
    def __init__(self): self.calls, self.provider = [], "anthropic"
    def any_configured(self): return True
    def resolve(self, choice): return (self.provider, "m")
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low", messages=None):
        self.calls.append({"system": system, "messages": messages, "prompt": prompt, "schema": name})
        if on_usage: on_usage(100)
        last = (messages or [{"content": prompt}])[-1]["content"]
        text = last if isinstance(last, str) else " ".join(b.get("text", "") for b in last if b.get("type") == "text")
        if name == "reply":
            return {"reply": "ok: " + text.rsplit("The user's message:", 1)[-1].strip(), "suggestions": ["next"],
                    "task": {"title": "Benchmark the miner" if "task" in text else "", "detail": "Run it."}}
        return {"status": "done", "result": "the work", "summary": "delivered"}


class FakeHub:
    def __init__(self): self.llm, self.used = FakeLLM(), []
    def gate(self, me): return me
    def material(self, me, atts): return [f"<attached_file name=\"{a.id}\">body</attached_file>" for a in atts], [{"kind": "file", "label": a.id} for a in atts]
    def log_usage(self, me, source, tokens, agent_id=None, model=None): self.used.append((source, tokens))
    def model_of(self, m): return m


class FakeMining:
    def __init__(self, db): self.db, self.created = db, []
    def data(self): return {"subnets": [{"netuid": 62, "name": "Ridges"}, {"netuid": 19, "name": "Nineteen"}, {"netuid": 5, "name": "Five"}]}
    def subnet_comps(self, me, netuid): return {"competitions": [{"mech": 0, "name": "Competition 1", "share": 1.0, "taken": True}]}
    def create(self, me, b, ip):
        self.created.append(b)
        cid = self.db.q("INSERT INTO mh_campaigns (user_id, netuid, mech, status, settings) VALUES (?,?,?,?,?) RETURNING id",
                        (me["id"], b.netuid, b.mechs[0], "live", json.dumps({"target": b.target})), one=True)["id"]
        return {"id": cid, "ids": [cid]}


class FakeWork:
    def __init__(self, db): self.db, self.m, self.tasks = db, FakeMining(db), []
    def day_tokens(self, wid): return 1000
    def _sandbox_state(self): return {"ready": True, "why": ""}
    def create(self, me, cid, b, ip):
        wid = self.db.q("INSERT INTO mw_comps (campaign_id, number, name, status, goal, budget) VALUES (?,?,?,?,?,?) RETURNING id",
                        (cid, b.number, b.name, b.status, b.goal, 150000), one=True)["id"]
        self.db.q("INSERT INTO mw_agents (comp_id, role, name, title, lead, active) VALUES (?,?,?,?,1,1)", (wid, "lead", "Nova", "Lead"))
        return {"comp": {"id": wid}}
    def update(self, me, wid, b):
        sets = b.model_dump(exclude_unset=True)
        self.db.q(f"UPDATE mw_comps SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), wid))
    def add_task(self, me, wid, b):
        tid = self._add_task(me, wid, b)
        return {"tasks": [{"id": tid, "title": b.title}]}

    def _add_task(self, me, wid, b, actor=None):  # mining_work.Work._add_task: the board task's id; the team's own mission is stored as NULL
        mission = getattr(b, "mission", None)
        has = "mission" in {c["name"] for c in self.db.q("PRAGMA table_info(mw_tasks)")}
        if has:
            return self.db.q("INSERT INTO mw_tasks (comp_id, title, status, priority, agent_id, mission) VALUES (?,?,?,?,?,?) RETURNING id",
                             (wid, b.title, "todo", b.priority, b.agent, mission if mission != f"comp:{wid}" else None), one=True)["id"]
        return self.db.q("INSERT INTO mw_tasks (comp_id, title, status, priority, agent_id) VALUES (?,?,?,?,?) RETURNING id",
                         (wid, b.title, "todo", b.priority, b.agent), one=True)["id"]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        seed_sources(self.db)
        seed_bittensor(self.db)
        self.o = organization.Organization(self.db)
        self.hub = FakeHub()
        self.ch = control_hub.ControlHub(self.db, self.o, FakeWork(self.db), None, self.hub)
        self.ch.pool = Sync()
        self.t = self.ch.tree(ME)
        # research before fixed tasks (task_research.py) holds a template task for its brief: the dispatch tests here test the
        # dispatch itself, so it's off; tests/unit/test_task_research.py turns it on
        from app import task_research
        self._research, task_research.ENABLED = task_research.ENABLED, False

    def tearDown(self):
        from app import task_research
        task_research.ENABLED = self._research
        self.dir.cleanup()

    def dept(self, name):
        return next(d for d in self.t["departments"] + self.t["bittensor"]["departments"] if d["name"].startswith(name))

    def team(self, name):
        return next(tm for d in self.t["departments"] + self.t["bittensor"]["departments"] for tm in d["teams"] if tm["name"].endswith(name))

    def key(self, name): return next(a["key"] for a in self.o.view(ME)["agents"] if a["name"] == name)


class Tree(Base):
    def test_a_subnet_is_a_department_and_a_competition_a_team(self):
        bt = self.t["bittensor"]
        self.assertEqual([d["name"] for d in bt["departments"]], ["SN19 · Nineteen", "SN62 · Ridges"])
        sn62 = self.dept("SN62")
        self.assertEqual(sorted(t["name"] for t in sn62["teams"]), ["SN62 · Competition 28", "SN62 · Competition 29"])
        c28 = self.team("Competition 28")
        self.assertEqual((c28["kind"], c28["comp_id"], c28["subnet"]), ("competition", 1, 62))
        self.assertEqual([a["name"] for a in c28["agents"]], ["Dora", "Rex"])  # the Director first
        self.assertFalse(any(t["comp_id"] == 3 for d in bt["departments"] for t in d["teams"]), "another user's team isn't here")

    def test_other_top_units_are_departments_and_bittensor_is_not_one_of_them(self):
        names = [d["name"] for d in self.t["departments"]]
        self.assertIn("Handshake", names)
        self.assertNotIn("Bittensor", names)
        self.assertEqual(self.t["bittensor"]["name"], "Bittensor")
        self.assertTrue(any(s["name"] == "Gus" for s in self.t["bittensor"]["staff"]))

    def test_an_assigned_specialist_shows_on_both_teams(self):
        c28 = self.team("Competition 28")
        self.o.apply(ME, "assign_unit", {"unit_id": c28["unit_id"], "key": self.key("Lena"), "role": "Python help"})
        self.ch._cache.clear()
        t = self.ch.tree(ME)
        c28 = next(tm for d in t["bittensor"]["departments"] for tm in d["teams"] if tm["comp_id"] == 1)
        lena = next(a for a in c28["agents"] if a["name"] == "Lena")
        self.assertEqual((lena["assigned"], lena["title"]), (True, "Python help"))
        self.assertTrue(any(a["name"] == "Lena" for d in t["departments"] for tm in d["teams"] + [d] for a in tm.get("agents", tm.get("staff", []))))


class Recommend(Base):
    def test_factors_reasons_and_expected_cost(self):
        r = self.ch.recommend(ME, self.team("Competition 28")["id"], control_hub.RecommendIn(skills=["python"], size=2))
        self.assertEqual(set(r["weights"]), {"capability", "performance", "availability", "compatibility", "cost", "reliability", "collaboration"})
        first = r["picks"][0]
        self.assertEqual(first["name"], "Ivo")  # python 5/5
        self.assertIn("python 5/5", first["why"])
        self.assertTrue(first["estimated"])
        self.assertEqual(first["expected_tokens_day"], control_hub.NEUTRAL_TOKENS * control_hub.EST_RUNS_DAY)
        keys = {c["key"] for c in r["candidates"]}
        self.assertNotIn("teams:1", keys)  # the team's own people aren't candidates
        self.assertNotIn(self.o.view(ME)["org"]["ceo"], keys)

    def test_staffing_follows_the_mode(self):
        ref = self.team("Competition 28")["id"]
        b = control_hub.RecommendIn(skills=["python"], size=1)
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="manual"))
        self.assertEqual(self.ch.auto_staff(ME, ref, b)["done"][0]["result"], "recommended")
        self.assertFalse(self.db.q("SELECT 1 FROM og_assign WHERE status='active' AND unit_id IS NOT NULL", one=True))
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))
        d = self.ch.auto_staff(ME, ref, b)["done"][0]
        self.assertEqual(d["result"], "requested")
        req = self.db.q("SELECT * FROM og_requests WHERE id=?", (d["request_id"],), one=True)
        self.assertEqual((req["kind"], req["status"], req["by"]), ("assign_unit", "pending", "AXoR"))
        self.ch.decide(ME, d["request_id"], True)
        self.assertTrue(self.db.q("SELECT 1 FROM og_assign WHERE status='active' AND agent_key=?", (d["key"],), one=True))
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="auto"))
        d2 = self.ch.auto_staff(ME, ref, b)["done"][0]
        self.assertEqual(d2["result"], "assigned")
        self.assertNotEqual(d2["key"], d["key"])


class Fixed(Base):
    def body(self, **kw):
        return control_hub.FixedIn(**{"netuid": 62, "mech": 0, "number": 30, "name": "Competition 30", "target_rank": 7, "budget": 200000, **kw})

    def test_validation_stops_a_second_team_on_the_same_competition(self):
        v = self.ch.validate(ME, self.body(number=28, name=""))
        self.assertFalse(v["ok"])
        self.assertEqual(next(c for c in v["checks"] if c["key"] == "competition")["level"], "stop")
        self.assertTrue(self.ch.validate(ME, self.body())["ok"])
        self.assertFalse(self.ch.validate(ME, self.body(netuid=4000))["ok"], "not on chain")

    def test_activation_makes_the_team_records_the_objective_and_staffs_it(self):
        out = self.ch.activate(ME, self.body(agents=[self.key("Lena")], objectives="Beat the median by 5%"))
        f = self.db.q("SELECT * FROM ctl_fixed WHERE comp_id=?", (out["comp_id"],), one=True)
        self.assertEqual((f["target_rank"], f["objectives"]), (7, "Beat the median by 5%"))
        w = self.db.q("SELECT * FROM mw_comps WHERE id=?", (out["comp_id"],), one=True)
        self.assertEqual((w["campaign_id"], w["budget"]), (1, 200000))  # joins the SN62 campaign that exists
        self.assertTrue(w["goal"].startswith("Reach and hold a top 7 miner rank"))
        self.assertEqual(out["department"], "sn:62")
        self.assertEqual(out["staffed"][0]["result"], "assigned")
        t = self.ch.tree(ME, True)
        self.assertTrue(any(tm["comp_id"] == out["comp_id"] and tm["fixed"]["target_rank"] == 7 for d in t["bittensor"]["departments"] for tm in d["teams"]))

    def test_a_new_subnet_gets_a_campaign_at_the_next_target(self):
        out = self.ch.activate(ME, self.body(netuid=5, number=None, name="Main"))
        self.assertEqual(self.ch.w.m.created[0].target, 10)  # top 7 → the campaign's nearest target, top 10
        self.assertEqual(out["department"], "sn:5")

    def test_the_gap_says_where_the_team_stands(self):
        d = self.ch.node(ME, self.team("Competition 28")["id"])
        self.assertEqual(d["fixed"]["gap"]["state"], "unset")
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))
        d = self.ch.node(ME, self.team("Competition 28")["id"])
        self.assertEqual((d["fixed"]["gap"]["state"], d["fixed"]["gap"]["places"]), ("behind", 4))
        self.assertTrue(self.db.q("SELECT goal FROM mw_comps WHERE id=1", one=True)["goal"].startswith("Reach and hold a top 10"))


class Tasks(Base):
    def test_routes_board_agent_and_review(self):
        c28 = self.team("Competition 28")["id"]
        t = self.ch.add_task(ME, control_hub.TaskIn(team=c28, title="Profile the miner", agent="teams:2"))
        self.assertEqual(t["route"], "board")
        self.assertTrue(self.db.q("SELECT 1 FROM mw_tasks WHERE title='Profile the miner' AND agent_id=2", one=True))
        eng = next(tm for d in self.t["departments"] for tm in d["teams"]) if any(d["teams"] for d in self.t["departments"]) else None
        unit = eng["id"] if eng else f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}"
        t2 = self.ch.add_task(ME, control_hub.TaskIn(team=unit, title="Write the launch plan", agent=self.key("Noor")))
        self.assertEqual((t2["route"], t2["status"]), ("agent", "review"))
        self.assertEqual(self.ch.task(ME, t2["id"])["result"], "the work")
        t3 = self.ch.patch_task(ME, t2["id"], control_hub.TaskPatch(agent=self.key("Lena")))
        self.assertEqual(t3["agent_key"], self.key("Lena"))
        self.assertEqual(self.ch.patch_task(ME, t2["id"], control_hub.TaskPatch(status="done"))["status"], "done")

    def test_a_board_needs_a_competition_team(self):
        unit = f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}"
        with self.assertRaises(HTTPException): self.ch.add_task(ME, control_hub.TaskIn(team=unit, title="Something", agent="", route="board"))


class Chat(Base):
    def test_a_message_with_a_picture_a_recording_and_the_web(self):
        old_s, old_t = control_hub.web_search, control_hub.transcribe
        control_hub.web_search = lambda q, n=5: ([("Ridges docs", "https://ridges.ai/docs")], "Title: Ridges docs\nURL: https://ridges.ai/docs\nText: …")
        control_hub.transcribe = lambda hub, data, name: "we should profile the miner"
        try:
            self.ch.chat(ME, "teams:1", control_hub.ChatIn(text="What do you see?", images=[control_hub.MediaIn(name="a.png", mime="image/png", data=PNG)],
                                                            audio=control_hub.MediaIn(name="v.webm", mime="audio/webm", data=PNG), video="demo.mp4", web=True, context=["team"]))
        finally:
            control_hub.web_search, control_hub.transcribe = old_s, old_t
        msgs = self.ch.messages(ME, "teams:1")
        self.assertEqual([m["role"] for m in msgs], ["user", "agent"])
        a = msgs[1]
        self.assertEqual((a["status"], a["body"]), ("done", "ok: What do you see?"))
        self.assertEqual((a["meta"]["saw"], a["meta"]["transcript"], a["meta"]["web"][0]["url"]), (1, "we should profile the miner", "https://ridges.ai/docs"))
        content = self.hub.llm.calls[-1]["messages"][-1]["content"]
        self.assertEqual(content[1]["type"], "image")
        self.assertIn("<transcript", content[0]["text"]); self.assertIn("<web_results", content[0]["text"]); self.assertIn("<team_brief>", content[0]["text"])
        self.assertIn("You are Dora, Director", self.hub.llm.calls[-1]["system"])

    def test_pictures_need_a_model_that_sees(self):
        self.hub.llm.provider = "terminal"
        with self.assertRaises(HTTPException) as e:
            self.ch.chat(ME, "teams:1", control_hub.ChatIn(text="look", images=[control_hub.MediaIn(name="a.png", mime="image/png", data=PNG)]))
        self.assertEqual(e.exception.status_code, 409)

    def test_a_proposed_task_runs_only_once_approved(self):
        self.ch.chat(ME, "teams:1", control_hub.ChatIn(text="Make it a task please"))
        rid = self.ch.messages(ME, "teams:1")[-1]["id"]
        self.assertEqual(self.ch.messages(ME, "teams:1")[-1]["meta"]["proposal"]["status"], "proposed")
        self.assertFalse(self.db.q("SELECT 1 FROM ctl_tasks", one=True))
        out = self.ch.approve_proposal(ME, "teams:1", rid)
        self.assertEqual(out["task"]["route"], "board")  # a team agent's work goes on its team's board
        with self.assertRaises(HTTPException): self.ch.approve_proposal(ME, "teams:1", rid)

    def test_history_alternates_and_files_are_read(self):
        self.ch.chat(ME, "teams:2", control_hub.ChatIn(text="first"))
        self.ch.chat(ME, "teams:2", control_hub.ChatIn(text="second", files=[control_hub.AttachIn(kind="file", id="notes.md")]))
        msgs = self.hub.llm.calls[-1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertIn('<attached_file name="notes.md">', msgs[-1]["content"])


class Ledger(Base):
    def test_one_chat_and_one_task_are_one_run_each_in_the_ledger(self):
        """log_usage inside the run, then end(): the tokens count once (after end() they'd become a second row)."""
        agent_core.init(self.db)
        self.hub.log_usage = lambda me, source, tokens, agent_id=None, model=None: agent_core.chat(me["id"], source, tokens, None, model)
        try:
            self.ch.chat(ME, "teams:1", control_hub.ChatIn(text="hello"))
            unit = f"u:{next(u['id'] for u in self.o.view(ME)['units'] if u['name'] == 'Handshake')}"
            self.ch.add_task(ME, control_hub.TaskIn(team=unit, title="Write the launch plan", agent=self.key("Noor")))
            rows = self.db.q("SELECT kind, tokens, status FROM ac_runs WHERE owner_id=7 ORDER BY id")
            self.assertEqual([(r["kind"], r["status"]) for r in rows], [("chat", "done"), ("task", "done")])
            self.assertEqual([r["tokens"] for r in rows], [100, 100])
        finally:
            agent_core._core = None


class CommandCenter(Base):
    def test_seven_days_of_runs_and_the_last_day_success_rate(self):
        """The Command Center's spend chart and success rate: one bucket per day, oldest first; running and stopped runs aren't outcomes."""
        agent_core.init(self.db)
        try:
            now, today = time.time(), agent_core._today()
            rows = [(today + 60, "done", 500), (today + 120, "failed", 100), (today + 180, "running", 0), (today + 240, "stopped", 50),
                    (today - 2 * 86400 + 600, "done", 700), (today - 2 * 86400 + 900, "lost", 0), (today - 9 * 86400, "done", 9999)]
            for st, status, tok in rows:
                self.db.q("INSERT INTO ac_runs (system, owner_id, agent_key, kind, status, tokens, started) VALUES ('hub', 7, 'hub:1', 'task', ?, ?, ?)",
                          (status, tok, min(st, now - 1)))
            v = self.ch.hub_view(ME)
            self.assertEqual(len(v["week"]), 7)
            self.assertEqual(v["week"][-1]["day"], today)
            self.assertEqual((v["week"][-1]["tokens"], v["week"][-1]["runs"], v["week"][-1]["done"], v["week"][-1]["failed"]), (650, 4, 1, 1))
            self.assertEqual((v["week"][4]["tokens"], v["week"][4]["done"], v["week"][4]["failed"]), (700, 1, 1))
            self.assertEqual(sum(d["tokens"] for d in v["week"]), 1350)  # nine days ago is outside the chart
            r = v["runs24"]
            self.assertEqual((r["done"], r["failed"]), (1, 1))
            # one definition (agent_core.outcomes): every run of the 24 hours in exactly one state, the parts add up to the total
            self.assertEqual((r["success"], r["failed"], r["running"], r["cancelled"], r["total"]), (1, 1, 1, 1, 4))
            self.assertEqual(sum(r[k] for k in ("success", "failed", "timeout", "cancelled", "restarted", "running", "other")), r["total"])
            self.assertEqual(r["success_pct"], 50.0)  # a person's stop is neither a success nor a failure
        finally:
            agent_core._core = None


if __name__ == "__main__":
    unittest.main()
