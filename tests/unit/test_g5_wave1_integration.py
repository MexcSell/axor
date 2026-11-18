"""G5 wave-1 cross-stream integration (integration branch dev/integration-g5-wave1; owner: the integration session).

Each stream's own tests prove its component. These prove the contracts *between* streams that merged here for the first time:

- V4.4 (G5-4) × D4.3 (D-004): a valid internal benchmark (technical PASS on a clean sandbox run) is read by the mission cycle and
  recorded in its technical dimension, but never meets the criteria and never appears in a decision's rests_on. Only external
  evidence meets the criteria (positive control: the same mission does reach rule 1 once the chain passes).
- R3.1 (G5-3) × D4.3 × V4.4: the register's feeds and the mission cycles never write each other's state, and sandbox failures fed
  to the register don't disturb the clean sandbox run a benchmark rests on.

Not covered here, because it isn't built: R3.3 (register rows in cycle evidence), L5.5 (improve → proposal), L5.4 (trial and
promotion), L5.6 (the closed loop). See ACCEPTANCE_MATRIX.md in g5-plan/parallel/.
"""
import json, os, sys, time, types, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_release as R  # noqa: E402
import test_mission_cycles as tc  # noqa: E402  (modules, not classes: their own tests don't run again here)
import test_g54_release_evidence as tr  # noqa: E402
from test_mission_persistent_evidence import HOT, TEAM_ACCOUNT, WID, bench_measure, chain_measure  # noqa: E402

BUSY = "The sandbox is busy (2 runs at once)"   # an io_sbx class the R3.1 feed takes (not the run's own)
QUOTA = "plan rate limit reached"               # an io_diag class the R3.1 feed takes


class Wave1(tc.Base):
    def setUp(self):
        super().setUp()
        R.Release(types.SimpleNamespace(db=self.db))  # mw_release / mw_bench with V4.3 / V4.4's columns
        tr.sbx_table(self.db.q)
        self.db.q("""CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, system TEXT, kind TEXT, ref TEXT,
                     corr TEXT, team TEXT, agent_key TEXT, status TEXT, error TEXT, score REAL, tokens INTEGER, started REAL, finished REAL)""")

    def release(self):
        return self.db.q("""INSERT INTO mw_release (comp_id, version, commit_ref, sha256, suite, suite_tasks, suite_hash, repeats, frozen, current, image_digest)
                            VALUES (?, 1, ?, NULL, 'swe-mini', 3, 'h1', 1, ?, 1, ?) RETURNING id""", (WID, tr.CAND, time.time(), tr.DIGEST), one=True)["id"]

    def bench_row(self, score, ref, rel):
        self.db.q("""INSERT INTO mw_bench (comp_id, release_id, candidate, suite, suite_tasks, suite_hash, repeats, score, comparable, ts, evidence_ref)
                     VALUES (?, ?, ?, 'swe-mini', 3, 'h1', 1, ?, 1, ?, ?)""", (WID, rel, tr.CAND, score, time.time(), ref))

    def backed_mission(self):
        """Chain rank ≤ 5 (ours ranks 7th: competition FAIL) + a frozen-suite score ≥ 0.8 backed by a clean sandbox run (0.9: technical PASS)."""
        rel = self.release()
        clean = tr.sbx(self.db.q, WID, tr.RUN)
        self.bench_row(0.9, f"sbx:{clean}", rel)
        self.fresh()
        return self.create([chain_measure(target=5), bench_measure()], keys=[HOT]), clean

    # ---------- V4.4 × D4.3 ----------
    def test_a_technical_pass_is_recorded_by_every_cycle_but_never_meets_the_criteria(self):
        mid, clean = self.backed_mission()
        recs = [self.cycle(mid, "baseline")] + [self.cycle(mid) for _ in range(5)]  # past the hold window (K-34, default 3)
        for rec in recs:
            bench = next(e for e in rec["evidence"] if e["source"] == "bench")
            self.assertEqual((bench["status"], bench["pass"], bench["basis"]["kind"]), ("valid", True, "internal_measured"))
            self.assertEqual(bench["evidence_ref"]["sandbox_run"], f"sbx:{clean}")
            self.assertEqual(rec["dimensions"]["technical"]["value"], "PASS")
            self.assertNotEqual(rec["dimensions"]["competition"]["value"], "PASS")
            self.assertNotEqual(rec["decision"]["rule"], 1, rec["decision"])
            self.assertNotIn("internal_measured", rec["decision"]["rests_on"])
            self.assertEqual(rec["hold"]["consecutive_pass"], 0)
        self.assertEqual(self.reqs(mid, "deliver"), [])

    def test_positive_control_the_same_mission_meets_its_criteria_on_external_evidence_only(self):
        mid, _ = self.backed_mission()
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.95)  # now first by emission: the chain measure passes
        recs = [self.cycle(mid) for _ in range(3)]
        last = recs[-1]
        self.assertEqual(last["decision"]["rule"], 1, last["decision"])
        self.assertTrue(last["decision"]["rests_on"])
        self.assertNotIn("internal_measured", last["decision"]["rests_on"])  # the benchmark passed too, but isn't what it rests on
        self.assertEqual(len(self.reqs(mid, "deliver")), 1)

    # ---------- R3.1 × D4.3 × V4.4 ----------
    def snap_mission(self, mid):
        q = self.db.q
        return json.dumps([q("SELECT * FROM mx_missions WHERE id=?", (mid,)), q("SELECT * FROM mx_events WHERE mission_id=? ORDER BY id", (mid,)),
                           q("SELECT * FROM mx_requests WHERE mission_id=? ORDER BY id", (mid,)),
                           q("SELECT key, status, payload FROM io_events WHERE corr=? ORDER BY id", (f"mx:{mid}",))], default=str, sort_keys=True)

    def snap_register(self):
        return json.dumps(self.db.q("SELECT * FROM io_risks ORDER BY id"), default=str, sort_keys=True)

    def test_register_feeds_and_mission_cycles_never_write_each_others_state(self):
        mid, clean = self.backed_mission()
        self.cycle(mid, "baseline")
        now = time.time()
        for _ in range(3):  # three failures of one non-own class in the team's scope, of both feed kinds
            self.db.q("INSERT INTO mw_sbx (comp_id, task_id, status, error, started) VALUES (?,?,?,?,?)", (WID, 1, "error", BUSY, now))
            self.db.q("INSERT INTO ac_runs (owner_id, system, kind, ref, corr, team, status, error, started) VALUES (?,?,?,?,?,?,?,?,?)",
                      (TEAM_ACCOUNT, "teams", "task", "mw:1", None, f"comp:{WID}", "failed", QUOTA, now))
        self.orc.diagnose(); self.orc.diagnose_sandbox()
        before = self.snap_mission(mid)
        self.assertGreaterEqual(self.orc.risk_feeds(now), 2)
        self.assertEqual(self.snap_mission(mid), before)  # the feeds touch no mission state
        fed = {r["rkey"]: r for r in self.orc.risks(TEAM_ACCOUNT, limit=500) if r["source"] in ("diagnosis", "sandbox")}
        self.assertEqual({r["mission"] for r in fed.values()}, {f"comp:{WID}"})  # the team's scope; never an invented mx: reference
        reg = self.snap_register()
        rec = self.cycle(mid)
        self.assertEqual(self.snap_register(), reg)  # a cycle writes no register row
        bench = next(e for e in rec["evidence"] if e["source"] == "bench")
        self.assertEqual((bench["status"], bench["evidence_ref"]["sandbox_run"]), ("valid", f"sbx:{clean}"))  # failures elsewhere don't touch it
        self.assertEqual(self.orc.risk_feeds(now + 60), 0)  # idempotent across a cycle in between


if __name__ == "__main__":
    unittest.main()
