"""agent_core.py: the run ledger every agent system writes to, the budget, the registry mirror; and the model-call wrapper
in llm.py that feeds them."""
import os, tempfile, threading, time, unittest

from app import agent_core
from app.auth import AuthDB
from app.llm import LLMError, Providers


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.core = agent_core.init(self.db)

    def tearDown(self):
        agent_core._local.run = None
        agent_core._core = None
        self.dir.cleanup()

    def row(self, rid): return self.db.q("SELECT * FROM ac_runs WHERE id=?", (rid,), one=True)


class Ledger(Base):
    def test_calls_in_a_run_add_up_and_the_system_count_is_kept_aside(self):
        rid = agent_core.begin("workforce", 5, "execute", ref="wf:1", agent_key="workforce:3")
        agent_core.used(100); agent_core.used(20)
        agent_core.end("done", tokens=118)
        r = self.row(rid)
        self.assertEqual((r["status"], r["tokens"], r["reported"], r["owner_id"]), ("done", 120, 118, 5))
        agent_core.used(50)  # no run open any more: counted nowhere
        self.assertEqual(self.row(rid)["tokens"], 120)

    def test_reported_tokens_stand_in_when_no_call_was_counted(self):
        rid = agent_core.begin("teams", 5, "task", ref="mw:1")
        agent_core.end("failed", tokens=40, error="boom")
        r = self.row(rid)
        self.assertEqual((r["status"], r["tokens"], r["error"]), ("failed", 40, "boom"))

    def test_a_run_left_open_is_closed_as_lost_by_the_next(self):
        a = agent_core.begin("teams", 5, "task", ref="mw:1")
        b = agent_core.begin("teams", 5, "task", ref="mw:2")
        agent_core.used(7)
        self.assertEqual(self.row(a)["status"], "lost")
        self.assertEqual((self.row(b)["status"], self.row(b)["tokens"]), ("running", 7))

    def test_end_by_ref_from_another_thread_leaves_this_threads_run(self):
        mine = agent_core.begin("company", 5, "task", ref="co:1")
        t = threading.Thread(target=lambda: agent_core.begin("teams", 5, "task", ref="mw:9")); t.start(); t.join()
        agent_core.end("done", ref="mw:9")
        agent_core.end("done", ref="mw:404")  # nothing open by that ref: nothing happens
        agent_core.used(3)
        self.assertEqual(self.row(mine)["tokens"], 3)
        self.assertEqual(self.db.q("SELECT status FROM ac_runs WHERE ref='mw:9'", one=True)["status"], "done")

    def test_chats_become_their_own_runs_only_outside_a_run(self):
        agent_core.chat(5, "chat", 30, "hub:2", "anthropic:x")
        agent_core.begin("company", 5, "task"); agent_core.chat(5, "company", 99)
        rows = self.db.q("SELECT system, kind, tokens, agent_key FROM ac_runs WHERE status='done'")
        self.assertEqual(rows, [{"system": "hub", "kind": "chat", "tokens": 30, "agent_key": "hub:2"}])

    def test_record_never_touches_this_thread(self):
        agent_core.record("workflow", 5, "engineer", "mb:r1")
        agent_core.used(10)
        agent_core.record("workflow", 5, "engineer", "mb:r1", status="done", cost=0.25)
        r = self.db.q("SELECT * FROM ac_runs WHERE ref='mb:r1'", one=True)
        self.assertEqual((r["status"], r["tokens"], r["cost"]), ("done", 0, 0.25))

    def test_a_restart_closes_open_runs(self):
        rid = agent_core.begin("teams", 5, "task")
        agent_core._local.run = None
        agent_core.init(self.db)
        self.assertEqual(self.row(rid)["status"], "lost")

    def test_workbench_runs_go_on_through_a_restart(self):
        agent_core.record("workflow", 5, "engineer", "mb:r2")
        agent_core.init(self.db)  # the web pod restarts; the run goes on on the host
        self.assertEqual(self.db.q("SELECT status FROM ac_runs WHERE ref='mb:r2'", one=True)["status"], "running")
        agent_core.record("workflow", 5, "engineer", "mb:r2", status="done", cost=0.3)
        r = self.db.q("SELECT status, cost FROM ac_runs WHERE ref='mb:r2'", one=True)
        self.assertEqual((r["status"], r["cost"]), ("done", 0.3))

    def test_a_run_swept_as_lost_takes_its_real_outcome(self):
        self.db.q("INSERT INTO ac_runs (system, owner_id, kind, ref, status, started) VALUES ('workflow', 5, 'check', 'mb:r3', 'lost', 0)")
        agent_core.record("workflow", 5, "check", "mb:r3", status="failed", error="eval crashed")
        self.assertEqual(self.db.q("SELECT status, error FROM ac_runs WHERE ref='mb:r3'", one=True), {"status": "failed", "error": "eval crashed"})

    def test_the_run_context_manager_marks_failures(self):
        with self.assertRaises(ValueError):
            with agent_core.run("missions", 5, "direct", ref="mx:1"): raise ValueError("no")
        r = self.db.q("SELECT status, error FROM ac_runs WHERE ref='mx:1'", one=True)
        self.assertEqual(r, {"status": "failed", "error": "no"})


class Budget(Base):
    def test_off_by_default(self):
        agent_core.begin("teams", 5, "task"); agent_core.used(10 ** 9)
        self.assertIsNone(agent_core.over())

    def test_a_used_up_limit_stops_the_owners_runs_only(self):
        self.core.set_cap(5, 100, "alice")
        agent_core.begin("teams", 5, "task"); agent_core.used(60)
        self.assertIsNone(agent_core.over())
        agent_core.chat(5, "chat", 0, None)  # nothing
        agent_core.end("done")
        agent_core.chat(5, "chat", 50)  # chats count toward the day too
        agent_core.begin("workforce", 5, "execute")
        self.assertIn("110 of your 100", agent_core.over())
        agent_core.begin("workforce", 6, "execute")
        self.assertIsNone(agent_core.over())

    def test_agent_hq_is_never_gated(self):
        self.core.set_cap(0, 1, "admin")
        agent_core.begin("hq", 0, "patrol"); agent_core.used(500)
        self.assertIsNone(agent_core.over())

    def test_view(self):
        self.core.set_cap(5, 1000, "alice")
        agent_core.begin("teams", 5, "task"); agent_core.used(40); agent_core.end()
        agent_core.chat(5, "chat", 10)
        b = self.core.budget(5)
        self.assertEqual((b["daily_tokens"], b["today"]), (1000, 50))
        self.assertEqual([x["system"] for x in b["by_system"]], ["teams", "hub"])


class Wrapper(Base):
    """Providers.completer / structured: tokens to the open run, the budget checked before each call."""
    def providers(self):
        p = object.__new__(Providers)
        p._completer = lambda choice, effort="medium": ((lambda s, t, m: ([{"type": "text", "text": "hi"}], "end_turn", 25)), "fake:m")
        def structured(choice, system, prompt, schema, name="result", on_usage=None, effort="low", messages=None):
            on_usage(9); return {"ok": True}
        p._structured = structured
        return p

    def test_completer_counts_into_the_run(self):
        rid = agent_core.begin("teams", 5, "task")
        call, label = self.providers().completer("auto")
        call("sys", [], [])
        self.assertEqual((label, self.row(rid)["tokens"]), ("fake:m", 25))

    def test_structured_chains_on_usage_by_keyword_and_by_position(self):
        rid = agent_core.begin("teams", 5, "task")
        p, got = self.providers(), []
        p.structured("auto", "s", "p", {}, "n", on_usage=got.append)
        p.structured("auto", "s", "p", {}, "n", got.append)
        p.structured("auto", "s", "p", {})
        self.assertEqual((got, self.row(rid)["tokens"]), ([9, 9], 27))

    def test_a_used_up_budget_refuses_the_call(self):
        self.core.set_cap(5, 10, "alice")
        agent_core.begin("teams", 5, "task"); agent_core.used(10)
        call, _ = self.providers().completer("auto")
        with self.assertRaises(LLMError): call("sys", [], [])
        with self.assertRaises(LLMError): self.providers().structured("auto", "s", "p", {})


class Registry(Base):
    def test_sync_mirrors_and_marks_the_gone(self):
        self.db.q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, status TEXT)")
        self.db.q("CREATE TABLE wf_agents (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, title TEXT, role TEXT, team TEXT, status TEXT)")
        self.db.q("INSERT INTO custom_agents VALUES (1, 5, 'Scout', 'analyst', 'live'), (2, 6, 'Other', 'x', 'live')")
        self.db.q("INSERT INTO wf_agents VALUES (3, 5, 'Atlas', 'CEO', 'ceo', 'exec', 'active')")
        self.core.sync(force=True)
        got = {r["key"]: (r["owner_id"], r["name"], r["status"]) for r in self.db.q("SELECT * FROM ac_agents WHERE system!='hq'")}
        self.assertEqual(got, {"hub:1": (5, "Scout", "live"), "hub:2": (6, "Other", "live"), "workforce:3": (5, "Atlas", "active")})
        self.db.q("DELETE FROM custom_agents WHERE id=2")
        self.core.sync(force=True)
        self.assertEqual(self.db.q("SELECT status FROM ac_agents WHERE key='hub:2'", one=True)["status"], "gone")
        self.assertTrue(self.db.q("SELECT 1 FROM ac_agents WHERE system='hq'"), "Agent HQ's staff are listed from hq.py")

    def test_agent_stats_from_the_ledger(self):
        agent_core.begin("teams", 5, "task", agent_key="teams:1"); agent_core.used(5)
        agent_core.begin("teams", 5, "task", agent_key="teams:2"); agent_core.end("failed")
        s = self.core.agent_stats((5,), time.time() - 3600)
        self.assertEqual((s["teams:1"]["running"], s["teams:1"]["failed"], s["teams:1"]["tokens"]), (False, True, 5))  # lost when the next began
        self.assertTrue(s["teams:2"]["failed"])


if __name__ == "__main__":
    unittest.main()
