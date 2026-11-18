"""orchestrator.EVALUATORS: every run type the code records has an evaluator (or an explicit exclusion), and the verdicts that
are derived from each system's own records (a person's accept, a team task's review, a plan's delivered tasks, Mission
Intelligence's approved proposals) score the runs; a verdict that comes after the deadline still turns a gap into a score."""
import os, re, time, unittest

from app import orchestrator as orc
from test_orchestrator import G5

APP = os.path.join(os.path.dirname(orc.__file__))
DAY = 86400

# every agent_core.begin()/record() call site, file → one (system, kind, ref) sample each. A new call site fails
# test_every_call_site_is_listed until it's listed here, which makes you give its run type an evaluator.
SITES = {
    "control_hub.py": [("hub", "task", "ctl:t1"), ("hub", "chat", "ctl:m1")],
    "control_missions.py": [("other", "intelligence", "ctl:mi:bittensor")],
    "company.py": [("company", "task", "co:1"), ("company", "brief", "cob:1")],
    "company_agents.py": [("company", "chat", "coc:1")],
    "evolution.py": [("evolution", "cases", "evb:1"), ("evolution", "draft", "evd:1"), ("evolution", "experiment", "ev:1")],
    "team_eval.py": [("evolution", "team-test", "te:1")],
    "hq.py": [("hq", "patrol", "hq:1")],
    "infiagent.py": [("longtask", "segment", "ia:1")],
    "marketplace.py": [("marketplace", "tasks", "mpt:1"), ("marketplace", "eval", "mpe:1")],
    "mining_bench.py": [("workflow", "engineer", "mb:r1"), ("workflow", "review", "mb:r2")],
    "mining_director.py": [("teams", "report", "mw:1")],
    "mining_improve.py": [("workflow", "improve", "mb:r3")],
    "mining_portfolio.py": [("teams", "portfolio", "mp:1")],
    "mining_upgrade.py": [("teams", "upgrade:practice", "au:1")],
    "mining_work.py": [("teams", "task", "mw:1"), ("teams", "review", "mw:2"), ("teams", "plan", "mw:3")],
    "mission_intel.py": [("missions", "discover", "mx:1")],
    "missions.py": [("missions", "plan", "mx:1"), ("missions", "understand", "mx:1")],  # _ask, and _see (attached pictures)
    "swarm.py": [("workforce", "swarm-work", "sw:1")],
    "task_research.py": [("other", "research", "ctl:t1")],
    "team.py": [("team", "cycle", "tc:1"), ("team", "task", "tt:1")],
    "workforce.py": [("workforce", "execute", "wf:1")],
}
# run types nobody judges yet, on purpose and by name (the page lists them as gaps with this reason)
NO_EVALUATOR = {("company", "brief"), ("longtask", "segment"), ("workflow", "improve"), ("other", "research")}
MORE = [("missions", s, "mx:1") for s in ("understand", "allocate", "execute", "verify", "deliver", "learn")] + \
       [("workforce", k, "wf:1") for k in ("plan", "delegate", "synthesize", "learn", "rework", "evaluate", "critique")] + [("marketplace", "watch", "mpe:1"), ("workflow", "plan", "mb:r4"),
       ("workflow", "check", "mb:r5"), ("teams", "upgrade:exam", "au:2"), ("company", "research", "co:2")]


class Registry(unittest.TestCase):
    def test_every_call_site_is_listed(self):
        found = {}
        for f in sorted(os.listdir(APP)):
            if not f.endswith(".py") or f == "agent_core.py": continue
            with open(os.path.join(APP, f), encoding="utf-8") as fh:
                code = "\n".join(ln for ln in fh if not ln.lstrip().startswith("#"))  # comments don't count
            n = len(re.findall(r"agent_core\.(?:begin|record)\(", code))
            if n: found[f] = n
        self.assertEqual(found, {f: len(v) for f, v in SITES.items()},
                         "A run type was added or removed: list its call site in SITES and give it a row in orchestrator.EVALUATORS")

    def test_every_run_type_has_an_evaluator(self):
        for s, k, ref in [x for v in SITES.values() for x in v] + MORE:
            E = orc.evaluator_for(s, k, ref)
            self.assertIsNotNone(E, f"{s} '{k}' ({ref}) has no evaluator")
            self.assertEqual(E[3] == "none", (s, k) in NO_EVALUATOR or (s == "workflow" and k == "plan"), f"{s} '{k}': {E}")

    def test_order(self):
        self.assertEqual(orc.evaluator_for("teams", "review", "mw:2")[3], "exclude")  # evaluation tooling, not a gap
        self.assertEqual(orc.evaluator_for("missions", "verify", "mx:1")[3], "exclude")
        self.assertEqual(orc.evaluator_for("workforce", "swarm-work", "sw:1")[3], "own")
        for k in ("evaluate", "critique", "factcheck", "swarm-evaluate"): self.assertEqual(orc.evaluator_for("workforce", k, "wf:1")[3], "exclude")
        self.assertEqual(orc.evaluator_for("company", "task", "co:1")[3], "company_task")
        self.assertIsNone(orc.evaluator_for("other", "mystery", "zz:1"))
        # a Control Hub task runs under its agent's system: the ctl:t row must win over that system's own
        for sysname in ("workforce", "company", "teams", "hub"): self.assertEqual(orc.evaluator_for(sysname, "task", "ctl:t9")[3], "control_task", sysname)


class Derived(G5):
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        q = self.db.q
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, origin TEXT)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, kind TEXT, status TEXT)")
        q("""CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, origin TEXT, mission TEXT, created REAL)""")

    def state(self, rid):
        r = self.ev_row(rid)
        return (r["state"], r["score"]) if r else None

    def test_team_tasks_reviews_and_plans(self):
        q, old = self.db.q, time.time() - 5 * DAY
        q("INSERT INTO mw_tasks VALUES (1, 5, 'done', NULL), (2, 5, 'working', NULL), (3, 5, 'done', 'plan:30'), (4, 5, 'todo', 'plan:30')")
        q("INSERT INTO mw_runs VALUES (10, 5, 1, 'task', 'done'), (11, 5, 1, 'task', 'done'), (12, 5, 2, 'task', 'done'), (13, 5, 1, 'review', 'done')")
        first = self.run_row(system="teams", kind="task", ref="mw:10")
        last = self.run_row(system="teams", kind="task", ref="mw:11")
        open_ = self.run_row(system="teams", kind="task", ref="mw:12")
        review = self.run_row(system="teams", kind="review", ref="mw:13")
        plan = self.run_row(system="teams", kind="plan", ref="mw:30")
        oldplan = self.run_row(system="teams", kind="plan", ref="mw:30", started=old, finished=old)
        self.o.evaluate()
        # G5-5 L5.1 (IC-11): a review is a verdict, not a score: RC1 gave these 30 and 100
        self.assertEqual(self.state(first), ("reviewed", None)); self.assertIn("Sent back", self.ev_row(first)["reason"])  # a later run of the same task
        self.assertEqual(self.state(last), ("reviewed", None)); self.assertIn("Approved", self.ev_row(last)["reason"])  # its task is done
        self.assertIsNone(self.state(open_))  # waits for a verdict (a person's decision: 3 days)
        self.assertEqual(self.ev_row(review)["state"], "excluded"); self.assertIn("Evaluation tooling", self.ev_row(review)["reason"])
        self.assertIsNone(self.state(plan))  # one of its two tasks is still open
        self.assertEqual(self.state(oldplan), ("scored", 50))  # after the deadline: the share delivered
        self.assertIsNone(self.db.q("SELECT score FROM ac_runs WHERE id=?", (last,), one=True)["score"])  # nothing is copied onto the ledger
        self.assertEqual(self.db.q("SELECT score FROM ac_runs WHERE id=?", (oldplan,), one=True)["score"], 50)  # a derived number still is (IC-11 open point (b))

    def test_control_task_and_a_late_decision(self):
        q, old = self.db.q, time.time() - 5 * DAY
        q("INSERT INTO ctl_tasks VALUES (1, 7, 'review', NULL, NULL, ?)", (old,))
        rid = self.run_row(system="hub", kind="task", ref="ctl:t1", started=old, finished=old)
        self.o.evaluate()
        self.assertEqual(self.ev_row(rid)["state"], "gap"); self.assertIn("No verdict within 72 hours from your decision", self.ev_row(rid)["reason"])
        q("UPDATE ctl_tasks SET status='done' WHERE id=1")
        self.o._gaps_at = None
        self.o.evaluate()
        self.assertEqual(self.state(rid), ("scored", 100))
        self.assertEqual(self.ev_row(rid)["source"], "You accepted its result")

    def test_mission_intelligence_by_what_you_approved(self):
        q, t0 = self.db.q, time.time() - 3 * DAY
        rid = self.run_row(system="other", kind="intelligence", ref="ctl:mi:bittensor", started=t0, finished=t0 + 30)
        for st in ("todo", "done", "declined"): q("INSERT INTO ctl_tasks (user_id, status, origin, mission, created) VALUES (7, ?, 'intelligence', 'bittensor', ?)", (st, t0 + 20))
        q("INSERT INTO ctl_tasks (user_id, status, origin, mission, created) VALUES (7, 'declined', 'intelligence', 'other', ?)", (t0 + 20,))
        none = self.run_row(system="other", kind="intelligence", ref="ctl:mi:comp:9", started=t0, finished=t0 + 30)
        self.o.evaluate()
        self.assertEqual(self.state(rid), ("scored", 67))
        self.assertEqual(self.ev_row(none)["state"], "excluded")

    def test_an_unassigned_run_type_is_a_named_gap(self):
        rid = self.run_row(system="other", kind="mystery", ref="zz:1")
        self.o.evaluate()
        self.assertEqual(self.ev_row(rid)["state"], "gap"); self.assertIn("No evaluator assigned", self.ev_row(rid)["reason"])
        self.assertEqual(self.o.coverage(7, time.time() - 7 * DAY)["target"], 95)


if __name__ == "__main__":
    unittest.main()


class Spend(G5):
    """Dollars per run where the ledger has none (estimated at list price), plan calls apart, cost per validated deliverable,
    and hard limits suggested (never set) from the busiest day."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)

    def test_estimates_plan_calls_and_cost_per_validated(self):
        self.run_row(system="workforce", model="anthropic:claude-sonnet-4", tokens=1_000_000, ref="wf:1", score=80)
        self.run_row(system="teams", model="terminal:claude", tokens=500_000, ref="mw:1", score=90)
        self.run_row(system="teams", model="openai:gpt-4.1", tokens=10, cost=0.5, ref="mw:2")
        s = self.o.spend(7, time.time() - 7 * DAY)
        self.assertEqual((s["recorded_usd"], s["estimated_usd"], s["plan_tokens"]), (0.5, 4.0, 500_000))
        self.assertEqual((s["usd"], s["validated"], s["usd_per_validated"]), (4.5, 2, 2.25))
        self.assertEqual({b["system"] for b in s["by_system"]}, {"workforce", "teams"})

    def test_limits_are_suggested_not_set(self):
        for i in range(3): self.run_row(system="teams", tokens=40_000, ref=f"mw:{i}", started=time.time() - 2 * DAY + i)
        self.run_row(system="teams", tokens=10_000, ref="mw:9", started=time.time() - 5 * DAY)
        sg = {(x["scope"], x["key"]): x for x in self.o.suggest_limits(7)}
        self.assertEqual(sg[("global", "*")]["tokens"], 180_000)  # 1.5 × the busiest day (120,000)
        self.assertEqual(sg[("system", "teams")]["period"], "day")
        self.assertFalse(self.db.q("SELECT 1 FROM ac_limits", one=True))
        self.core.set_limit(7, "global", "*", tokens=100_000, period="day")
        self.assertNotIn(("global", "*"), {(x["scope"], x["key"]) for x in self.o.suggest_limits(7)})
