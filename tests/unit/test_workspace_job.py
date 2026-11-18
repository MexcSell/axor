"""D-032c step 1 (amended 2026-11-13; the integration owner, the AEF session and the SN61 session agreed it): a VM job takes
named folders from its mission's workspace.

Before this an agent could edit a candidate in the mission's workspace and docker_job would build the team's files: the job
never saw the edit and nothing said so.

- `workspace_paths` names folders or files of the workspace. Under each of them the job gets the workspace's files and none of
  the team's; everywhere else the team's. A file keeps the path it has in the workspace, the path a team file would have.
- AXoR reads the snapshot when the job is submitted (the pod reads nothing): the newest of the task's own mission, or the one
  named in `workspace_snapshot`, and only if it is whole. The record says which.
- Nothing differs silently: a file that isn't text, a link, a root with nothing under it, or files that don't fit refuse the
  job by name. A clone's .git folder is left out by rule and counted.
- A job that names nothing is the job it always was: same files, same hashes, and it doesn't need a workspace at all.
"""
import json, os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from app import exec_env as ex, mining_work, runner as V  # noqa: E402
import test_measuring_job as tm  # noqa: E402  (fixtures; as modules, so their own tests don't run again here)
import test_mission_persistent_evidence as tp  # noqa: E402
import test_runner_job_hashes as th  # noqa: E402
import test_vm_runner as tv  # noqa: E402

MISSION = "mx:7"
CAND2 = "module.exports = () => 2;  // edited in the workspace\n"


class Workspace(tm.Fixture):
    """A team with the workspace switch on, a task of mission mx:7, and a way to save snapshots as a sandbox run would."""
    def workspace(self):
        self.seed()
        self._wsdir = tempfile.TemporaryDirectory()
        self._exroot = ex.ROOT; ex.ROOT = Path(self._wsdir.name) / "exec"
        ex._STORES.pop(id(self.db), None)
        self.st = ex.store(self.db)
        self.db.setting(f"exec.comp:{tp.WID}", v=json.dumps({"workspace": True}))
        self.db.q("INSERT OR REPLACE INTO mw_tasks (id, comp_id, title, mission) VALUES (5, ?, 'measure the candidate', ?)", (tp.WID, MISSION))
        self.db.q("INSERT OR REPLACE INTO mw_tasks (id, comp_id, title, mission) VALUES (6, ?, 'another mission', 'mx:8')", (tp.WID,))

    def close_workspace(self):
        ex._STORES.pop(id(self.db), None); ex.ROOT = self._exroot; self._wsdir.cleanup()

    def save(self, files, mission=MISSION, links=None):
        """A run's save: `files` is the whole workspace as that run holds it (a path it no longer has is removed)."""
        head = self.st.head(tp.WID, mission)
        entries = {p: [self.st.put(t if isinstance(t, bytes) else t.encode()), len(t if isinstance(t, bytes) else t.encode()), 0o644] for p, t in files.items()}
        return self.st.commit(tp.WID, mission, head["id"] if head else None, entries, links or {})["snapshot"]

    def ws_job(self, roots=("miner",), task=5, **kw):
        self.run_no += 1
        spec = tv.spec(**{"kind": "bench", "command": "sh bench/run.sh", "score_file": "bench_out/live.json", "workspace_paths": list(roots), **kw})
        return self.w._docker_job(self.comp, self.c, spec, task=task, run=self.run_no, agent=self.agent)

    def sent(self): return self.w.runner.jobs[-1]
    def refusal(self, **kw):
        with self.assertRaises(LookupError) as e: self.ws_job(**kw)
        return str(e.exception)


@tv.own_tests
class WorkspaceJob(Workspace, tv.Board):
    def setUp(self):
        super().setUp(); self.workspace()
        self.s1 = self.save({"miner/detect.js": CAND2, "miner/lib/util.js": "exports.x = 1;\n", "notes/plan.md": "try the cache\n"})

    def tearDown(self): self.close_workspace(); super().tearDown()

    def test_the_named_folder_comes_from_the_workspace_and_everything_else_from_the_teams_files(self):
        self.add("miner/old.js", "left over in the team's files\n")
        out = self.ws_job()
        job, files = self.sent()
        self.assertEqual((files["miner/detect.js"], files["miner/lib/util.js"]), (CAND2, "exports.x = 1;\n"))   # the edit, under the path a team file would have
        self.assertNotIn("miner/old.js", files)                              # under a named root the team's files are left out: nothing is merged
        self.assertNotIn("notes/plan.md", files)                             # the rest of the workspace isn't taken
        for p, t in tv.FILES.items(): self.assertEqual(files[p], t, p)       # outside the root: the team's files, as always
        self.assertEqual(files["bench/mock.sh"], tm.MOCK)
        self.assertEqual(job["workspace_paths"], ["miner"]); self.assertNotIn("workspace_snapshot", job)
        self.assertEqual(out["status"], "done")

    def test_the_record_says_which_snapshot_of_which_mission(self):
        out = self.ws_job()
        row = self.st.row(tp.WID, self.s1)
        want = {"mission": MISSION, "snapshot": self.s1, "snapshot_tree": row["tree"], "saved": row["created"], "asked": "newest", "roots": ["miner"], "files": 2}
        self.assertEqual(out["inputs"]["workspace"], want)
        self.assertEqual(out["workspace"], {k: want[k] for k in ("mission", "snapshot", "roots", "files")})   # and the agent is told at once
        doc = V.stored(self.db, tp.WID, out["sbx"])
        self.assertEqual(doc["inputs"]["workspace"], want)                    # kept with the result
        self.assertEqual(sorted(p for p in doc["inputs"]["tree"] if p.startswith("miner/")), ["miner/detect.js", "miner/lib/util.js"])

    def test_the_newest_snapshot_unless_one_is_named(self):
        s2 = self.save({"miner/detect.js": "module.exports = () => 3;\n"})
        self.assertEqual(self.ws_job()["inputs"]["workspace"]["snapshot"], s2); self.assertIn("=> 3", self.sent()[1]["miner/detect.js"])
        out = self.ws_job(workspace_snapshot=self.s1)                        # the earlier candidate, measured again
        self.assertEqual((out["inputs"]["workspace"]["snapshot"], out["inputs"]["workspace"]["asked"]), (self.s1, "named"))
        self.assertEqual(self.sent()[1]["miner/detect.js"], CAND2); self.assertEqual(self.sent()[0]["workspace_snapshot"], self.s1)

    def test_a_named_snapshot_changes_the_jobs_hash_and_not_its_measuring_hash(self):
        """It says which candidate, as the declared source does: the measurement's configuration is the same job."""
        spec = dict(th.REGISTRY_BENCH, workspace_paths=["miner"])
        a, b, newest = (V.validate(tv.spec(**spec, **kw), tv.FILES)[0] for kw in ({"workspace_snapshot": 3}, {"workspace_snapshot": 4}, {}))
        self.assertEqual(len({V.job_sha(a), V.job_sha(b), V.job_sha(newest)}), 3)
        self.assertEqual(len({V.measure_sha(a), V.measure_sha(b), V.measure_sha(newest)}), 1)
        other = V.validate(tv.spec(**{**spec, "workspace_paths": ["miner", "bench"]}), tv.FILES)[0]
        self.assertNotEqual(V.measure_sha(other), V.measure_sha(a))          # the roots are part of the measurement's configuration

    def test_a_job_that_names_nothing_is_the_job_it_always_was(self):
        self.db.setting(f"exec.comp:{tp.WID}", v="{}")                       # no workspace at all: it isn't even asked
        for kw in ({}, {"workspace_paths": []}, {"workspace_paths": [], "workspace_snapshot": 0}, {"workspace_paths": ["", "  "]}):
            self.run_no += 1
            out = self.w._docker_job(self.comp, self.c, tv.spec(**th.REGISTRY_BENCH, **kw), task=5, run=self.run_no, agent=self.agent)
            job, files = self.sent()
            self.assertEqual(V.job_sha({k: v for k, v in job.items() if k != "id"}), th.PINS["registry bench"], kw)
            self.assertEqual(files["miner/detect.js"], "module.exports = () => 1;\n", kw)             # the team's own candidate
            self.assertNotIn("workspace", out["inputs"]); self.assertNotIn("workspace", out)

    def test_another_missions_snapshot_or_one_that_is_gone_is_refused(self):
        theirs = self.save({"miner/detect.js": "theirs\n"}, mission="mx:8")
        self.assertIn(f"There is no snapshot #{theirs} of {MISSION}'s workspace", self.refusal(workspace_snapshot=theirs))
        self.assertIn("There is no snapshot #99999", self.refusal(workspace_snapshot=99999))
        self.assertEqual(self.w.runner.jobs, [])                             # neither refused job reached the runner
        own = self.ws_job(task=6)["inputs"]["workspace"]                     # a task of that mission gets its own workspace, and only that
        self.assertEqual((own["mission"], own["snapshot"]), ("mx:8", theirs)); self.assertEqual(self.sent()[1]["miner/detect.js"], "theirs\n")

    def test_what_would_differ_silently_refuses_the_job_by_name(self):
        n = len(self.w.runner.jobs)
        self.save({"miner/model.bin": b"\xff\xfe\x00\x01binary", "miner/detect.js": CAND2})
        self.assertIn("miner/model.bin", w := self.refusal()); self.assertIn("isn't text", w)
        self.save({"miner/detect.js": CAND2})                                # the run removed the binary file
        self.assertRegex(self.refusal(roots=("miner", "tools")), r"holds no file under tools")
        self.assertIn("never saved to a workspace", self.refusal(roots=("tools",)))
        self.assertEqual(len(self.w.runner.jobs), n)

    def test_a_link_under_a_named_root_refuses_the_job(self):
        n = len(self.w.runner.jobs)
        self.save({"miner/detect.js": CAND2, "shared-lib/a.js": "x\n"}, links={"miner/vendor": "../shared-lib"})
        w = self.refusal()
        self.assertIn("miner/vendor", w); self.assertIn("can't take a link", w); self.assertEqual(len(self.w.runner.jobs), n)
        self.assertEqual(self.ws_job(roots=("shared-lib",))["status"], "done")     # a link elsewhere doesn't concern a job that doesn't name it

    def test_a_clones_git_folder_is_left_out_and_counted(self):
        self.save({"miner/detect.js": CAND2, "miner/.git/HEAD": "ref: refs/heads/main\n", "miner/.git/objects/pack/pack-1.pack": b"PACK\x00\x00\x00\x02", "miner/sub/.git/config": "[core]\n"})
        out = self.ws_job()
        self.assertEqual(sorted(p for p in self.sent()[1] if p.startswith("miner/")), ["miner/detect.js"])
        self.assertEqual((out["inputs"]["workspace"]["left_out"], out["workspace"]["left_out"]), ({".git": 3}, {".git": 3}))
        self.assertEqual(out["inputs"]["workspace"]["files"], 1)

    def test_a_file_that_loses_its_executable_bit_is_named(self):
        """The job's input is text, and the VM makes .sh and .py files executable and nothing else. So an executable file with
        another name arrives without the bit: counted and named, not silent. A .sh script keeps working and isn't counted."""
        head = self.st.head(tp.WID, MISSION)
        entry = lambda t, mode: [self.st.put(t.encode()), len(t.encode()), mode]
        self.st.commit(tp.WID, MISSION, head["id"], {"miner/detect.js": entry(CAND2, 0o644), "miner/run.sh": entry("#!/bin/sh\nnode detect.js\n", 0o755),
                                                      "miner/bin/score": entry("#!/bin/sh\necho 1\n", 0o755)}, {})
        out = self.ws_job()
        self.assertEqual(self.sent()[1]["miner/bin/score"], "#!/bin/sh\necho 1\n")                 # the file itself goes in
        want = {"executable": 1, "first": ["miner/bin/score"]}
        self.assertEqual((out["inputs"]["workspace"]["modes_not_carried"], out["workspace"]["modes_not_carried"]), (want, want))
        self.save({"miner/detect.js": CAND2})                                                      # the control: nothing executable, nothing said
        self.assertNotIn("modes_not_carried", self.ws_job()["inputs"]["workspace"])
        self.assertIn(".sh and .py files are executable and nothing else is", mining_work.DOCKER_TOOL["description"])

    def test_the_tasks_mission_comes_from_the_fabrics_public_function(self):
        calls, real = [], ex.mission_of
        ex.mission_of = lambda db, comp, task: (calls.append(task), real(db, comp, task))[1]
        try: self.assertEqual(self.ws_job()["inputs"]["workspace"]["mission"], MISSION)
        finally: ex.mission_of = real
        self.assertIn(5, calls)

    def test_without_the_switch_or_a_saved_workspace_the_job_says_what_to_do(self):
        self.db.setting(f"exec.comp:{tp.WID}", v="{}")
        self.assertIn("the workspace switch is off", self.refusal())
        self.db.setting(f"exec.comp:{tp.WID}", v=json.dumps({"workspace": True}))
        self.db.q("DELETE FROM mw_ws WHERE mission=?", (MISSION,))
        self.assertIn("holds nothing yet", self.refusal())

    def test_a_snapshot_that_is_not_whole_is_refused_and_no_older_one_is_used(self):
        s2 = self.save({"miner/detect.js": "module.exports = () => 3;\n"})
        os.remove(self.st.path(self.st.tree(self.st.row(tp.WID, s2))["files"]["miner/detect.js"][0]))
        n = len(self.w.runner.jobs)
        self.assertIn("can't be restored", self.refusal()); self.assertEqual(len(self.w.runner.jobs), n)

    def test_a_run_of_the_same_mission_that_is_still_running_is_named(self):
        q = self.db.q
        mine = q("INSERT INTO mw_sbx (comp_id, task_id, status, services, started) VALUES (?, 5, 'running', '', 1) RETURNING id", (tp.WID,), one=True)["id"]
        q("INSERT INTO mw_sbx (comp_id, task_id, status, services, started) VALUES (?, 6, 'running', '', 1)", (tp.WID,))           # another mission's run
        q("INSERT INTO mw_sbx (comp_id, task_id, status, services, started) VALUES (?, 5, 'running', ?, 1)", (tp.WID, V.SERVICE))   # a VM job saves nothing
        out = self.ws_job()
        self.assertEqual(out["inputs"]["workspace"]["running"], [mine])
        self.assertEqual(out["workspace"]["note"], f"Run #{mine} of this mission is still running: what it hasn't saved is not in snapshot #{self.s1}.")
        q("UPDATE mw_sbx SET status='done' WHERE id=?", (mine,))
        self.assertNotIn("note", self.ws_job()["workspace"])

    def test_what_a_job_may_ask_of_the_workspace(self):
        bad = lambda **kw: self.assertRaises(V.RunnerError, V.validate, tv.spec(**th.REGISTRY_BENCH, **kw), tv.FILES)
        bad(workspace_paths=["../other"]); bad(workspace_paths=["/etc"]); bad(workspace_paths=[f"d{i}" for i in range(13)])
        bad(workspace_snapshot=3)                                            # a snapshot without a root
        bad(workspace_paths=["miner"], workspace_snapshot=-1); bad(workspace_paths=["miner"], workspace_snapshot=True); bad(workspace_paths=["miner"], workspace_snapshot="3")
        job = V.validate(tv.spec(**th.REGISTRY_BENCH, workspace_paths=["miner/", "./bench", "miner"]), tv.FILES)[0]
        self.assertEqual(job["workspace_paths"], ["bench", "miner"])         # normalized, sorted, once each: the same request has one hash

    def test_the_tool_offers_both_fields_and_says_what_they_do(self):
        t = mining_work.DOCKER_TOOL
        props = t["input_schema"]["properties"]
        self.assertEqual((props["workspace_paths"], props["workspace_snapshot"]), ({"type": "array", "items": {"type": "string"}}, {"type": "integer"}))
        for part in ("workspace_paths", "/work/mission", "none of the team's", "workspace_snapshot", "a .git folder is left out", "refuse the job by name", "same workspace_paths"):
            self.assertIn(part, t["description"])


@tv.own_tests
class Measured(Workspace, tv.Board):
    """Where the workspace meets the frozen measuring job (D-034; the integration owner's condition A, the SN61 session's first)."""
    def setUp(self):
        super().setUp(); self.workspace()
        self.save({"miner/detect.js": CAND2, "bench/mock.sh": tm.MOCK, "bench/run.sh": tv.FILES.get("bench/run.sh", "#!/bin/sh\n")})

    def tearDown(self): self.close_workspace(); super().tearDown()

    def differs(self, out, rel=None): return V.differs(V.stored(self.db, tp.WID, out["sbx"]), self.rel.measure(rel or self.rel.current(tp.WID)))

    def test_a_workspace_job_naming_the_candidate_root_is_the_measuring_job_and_a_harness_change_is_not(self):
        ref = self.ws_job()                                                  # the reference run: candidate from the workspace, harness from the team's files
        self.freeze_measuring(ref["sbx"])
        self.assertEqual(self.differs(self.ws_job()), "")                    # the same job again: it is the release's measuring job
        self.add("bench/mock.sh", tm.MOCK + "# the scorer, edited in the team's files\n")
        self.assertIn("the harness files differ", self.differs(self.ws_job()))

    def test_the_frozen_candidate_is_measured_again_by_naming_its_snapshot(self):
        """D-034a with the workspace: agents keep saving, so the head moves on to the next candidate. The release still measures the
        candidate it froze, and a job that names that snapshot is its measurement; a job on the newest one is another candidate."""
        s1 = self.st.head(tp.WID, MISSION)["id"]
        ref = self.ws_job()
        self.freeze_measuring(ref["sbx"])
        ver = self.rel.current(tp.WID)["version"]
        self.save({"miner/detect.js": "module.exports = () => 3;\n", "bench/mock.sh": tm.MOCK, "bench/run.sh": tv.FILES.get("bench/run.sh", "#!/bin/sh\n")})
        newest = self.ws_job()
        self.assertIn("it measured another candidate than the one this release froze (the files under miner/ differ)", self.differs(newest))
        self.assertEqual((newest["measuring"]["release"], newest["measuring"]["is_measuring_job"]), (ver, False))
        again = self.ws_job(workspace_snapshot=s1)
        self.assertEqual(self.differs(again), ""); self.assertEqual(again["measuring"], {"release": ver, "is_measuring_job": True})

    def test_a_harness_changed_through_the_workspace_is_not_the_measuring_job(self):
        """An agent names a root that reaches into the harness and edits the scorer there: the job runs, and isn't a measurement."""
        ref = self.ws_job(roots=("miner", "bench"))
        self.freeze_measuring(ref["sbx"])
        self.assertEqual(self.differs(self.ws_job(roots=("miner", "bench"))), "")
        self.save({"miner/detect.js": CAND2, "bench/run.sh": tv.FILES.get("bench/run.sh", "#!/bin/sh\n"), "bench/mock.sh": tm.MOCK + "echo '{\"score\": 1.0}' > bench_out/live.json\n"})
        out = self.ws_job(roots=("miner", "bench"))
        self.assertEqual(out["status"], "done"); self.assertIn("the harness files differ", self.differs(out))

    def test_a_release_frozen_from_a_team_files_job_is_not_measured_by_a_workspace_job_and_the_other_way_round(self):
        team, _ = self.job_run()
        self.freeze_measuring(team)
        self.assertIn("the job (its command, images, limits or network) differ", self.differs(self.ws_job()))   # workspace_paths is part of the frozen spec
        ref = self.ws_job()
        self.freeze_measuring(ref["sbx"])
        again, _ = self.job_run()
        self.assertIn("the job (its command, images, limits or network) differ", V.differs(V.stored(self.db, tp.WID, again), self.rel.measure(self.rel.current(tp.WID))))


@tv.own_tests
class Sent(tv.Running):
    """In the runner itself: a workspace job isn't started without the workspace's record, and never loses a workspace file to size."""
    WS = {"mission": MISSION, "snapshot": 4, "roots": ["miner"], "files": 1}

    def run_job(self, files, workspace=None, **spec):
        job = V.validate(tv.spec(**th.REGISTRY_BENCH, **spec), {**tv.FILES, **files})[0]
        self.proxy, self.egress = tv.FakeProxy(), tv.FakeEgress()
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(job), proxy=self.proxy)
        return V.Runner(self.kube, self.proxy, self.egress).run({**job, "id": 9}, {**tv.FILES, **files}, **({"workspace": workspace} if workspace else {}))

    def test_a_job_naming_workspace_paths_is_not_started_without_the_workspaces_record(self):
        with self.assertRaisesRegex(V.RunnerError, "no workspace was read for it"): self.run_job({"miner/a.js": "x"}, workspace_paths=["miner"])
        self.assertEqual(self.kube.created, [])
        r = self.run_job({"miner/a.js": "x"}, workspace=self.WS, workspace_paths=["miner"])
        self.assertEqual((r["status"], r["inputs"]["workspace"]), ("done", self.WS))

    def test_a_workspace_file_is_never_left_out_for_size(self):
        big = "x" * V.INPUT_BYTES
        with self.assertRaisesRegex(V.RunnerError, r"would be from the workspace \(miner/data\.jsonl\)"):
            self.run_job({"miner/data.jsonl": big, "miner/a.js": "x"}, workspace=self.WS, workspace_paths=["miner"])
        self.assertEqual(self.kube.created, [])
        r = self.run_job({"bench/data.jsonl": big, "miner/a.js": "x"}, workspace=self.WS, workspace_paths=["miner"])   # a team file may be left out, as before, and is named
        self.assertEqual((r["status"], r["omitted"]), ("done", ["bench/data.jsonl"]))

    def test_a_job_that_names_nothing_ignores_a_workspace_record(self):
        r = self.run_job({}, workspace=self.WS)
        self.assertNotIn("workspace", r["inputs"])


if __name__ == "__main__":
    unittest.main()
