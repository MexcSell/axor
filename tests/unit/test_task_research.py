"""task_research.py: the Intelligence brief before a predefined mission's fixed tasks, in the Control Hub's dispatcher.
A template task that needs it waits for its research, then goes to the board with the brief's digest; research never gates."""
import os, sys, time, unittest

from app import control_dispatch as cd, control_hub, control_missions as cm, task_research as tr

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base  # noqa: E402
from test_mission_intel import LLM as Scripted  # noqa: E402
from test_organization import ME  # noqa: E402


class Later:
    """Starts nothing: the test runs the research when it chooses (a thread that hasn't finished yet)."""
    def __init__(self): self.jobs = []
    def __call__(self, fn): self.jobs.append(fn)


class LLM(Scripted):
    """The scripted analyst, as a configured provider."""
    def any_configured(self): return True
    def resolve(self, choice): return ("anthropic", "m")


class Research(Base):
    def setUp(self):
        super().setUp()  # test_control_missions.Missions' setup, without re-running its tests
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))
        tr.ENABLED = True
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))
        self.details, self.files = {}, {}
        add = self.ch.w._add_task  # what the dispatcher calls (control_missions._to_board): the board task's id
        def add_task(me, wid, b, actor=None):
            out = add(me, wid, b)
            self.details[b.title] = b.detail
            return out
        self.ch.w._add_task = add_task
        self.ch.w._write_file = lambda wid, path, content, agent_id=None: self.files.__setitem__(path, content)
        self.hub.llm = LLM([("read_page", {"url": "https://www.ridges.ai/explore/28"})])
        self.later = Later()

    def tearDown(self):
        tr._running.clear()
        super().tearDown()

    def fixed(self, key, ref="comp:1"):
        return self.db.q("SELECT * FROM ctl_tasks WHERE mission=? AND template=?", (ref, key), one=True)

    def test_only_the_tasks_that_need_it_wait(self):
        cm.missions(self.ch, ME)  # seeds the template
        go, detail = tr.ready(self.ch, ME, self.fixed("availability"), start=self.later)
        self.assertTrue(go); self.assertIn("Done when:", detail); self.assertEqual(self.later.jobs, [])
        go, _ = tr.ready(self.ch, ME, self.fixed("interfaces"), start=self.later)
        self.assertFalse(go); self.assertEqual(len(self.later.jobs), 1)
        go, _ = tr.ready(self.ch, ME, self.fixed("interfaces"), start=self.later)   # still under research: no second run
        self.assertFalse(go); self.assertEqual(len(self.later.jobs), 1)

    def test_the_brief_travels_with_the_task_to_the_board(self):
        cm.missions(self.ch, ME)
        r = self.fixed("interfaces")
        tr.ready(self.ch, ME, r, start=self.later)
        self.later.jobs[0]()                                                           # the research thread runs and files its brief
        row = self.db.q("SELECT * FROM ctl_briefs WHERE task_id=?", (r["id"],), one=True)
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["file"], f"data/research/interfaces-t{r['id']}.md")
        self.assertIn("# Research before:", self.files[row["file"]])
        go, detail = tr.ready(self.ch, ME, r, start=self.later)
        self.assertTrue(go)
        self.assertIn("Intelligence brief", detail); self.assertIn("Full brief: data/research/", detail); self.assertLessEqual(len(detail), tr.DETAIL)
        self.assertIn("Done when:", detail)                                           # the acceptance criteria stay
        self.assertIn("read_page", self.hub.llm.seen[0])                               # the analyst can read the competition's pages

    def test_dispatch_waits_for_research_then_sends_the_task_with_its_brief(self):
        cm.missions(self.ch, ME)
        start = tr._thread
        tr._thread = self.later
        try:
            out = cd.dispatch(self.ch, ME)
            self.assertEqual(out["researching"], 9)                                    # interfaces, deliverables, infra on 3 missions
            self.assertEqual(out["board"], 3)                                          # availability goes at once
            self.assertEqual(len(self.later.jobs), tr.MAX_AT_ONCE)                     # research runs a few at a time, the rest wait their turn
            held = [t for t in cm.mission(self.ch, ME, "comp:1")["fixed"] if t["template"] in tr.NEEDS]
            self.assertTrue(all(t["why"]["state"] == "queued" and t["why"]["text"].startswith(cd.RESEARCHING) for t in held), held)
            self.assertEqual(cd.dispatch(self.ch, ME)["board"], 0)                     # nothing goes while its research runs
            sent, passes = 3, 0
            while sent < 12 and passes < 20:
                passes += 1
                jobs, self.later.jobs = list(self.later.jobs), []
                for job in jobs: job()
                sent += cd.dispatch(self.ch, ME)["board"]
                self.assertLessEqual(len(self.later.jobs), tr.MAX_AT_ONCE)
            self.assertEqual(sent, 12)
        finally:
            tr._thread = start
        t = next(k for k in self.details if k.startswith("Implement the competition"))
        self.assertIn("Intelligence brief", self.details[t])
        self.assertFalse(any((r["summary"] or "").startswith(cd.RESEARCHING) for r in self.db.q("SELECT summary FROM ctl_tasks")))  # cleared once sent

    def test_research_never_gates(self):
        cm.missions(self.ch, ME)
        # no budget left on the team's day: skipped at once, and the task goes without a brief
        self.db.q("UPDATE mw_comps SET budget=10000 WHERE id=1")
        r = self.fixed("deliverables")
        tr.ready(self.ch, ME, r, start=self.later); self.later.jobs.pop()()
        self.assertIn("budget", tr.brief_of(self.db, r["id"])["skipped"])
        go, detail = tr.ready(self.ch, ME, r)
        self.assertTrue(go); self.assertNotIn("Intelligence brief", detail)
        self.db.q("UPDATE mw_comps SET budget=150000 WHERE id=1")
        # a model that fails: skipped with the reason
        self.hub.llm = LLM([], fail=RuntimeError("provider down"))
        r = self.fixed("infra")
        tr.ready(self.ch, ME, r, start=self.later); self.later.jobs.pop()()
        self.assertIn("provider down", tr.brief_of(self.db, r["id"])["skipped"])
        # cut off by a restart (no thread on a running brief): run again once, then go without it
        r = self.fixed("interfaces")
        tr.ready(self.ch, ME, r, start=self.later); self.later.jobs.clear(); tr._running.clear()
        self.assertFalse(tr.ready(self.ch, ME, r, start=self.later)[0]); self.assertEqual(len(self.later.jobs), 1)
        self.later.jobs.clear(); tr._running.clear()
        go, _ = tr.ready(self.ch, ME, r, start=self.later)
        self.assertTrue(go); self.assertIn("cut off", tr.brief_of(self.db, r["id"])["skipped"])

    def test_counts_for_the_intelligence_layers(self):
        cm.missions(self.ch, ME)
        r = self.fixed("interfaces")
        tr.ready(self.ch, ME, r, start=self.later); self.later.jobs.pop()()
        r2 = self.fixed("infra")
        tr.ready(self.ch, ME, r2, start=self.later)
        c = tr.counts(self.db, ME["id"], time.time() - 3600)
        self.assertEqual((c["researched"] + c["no_web"], c["no_web"], c["running"], c["week"]), (1, 1, 1, 1))  # no MCP tool here: researched without the web


if __name__ == "__main__":
    unittest.main()
