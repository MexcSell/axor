"""G5-5 L5.4b part A (K-21, K-22; PROMOTION_GATE_ARCHITECTURE.md §5 and §6): a person's direct change to what an agent does is a
manual edit, never an improvement. It needs a reason, writes a version row in the agent's own store and one `agent.edit` audit row
(author, reason, previous version, new version, time, rollback reference, evidence if given), and can be compared and undone.

Runtime: the three edit paths that were unversioned or unaudited (competition team agents, Workforce tools and instructions, the
Workbench's Team card), each with: refused without a reason and nothing written; versioned and audited with one; staffing-only
changes untouched; rollback through the store.

Static: every statement in backend/app that writes an agent table or a version table of these three stores is classified below. A
new writer, or a manual-edit function that stops writing the audit row, fails this test until it is classified. The promotion
paths listed under PROMOTION are the ones L5.4b's second part routes through the gate; this test doesn't claim they are routed.
"""
import ast, json, os, pathlib, re, tempfile, threading, time, types, unittest

from fastapi import HTTPException

from app import mining_bench, mining_improve, mining_loadout, mining_upgrade, mining_work, workforce
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
WID = 3
OLD = "Review every change for failing tests before you approve it."
NEW = "Review every change for failing tests and missing benchmarks before you approve it."
APP = pathlib.Path(mining_work.__file__).parent


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))

    def tearDown(self):
        try: self.db.db.close()  # on Postgres an AuthDB holds a connection for as long as it lives (PX-R13)
        except Exception: pass   # noqa: BLE001
        self.dir.cleanup()

    def edits(self):
        rows = self.db.q("SELECT * FROM audit WHERE action='agent.edit' ORDER BY id")
        for r in rows: r["d"] = json.loads(r["detail"])
        return rows

    def refused(self, code, fn, *a, **k):
        with self.assertRaises(HTTPException) as e: fn(*a, **k)
        self.assertEqual(e.exception.status_code, code, e.exception.detail)


# ---------- competition team agents: mining_work.update_agent, versions in the Upgrade Factory's au_versions ----------
class TeamAgent(Base):
    def setUp(self):
        super().setUp()
        self.db.q("""CREATE TABLE mw_agents (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, role TEXT, name TEXT, title TEXT, job TEXT,
                     instructions TEXT, icon TEXT, color TEXT, model TEXT DEFAULT 'auto', lead INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
                     created REAL, squad TEXT, head INTEGER DEFAULT 0)""")
        self.db.q("INSERT INTO mw_agents (id, comp_id, role, name, title, job, instructions, model) VALUES (2, ?, 'reviewer', 'Rae', 'Reviewer', 'Reviews', ?, 'auto')",
                  (WID, OLD))
        w = object.__new__(mining_work.Work)
        w.db, w.lock = self.db, threading.Lock()
        w._own = lambda me, wid: ({"id": wid}, {"id": 1, "user_id": ME["id"]})
        w._event = lambda *a, **k: None
        w._kick = lambda wid: None
        w.view = lambda me, wid: {"ok": True}
        self.w, self.up = w, mining_upgrade.Upgrade(w)
        self.up.view = lambda me, wid: {"ok": True}

    def agent(self): return self.db.q("SELECT * FROM mw_agents WHERE id=2", one=True)
    def versions(self): return self.db.q("SELECT * FROM au_versions WHERE agent_id=2 ORDER BY version")
    def patch(self, **kw): return self.w.update_agent(ME, WID, 2, mining_work.AgentPatch(**kw), "10.0.0.9")

    def test_a_change_without_a_reason_is_refused_and_writes_nothing(self):
        for kw in ({"instructions": NEW}, {"model": "anthropic:claude-opus"}, {"job": "Reviews and benchmarks"},
                   {"instructions": NEW, "reason": "  "}, {"instructions": NEW, "reason": "ok"}):
            self.refused(422, self.patch, **kw)
        self.assertEqual((self.agent()["instructions"], self.agent()["model"], self.agent()["job"]), (OLD, "auto", "Reviews"))
        self.assertEqual((self.versions(), self.edits()), ([], []))

    def test_an_instructions_edit_is_versioned_and_audited(self):
        t0 = time.time()
        self.patch(instructions=NEW, reason="Reviews approved a change\n with no benchmark run", evidence="sbx:41")
        self.assertEqual(self.agent()["instructions"], NEW)
        v1, v2 = self.versions()
        self.assertEqual((v1["version"], v1["instructions"], v1["source"]), (1, OLD, "original"))  # what it replaced is kept
        self.assertEqual((v2["version"], v2["instructions"], v2["source"], v2["by_user"]), (2, NEW, "edit", "leo"))
        (e,) = self.edits()
        self.assertEqual((e["actor"], e["target"], e["ip"]), ("leo", "teams:2", "10.0.0.9"))
        self.assertGreaterEqual(e["ts"], t0)
        self.assertEqual(e["d"], {"reason": "Reviews approved a change with no benchmark run", "store": "au_versions", "previous_version": 1,
                                  "new_version": 2, "rollback": {"restore": v1["id"]}, "changed": ["instructions"], "evidence": "sbx:41"})

    def test_a_model_or_job_edit_gets_a_version_row_and_its_values_in_the_audit_row(self):
        self.patch(model="anthropic:claude-opus", job="Reviews and benchmarks", reason="Opus catches more regressions")
        self.assertEqual((self.agent()["model"], self.agent()["job"], self.agent()["instructions"]), ("anthropic:claude-opus", "Reviews and benchmarks", OLD))
        self.assertEqual([(v["version"], v["instructions"], v["source"]) for v in self.versions()], [(1, OLD, "original"), (2, OLD, "edit")])
        (e,) = self.edits()
        self.assertEqual(e["d"]["changed"], ["job", "model"])
        self.assertEqual(e["d"]["values"], {"model": ["auto", "anthropic:claude-opus"], "job": ["Reviews", "Reviews and benchmarks"]})
        self.assertNotIn("evidence", e["d"])

    def test_staffing_changes_and_unchanged_values_need_no_reason_and_write_no_version(self):
        self.patch(on=False); self.patch(color="blue", title="Senior reviewer"); self.patch(instructions=OLD, model="auto", job="Reviews")
        self.assertEqual((self.agent()["active"], self.agent()["title"]), (0, "Senior reviewer"))
        self.assertEqual((self.versions(), self.edits()), ([], []))

    def test_rollback_and_comparison_go_through_the_store(self):
        self.patch(instructions=NEW, reason="Add the benchmark check")
        (e,) = self.edits()
        new = self.versions()[-1]
        cmp_ = self.up.compare(ME, new["id"])
        self.assertEqual((cmp_["from"]["version"], cmp_["to"]["version"], cmp_["same"]), (1, 2, False))
        self.assertIn("-" + OLD, cmp_["diff"]); self.assertIn("+" + NEW, cmp_["diff"])
        self.up.restore(ME, e["d"]["rollback"]["restore"])  # the audit row's reference is what undoes the edit
        self.assertEqual(self.agent()["instructions"], OLD)
        self.assertEqual([v["source"] for v in self.versions()], ["original", "edit", "restored v1"])
        e2 = self.edits()[-1]
        self.assertEqual((e2["d"]["reason"], e2["d"]["previous_version"], e2["d"]["new_version"], e2["d"]["rollback"]),
                         ("Restored version 1", 2, 3, {"restore": new["id"]}))
        self.assertTrue(self.up.compare(ME, self.versions()[-1]["id"], against=self.versions()[0]["id"])["same"])

    def test_without_the_version_store_nothing_is_changed(self):
        del self.w.upgrade
        self.refused(503, self.patch, instructions=NEW, reason="Add the benchmark check")
        self.assertEqual((self.agent()["instructions"], self.edits()), (OLD, []))
        self.patch(on=False)  # staffing still works
        self.assertEqual(self.agent()["active"], 0)

    def test_a_refused_edit_writes_no_version(self):
        self.db.q("INSERT INTO mw_agents (id, comp_id, name) VALUES (5, ?, 'Gus')", (WID,))
        self.w._by_name = lambda wid: {"gus": {"id": 5}}
        self.refused(409, self.patch, name="Gus", instructions=NEW, reason="Add the benchmark check")
        self.assertEqual((self.agent()["instructions"], self.versions(), self.edits()), (OLD, [], []))


# ---------- Workforce agents: workforce.patch_agent, versions in wf_versions ----------
class Hub:
    llm = source = None
    def tools_for(self, owner): return []
    def gate(self, me): return me


class WorkforceAgent(Base):
    def setUp(self):
        super().setUp()
        self.wf = workforce.Workforce(self.db, Hub(), None)
        self.wf.agent_view = lambda me, key: {"ok": True}
        self.a = next(a for a in self.wf._agents(ME["id"]) if a["team"] != "exec" and len(workforce.TEAM_TOOLS.get(a["team"], ())) > 1)
        self.key = self.a["key"]
        allowed = sorted(workforce.TEAM_TOOLS[self.a["team"]])
        self.tools = [t for t in allowed if t not in self.a["tools"]][:1] or allowed[:1]
        if sorted(self.tools) == sorted(self.a["tools"]): self.tools = []

    def agent(self): return next(a for a in self.wf._agents(ME["id"]) if a["key"] == self.key)
    def versions(self): return self.db.q("SELECT * FROM wf_versions WHERE agent_id=? ORDER BY version", (self.a["id"],))
    def patch(self, **kw): return self.wf.patch_agent(ME, self.key, workforce.AgentPatch(**kw), "10.0.0.9")

    def test_a_change_without_a_reason_is_refused_and_writes_nothing(self):
        text = self.a["instructions"] + " Always cite the block number."
        for kw in ({"tools": self.tools}, {"instructions": text}, {"tools": self.tools, "instructions": text, "note": " "},
                   {"tools": self.tools, "status": "paused", "name": "Renamed"}):
            self.refused(422, self.patch, **kw)
        a = self.agent()
        self.assertEqual((a["tools"], a["instructions"], a["version"], a["status"], a["name"]),
                         (self.a["tools"], self.a["instructions"], self.a["version"], self.a["status"], self.a["name"]))
        self.assertEqual((len(self.versions()), self.edits()), (1, []))

    def test_a_tools_edit_is_versioned_with_the_tool_set_and_audited(self):
        self.patch(tools=self.tools, note="The team no longer reads the repository", evidence="wf mission 12")
        a = self.agent()
        self.assertEqual((a["tools"], a["version"]), (sorted(self.tools), self.a["version"] + 1))
        v = self.versions()[-1]
        self.assertEqual((v["version"], v["instructions"], v["source"], v["author"]), (a["version"], self.a["instructions"], "user", "leo"))
        self.assertTrue(v["note"].startswith(f"Tools: {','.join(sorted(self.tools)) or 'none'}. The team no longer"), v["note"])
        (e,) = self.edits()
        self.assertEqual((e["actor"], e["target"], e["ip"]), ("leo", f"workforce:{self.a['id']}", "10.0.0.9"))
        self.assertEqual(e["d"], {"reason": "The team no longer reads the repository", "store": "wf_versions", "previous_version": self.a["version"],
                                  "new_version": a["version"], "rollback": {"restore": self.a["version"]}, "changed": ["tools"],
                                  "values": {"tools": [",".join(sorted(self.a["tools"])), ",".join(sorted(self.tools))]}, "evidence": "wf mission 12"})

    def test_instructions_and_tools_together_make_one_version_and_one_audit_row(self):
        text = self.a["instructions"] + " Always cite the block number."
        self.patch(tools=self.tools, instructions=text, note="Reports lacked the block they read")
        a = self.agent()
        self.assertEqual((a["instructions"], a["version"], len(self.versions())), (text, self.a["version"] + 1, 2))
        (e,) = self.edits()
        self.assertEqual((e["d"]["changed"], e["d"]["reason"]), (["instructions", "tools"], "Reports lacked the block they read"))

    def test_staffing_changes_and_unchanged_values_need_no_reason(self):
        self.patch(name="Renamed", title="Lead analyst"); self.patch(tools=self.a["tools"], instructions=self.a["instructions"])
        self.assertEqual((self.agent()["name"], self.agent()["version"], len(self.versions()), self.edits()), ("Renamed", self.a["version"], 1, []))

    def test_restore_is_audited_and_undoes_the_instructions(self):
        text = self.a["instructions"] + " Always cite the block number."
        self.patch(instructions=text, note="Reports lacked the block they read")
        (e,) = self.edits()
        self.wf.restore(ME, self.key, workforce.RestoreIn(version=e["d"]["rollback"]["restore"]), "10.0.0.9")
        a = self.agent()
        self.assertEqual((a["instructions"], a["version"]), (self.a["instructions"], self.a["version"] + 2))
        e2 = self.edits()[-1]
        self.assertEqual((e2["d"]["reason"], e2["d"]["previous_version"], e2["d"]["new_version"]), ("Restored version 1", a["version"] - 1, a["version"]))


# ---------- Workbench agents: mining_bench.update_agent (the Team card), versions in the loadout's ml_versions ----------
class WorkbenchAgent(Base):
    def setUp(self):
        super().setUp()
        work = types.SimpleNamespace(db=self.db, _own=lambda me, wid: ({"id": wid}, {"id": 1, "user_id": ME["id"]}))
        self.b = mining_bench.Bench(work, url="", token="")
        self.lo = mining_loadout.Loadouts(work)
        self.b.view = lambda me, wid: {"ok": True}
        self.lo.view = lambda me, fid: {"ok": True}
        self.db.q("INSERT INTO mb_flows (id, comp_id, user_id, created) VALUES (1, ?, ?, ?)", (WID, ME["id"], time.time()))
        self.db.q("INSERT INTO mb_agents (id, flow_id, role, name, instructions, model, created) VALUES (4, 1, 'reviewer', 'Rae', ?, 'sonnet', ?)", (OLD, time.time()))

    def agent(self): return self.db.q("SELECT * FROM mb_agents WHERE id=4", one=True)
    def versions(self): return self.db.q("SELECT * FROM ml_versions WHERE agent_id=4 ORDER BY n")
    def patch(self, **kw): return self.b.update_agent(ME, 4, mining_bench.AgentPatch(**kw))

    def test_a_change_without_a_reason_is_refused_and_writes_nothing(self):
        for kw in ({"model": "opus"}, {"instructions": NEW}, {"name": "Rae", "model": "opus", "instructions": NEW, "reason": ""}):
            self.refused(422, self.patch, **kw)
        self.assertEqual((self.agent()["model"], self.agent()["instructions"], self.versions(), self.edits()), ("sonnet", OLD, [], []))

    def test_a_team_card_edit_is_versioned_and_audited(self):
        self.patch(name="Rae", model="opus", instructions=NEW, reason="Reviews missed failing tests", evidence="mb task 9")
        self.assertEqual((self.agent()["model"], self.agent()["instructions"]), ("opus", NEW))
        v1, v2 = self.versions()
        self.assertEqual((json.loads(v1["snap"])["model"], json.loads(v1["snap"])["instructions"]), ("sonnet", OLD))  # the state before, kept
        self.assertEqual((v2["n"], json.loads(v2["snap"])["model"], json.loads(v2["snap"])["instructions"], v2["note"], v2["source"], v2["user"]),
                         (2, "opus", NEW, "Reviews missed failing tests", "manual", "leo"))
        (e,) = self.edits()
        self.assertEqual((e["actor"], e["target"]), ("leo", "workflow:4"))
        self.assertEqual(e["d"], {"reason": "Reviews missed failing tests", "store": "ml_versions", "previous_version": 1, "new_version": 2,
                                  "rollback": {"restore": 1}, "changed": ["instructions", "model"], "values": {"model": ["sonnet", "opus"]},
                                  "evidence": "mb task 9"})

    def test_staffing_changes_and_unchanged_values_need_no_reason(self):
        self.patch(name="Rae B", on=False); self.patch(name="Rae B", model="sonnet", instructions=OLD)  # the card always sends all three
        self.assertEqual((self.agent()["name"], self.agent()["on_team"], self.versions(), self.edits()), ("Rae B", 0, [], []))

    def test_restore_undoes_the_edit_and_is_audited(self):
        self.patch(model="opus", instructions=NEW, reason="Reviews missed failing tests")
        (e,) = self.edits()
        self.lo.restore(ME, 4, mining_loadout.RestoreIn(version=e["d"]["rollback"]["restore"]))
        self.assertEqual((self.agent()["model"], self.agent()["instructions"]), ("sonnet", OLD))
        e2 = self.edits()[-1]
        self.assertEqual((e2["target"], e2["d"]["reason"], e2["d"]["previous_version"], e2["d"]["new_version"], e2["d"]["store"]),
                         ("workflow:4", "Back to version 1", 2, 3, "ml_versions"))

    def test_a_loadout_save_by_a_person_is_audited_and_a_promotion_is_not_called_an_edit(self):
        body = dict(skills=[], plugins=[], mcp=[], memory="own", effort="", budget=None)
        self.lo.save(ME, 4, mining_loadout.LoadoutIn(model="opus", note="Harder reviews", **body))
        (e,) = self.edits()
        self.assertEqual((e["d"]["reason"], e["d"]["changed"], e["d"]["new_version"]), ("Harder reviews", ["loadout"], self.versions()[-1]["n"]))
        self.lo.save(ME, 4, mining_loadout.LoadoutIn(model="haiku", note="Improvement #3: cheaper", source="improvement", **body))
        self.assertEqual(len(self.edits()), 1)  # the Improvements path is a promotion path (the gate's, L5.4b), not a manual edit


# ---------- K-21: "apply untested" is no longer a promotion ----------
class ApplyUntested(Base):
    def setUp(self):
        super().setUp()
        work = types.SimpleNamespace(db=self.db, _own=lambda me, wid: ({"id": wid}, {"id": 1, "user_id": ME["id"]}))
        self.b = mining_bench.Bench(work, url="", token="")
        self.lo = mining_loadout.Loadouts(work)
        self.imp = mining_improve.Improve(work)
        self.db.q("INSERT INTO mb_flows (id, comp_id, user_id, created) VALUES (1, ?, ?, ?)", (WID, ME["id"], time.time()))
        self.db.q("INSERT INTO mb_agents (id, flow_id, role, name, instructions, model, created) VALUES (4, 1, 'engineer', 'Eve', ?, 'sonnet', ?)", (OLD, time.time()))

    def test_an_untested_proposal_is_never_applied_whatever_its_state(self):
        for status in ("proposed", "same", "worse", "trial_failed", "better"):
            self.db.q("""INSERT INTO mb_improvements (flow_id, agent_id, base_version, status, change, candidate, created, updated)
                         VALUES (1, 4, 1, ?, 'Rewrite the instructions', ?, 1, 1)""", (status, json.dumps({"instructions": NEW, "model": "opus"})))
            iid = self.db.q("SELECT MAX(id) id FROM mb_improvements", one=True)["id"]
            with self.assertRaises(HTTPException) as e: self.imp.decide(ME, iid, mining_improve.DecideIn(decision="apply"))
            self.assertEqual(e.exception.status_code, 409); self.assertIn("can't be applied any more", e.exception.detail)
            self.assertEqual(self.db.q("SELECT status FROM mb_improvements WHERE id=?", (iid,), one=True)["status"], status)
        a = self.db.q("SELECT instructions, model FROM mb_agents WHERE id=4", one=True)
        self.assertEqual((a["instructions"], a["model"], self.db.q("SELECT COUNT(*) n FROM ml_versions", one=True)["n"]), (OLD, "sonnet", 0))
        self.assertNotIn('"applied"', open(APP / "mining_improve.py").read().split("def decide")[1].split("def ")[0])  # nothing sets that state any more


# ---------- static: every writer of these agent and version tables is classified ----------
TABLES = ("mw_agents", "mb_agents", "wf_agents", "ml_loadouts", "au_versions", "ml_versions", "wf_versions")
WRITE = re.compile(r"\b(UPDATE|INSERT(?: OR \w+)? INTO|DELETE FROM)\s+(%s)\b" % "|".join(TABLES))
VERSION_CALL = re.compile(r"(\.edited\(|upgrade\._version\(|self\._version\(|_new_version\(|\.lo\.save\(|\.lo\.restore\(|loadout\.save\(|loadout\.restore\(|self\.save\(|lo\._version\(.*note=)")
FILES = ("mining_work.py", "mining_upgrade.py", "mining_bench.py", "mining_loadout.py", "mining_improve.py", "mining_evolve.py", "mining_ops.py",
         "mining_portfolio.py", "workforce.py")

MANUAL = {  # a person's edit: must write the agent.edit audit row itself
    ("mining_work.py", "update_agent"), ("mining_upgrade.py", "restore"), ("workforce.py", "patch_agent"), ("workforce.py", "restore"),
    ("mining_bench.py", "update_agent"), ("mining_loadout.py", "save"),
}
STORE = {  # the stores' own version writers, and callers that only pass a person's edit on to a MANUAL function
    ("mining_upgrade.py", "_version"), ("mining_upgrade.py", "edited"), ("workforce.py", "_new_version"), ("mining_loadout.py", "_version"),
    ("mining_loadout.py", "template"), ("mining_loadout.py", "restore"),
    ("mining_loadout.py", "started"),  # a run records the version it ran on (a Team-card change not yet versioned becomes one here)
}
GATE = {("mining_upgrade.py", "gate_apply")}  # the promotion gate's own write (evolution.py, L5.4): trial start and end, promotion, rollback
PROMOTION = {  # the automated or measured paths that write an agent themselves. The Upgrade Factory's decide left this list with D-031
    # (Owner, 2026-11-13): it sends its candidate to the gate and writes nothing (tests/unit/test_upgrade_screening.py). These three
    # write Workforce and Workflow agents, not a Competition team's (mw_agents): whether D-031's rule extends to them is the Owner's.
    ("workforce.py", "decide_improvement"), ("mining_improve.py", "decide"),
    ("mining_evolve.py", "recorded"),  # self-improvement mode's automatic rollback: it restores through the loadout store under its own actor
}
STAFFING = {  # who is on a team, what an agent is called or looks like, new and removed agents, a renamed library skill: not configuration edits
    ("mining_work.py", "_seed"), ("mining_work.py", "_seed_pack"), ("mining_work.py", "create"), ("mining_work.py", "add_agent"),
    ("mining_work.py", "remove_agent"), ("mining_ops.py", "move"), ("mining_portfolio.py", "start_force"), ("mining_portfolio.py", "_dissolve"),
    ("mining_bench.py", "create"), ("mining_bench.py", "add_agent"), ("mining_bench.py", "remove_agent"), ("mining_loadout.py", "_rename"),
    ("workforce.py", "_seed"), ("workforce.py", "hire"), ("workforce.py", "fire"),
}


def writers():
    """(file, function) of every statement that writes one of TABLES, and of every call into a version writer, across backend/app."""
    found, bodies = {}, {}
    for p in sorted(APP.glob("*.py")):
        src = p.read_text()
        funcs = [(n.lineno, n.end_lineno, n.name) for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            if not (WRITE.search(line) or (p.name in FILES and VERSION_CALL.search(line) and not line.lstrip().startswith(("def ", "#")))): continue
            lo, hi, name = max((f for f in funcs if f[0] <= i <= f[1]), key=lambda f: f[0], default=(1, len(lines), "<module>"))
            found.setdefault((p.name, name), []).append(i)
            bodies[(p.name, name)] = "\n".join(lines[lo - 1:hi])
    return found, bodies


class EveryWriterIsClassified(unittest.TestCase):
    def test_no_writer_is_unclassified_and_no_classification_is_stale(self):
        found, _ = writers()
        known = MANUAL | STORE | PROMOTION | STAFFING | GATE
        self.assertEqual(sorted(set(found) - known), [], "new writers of an agent or version table: classify them in this test")
        self.assertEqual(sorted(known - set(found)), [], "classified here but no longer writing: remove them from this test")
        self.assertEqual(len(known), len(MANUAL) + len(STORE) + len(PROMOTION) + len(STAFFING) + len(GATE), "a writer is in two classes")

    def test_every_manual_edit_function_writes_the_audit_row(self):
        _, bodies = writers()
        for key in sorted(MANUAL):
            self.assertIn("agent_edit(", bodies[key], f"{key} changes an agent's configuration without the agent.edit audit row")

    def test_the_gates_write_is_called_only_by_the_gate(self):
        callers = {(p.name, n.name) for p in APP.glob("*.py") for n in ast.walk(ast.parse(p.read_text()))
                   if isinstance(n, ast.FunctionDef) and n.name != "gate_apply" and "gate_apply(" in ast.get_source_segment(p.read_text(), n)}
        self.assertEqual(callers, {("evolution.py", "trial_start"), ("evolution.py", "trial_end"), ("evolution.py", "promote"), ("evolution.py", "rollback")})

    def test_only_manual_edit_functions_write_the_audit_row(self):
        callers = {(p.name, n.name) for p in APP.glob("*.py") for n in ast.walk(ast.parse(p.read_text()))
                   if isinstance(n, ast.FunctionDef) and n.name != "agent_edit" and "agent_edit(" in ast.get_source_segment(p.read_text(), n)}
        self.assertEqual(callers, MANUAL)


if __name__ == "__main__":
    unittest.main()
