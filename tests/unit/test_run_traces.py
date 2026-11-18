"""run_traces (P2, D-022): a team's agents read their own team's task runs, read-only. Never another team's runs, review runs,
plans or Team tests benchmark missions; credentials redacted; the answer capped."""
import json, os, sys, unittest
from unittest import mock

from app import mining_work, missions

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402

KEY = "sk-ant-oat01-" + "K" * 40


class Traces(BoardBase):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("ALTER TABLE mw_runs ADD COLUMN model TEXT"); q("ALTER TABLE mw_runs ADD COLUMN error TEXT")
        q("""CREATE TABLE mw_spans (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, ts REAL, end REAL, kind TEXT, name TEXT,
             input TEXT, output TEXT, tokens INTEGER DEFAULT 0, error INTEGER DEFAULT 0)""")
        self.w._agents = lambda wid: [{"id": 1, "name": "Gus"}, {"id": 2, "name": "Devon"}]
        def run(comp, kind, status, task, error=None, mission=None, spans=()):
            rid = q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started, finished, tokens, model, error, mission) VALUES (?,?,?,?,?,1,21,0,'codex:x',?,?) RETURNING id",
                    (comp, task, 2, kind, status, error, mission), one=True)["id"]
            for k, n, out, err in spans: q("INSERT INTO mw_spans (run_id, kind, name, output, error) VALUES (?,?,?,?,?)", (rid, k, n, out, err))
            return rid
        self.failed = run(WID, "task", "failed", 7, "Devon finished without filing the work: it used all its 10 steps without calling submit_work.",
                          spans=[("model", "gpt", "→ web_read", 0)] * 10 + [("tool", "web_read", f"Authorization: Bearer {KEY}", 0)])
        self.review = run(WID, "review", "done", 7, spans=[("model", "gpt", "hidden check: expected answer 42", 0)])
        self.other = run(WID + 1, "task", "failed", 9, "another team's failure")
        q("INSERT INTO mw_tasks (id, comp_id, title, status, mission) VALUES (8, ?, 'Benchmark item', 'done', 'mx:55')", (WID,))
        self.bench = run(WID, "task", "done", 8)                               # as the board writes it: the run carries no mission

    def traces(self, **a): return self.w._traces(self.w._comp(WID) if hasattr(self.w, "_comp") else {"id": WID}, {"task_id": 0, "run_id": 0, "status": "", **a})

    def test_own_task_runs_only_with_why_they_failed(self):
        with mock.patch.object(missions, "ISOLATED", lambda mid: mid == 55):
            out = self.traces()
        ids = [r["run"] for r in out["runs"]]
        self.assertEqual(ids, [self.failed])                                   # not the review, not team WID+1, not the benchmark
        r = out["runs"][0]
        self.assertEqual((r["model_steps"], r["agent"], r["tools_used"]), (10, "Devon", ["web_read"]))
        self.assertIn("used all its 10 steps", r["error"])

    def test_secrets_are_redacted_and_hidden_checks_unreachable(self):
        self.db.q("INSERT INTO mw_spans (run_id, kind, name, output, error) VALUES (?, 'tool', 'file_read', ?, 0)", (self.failed, "pinned sha256 " + "ab" * 32))
        blob = json.dumps(self.traces(run_id=self.failed)) + json.dumps(self.traces(run_id=self.review)) + json.dumps(self.traces(run_id=self.other))
        self.assertIn("ab" * 32, blob)                                         # a sha256 pin stays readable
        self.assertNotIn(KEY, blob); self.assertNotIn("KKKKKKKK", blob); self.assertIn("[redacted]", blob)
        self.assertNotIn("expected answer", blob); self.assertNotIn("another team", blob)

    def test_the_answer_is_capped(self):
        for i in range(30):
            self.db.q("INSERT INTO mw_runs (comp_id, task_id, agent_id, kind, status, started, finished, error) VALUES (?,?,?,?,?,1,2,?)", (WID, 100 + i, 2, "task", "failed", "x" * 300))
        out = self.traces()
        self.assertLessEqual(len(out["runs"]), mining_work.TRACE_RUNS)
        self.assertLessEqual(len(json.dumps(out)), mining_work.TRACE_CHARS + 2000)

    def test_it_is_a_board_tool_and_reads_only(self):
        self.assertIn("run_traces", [t["name"] for t in mining_work.BOARD_TOOLS])
        before = self.db.q("SELECT COUNT(*) n FROM mw_runs", one=True)["n"]
        self.traces(status="failed")
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_runs", one=True)["n"], before)


if __name__ == "__main__":
    unittest.main()
