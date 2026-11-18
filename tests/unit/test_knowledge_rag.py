"""Knowledge Hub RAG (knowledge_rag.py): chunking along a document's structure, the BM25 keyword index over passages, passage
vectors, query understanding, hybrid fusion + rerank + graph expansion, permission filtering before ranking, Ask with points,
multi-hop and citation checks, the retrieval log and the evaluation center."""
import os, tempfile, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

import fake_knowledge_apis as fake
from app import knowledge_hub as kh, knowledge_media as km, knowledge_rag as kr
from app.auth import AuthDB
from app.knowledge_spaces import CaptureIn, GrantIn, LinkIn, RecordIn
from app.knowledge_rag import EvalIn, EvalRunIn, RagAskIn, TryIn

ME = {"id": 7, "username": "leo", "role": "admin"}
SRV, URL = fake.start()

LONG = "\n\n".join([
    "# Miner handbook",
    "This handbook collects what we learned running miners. " * 6,
    "[page 1]",
    "## Setup",
    "Install the toolkit and pull the weights. Keep the GPU drivers current. " * 8,
    "[page 2]",
    "## Evaluation",
    "Score every checkpoint on the held-out tasks before you push it. The harness compares against the base. " * 6,
    "```python\ndef evaluate(model):\n    # the harness\n    return run(model, tasks)\n```",
    "| run | score |\n| --- | --- |\n| r1 | 0.82 |\n| r2 | 0.91 |",
    "[page 3]",
    "## Failures",
    "Filler about logistics and planning and meetings. " * 100,
    "When the pod restarts mid-run the uploader dies with ERR_CONN_RESET_42 and the checkpoint is lost; retry with backoff.",
])


class LLM:
    def __init__(self): self.calls = []
    def any_configured(self): return True
    def resolve(self, m): return ("anthropic", "claude-test")
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort=None, messages=None):
        self.calls.append(name)
        if on_usage: on_usage(10)
        refs = [ln.split("]")[0][1:] for ln in prompt.splitlines() if ln.startswith("[kb:")]
        if name == "hops": return {"queries": ["reward curve emissions"]}
        if name == "rerank":
            n = prompt.count("\n[") + 1
            return {"ratings": [{"n": i, "score": 3 if i == n - 1 else (0 if i == 0 else 1)} for i in range(n)]}
        if name == "ask":
            return {"answer": f"Retry the upload with backoff [{refs[0]}]. Unknown [kb:99999].",
                    "points": [{"claim": "Retry the uploader with backoff when the pod restarts", "refs": [refs[0], "kb:99999"], "basis": "evidence"},
                               {"claim": "Quantum entanglement doubles miner throughput", "refs": [refs[0]], "basis": "evidence"},
                               {"claim": "It probably helps on every subnet", "refs": [], "basis": "evidence"}],
                    "evidence": [{"ref": r, "why": "Says so."} for r in refs[:2]] + [{"ref": "kb:99999", "why": "x"}],
                    "gaps": ["No numbers."], "directions": ["Measure it."], "limitations": ["One source."], "confidence": "medium"}
        raise AssertionError(name)


class HubStub:
    def __init__(self): self.llm = LLM()
    def log_usage(self, *a, **k): pass
    def model_of(self, m): return "fake"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old = km.DATA_DIR
        km.DATA_DIR = __import__("pathlib").Path(self.dir.name)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q, now = self.db.q, time.time()
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        q("CREATE TABLE co_company (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, name TEXT)")
        q("CREATE TABLE co_divisions (id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, status TEXT DEFAULT 'active')")
        q("CREATE TABLE co_projects (id INTEGER PRIMARY KEY, company_id INTEGER, division_id INTEGER, name TEXT, objective TEXT, status TEXT DEFAULT 'planning')")
        q("INSERT INTO custom_agents VALUES (1, 7, 'Scout', 'Researcher', '', 'Research.', '[]', 'live', ?)", (now,))
        q("INSERT INTO co_company VALUES (1, 7, 'Acme')")
        q("INSERT INTO co_divisions VALUES (1, 1, 'Mining', 'active')")
        q("INSERT INTO co_projects VALUES (3, 1, 1, 'SN62 miner', 'Win', 'active')")
        q("INSERT INTO users (id, username, pw_hash, created) VALUES (7, 'leo', 'x', ?)", (now,))
        self.hub = HubStub()
        self.K = kh.Hub(self.db, self.hub, lambda m: None)
        for k in ("KNOWLEDGE_EMBED_URL", "KNOWLEDGE_EMBED_MODEL"): os.environ.pop(k, None)

    def tearDown(self):
        km.DATA_DIR = self.old
        for k in ("KNOWLEDGE_EMBED_URL", "KNOWLEDGE_EMBED_MODEL"): os.environ.pop(k, None)
        self.dir.cleanup()

    def note(self, title, text, **kw):
        return self.K.capture(ME, CaptureIn(kind="note", title=title, text=text, **kw))

    def doc(self, title="Miner handbook", text=LONG):
        return self.K.capture(ME, CaptureIn(kind="paste", title=title, text=text))

    def refs(self, query, **kw):
        return [h["ref"] for h in self.K.retrieve(ME, query, 10, kw.pop("reach", "page"), **kw)]


class Chunking(Base):
    def test_structure_is_kept(self):
        parts = kr.chunk("Miner handbook", LONG)
        self.assertGreater(len(parts), 3)
        ev = next(p for p in parts if "held-out tasks" in p["text"])
        self.assertIn("page 2", ev["where"]); self.assertIn("Evaluation", ev["where"])
        code = next(p for p in parts if "def evaluate" in p["text"])
        self.assertIn("return run(model, tasks)", code["text"])  # the code block stays whole
        table = next(p for p in parts if "| r1 | 0.82 |" in p["text"])
        self.assertIn("| r2 | 0.91 |", table["text"])
        fail = next(p for p in parts if "ERR_CONN_RESET_42" in p["text"])
        self.assertIn("page 3", fail["where"]); self.assertIn("Failures", fail["where"])
        self.assertTrue(all(len(p["text"]) <= kr.CHUNK_MAX * 2 for p in parts))
        self.assertEqual(len(kr.chunk("Short", "One line.")), 1)

    def test_understanding(self):
        u = kr.understand("Compare subnet 62 and netuid 64 results from last week")
        self.assertEqual(u["intent"], "compare"); self.assertTrue(u["multi"])
        self.assertIn("sn62", u["entities"]); self.assertIn("sn64", u["entities"])
        self.assertAlmostEqual(u["since"], time.time() - 7 * 86400, delta=5)
        self.assertTrue(kr.understand("what is the latest SN62 miner config")["recent"])
        self.assertIn("err_conn_reset_42", kr.entities("it died with ERR_CONN_RESET_42"))
        self.assertEqual(kr.understand("in 2025 what changed")["since"], kr._day("2025-01-01"))


class Hybrid(Base):
    def test_exact_identifier_deep_in_a_document(self):
        d = self.doc()
        self.note("Planning", "Notes about logistics and meetings.")
        self.assertNotIn(f"kb:{d['id']}", self.refs("ERR_CONN_RESET_42", strategy="words"))  # beyond what the old ranking read
        hits = self.K.retrieve(ME, "uploader ERR_CONN_RESET_42", 5, "page", trace=(tr := {}))
        self.assertEqual(hits[0]["ref"], f"kb:{d['id']}")
        self.assertIn("ERR_CONN_RESET_42", hits[0]["text"]); self.assertIn("page 3", hits[0]["where"])
        self.assertIn("keyword", hits[0]["legs"])
        self.assertEqual(tr["strategy"], "full"); self.assertGreaterEqual(tr["candidates"], 2)

    def test_queries_are_sanitized(self):
        self.doc()
        for q in ['"unbalanced', "a:b NEAR(c d)", "-x OR AND *", "()", "SN62's (latest) -- config?"]:
            self.K.retrieve(ME, q, 5, "page")  # no FTS syntax error escapes

    def test_edits_rechunk(self):
        n = self.note("Rate limits", "The pool caps uploads at forty per minute " * 40)
        self.assertIn(f"kb:{n['id']}", self.refs("forty uploads"))
        self.K.update(ME, n["id"], kh.ItemPatch(body="The pool caps downloads at ninety per hour " * 40))
        self.assertNotIn(f"kb:{n['id']}", self.refs("forty", strategy="keyword"))
        self.assertIn(f"kb:{n['id']}", self.refs("ninety", strategy="keyword"))
        self.K.delete(ME, n["id"])
        self.assertFalse(self.db.q("SELECT 1 FROM kb_chunks WHERE item_id=?", (n["id"],)))
        self.assertFalse(self.db.q("SELECT rowid FROM kb_fts WHERE item_id=?", (n["id"],)))

    def test_graph_expansion(self):
        a = self.note("Uploader crash", "The uploader crashes when the pod restarts.")
        b = self.note("Backoff policy", "Wait two, four, then eight seconds between tries.")
        self.K.link(ME, LinkIn(item_id=a["id"], ref=f"kb:{b['id']}", rel="supports", why="The fix."))
        hits = self.K.retrieve(ME, "uploader crashes pod", 5, "page")
        linked = next(h for h in hits if h["ref"] == f"kb:{b['id']}")
        self.assertEqual(linked["match"], "linked"); self.assertEqual(linked["via"]["ref"], f"kb:{a['id']}")
        self.assertNotIn(f"kb:{b['id']}", self.refs("uploader crashes pod", strategy="hybrid"))

    def test_passage_vectors(self):
        os.environ["KNOWLEDGE_EMBED_URL"], os.environ["KNOWLEDGE_EMBED_MODEL"] = URL + "/v1", "fake-embed"
        d = self.doc(text=LONG + "\n\n[page 4]\n\n## Onboarding\n\nEnroll the validator. Registration of the validator: enroll, register, signup.")
        self.assertGreater(self.K.rag_index(ME["id"]), 0)
        st = self.K.rag_status(ME)
        self.assertGreater(st["embedded"], 2); self.assertTrue(st["model"]["meaning"])
        self.assertEqual(st["models"][0]["dims"], fake.DIM)
        hits = self.K.retrieve(ME, "signup verifier", 5, "page", strategy="vector")  # no shared word: meaning only
        self.assertEqual(hits[0]["ref"], f"kb:{d['id']}"); self.assertIn("page 4", hits[0]["where"]); self.assertIn("Onboarding", hits[0]["where"]); self.assertIn("signup", hits[0]["text"])
        self.assertEqual(hits[0]["match"], "meaning")
        os.environ["KNOWLEDGE_EMBED_MODEL"] = "other-embed"  # a model change: old vectors are kept apart, then removed
        self.assertNotIn("fake-embed@", self.K.rag_drop_model(ME, f"fake-embed@{URL}/v1")["models"][0]["model"])
        self.assertFalse(self.db.q("SELECT 1 FROM kb_chunk_vecs WHERE model LIKE 'fake-embed@%'"))


class Permissions(Base):
    def setUp(self):
        super().setUp()
        self.private = self.note("Private zebra plan", "zebra moonshot strategy, only for me")
        self.shared = self.note("Shared zebra tips", "zebra tips my agents may read")
        self.K.update(ME, self.shared["id"], kh.ItemPatch(reach="agents"))
        self.pending = self.K.add_record(ME, RecordIn(title="Unreviewed zebra fact", body="zebra fact nobody reviewed yet", ktype="declarative"))
        self.project = self.K.add_record(ME, RecordIn(title="Project zebra procedure", body="zebra procedure for the SN62 project", ktype="procedural", scope="project:3", approve=True))
        self.company = self.K.add_record(ME, RecordIn(title="Company zebra decision", body="zebra decision for everyone", ktype="declarative", approve=True))

    def test_agents_read_only_what_they_may(self):
        mine = set(self.refs("zebra"))
        self.assertTrue({f"kb:{x['id']}" for x in (self.private, self.shared, self.pending, self.project, self.company)} <= mine)
        got = {r["ref"] for r in self.K.tool(ME, {"query": "zebra", "scope": "", "knowledge_type": ""}, "search_knowledge", "hub:1")["results"]}
        self.assertEqual(got, {f"kb:{self.shared['id']}", f"kb:{self.company['id']}"})
        self.K.grant(ME, GrantIn(scope="project:3", actor="hub:1"))
        got = {r["ref"] for r in self.K.tool(ME, {"query": "zebra", "scope": "", "knowledge_type": ""}, "search_knowledge", "hub:1")["results"]}
        self.assertIn(f"kb:{self.project['id']}", got); self.assertNotIn(f"kb:{self.private['id']}", got)
        teams = set(self.refs("zebra", reach="teams", actor="teams:5", internal=False))
        self.assertEqual(teams, {f"kb:{self.company['id']}"})  # shared with agents, not teams

    def test_try_as_actor_and_the_log(self):
        r = self.K.rag_try(ME, TryIn(query="zebra", actor="hub:1"))
        self.assertEqual({x["ref"] for x in r["results"]}, {f"kb:{self.shared['id']}", f"kb:{self.company['id']}"})
        with self.assertRaises(Exception): self.K.rag_try(ME, TryIn(query="zebra", actor="hub:999"))
        self.K.tool(ME, {"query": "zebra decision", "scope": "", "knowledge_type": ""}, "search_knowledge", "hub:1")
        lg = self.K.rag_log(ME)
        self.assertEqual(lg["rows"][0]["label"], "Scout"); self.assertEqual(lg["rows"][0]["query"], "zebra decision")
        self.assertTrue(lg["rows"][0]["refs"][0]["title"])
        self.assertTrue(any(a["actor"] == "hub:1" for a in lg["actors"]))

    def test_folders_narrow_cross_space(self):
        other = self.K.capture(ME, CaptureIn(kind="note", title="Filed zebra", text="zebra filed elsewhere", path="/07-Knowledge/Research"))
        got = set(self.refs("zebra", filters={"folders": ["/07-Knowledge"]}))
        self.assertIn(f"kb:{other['id']}", got); self.assertIn(f"kb:{self.company['id']}", got)
        self.assertNotIn(f"kb:{self.private['id']}", got)

    def test_evaluation_center(self):
        ev = self.K.add_eval(ME, EvalIn(question="zebra decision", expected=[f"kb:{self.company['id']}"]))
        self.assertEqual(len(ev["cases"]), 1)
        with self.assertRaises(Exception): self.K.add_eval(ME, EvalIn(question="x y z", expected=["kb:99999"]))
        self.K.add_eval(ME, EvalIn(question="moonshot strategy", expected=[f"kb:{self.private['id']}"], where="mine"))
        out = self.K.run_evals(ME, EvalRunIn(k=3))
        run = out["runs"][0]
        self.assertEqual(set(run["metrics"]), set(kr.STRATEGIES))
        self.assertEqual(run["metrics"]["full"]["recall"], 1.0); self.assertEqual(run["metrics"]["full"]["mrr"], 1.0)
        self.assertTrue(run["isolation"]["ok"]); self.assertGreater(run["isolation"]["checked"], 0)
        self.assertGreater(run["isolation"]["withheld"], 0)  # the private note matched for you, not for the probes
        self.assertEqual(len(out["last"]), 2)
        self.assertFalse(self.db.q("SELECT 1 FROM kb_queries WHERE strategy='keyword'"))  # evaluation runs aren't logged as use


class Agentic(Base):
    """Milestone 7: retrieval tools for every agent system, multi-step research, ratings that move the ranking, task-matched Company context."""
    def setUp(self):
        super().setUp()
        self.d = self.doc()
        self.shared = self.note("Backoff policy", "Retry the uploader with backoff: two, four, eight seconds. The uploader crashes when the pod restarts.")
        self.K.update(ME, self.shared["id"], kh.ItemPatch(reach="agents"))
        self.private = self.note("Private uploader notes", "uploader crashes, my private notes on the pod")
        self.rec = self.K.add_record(ME, RecordIn(title="Checkpoint policy", body="Score every checkpoint on held-out tasks before you push it.", ktype="procedural", approve=True))

    def test_research_runs_several_searches_inside_permissions(self):
        self.assertIn("research_knowledge", self.K.NAMES)
        r = self.K.tool(ME, {"question": "Why does the uploader crash and also how do we score checkpoints?", "scope": ""}, "research_knowledge", "hub:1")
        self.assertGreaterEqual(len(r["searches"]), 3)
        self.assertEqual(r["searches"][0]["why"], "the question")
        refs = {x["ref"] for x in r["results"]}
        self.assertIn(f"kb:{self.shared['id']}", refs); self.assertIn(f"kb:{self.rec['id']}", refs)
        self.assertNotIn(f"kb:{self.private['id']}", refs); self.assertNotIn(f"kb:{self.d['id']}", refs)  # private: not for agents
        self.assertTrue(all(x["found_by"] for x in r["results"]))
        self.assertEqual(kr.Rag._parts("compare SN62 miners with SN64 miners"), ["SN62 miners", "SN64 miners"])

    def test_teams_read_with_team_reach(self):
        tools = self.K.agent_tools(ME["id"], "teams:5", "SN62 · Alpha")
        self.assertEqual(set(tools), {"search_knowledge", "research_knowledge", "knowledge_feedback", "report_outcome", "request_knowledge_access", "recall_experience"})  # + knowledge_improve.py, experience.py
        got = {x["ref"] for x in tools["search_knowledge"][1]({"query": "uploader checkpoint", "scope": "", "knowledge_type": ""})["results"]}
        self.assertEqual(got, {f"kb:{self.rec['id']}"})  # shared with agents, not with teams
        self.K.update(ME, self.shared["id"], kh.ItemPatch(reach="teams"))
        got = {x["ref"] for x in tools["search_knowledge"][1]({"query": "uploader crashes", "scope": "", "knowledge_type": ""})["results"]}
        self.assertIn(f"kb:{self.shared['id']}", got)
        self.assertTrue(tools["knowledge_feedback"][1]({"ref": f"kb:{self.shared['id']}", "useful": True, "note": "it worked"})["ok"])
        self.assertIn("SN62 · Alpha", [r["label"] for r in self.K.rag_log(ME)["rows"]])

    def test_ratings_move_the_ranking_when_on(self):
        a = self.note("Gamma tuning A", "gamma tuning for the miner")
        b = self.note("Gamma tuning B", "gamma tuning for the miner")
        for x in (a, b): self.K.update(ME, x["id"], kh.ItemPatch(reach="agents"))
        first = self.refs("gamma tuning miner", strategy="full")[:2]
        loser = first[1]
        for _ in range(3):
            self.K.tool(ME, {"query": "gamma tuning", "scope": "", "knowledge_type": ""}, "search_knowledge", "hub:1")
            self.K.tool(ME, {"ref": loser, "useful": True, "note": ""}, "knowledge_feedback", "hub:1")
        self.assertEqual(self.refs("gamma tuning miner", strategy="learned")[0], loser)
        self.assertEqual(self.refs("gamma tuning miner")[:2], first)  # off by default: the default ranking is unchanged
        st = self.K.rag_settings(ME, kr.SettingsIn(learn=True))
        self.assertTrue(st["learning"]["on"]); self.assertEqual(st["learning"]["useful"], 3)  # one rating per use
        self.assertEqual(self.refs("gamma tuning miner")[0], loser)
        self.K.add_eval(ME, EvalIn(question="gamma tuning miner", expected=[loser]))
        self.K.run_evals(ME, EvalRunIn(k=1))
        ev = self.K.rag_status(ME)["learning"]["eval"]
        self.assertEqual(ev["verdict"], "better"); self.assertGreater(ev["delta"]["mrr"], 0)
        self.assertTrue(any(r["kind"] == "hub" and r["n"] for r in self.K.rag_status(ME)["readers"]))

    def test_company_runs_get_the_records_that_fit_their_task(self):
        other = self.K.add_record(ME, RecordIn(title="Holiday rota", body="Who is on call over the holidays.", ktype="declarative", approve=True))
        self.db.q("UPDATE kb_items SET confidence=0.99 WHERE id=?", (other["id"],))  # the most confident record, but off topic
        p = {"id": 3, "division_id": 1, "name": "SN62 miner", "objective": "Win"}
        rows = self.K.company_rows(ME["id"], p, task={"title": "Gate releases on checkpoint scores", "description": "held-out tasks"})
        self.assertEqual(rows[0]["ref"], f"kb:{self.rec['id']}"); self.assertIn("fits this task", rows[0]["scope"])
        self.assertEqual(rows[0]["title"], "Checkpoint policy")
        self.assertIn(f"kb:{other['id']}", [r["ref"] for r in rows])  # the rest still fill the places
        self.assertEqual(self.K.company_rows(ME["id"], p)[0]["ref"], f"kb:{other['id']}")  # without a task: most confident first, as before


class Asking(Base):
    def test_ask_points_checks_hops_and_rerank(self):
        d = self.doc()
        self.note("Reward curve", "Emissions follow the reward curve; the incentive drops after the first week.")
        r = self.K.ask(ME, RagAskIn(question="Why does the uploader fail and how do we retry it, and also what does the reward curve do?", rerank=True))
        self.assertEqual(self.hub.llm.calls, ["hops", "rerank", "ask"])
        self.assertEqual(r["hops"][0]["query"], "reward curve emissions")
        self.assertTrue(r["reranked"])
        self.assertNotIn("kb:99999", r["answer"])
        self.assertTrue(all(e["ref"] != "kb:99999" for e in r["evidence"]))
        self.assertEqual([p["refs"] for p in r["points"]][0], [r["evidence"][0]["ref"]])
        self.assertEqual(r["points"][2]["basis"], "unverified")  # "evidence" with nothing cited isn't evidence
        self.assertEqual((r["checks"]["cited"], r["checks"]["supported"]), (2, 1))
        self.assertEqual(r["checks"]["weak"], ["Quantum entanglement doubles miner throughput"])
        self.assertEqual(r["confidence"], "medium")
        self.assertIn(f"kb:{d['id']}", [h["ref"] for h in r["hits"]])
        q = self.db.q("SELECT strategy, cited FROM kb_queries WHERE strategy='ask'", one=True)
        self.assertIn("kb:", q["cited"])
        self.assertTrue(self.K.evals(ME)["suggestions"])  # the cited records become a suggested test question

    def test_no_hits_and_old_requests(self):
        self.note("Unrelated", "Weather in Paris.")
        r = self.K.ask(ME, RagAskIn(question="validator registration quorum"))
        self.assertEqual(r["answer"], ""); self.assertIn("by meaning", r["gaps"][0])
        self.assertEqual(self.hub.llm.calls, [])
        from app.knowledge_spaces import AskIn
        self.note("Validator", "Run the validator before you register.")
        self.assertTrue(self.K.ask(ME, AskIn(question="validator register"))["evidence"])


if __name__ == "__main__":
    unittest.main()
