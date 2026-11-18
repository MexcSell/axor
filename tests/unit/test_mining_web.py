"""mining_web.py: live web reading for Competition teams. Generic unpacking (Next.js flight data with records scattered through a
component tree, HTML tables, JSON APIs), recipes that survive a redesign, watches and their change reports, the sandbox's
network hint; and mining_work.update_task: a task an agent left for the user doesn't close empty."""
import json, os, tempfile, unittest

from fastapi import HTTPException

from app import mining_web, mining_work
from app.auth import AuthDB


def flight_page(agents, extra=""):
    """A page shaped like ridges.ai/explore/<n>: Next.js flight chunks, each agent's record inside a React element's props."""
    cards = [["$", "div", None, {"className": "card", "children": [["$", "span", None, {"className": "name", "children": a["name"]}],
                                                                   ["$", "$L2f", None, {"agent": a}]]}] for a in agents]
    payload = "0:" + json.dumps(["$", "main", None, {"className": "page", "children": cards}]) + "\n1:I[\"chunk.js\"]\n"
    return (f"<html><head><title>Overview | Example</title></head><body><h1>Top Agents</h1><p>To Beat 38% / $0.09 {extra}</p>"
            f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script></body></html>")

def agent(name, v, score, hk):
    return {"agent_id": f"id-{name}-{v}", "miner_hotkey": hk, "name": name, "version_num": v, "status": "finished",
            "created_at": "$D2026-10-30T04:08:40.252Z", "competition_state": {"set_id": 28, "final_score": score, "status": "approved"}}

TOP = [agent("GGbond", 14, 0.38, "5Cf"), agent("Polaris", 2, 0.38, "5Ho"), agent("mino", 17, 0.38, "5F9"), agent("JUTOPIA", 22, 0.36, "5EZ")]

def page_of(text, kind="text/html", url="https://example.org/explore/28"):
    return {"text": text, "kind": kind, "url": url, "final": url, "fetched_at": "2026-11-05 18:00:00 UTC", "age": None, "last_modified": None}


class Unpack(unittest.TestCase):
    def test_records_scattered_through_a_component_tree_become_one_list(self):
        u = mining_web.unpack(page_of(flight_page(TOP)))
        lst = next(l for l in u["lists"] if l["parent"] == "agent")
        self.assertEqual(len(lst["rows"]), 4)
        rows = mining_web.rows_of(lst, ["name", "competition_state.final_score"])
        self.assertEqual(rows[0], {"name": "GGbond", "competition_state.final_score": 0.38})
        self.assertEqual(mining_web.rows_of(lst)[0]["created_at"], "2026-10-30T04:08:40.252Z")  # Next.js "$D" dates come back plain
        self.assertFalse(any("className" in l["keys"] for l in u["lists"]))  # display props aren't data

    def test_the_text_is_searchable(self):
        u = mining_web.unpack(page_of(flight_page(TOP)))
        ix = mining_web.index(page_of(""), u, "To Beat")
        self.assertIn("38%", ix["found"][0])
        self.assertEqual(ix["lists"][0]["id"], "L1")
        self.assertIn("note", ix)

    def test_html_tables_and_json_apis(self):
        t = "<table><tr><th>Miner</th><th>Score</th></tr><tr><td>a</td><td>1</td></tr><tr><td>b</td><td>2</td></tr></table>"
        u = mining_web.unpack(page_of(f"<html><body>{t}</body></html>"))
        self.assertEqual(mining_web.rows_of(u["lists"][0]), [{"Miner": "a", "Score": "1"}, {"Miner": "b", "Score": "2"}])
        api = mining_web.unpack(page_of(json.dumps([{"uid": 1, "x": 2}, {"uid": 2, "x": 3}]), "application/json"))
        self.assertEqual(len(api["lists"][0]["rows"]), 2)

    def test_a_page_without_records_says_where_to_look(self):
        ix = mining_web.index(page_of(""), mining_web.unpack(page_of("<html><body><p>Loading…</p></body></html>")))
        self.assertIn("API", ix["hint"])

    def test_where_keeps_rows_with_every_word(self):
        lst = next(l for l in mining_web.unpack(page_of(flight_page(TOP)))["lists"] if l["parent"] == "agent")
        self.assertEqual([r["name"] for r in mining_web.rows_of(lst, ["name"], "0.36")], ["JUTOPIA"])
        self.assertEqual(mining_web.rows_of(lst, ["name"], "mino 17"), [{"name": "mino"}])


class Recipes(unittest.TestCase):
    def test_a_saved_signature_still_matches_after_a_redesign_adds_fields(self):
        lst = next(l for l in mining_web.unpack(page_of(flight_page(TOP)))["lists"] if l["parent"] == "agent")
        sig = mining_web.signature(lst)
        redesigned = [dict(a, emission=0.1, badge="new") for a in TOP]
        self.assertIsNotNone(mining_web.match(mining_web.unpack(page_of(flight_page(redesigned)))["lists"], sig))
        other = mining_web.unpack(page_of(json.dumps([{"title": "x", "body": "y"}, {"title": "z", "body": "w"}]), "application/json"))
        self.assertIsNone(mining_web.match(other["lists"], sig))

    def test_diff_in_words(self):
        old = [{"agent_id": "1", "name": "GGbond", "version_num": 14, "score": 0.38}, {"agent_id": "2", "name": "mino", "version_num": 17, "score": 0.38}]
        new = [{"agent_id": "1", "name": "GGbond", "version_num": 14, "score": 0.40}, {"agent_id": "3", "name": "Polaris", "version_num": 3, "score": 0.39}]
        d = mining_web.diff(old, new)
        self.assertIn("1 new (Polaris v3)", d)
        self.assertIn("1 gone (mino v17)", d)
        self.assertIn("score 0.38→0.4", d)
        self.assertEqual(mining_web.diff(new, new), "")


class SandboxHint(unittest.TestCase):
    def test_network_errors_get_the_hint_and_others_dont(self):
        self.assertIn("web_read", mining_web.sandbox_hint("curl: (7) Failed to connect to www.ridges.ai port 443"))
        self.assertIn("web_read", mining_web.sandbox_hint("socket.gaierror: [Errno -3] Temporary failure in name resolution"))
        self.assertIn("web_read", mining_web.sandbox_hint("ERROR: No matching distribution found for sqlalchemy==1.4.54"))
        self.assertIsNone(mining_web.sandbox_hint("AssertionError: 3 != 4"))


class FakeWork:
    def __init__(self, db):
        self.db, self.events = db, []
        db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, status TEXT)")
        db.q("CREATE TABLE mw_files (comp_id INTEGER, path TEXT, content TEXT, size INTEGER, agent_id INTEGER, updated REAL, UNIQUE(comp_id, path))")
        db.q("INSERT INTO mw_comps (id, status) VALUES (20, 'active')")
    def _write_file(self, wid, path, content, agent_id=None):
        self.db.q("""INSERT INTO mw_files (comp_id, path, content, size, agent_id, updated) VALUES (?,?,?,?,?,0)
                     ON CONFLICT(comp_id, path) DO UPDATE SET content=excluded.content""", (wid, path, content, len(content), agent_id))
        return len(content)
    def _event(self, wid, kind, text, agent=None, task=None): self.events.append(text)
    def _own(self, me, wid): return {"id": wid}, {}


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work = FakeWork(AuthDB(os.path.join(self.tmp, "t.db")))
        self.web = mining_web.Web(self.work)
        self.pages = {"https://example.org/explore/28": flight_page(TOP)}
        self.real = mining_web.fetch
        mining_web.fetch = lambda url: page_of(self.pages[url], url=url)
        self.w, self.a = {"id": 20}, {"id": 7, "name": "Jules"}

    def tearDown(self): mining_web.fetch = self.real

    def call(self, **kw):
        args = {"url": "https://example.org/explore/28", "find": "", "list": "", "fields": [], "where": "", "save_as": "", "every_min": 0} | kw
        return self.web.call(self.w, self.a, 1, "web_read", args)

    def file(self, name):
        r = self.work.db.q("SELECT content FROM mw_files WHERE comp_id=20 AND path=?", (f"data/web/{name}.json",), one=True)
        return json.loads(r["content"]) if r else None

    def test_index_then_rows_then_a_watch_that_reports_changes(self):
        ix = self.call()
        lid = next(l["id"] for l in ix["lists"] if "competition_state.final_score" in l["fields"])
        out = self.call(list=lid, fields=["name", "version_num", "competition_state.final_score"], save_as="ridges-top", every_min=30)
        self.assertEqual(out["total"], 4)
        self.assertEqual(out["saved"]["file"], "data/web/ridges-top.json")
        self.assertEqual(self.file("ridges-top")["rows"][1]["name"], "Polaris")
        again = self.call()  # the address now has a recipe: it comes back applied
        self.assertEqual(again["recipe"]["name"], "ridges-top")
        self.assertEqual(again["recipe"]["total"], 4)
        # the page changes; the watch notices
        self.pages["https://example.org/explore/28"] = flight_page([agent("GGbond", 15, 0.40, "5Cf")] + TOP[1:])
        self.work.db.q("UPDATE mw_web SET next_at=0")
        self.assertEqual(self.web.tick(), 1)
        self.assertIn("Watch ridges-top: 1 changed (GGbond v15: version_num 14→15", self.work.events[-1])  # same miner (by name), new version
        self.assertEqual(self.file("ridges-top")["rows"][0]["version_num"], 15)

    def test_text_can_be_saved_too(self):
        out = self.call(find="To Beat", save_as="bar")
        self.assertIn("To Beat 38%", self.file("bar")["text"])
        self.assertEqual(out["saved"]["watch"], "no")

    def test_mistakes_are_explained(self):
        with self.assertRaises(ValueError): self.call(every_min=30)
        with self.assertRaises(ValueError): self.call(save_as="Bad Name!")
        with self.assertRaises(ValueError): self.call(list="L1", save_as="x", every_min=2)
        self.assertIn("error", self.call(list="L99"))

    def test_a_watch_that_breaks_says_so_after_three_failures(self):
        self.call(list="L1", save_as="w", every_min=10)
        self.pages["https://example.org/explore/28"] = "<html><body>gone</body></html>"
        for _ in range(3):
            self.work.db.q("UPDATE mw_web SET next_at=0")
            self.web.tick()
        self.assertIn("failed 3 times", self.work.events[-1])
        self.assertEqual(self.web._watches(self.w, {"action": "list", "name": ""})["saved"][0]["status"], "failed")


class AskedTasks(unittest.TestCase):
    """mining_work.update_task: a task an agent left for the user closes only with what they give back."""
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.db = AuthDB(os.path.join(tmp, "t.db"))
        self.db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, agent_id INTEGER, origin TEXT, result TEXT, summary TEXT, done_at REAL, hold TEXT, fails INTEGER, updated REAL)")
        w = object.__new__(mining_work.Work)
        w.db, self.events = self.db, []
        w._task = lambda me, tid: (self.db.q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True), {"id": 20}, None)
        w._event = lambda wid, kind, text, agent=None, task=None: self.events.append(text)
        w.view = lambda me, wid: {"ok": True}
        self.w, self.me = w, {"id": 4, "username": "leonardo"}

    def add(self, origin, result=None):
        self.db.q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, origin, result) VALUES (20, 'Paste the top 3', 'todo', NULL, ?, ?)", (origin, result))
        return self.db.q("SELECT MAX(id) id FROM mw_tasks", one=True)["id"]

    def test_an_agents_ask_needs_an_answer(self):
        tid = self.add("agent:408:1680")
        with self.assertRaises(HTTPException) as e: self.w.update_task(self.me, tid, mining_work.TaskPatch(status="done"))
        self.assertEqual(e.exception.status_code, 409)
        self.w.update_task(self.me, tid, mining_work.TaskPatch(status="done", answer="GGbond v14 38%, Polaris v2 38%, mino v17 38%"))
        t = self.db.q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True)
        self.assertEqual((t["status"], t["result"][:6]), ("done", "GGbond"))
        self.assertIn("answered", self.events[-1])

    def test_the_users_own_tasks_close_as_before(self):
        tid = self.add("you")
        self.w.update_task(self.me, tid, mining_work.TaskPatch(status="done"))
        self.assertEqual(self.db.q("SELECT status FROM mw_tasks WHERE id=?", (tid,), one=True)["status"], "done")


if __name__ == "__main__":
    unittest.main()
