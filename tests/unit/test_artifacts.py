"""artifacts.py: one catalog over the stores, each read through its own access path: only your teams, missions and long tasks; a
store that fails or isn't set up is reported and the rest still list; scopes and search."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import artifacts
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "user"}
OTHER = {"id": 99, "username": "eve", "role": "user"}


class FakeWork:
    def __init__(self, db): self.db = db
    def all(self, me):
        rows = self.db.q("SELECT w.id, w.number, c.netuid FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=?", (me["id"],))
        return {"comps": [{"id": r["id"], "label": f"Competition {r['number']}", "netuid": r["netuid"]} for r in rows]}
    def _own(self, me, wid):
        if not self.db.q("SELECT 1 FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE w.id=? AND c.user_id=?", (wid, me["id"]), one=True):
            raise HTTPException(404, "no")


class FakeMissions:
    def __init__(self, db): self.db = db
    def _m(self, mid):
        m = self.db.q("SELECT * FROM mx_missions WHERE id=?", (mid,), one=True)
        m["deliverable"] = json.loads(m["deliverable"]) if m["deliverable"] else None
        return m


class FakeDrive:
    enabled = True
    def __init__(self, fail=False): self.fail, self.calls = fail, []
    def call(self, method, path, me, params=None):
        self.calls.append((path, params))
        if self.fail: raise RuntimeError("drive server down")
        return [{"id": "a" * 32, "kind": "file", "name": "miner-notes.md", "space": "mine", "parent": None, "size": 120, "updated": time.time() - 5,
                 "versions": 3, "owner": "leo", "path": ""},
                {"id": "b" * 32, "kind": "file", "name": "plan.pdf", "space": "shared", "parent": "c" * 32, "size": 900, "updated": time.time() - 50,
                 "versions": 1, "owner": "ann", "path": "Team"}]


class Hub:
    def __init__(self, allow=True): self.allow = allow
    def gate(self, me):
        if not self.allow: raise HTTPException(403, "Agents aren't enabled for you.")
        return me


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q, now = self.db.q, time.time()
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER)")
        q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT, size INTEGER, updated REAL)")
        q("CREATE TABLE mw_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, body TEXT, ts REAL)")
        q("CREATE TABLE mx_missions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, deliverable TEXT, updated REAL, finished REAL)")
        q("CREATE TABLE ia_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT)")
        q("CREATE TABLE ia_files (task_id INTEGER, path TEXT, source TEXT, size INTEGER, updated REAL)")
        q("INSERT INTO mh_campaigns VALUES (1, 7, 62), (2, 99, 62)")
        q("INSERT INTO mw_comps VALUES (10, 1, 28), (20, 2, 28)")
        q("INSERT INTO mw_files (comp_id, path, size, updated) VALUES (10, 'agent.py', 40, ?), (20, 'secret-agent.py', 40, ?)", (now, now))
        q("INSERT INTO mw_notes (comp_id, title, ts) VALUES (10, 'Ties break the ordering', ?)", (now,))
        q("INSERT INTO mx_missions (user_id, title, deliverable, updated) VALUES (7, 'Market report', ?, ?), (99, 'Eve report', ?, ?)",
          (json.dumps({"text": "# Report", "summary": "Done.", "files": ["out/report.md"]}), now, json.dumps({"text": "x"}), now))
        q("INSERT INTO ia_tasks (id, user_id, title) VALUES (1, 7, 'Survey'), (2, 99, 'Hers')")
        q("INSERT INTO ia_files VALUES (1, 'notes/survey.md', 'agent', 10, ?), (2, 'theirs.md', 'agent', 10, ?)", (now, now))

    def tearDown(self): self.dir.cleanup()

    def cat(self, drive=None, allow=True):
        return artifacts.Catalog(self.db, drive=drive, work=FakeWork(self.db), ia=object(), missions=FakeMissions(self.db), hub=Hub(allow))


class Catalog(Base):
    def test_lists_every_store_with_scopes_and_only_yours(self):
        r = self.cat(FakeDrive()).search(ME)
        titles = {i["title"] for i in r["items"]}
        self.assertTrue({"miner-notes.md", "plan.pdf", "agent.py", "Ties break the ordering", "Deliverable: Market report", "report.md", "survey.md"} <= titles)
        self.assertFalse({"secret-agent.py", "Deliverable: Eve report", "theirs.md"} & titles)  # another user's
        by = {i["title"]: i["scope"] for i in r["items"]}
        self.assertEqual((by["miner-notes.md"], by["plan.pdf"], by["agent.py"], by["Deliverable: Market report"], by["survey.md"]),
                         ("personal", "company", "team", "mission", "agent"))
        self.assertEqual(next(i for i in r["items"] if i["title"] == "miner-notes.md")["versions"], 3)
        self.assertEqual(r["untracked"], ["Division", "Project"])
        self.assertTrue(all(s["ok"] for k, s in r["sources"].items() if k != "knowledge"))

    def test_search_and_scope(self):
        r = self.cat(FakeDrive()).search(ME, q="report")
        self.assertEqual({i["source"] for i in r["items"]} - {"drive"}, {"missions"})
        self.assertEqual(r["counts"]["mission"], 2)
        r = self.cat(FakeDrive()).search(ME, scope="team")
        self.assertEqual({i["scope"] for i in r["items"]}, {"team"})
        self.assertEqual(self.cat(FakeDrive()).search(ME, q="ties")["items"][0]["open"], {"view": "teams", "team": 10, "sub": "notes"})

    def test_a_failing_store_leaves_the_rest(self):
        r = self.cat(FakeDrive(fail=True)).search(ME)
        self.assertFalse(r["sources"]["drive"]["ok"])
        self.assertIn("down", r["sources"]["drive"]["error"])
        self.assertTrue(any(i["source"] == "teams" for i in r["items"]))
        r = self.cat(None).search(ME)
        self.assertEqual(r["sources"]["drive"]["error"], "Not set up on this server.")

    def test_agent_stores_follow_the_agents_gate(self):
        r = self.cat(FakeDrive(), allow=False).search(ME)
        self.assertEqual({i["source"] for i in r["items"]}, {"drive"})
        self.assertFalse(r["sources"]["teams"]["ok"])

    def test_drive_search_needs_two_characters(self):
        d = FakeDrive()
        self.cat(d).search(ME, q="r")
        self.cat(d).search(ME, q="re")
        self.assertEqual([c[0] for c in d.calls], ["/v1/recent", "/v1/search"])


if __name__ == "__main__":
    unittest.main()
