"""mining_rivals.py: the competitor harvest of a Ridges competition (every agent, failed ones included) from synthetic pages
shaped like ridges.ai's (Next.js flight chunks; the code as a JSON string in a text row, as the code viewer passes it)."""
import json, os, tempfile, unittest
from unittest import mock

from app import mining_rivals as rv, mining_web, mining_work
from app.auth import AuthDB

CODE = 'import os\n\ndef solve(task):\n    """Read, explore, deliver, verify."""\n    return "patch"\n'


def page(*lines):
    """An HTML page whose flight payload is these rows (a JSON row is dumped; a (id, text) pair becomes a text row)."""
    rows = []
    for i, x in enumerate(lines):
        if isinstance(x, tuple):
            t = json.dumps(x[1])
            rows.append(f"{x[0]}:T{len(t.encode()):x},{t}")
        else:
            rows.append(f"{i + 1:x}:{json.dumps(x)}\n")
    payload = "".join(rows)
    half = len(payload) // 2  # split across two pushes, as a real page does
    return "<html><body>" + "".join(f"<script>self.__next_f.push([1,{json.dumps(p)}])</script>" for p in (payload[:half], payload[half:])) + "</body></html>"


def agent(aid, name, v, hk, status, score, set_id=30):
    return {"agent_id": aid, "id": aid, "name": name, "version_num": v, "miner_hotkey": hk, "status": "finished", "created_at": f"$D2026-11-0{v + 1}T10:00:00Z",
            "competition_state": {"set_id": set_id, "status": status, "final_score": score, "approved": status == "approved"}}


def explore_page(agents):
    return page(["$", "div", None, {"children": [["$", "Row", a["agent_id"], {"agent": a}] for a in agents]}])


def run(p, reward, err=None, i=0):
    return {"evaluation_run_id": f"r{p}{i}{reward}", "evaluation_id": "e1", "status": "finished" if not err else "error", "problem_alias": p, "verifier_reward": reward,
            "error_code": None, "error_message": err, "cost_usd": 0.05, "benchmark_family": "problem_solving",
            "started_running_agent_at": "$D2026-11-08T22:49:06.902Z", "finished_or_errored_at": "$D2026-11-08T22:50:49.154Z"}


def agent_page(runs, code=CODE, versions=()):
    """An agent page: its runs, the miner's versions (rows without the hotkey, as on ridges.ai), and the code viewer when the code is shown."""
    rows = [{k: v for k, v in a.items() if k != "miner_hotkey"} for a in versions]
    parts = [["$", "div", None, {"runs": runs}], ["$", "ul", None, {"versions": rows}]]
    return page(("3b", code), *parts, ["$", "$L3a", None, {"code": "$3b", "showCopyButton": False}]) if code else page(*parts)


# the explore page: each miner's current agent; Monsoon's v8 is only on Monsoon's own pages
FIELD = [agent("a1", "Monsoon", 9, "hkA", "approved", 0.52), agent("b1", "Dani", 4, "hkB", "approved", 0.50),
         agent("c1", "Mine", 1, "hkME", "didnt_qualify", 0.20), agent("e1", "Fresh", 0, "hkE", "evaluating", None),
         agent("old", "Old", 3, "hkO", "approved", 0.9, set_id=29)]
MONSOON = [agent("a1", "Monsoon", 9, "hkA", "approved", 0.52), agent("a0", "Monsoon", 8, "hkA", "didnt_qualify", 0.41)]
SHOWN = {"a0": CODE, "c1": CODE + "# mine\n"}  # ridges.ai shows earlier versions' code, not always the current one's
RUNS = {"a1": [run("P1", 1), run("P2", 1), run("P3", 0), run("P4", 1)],
        "a0": [run("P1", 1), run("P2", 0), run("P3", 0), run("P4", 0, "The agent did not return a patch")],
        "b1": [run("P1", 1), run("P2", 1), run("P3", 0), run("P4", 0)],
        "c1": [run("P1", 1), run("P2", 0), run("P3", 0), run("P4", 0, "The agent did not return a patch")],
        "e1": [run("P1", 0)]}


class Parse(unittest.TestCase):
    def test_explore_keeps_one_competition_and_reads_its_standing(self):
        got = rv.explore(explore_page(FIELD), 30)
        self.assertEqual([a["agent_id"] for a in got], ["a1", "b1", "c1", "e1"])                 # set 29's agent left out
        self.assertEqual({a["agent_id"]: a["status"] for a in got}["c1"], "didnt_qualify")      # the competition's status, not "finished"
        self.assertEqual(got[0]["score"], 0.52); self.assertEqual(got[0]["version"], 9)

    def test_agent_page_gives_the_code_and_every_run(self):
        p = rv.agent_page(agent_page(RUNS["a0"], versions=MONSOON), 30, "hkA")
        self.assertEqual(p["code"], CODE)                                                         # the JSON-string text row, decoded
        self.assertEqual([(v["agent_id"], v["version"], v["hotkey"], v["status"]) for v in p["versions"]],
                         [("a1", 9, "hkA", "approved"), ("a0", 8, "hkA", "didnt_qualify")])     # the miner's versions, its hotkey carried over
        self.assertIsNone(rv.agent_page(agent_page(RUNS["a1"], code=None))["code"])
        self.assertEqual([r["problem"] for r in p["runs"]], ["P1", "P2", "P3", "P4"])
        self.assertEqual(p["runs"][3]["error"], "The agent did not return a patch")
        self.assertAlmostEqual(p["runs"][0]["seconds"], 102.3, places=1)

    def test_analysis_names_openings_failures_and_what_moved_scores(self):
        ags = [dict(a, runs=rv.agent_page(agent_page(RUNS[a["agent_id"]]))["runs"], code=CODE + ("# v9\n" if a["agent_id"] == "a1" else ""))
               for a in rv.explore(explore_page(FIELD), 30)]
        ags.append(dict(rv.explore(explore_page(MONSOON), 30)[1], runs=rv.agent_page(agent_page(RUNS["a0"]))["runs"], code=CODE, latest=False))
        s = rv.analyze(ags, ["hkME"])
        self.assertEqual((s["agents"], s["versions"]), (4, 1))                                   # the field is the current agents
        self.assertEqual([x["problem"] for x in s["nobody"]], ["P3"])
        self.assertEqual(s["leaders"][0]["name"], "Monsoon"); self.assertEqual(s["leaders"][0]["solved"], 3)
        self.assertEqual(s["failures"][0], {"error": "The agent did not return a patch", "runs": 1, "agents": 1, "side": "agent"})
        j = s["jumps"][0]
        self.assertEqual((j["name"], j["from"], j["to"], j["delta"], j["lines_changed"]), ("Monsoon", 8, 9, 0.11, 1))
        self.assertEqual({x["problem"] for x in s["misses"]}, {"P2", "P4"})                      # leaders solve them, the user's agent doesn't
        d = rv.digest(s, 900, 30)
        self.assertIn("never copy", d); self.assertIn("nobody solves: P3", d); self.assertLessEqual(len(d), 900)


class FakeWork:
    def __init__(self, db): self.db, self.events = db, []
    def _write_file(self, wid, path, content, agent_id=None):
        self.db.q("""INSERT INTO mw_files (comp_id, path, content, size, updated) VALUES (?,?,?,?,0)
                     ON CONFLICT(comp_id, path) DO UPDATE SET content=excluded.content, size=excluded.size""", (wid, path, content, len(content.encode())))
    def _event(self, wid, kind, text): self.events.append(text)
    def _own(self, me, wid): return {"id": wid}, {}


class Harvest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE IF NOT EXISTS mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER, keys TEXT)")
        q("CREATE TABLE IF NOT EXISTS mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT, link TEXT, source TEXT, import_key TEXT, goal TEXT)")
        q("CREATE TABLE IF NOT EXISTS mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT, size INTEGER, agent_id INTEGER, updated REAL, UNIQUE (comp_id, path))")
        q("INSERT INTO mh_campaigns (id, user_id, netuid, keys) VALUES (1, 1, 62, ?)", (json.dumps(["hkME"]),))
        q("INSERT INTO mw_comps (id, campaign_id, number, name, status, source) VALUES (1, 1, 30, 'Problem Solving', 'active', 'ridges')")
        self.r = rv.Rivals(FakeWork(self.db))
        self.reads = []

    def tearDown(self): self.dir.cleanup()

    def fetch(self, url):
        self.reads.append(url.rsplit("/", 1)[1])
        if "/explore/" in url: return {"text": explore_page(FIELD)}
        aid = url.rsplit("/", 1)[1]
        if aid == "refused": raise mining_web.WebError("The page answered 429 (it may refuse automated readers).")
        return {"text": agent_page(RUNS.get(aid, []), code=SHOWN.get(aid), versions=MONSOON if aid in ("a0", "a1") else ())}

    def files(self): return {f["path"]: f["content"] for f in self.db.q("SELECT path, content FROM mw_files WHERE comp_id=1")}

    def test_reads_every_agent_once_then_only_the_ones_still_evaluated(self):
        out = self.r.harvest(1, fetch=self.fetch, sleep=lambda s: None)
        self.assertEqual((out["read"], out["agents"]), (5, 4))
        self.assertEqual(self.reads[0], "30")                                                     # the competition's own explore page
        self.assertIn("a0", self.reads)                                                           # found on Monsoon's page, read too
        f = self.files()
        self.assertIn("data/rivals/30/summary.md", f); self.assertIn("never to copy", f["data/rivals/30/summary.md"])
        self.assertIn("data/rivals/30/code/Monsoon-v8.py", f)                                     # the leader's newest version whose code is shown
        self.assertNotIn("data/rivals/30/code/Monsoon-v9.py", f)
        self.assertIn("data/rivals/30/code/Mine-v1.py", f)                                        # the user's own agent too
        s = self.r.summary(1)
        self.assertEqual((s["agents"], s["versions"], s["code"]), (4, 1, 2))
        self.assertEqual((s["jumps"][0]["from"], s["jumps"][0]["to"], s["jumps"][0]["delta"]), (8, 9, 0.11))
        self.reads.clear()
        self.r.harvest(1, fetch=self.fetch, sleep=lambda s: None)
        self.assertEqual(self.reads, ["30", "e1"])                                                # finished agents never change: not read again
        self.assertIn("nobody solves", self.r.plan_note(1))

    def test_a_refusal_stops_the_pass_and_a_later_one_tries_again(self):
        field, real = FIELD + [agent("refused", "Shy", 0, "hkS", "approved", 0.6)], rv.explore
        with mock.patch.object(rv, "explore", lambda html, s: real(explore_page(field), s)):
            out = self.r.harvest(1, fetch=self.fetch, sleep=lambda s: None)
        self.assertIn("429", out["error"])
        self.assertEqual(self.reads[:2], ["30", "refused"])                                      # leaders first; the refusal ends the pass
        st = self.db.q("SELECT next_at, last_at FROM rv_state WHERE comp_id=1", one=True)
        self.assertLess(st["next_at"] - st["last_at"], rv.FRESH)                                  # it comes back sooner

    def test_files_stay_within_the_teams_space_and_old_code_is_evicted(self):
        self.db.q("INSERT INTO mw_files (comp_id, path, content, size) VALUES (1, 'data/rivals/30/code/Gone-v1.py', 'x', 1)")
        with mock.patch.object(mining_work, "FILES_BYTES", 6000):
            self.r.harvest(1, fetch=self.fetch, sleep=lambda s: None)
        f = self.files()
        self.assertNotIn("data/rivals/30/code/Gone-v1.py", f)
        self.assertLessEqual(sum(len(v.encode()) for p, v in f.items() if p.startswith("data/rivals/")), int(6000 * rv.CODE_SHARE))
        self.assertIn("data/rivals/30/summary.md", f)                                            # the summary goes first

    def test_two_researchers_of_one_team_share_one_pass(self):
        import threading, time as _t
        gate = threading.Event()
        def slow(url):
            gate.wait(5)
            return self.fetch(url)
        self.r.harvest = (lambda f: lambda wid: f(wid, fetch=slow, sleep=lambda s: None))(self.r.harvest)
        got = []
        ts = [threading.Thread(target=lambda: got.append(self.r.fresh(1))) for _ in range(2)]
        for t in ts: t.start()
        _t.sleep(0.2); gate.set()
        for t in ts: t.join(10)
        self.assertEqual(len(got), 2)
        self.assertTrue(all(g and g["agents"] == 4 for g in got))                                # the second waited, then read the first's summary
        self.assertEqual(self.reads.count("30"), 1)                                               # one pass, not two

    def test_only_ridges_competitions(self):
        self.db.q("UPDATE mw_comps SET source='import', link='https://example.org/contest' WHERE id=1")
        with self.assertRaises(ValueError): self.r.harvest(1, fetch=self.fetch)
        self.assertEqual(self.r.plan_note(1), "")


if __name__ == "__main__":
    unittest.main()
