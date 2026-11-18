"""The G5 mission-level acceptance scenario (Consolidated Implementation Directive §5; the plan's T-13 on fakes), on a synthetic
competition fixture: team SN62 competition 28, one persistent mission, one frozen release, scripted chain samples.

It runs the real code of every stream together, in the order a mission lives: D-004 (persistent mission, evidence reader,
cycles and decisions), G5-3 (register feeds), G5-4 (VM runner job records, the score from the job's own output, release
provenance), G5-5 (verified-only knowledge, the promotion gate on team agents). One scenario, seven stages; each stage asserts
the record that proves it and the ids that link it to the stage before.

What is real here and what is not:
- Real: every decision, record, rule and id chain inside AXoR.
- Stand-ins: the VM (tests/unit/test_vm_runner.FakeRunner hands over what a VM would, through the real finish()), the chain
  (scripted samples), and no model at all: nothing here plans, writes code or answers. So this proves the lifecycle's plumbing
  and rules on fixtures. It is not a mission executed by agents, and not an operational result.

The stages this scenario cannot run are named in GAPS and printed with the result (the line starting @@G5-ACCEPTANCE), so a
green run never reads as "the whole lifecycle works".
"""
import hashlib, json, os, sys, time, types, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import evolution as evo, mining_release as R, mining_upgrade, runner as V  # noqa: E402
import test_mission_cycles as tc  # noqa: E402  (modules, not classes: their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402
from test_g54_release_evidence import sbx_table  # noqa: E402
from test_mission_persistent_evidence import HOT, OWNER, TEAM_ACCOUNT, WID, bench_measure, chain_measure  # noqa: E402

BASE_TEXT = "Review every change for failing tests before you approve it."
CAND_TEXT = "Review every change for failing tests and run the frozen benchmark before you approve it."
BUSY = "The sandbox is busy (2 runs at once)"
GAPS = [  # stage, what the scenario does not exercise, status, why
    (2, "The team lead's plan: strategy, task breakdown, specialist selection, budget estimate", "NOT TESTED HERE", "needs a model; covered with a scripted model by the board's own suites"),
    (2, "A corrective mission running after the Owner approves it", "NOT TESTED HERE", "the approval starts an ordinary one-shot mission, which needs a model"),
    (3, "Agents doing the work (writing the candidate, choosing to run the benchmark)", "NOT TESTED HERE", "no model in this scenario; the job records are made by the same code an agent's tool call reaches"),
    (3, "A real VM job inside this scenario", "NOT TESTED HERE", "a stand-in hands over the VM's result; real VM jobs ran in local staging (runner-staging/)"),
    (4, "External evidence from a registered miner or a designated evaluator", "BLOCKED", "the Owner's external actions D-1 to D-3; the chain here is scripted"),
    (5, "A lesson written from this mission's verified outcome", "NOT IMPLEMENTED", "persistent-mission cycles write no lessons; lessons come from one-shot missions when they end"),
    (6, "Anyone but a person writing the answer's new instructions", "NOT TESTED HERE", "the cycle records the gap (L5.5); a person answers it with instructions typed here, no model drafts them"),
    (6, "The team making a better candidate because of the new instructions", "NOT TESTED HERE", "the scenario freezes a second artifact and scripts its scores; nothing here shows instructions cause a better artifact"),
    (6, "Monitoring after promotion and automatic rollback for team agents", "NOT IMPLEMENTED", "rollback is a person's action here"),
    (7, "A competition improvement caused by the promoted change", "NOT CLAIMED", "the improvement shown is on the internal frozen suite; the chain's change is scripted"),
    (7, "The mission comparing the measure after a promotion with the value that opened the gap (L5.6)", "NOT IMPLEMENTED", "the next cycle names the gap proposal, its answer and the version ids; it draws no conclusion from them"),
]


class Ov:
    def _agents_ok(self, me): return True


def analytics_targets(db):
    """The Owner's K-14 targets as Analytics computes them (analytics.targets), over everything on record."""
    from app import analytics
    return analytics.Analytics(db, None).targets(0)


class Lifecycle(tc.Base):
    def setUp(self):
        super().setUp()
        self._base = V.BASE_SHA; V.BASE_SHA = tv.BASE
        q = self.db.q
        q("DROP TABLE IF EXISTS mw_sbx"); sbx_table(q); q("ALTER TABLE mw_sbx ADD COLUMN net TEXT")
        q("DROP TABLE IF EXISTS mw_files")
        q("""CREATE TABLE mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT, size INTEGER, agent_id INTEGER,
             updated REAL, UNIQUE (comp_id, path))""")
        for p, t in tv.FILES.items(): q("INSERT INTO mw_files (comp_id, path, content, size) VALUES (?,?,?,?)", (WID, p, t, len(t)))
        q("DROP TABLE IF EXISTS mw_agents")
        q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT, instructions TEXT, model TEXT)")
        q("INSERT INTO mw_agents (id, comp_id, name, instructions) VALUES (2, ?, 'Rae', ?)", (WID, BASE_TEXT))
        q("""CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, system TEXT, kind TEXT, ref TEXT,
             corr TEXT, team TEXT, agent_key TEXT, status TEXT, error TEXT, score REAL, tokens INTEGER, model TEXT, started REAL, finished REAL)""")
        self.work = tv.board(self.db)
        self.work._own = lambda me, wid: ({"id": wid}, {"id": 1})
        self.rel = R.Release(types.SimpleNamespace(db=self.db))
        self.rid = q("""INSERT INTO mw_release (comp_id, version, commit_ref, sha256, suite, suite_tasks, suite_hash, repeats, frozen, current, image_digest)
                        VALUES (?, 1, ?, NULL, 'swe-mini', 16, 'h1', 1, ?, 1, ?) RETURNING id""", (WID, tv.CAND, time.time(), tv.D2), one=True)["id"]
        self.up = mining_upgrade.Upgrade(self.work)
        self.ev = evo.Evolution(self.db, Ov(), None, None); self.ev.teams = self.work
        self.mx.evolution = self.ev                                           # as main.py wires it (L5.5)
        self.owner, self.run_no, self.report = self.me(OWNER), 500, []

    def tearDown(self):
        V.BASE_SHA = self._base; self.ev.pool.shutdown(wait=True); db = self.db
        super().tearDown(); tv.close_db(db)

    def stage(self, n, name, **proof): self.report.append({"stage": n, "name": name, "status": "PASS", "proof": proof})

    def benchmark(self, score, filed=None):
        """One benchmark the way a team makes it: a VM runner job (bench) writes the score file; record_benchmark files the row."""
        self.run_no += 1
        self.work.runner = tv.FakeRunner(files={"bench_out/live.json": json.dumps({"score": score, "tasks": 16})})
        job = self.work._docker_job({"id": WID}, {"netuid": 62}, tv.spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json"),
                                    task=5, run=self.run_no, agent={"id": 2, "name": "Rae"})
        r = self.rel.current(WID)
        row = self.rel.record(WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score if filed is None else filed},
                              task=5, agent=2, run=self.run_no)
        return job, row

    def freeze_candidate(self):
        """The artifact the team made during the trial, frozen on the same suite: a new current release."""
        self.db.q("UPDATE mw_release SET current=0 WHERE comp_id=?", (WID,))
        return self.db.q("""INSERT INTO mw_release (comp_id, version, commit_ref, sha256, suite, suite_tasks, suite_hash, repeats, frozen, current, image_digest)
                            VALUES (?, 2, 'bcd2345ef67890', NULL, 'swe-mini', 16, 'h1', 1, ?, 1, ?) RETURNING id""", (WID, time.time(), tv.D1), one=True)["id"]

    def bench_of(self, rec): return next(e for e in rec["evidence"] if e["source"] == "bench")

    def test_the_mission_lifecycle_on_a_synthetic_competition(self):
        q = self.db.q
        # ---- Stage 1: mission understanding ----
        now = time.time()
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (901, ?, 90, 'worked', 'Reach the top of the SN62 competition: benchmark every candidate on the frozen suite first', 'verified', ?)", (OWNER, now))
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (902, ?, 91, 'failed', 'Reach the top of the SN62 competition: submit without a benchmark, it is faster', 'failed', ?)", (OWNER, now))
        self.fresh()                                                           # the chain: our key ranks 7th
        mid = self.create([chain_measure(target=5), bench_measure()], keys=[HOT])
        m = self.m(mid)
        g = self.orc.guidance(OWNER, "Reach the top 10 on SN62 competition 28")
        self.assertEqual([x["id"] for x in g["lessons"]], [901])               # earlier experience: the verified lesson only (L5.2)
        base_rec = self.cycle(mid, "baseline")
        self.assertEqual((m["persistent_team"], m["status"]), (WID, "monitoring"))
        self.assertEqual((base_rec["dimensions"]["competition"]["value"], self.bench_of(base_rec)["status"]), ("FAIL", "missing"))
        self.stage(1, "Mission understanding", mission=f"mx:{mid}", team=f"comp:{WID}", measures=[e["metric"] for e in base_rec["evidence"]],
                   lessons_given=[901], lessons_withheld=[902], baseline_cycle=base_rec["n"], competition="FAIL (rank 7, target 5)", technical="no benchmark yet")

        # ---- Stage 2: planning (as far as it needs no model) ----
        self.fresh(mine_em=0.001)                                              # the chain: we fell behind since the baseline
        rec = self.cycle(mid)
        self.assertEqual((rec["decision"]["rule"], rec["decision"]["kind"]), (4, "correct"), rec["decision"])
        cor = self.reqs(mid, "corrective")
        self.assertEqual(len(cor), 1)
        self.assertNotIn("internal_measured", rec["decision"]["rests_on"])
        (gap,) = q("SELECT * FROM ev_proposals WHERE origin='mission'")                # L5.5: the same decision recorded the gap it measured as a proposal
        gsig = json.loads(gap["signal"])
        self.assertEqual((gap["user_id"], gap["target_key"], gap["status"], gsig["mission"], gsig["cycle"], gsig["values"]["previous"]),
                         (TEAM_ACCOUNT, f"comp:{WID}", "proposed", f"mx:{mid}", rec["n"], 7))
        self.assertEqual(rec["improve"]["measure"], gsig["measure"])
        gap_cycle = rec["n"]
        self.stage(2, "Planning", cycle=rec["n"], decision=rec["decision"]["kind"], reason=rec["decision"]["reason"][:160], corrective_request=cor[0]["id"],
                   gap_proposal=gap["id"], gap_measure=gsig["measure"]["id"], gap_values=gsig["values"],
                   needs="the Owner's approval; then an ordinary one-shot mission with its own plan gate")

        # ---- Stage 3: execution, with a temporary problem on the way ----
        for _ in range(3): q("INSERT INTO mw_sbx (comp_id, task_id, status, error, started) VALUES (?,?,?,?,?)", (WID, 5, "error", BUSY, now))
        self.orc.diagnose_sandbox()
        fed = self.orc.risk_feeds(time.time())
        risks = [r for r in self.orc.risks(TEAM_ACCOUNT, limit=500) if r["source"] == "sandbox"]
        self.assertGreaterEqual(fed, 1); self.assertEqual({r["mission"] for r in risks}, {f"comp:{WID}"})
        runs = [self.benchmark(0.60, filed=0.90) for _ in range(3)]            # the agent files 0.90 each time; the jobs' own files say 0.60
        job, row = runs[-1]
        s = q("SELECT * FROM mw_sbx WHERE id=?", (job["sbx"],), one=True)
        self.assertEqual((s["services"], s["status"], s["exit_code"], s["run_id"], s["agent_id"], s["task_id"]), ("vm-docker", "done", 0, self.run_no, 2, 5))
        kept = V.stored(self.db, WID, job["sbx"])
        self.assertEqual((kept["environment"]["base_disk_sha256"], kept["inputs"]["job_sha256"]), (tv.BASE, job["inputs"]["job_sha256"]))
        self.stage(3, "Execution", jobs=[j["sbx"] for j, _ in runs], run_ids=list(range(self.run_no - 2, self.run_no + 1)), agent="teams:2", task=5,
                   environment={"base_disk_sha256": tv.BASE[:12], "job_sha256": job["inputs"]["job_sha256"][:12], "peak_memory_mb": job["stats"]["containers"]["api"]["peak_memory_mb"]},
                   temporary_problem={"class": "sandbox busy ×3", "register_rows": [r["rkey"] for r in risks]})

        # ---- Stage 4: evaluation ----
        self.assertEqual((row["evidence_ref"], row["score"], row["score_source"]), (f"job:{job['sbx']}", 0.60, "job_output"))
        rec = self.cycle(mid)
        b = self.bench_of(rec)
        self.assertEqual((b["status"], b["value"], b["pass"], b["evidence_ref"]["sandbox_run"], b["evidence_ref"]["score_source"]),
                         ("valid", 0.60, False, f"job:{job['sbx']}", "read from the job's output file"))
        self.assertEqual((rec["dimensions"]["technical"]["value"], rec["dimensions"]["competition"]["value"]), ("FAIL", "FAIL"))
        self.assertEqual(b["evidence_ref"]["job"]["inputs"]["job_sha256"], job["inputs"]["job_sha256"])       # mission → cycle → bench row → job → inputs
        self.assertEqual((b["evidence_ref"]["release"], b["evidence_ref"]["image_digest"]), (self.rid, tv.D2))
        bench_row = b["evidence_ref"]["bench_row"]
        self.stage(4, "Evaluation", cycle=rec["n"], bench_row=bench_row, evidence_ref=f"job:{job['sbx']}", measured=0.60, filed_by_agent=0.90, target=0.8,
                   technical="FAIL (valid, measured)", competition="FAIL (external, scripted chain)", release=self.rid)

        # ---- Stage 5: learning ----
        g = self.orc.guidance(OWNER, "Reach the top 10 on SN62 competition 28")
        self.assertEqual([x["id"] for x in g["lessons"]], [901])               # still the verified lesson only: nothing unverified reached a planner
        self.assertEqual(q("SELECT COUNT(*) n FROM mx_lessons WHERE mission_id=?", (mid,), one=True)["n"], 0)  # and this mission wrote none (see GAPS)
        self.stage(5, "Learning", verified_lessons_to_planners=[901], observations_kept_for_people=[902], register_rows=len(risks),
                   lessons_from_this_mission=0)

        # ---- Stage 6: evolution ----
        self.assertEqual(self.ev.set_experiments(self.owner, WID, evo.OptIn(on=True))["on"], True)
        team = self.me(TEAM_ACCOUNT)                                           # the gap belongs to the team's account: it answers, trials and promotes
        with self.assertRaises(Exception): self.ev.promote(team, gap["id"])    # the gap itself is never promoted
        ans = self.ev.answer(team, gap["id"], evo.AnswerIn(agent=2, title="Benchmark before approving", hypothesis="The frozen-suite score is 0.60 against a target of 0.8", instructions=CAND_TEXT))
        pid = ans["id"]
        self.assertEqual((ans["signal"]["from"], ans["signal"]["mission"], ans["signal"]["cycle"]), (gap["id"], f"mx:{mid}", gap_cycle))
        self.owner = team                                                      # from here "the person" is the team's account
        self.ev.trial_start(self.owner, pid)
        self.assertEqual(q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"], CAND_TEXT)
        rid2 = self.freeze_candidate()                                         # stand-in for the team's work under the trial's instructions: a new candidate, frozen on the same suite
        cand = [self.benchmark(0.85) for _ in range(3)]
        p = self.ev.trial_end(self.owner, pid)
        e = p["evidence"]
        self.assertEqual((p["status"], p["basis"], e["baseline"], e["candidate"], e["cases"]), ("verified", "measured_internal", 60.0, 85.0, 3))
        self.assertEqual((e["candidate_rows"], e["baseline_release"], e["candidate_releases"]),
                         ([q("SELECT id FROM mw_bench WHERE evidence_ref=?", (f"job:{j['sbx']}",), one=True)["id"] for j, _ in cand], self.rid, [rid2]))
        self.assertEqual(q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"], BASE_TEXT)   # a trial never promotes
        with self.assertRaises(Exception): self.ev.promote(self.owner, pid, by_policy=True)                         # nor does the policy
        done = self.ev.promote(self.owner, pid)
        self.assertEqual((done["status"], done["decision"], q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"]), ("promoted", "human", CAND_TEXT))
        closed = q("SELECT status, signal FROM ev_proposals WHERE id=?", (gap["id"],), one=True)
        self.assertEqual((closed["status"], json.loads(closed["signal"])["answered"]["proposal"]), ("answered", pid))
        self.stage(6, "Evolution", gap_proposal=gap["id"], gap_from=f"mx:{mid} cycle {gap_cycle}", answered_by=pid,
                   proposal=pid, opt_in=f"experiments.comp:{WID}", baseline_rows=e["baseline_rows"], candidate_rows=e["candidate_rows"],
                   baseline=e["baseline"], candidate=e["candidate"], evidence="measured internal (technical)", approved_by=done["decided_by"],
                   baseline_release=self.rid, candidate_release=rid2,
                   versions={"before": done["before_version"], "after": done["after_version"]})

        # ---- Stage 7: the next comparable measurement, under the promoted version ----
        job2, row2 = self.benchmark(0.85)
        rec = self.cycle(mid)
        b = self.bench_of(rec)
        self.assertEqual((b["status"], b["value"], b["pass"], b["evidence_ref"]["sandbox_run"], b["evidence_ref"]["release"]), ("valid", 0.85, True, f"job:{job2['sbx']}", rid2))
        self.assertEqual(rec["dimensions"]["technical"]["value"], "PASS")
        self.assertNotEqual(rec["decision"]["rule"], 1)                        # a technical pass alone never meets the mission's criteria
        (seen,) = rec["proposals"]["rows"]                                     # L5.5: the cycle after the promotion names the gap, its answer and the versions
        self.assertEqual((seen["id"], seen["status"], seen["cycles"], seen["answered_by"]), (gap["id"], "answered", [gap_cycle], pid))
        self.assertEqual((seen["answers"][0]["before_version"], seen["answers"][0]["after_version"]), (done["before_version"], done["after_version"]))
        self.fresh(mine_em=0.95)                                               # scripted: the chain now ranks us first
        last = [self.cycle(mid) for _ in range(3)][-1]                         # the hold window (K-34: three cycles)
        self.assertEqual(last["decision"]["rule"], 1, last["decision"])
        self.assertNotIn("internal_measured", last["decision"]["rests_on"])
        self.assertEqual(len(self.reqs(mid, "deliver")), 1)
        self.stage(7, "Subsequent measurement", cycle=rec["n"], technical_before=0.60, technical_after=0.85, evidence_ref=f"job:{job2['sbx']}",
                   cycle_names={"gap_proposal": seen["id"], "answer": pid, "before_version": done["before_version"], "after_version": done["after_version"]},
                   criteria_met_cycle=last["n"], criteria_rest_on=last["decision"]["rests_on"], delivery_request=self.reqs(mid, "deliver")[0]["id"])

        # ---- rollback capability (after the measurement, so the scenario keeps the improvement until then) ----
        back = self.ev.rollback(self.owner, pid)
        vs = q("SELECT version, source FROM au_versions WHERE agent_id=2 ORDER BY version")
        self.assertEqual((back["status"], q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"], vs[-1]["source"]), ("rolled_back", BASE_TEXT, f"gate #{pid} rolled back"))
        self.assertEqual([v["source"] for v in vs], ["original", f"trial #{pid}", f"trial #{pid} ended", f"gate #{pid}", f"gate #{pid} rolled back"])
        self.report.append({"stage": 6, "name": "Rollback", "status": "PASS", "proof": {"proposal": pid, "versions": [v["source"] for v in vs]}})
        acts = [r["action"] for r in q("SELECT action FROM ev_audit ORDER BY id")]
        self.assertEqual(acts, ["proposal.created", "experiments.opt_in", "proposal.created", "gap.answer_proposed", "trial.started", "trial.ended", "proposal.promoted",
                                "gap.answered", "proposal.rolled_back", "gap.reopened"])
        self.assertEqual(q("SELECT status FROM ev_proposals WHERE id=?", (gap["id"],), one=True)["status"], "proposed")  # the rollback opened the gap again

        out = {"scenario": "SN62 competition 28, synthetic fixture", "stages": self.report,
               "gaps": [{"stage": s, "what": w, "status": st, "why": why} for s, w, st, why in GAPS]}
        print("@@G5-ACCEPTANCE " + json.dumps(out, default=str))


if __name__ == "__main__":
    unittest.main()
