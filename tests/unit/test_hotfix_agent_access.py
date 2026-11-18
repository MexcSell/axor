"""Owner decisions 2026-11-17 (docs/engineering/OWNER_DECISIONS_2026-11-17_AGENT_ACCESS.md), the SN61 team's access and planning:
- limits: 24 tool calls a task run, 1000 files / 10 MB a workspace, a team run's CLI turn 300 s (600 s since the afternoon) (llm.turn_limit on the team pool only);
- failures: an expired or revoked Claude Code login is a provider/login failure, not "the task itself", and runs already diagnosed
  as 'task' are re-filed once;
- the lead's plan: every blocked task with its question, the counts and room left, the roadmap by id, and milestone changes applied."""
import os, sys, threading, time, unittest
from unittest import mock

from app import llm, mining_crew, mining_work, orchestrator as orc

sys.path.insert(0, os.path.dirname(__file__))
from test_orchestrator import G5  # noqa: E402

WID = 4


class Limits(unittest.TestCase):
    def test_the_raised_limits(self):
        self.assertEqual(mining_work.TOOL_CALLS, 24)
        self.assertEqual((mining_work.MAX_FILES, mining_work.FILE_BYTES, mining_work.FILES_BYTES), (1000, 300_000, 10_000_000))
        self.assertEqual(mining_work.TEAM_TURN_S, 600)  # 300 in the morning of 11-17; 600 from the afternoon (test_token_waste)

    def test_turn_limit_is_per_thread_and_restored(self):
        base = llm._cli_timeout("low")
        self.assertEqual(base, int(llm.CLI_TIMEOUT * .5))
        with llm.turn_limit(300):
            self.assertEqual(llm._cli_timeout("low"), 300)
            self.assertEqual(llm._cli_timeout("high"), 300)  # the caller's own limit, whatever the effort
            seen = []
            t = threading.Thread(target=lambda: seen.append(llm._cli_timeout("low"))); t.start(); t.join()
            self.assertEqual(seen, [base])  # another thread keeps the default
            with llm.turn_limit(500): self.assertEqual(llm._cli_timeout("low"), 500)
            self.assertEqual(llm._cli_timeout("low"), 300)
            with llm.turn_limit(0): self.assertEqual(llm._cli_timeout("low"), 300)  # falsy: no change
        self.assertEqual(llm._cli_timeout("low"), base)

    def test_mission_turns_stay_under_their_lease(self):
        from app import missions
        self.assertLess(llm._cli_timeout("high"), missions.LEASE)  # the default was not raised: only team runs get TEAM_TURN_S

    def test_every_team_pool_job_runs_under_the_team_turn(self):
        pool = mining_work._TeamPool(2)
        try:
            self.assertEqual(pool.submit(llm._cli_timeout, "low").result(5), mining_work.TEAM_TURN_S)
            self.assertEqual(pool.submit(lambda a, b=0: a + b, 1, b=2).result(5), 3)  # args and kwargs pass through
        finally: pool.shutdown()
        self.assertEqual(llm._cli_timeout("low"), int(llm.CLI_TIMEOUT * .5))


class LoginFailures(G5):
    MSGS = (llm.TOKEN_REJECTED,
            "The server Claude Code login doesn't work (the token in CLAUDE_CODE_OAUTH_TOKEN is missing, expired or was revoked).",
            "Your Claude Code login doesn't work any more (the token expired or was revoked).")

    def test_login_refusals_are_provider_failures_with_a_credential_flag(self):
        for m in self.MSGS:
            self.assertEqual(orc.fail_class("failed", m), "provider", m)
            self.assertTrue(orc.recognize("failed", m)["credential"], m)
        self.assertEqual(orc.fail_class("failed", "The miner's tests failed: 3 assertions"), "task")  # the task's own failure stays

    def test_runs_filed_as_task_are_refiled_once(self):
        o = orc.init(self.db)
        ago = time.time() - 3600
        ids = [self.run_row(system="teams", kind="report", status="failed", error=llm.TOKEN_REJECTED, team="comp:4", started=ago, finished=ago) for _ in range(3)]
        own = self.run_row(system="teams", kind="task", status="failed", error="The miner's tests failed", team="comp:4", started=ago, finished=ago)
        with mock.patch.object(orc, "fail_class", lambda st, e: "task"):  # as the old classifier filed them
            o.diagnose()
        self.assertEqual({r["cls"] for r in self.db.q("SELECT cls FROM io_diag")}, {"task"})
        o._rediagnosed = False
        o.diagnose()  # nothing new to diagnose; the once-a-process pass re-files the three
        rows = {r["run_id"]: r for r in self.db.q("SELECT * FROM io_diag")}
        self.assertEqual([rows[i]["cls"] for i in ids], ["provider"] * 3)
        self.assertEqual(rows[own]["cls"], "task")
        g = o.guidance(7, "Top 1 miner", team="comp:4")
        self.assertEqual(sorted((f["cls"], f["n"]) for f in g["failures"]), [("provider", 3), ("task", 1)])
        before = rows[ids[0]]["ts"]
        self.assertEqual(o._rediagnose(), 0)  # idempotent
        self.assertEqual(self.db.q("SELECT ts FROM io_diag WHERE run_id=?", (ids[0],), one=True)["ts"], before)  # window unchanged


class LLM:
    def __init__(self, out=None): self.prompts, self.out = [], out or {"summary": "Ship.", "tasks": [], "milestones": []}
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low"):
        self.prompts.append((system, prompt, schema))
        return self.out


class LeadPlan(G5):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, status TEXT, agent_id INTEGER,
             summary TEXT, question TEXT, note TEXT, hold TEXT, updated REAL)""")
        q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT)")
        q("INSERT INTO mw_agents VALUES (1, ?, 'Morgan', 'Director', 'Leads'), (2, ?, 'Clara', 'Test Engineer', 'Tests')", (WID, WID))
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, updated REAL)"); q("INSERT INTO mw_comps (id) VALUES (?)", (WID,))
        q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, ts REAL, agent_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        q("""CREATE TABLE mw_milestones (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, starts TEXT, due TEXT,
             status TEXT, agent_id INTEGER, created REAL, updated REAL)""")
        for t, d, s in (("Understand the competition", "2026-11-13", "doing"), ("A first working miner", "2026-11-16", "todo"), ("Ship", "2099-01-01", "todo")):
            q("INSERT INTO mw_milestones (comp_id, title, due, status, created, updated) VALUES (?,?,?,?,0,0)", (WID, t, d, s))
        q("INSERT INTO mw_milestones (comp_id, title, due, status, created, updated) VALUES (99, 'Another team', '2026-11-20', 'todo', 0, 0)")
        for i in range(70): q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, updated) VALUES (?,?, 'done', 2, ?)", (WID, f"Old {i}", i))
        q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, question, updated) VALUES (?, 'Write detectors', 'blocked', 2, 'Which files may be deleted?', 1)", (WID,))
        for _ in range(3): q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, hold, updated) VALUES (?, 'Held', 'todo', 2, 'budget', 0)", (WID,))
        for i in range(5): q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, updated) VALUES (?,?, 'todo', 2, 0)", (WID, f"New {i}"))

    def work(self, llm_):
        w = mining_work.Work.__new__(mining_work.Work)
        w.db = self.db
        w.m = mock.Mock(); w.m._campaign.return_value = {"user_id": 7, "netuid": 61}; w.m._title.return_value = "SN61"; w.m.hub.llm = llm_
        w.web = mock.Mock(); w.web.lead_note.return_value = ""
        w._comp = lambda wid: {"id": wid, "campaign_id": 1, "name": "Competition 1", "goal": "Top 1", "budget": 1}
        w._context = lambda wc, c: ("Context.", None)
        w._plan_prompt = lambda wid: (5, "")
        w._team = w._rules = w._directive = w._label = lambda *a: ""
        w._recall = lambda *a: ""
        w._agents = lambda wid: self.db.q("SELECT * FROM mw_agents WHERE comp_id=?", (wid,))
        w._span = lambda *a, **k: None
        w._end = lambda *a, **k: None
        w._said = lambda *a, **k: None
        w._by_name = lambda wid: {}
        w._enqueue = lambda tid: 0
        w.mission_of_origin = lambda ref: None
        crew = mining_crew.Crew.__new__(mining_crew.Crew)
        crew.db, crew.w = self.db, w
        w.crew = crew
        w._event = mining_work.Work._event.__get__(w)
        return w

    def test_the_plan_sees_every_blocked_question_counts_holds_and_the_roadmap(self):
        w = self.work(LLM())
        w._plan(WID, 1, 50, "anthropic:m", "", False)
        system, prompt, schema = w.m.hub.llm.prompts[0]
        self.assertIn("#71 Write detectors (Clara) asks: Which files may be deleted?", prompt)  # older than the newest 60 rows
        self.assertIn("9 open of at most 400 (1 blocked, 70 done, 8 todo).", prompt)
        self.assertIn("Waiting, not started: 3 held for budget.", prompt)
        self.assertIn("- id 1 [doing] Understand the competition, due 2026-11-13 (OVERDUE)", prompt)
        self.assertNotIn("(OVERDUE)", prompt.split("- id 3 ")[1].split("\n")[0])
        self.assertNotIn("Another team", prompt)
        self.assertEqual(prompt.count("Write detectors"), 1)  # not listed twice
        self.assertIn("milestones", schema["properties"])
        self.assertIn("milestones:", system)

    def test_a_full_board_says_so(self):
        w = self.work(LLM())
        with mock.patch.object(mining_work, "MAX_TASKS", 9):
            text = w._plan_board(WID, w._board(WID))
        self.assertIn("The board is full", text)

    def test_the_leads_milestone_changes_are_applied_to_its_own_roadmap_only(self):
        out = {"summary": "Roadmap current.", "tasks": [], "milestones": [
            {"id": 1, "status": "done", "due": ""}, {"id": 2, "status": "doing", "due": "2026-11-21"},
            {"id": 4, "status": "done", "due": ""},            # another team's milestone: ignored
            {"id": 3, "status": "todo", "due": "Nov 30"},      # nothing changes: same status, bad date
            {"id": "x", "status": "done", "due": ""}]}         # not an id
        w = self.work(LLM(out))
        w._plan(WID, 1, 51, "anthropic:m", "", False)
        m = {r["id"]: r for r in self.db.q("SELECT * FROM mw_milestones")}
        self.assertEqual((m[1]["status"], m[1]["due"]), ("done", "2026-11-13"))
        self.assertEqual((m[2]["status"], m[2]["due"]), ("doing", "2026-11-21"))
        self.assertEqual((m[3]["status"], m[3]["due"]), ("todo", "2099-01-01"))
        self.assertEqual(m[4]["status"], "todo")
        ev = [r["text"] for r in self.db.q("SELECT text FROM mw_events WHERE comp_id=? AND text LIKE '%kept the roadmap%' ORDER BY id", (WID,))]
        self.assertEqual(ev, ["Morgan kept the roadmap current: “Understand the competition”: marked it done",
                              "Morgan kept the roadmap current: “A first working miner”: marked it in progress and moved it from 2026-11-16 to 2026-11-21"])

    def test_a_plan_without_milestones_changes_nothing(self):
        w = self.work(LLM({"summary": "Old shape.", "tasks": []}))  # a reply without the field (an older model or fake)
        w._plan(WID, 1, 52, "anthropic:m", "", False)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_milestones WHERE updated>0", one=True)["n"], 0)


if __name__ == "__main__":
    unittest.main()
