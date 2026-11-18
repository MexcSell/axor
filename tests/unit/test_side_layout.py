"""side_layout.py: the saved Simple and User sidebar lists (System → Sidebar layout)."""
import json, os, tempfile, unittest

from fastapi import HTTPException

from app import side_layout
from app.auth import AuthDB


class Normalize(unittest.TestCase):
    def test_none_means_not_set(self):
        self.assertIsNone(side_layout.normalize(None))

    def test_items_and_headings(self):
        got = side_layout.normalize([{"h": "  Control   Hub "}, {"k": "nav-alerts"}, {"k": "v:explore", "on": False}, {"k": "a:cmd-dash", "on": True}])
        self.assertEqual(got, [{"h": "Control Hub"}, {"k": "nav-alerts", "on": True}, {"k": "v:explore", "on": False}, {"k": "a:cmd-dash", "on": True}])

    def test_duplicates_and_empty_headings_are_dropped(self):
        got = side_layout.normalize([{"k": "nav-mos"}, {"h": "   "}, {"k": "nav-mos", "on": False}])
        self.assertEqual(got, [{"k": "nav-mos", "on": True}])

    def test_an_empty_list_is_kept(self):
        self.assertEqual(side_layout.normalize([]), [])

    def test_bad_shapes_are_refused(self):
        for bad in ("nav-mos", [1], [{"k": ""}], [{"k": "<script>"}], [{"k": "x" * 81}], [{"k": f"k{i}"} for i in range(201)]):
            with self.assertRaises(ValueError, msg=repr(bad)[:60]): side_layout.normalize(bad)

    def test_long_headings_are_cut(self):
        self.assertEqual(len(side_layout.normalize([{"h": "x" * 100}])[0]["h"]), 40)


class Req:
    def __init__(self, user): self.user = user


class Router(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))

        def require(req):
            if not req.user: raise HTTPException(401, "Sign in.")
            return req.user

        def admin(req):
            u = require(req)
            if u["role"] != "admin": raise HTTPException(403, "Administrators only.")
            return u

        r = side_layout.build(self.db, require, admin, lambda req: "127.0.0.1")
        self.get = next(x.endpoint for x in r.routes if "GET" in x.methods)
        self.put = next(x.endpoint for x in r.routes if "PUT" in x.methods)
        self.admin = Req({"username": "boss", "role": "admin"})
        self.user = Req({"username": "ann", "role": "user"})

    def tearDown(self): self.dir.cleanup()

    def test_nothing_saved(self):
        d = self.get(self.user)
        self.assertIsNone(d["simple"]); self.assertIsNone(d["user"])

    def test_signed_out_cannot_read(self):
        with self.assertRaises(HTTPException) as e: self.get(Req(None))
        self.assertEqual(e.exception.status_code, 401)

    def test_admin_saves_and_everyone_reads(self):
        body = side_layout.Layout(simple=[{"h": "Work"}, {"k": "nav-mos"}], user=[{"k": "nav-alerts"}, {"k": "nav-help", "on": False}])
        self.put(body, self.admin)
        d = self.get(self.user)
        self.assertEqual(d["simple"], [{"h": "Work"}, {"k": "nav-mos", "on": True}])
        self.assertEqual(d["user"], [{"k": "nav-alerts", "on": True}, {"k": "nav-help", "on": False}])
        self.assertEqual(d["by"], "boss")
        self.assertTrue(self.db.q("SELECT 1 FROM audit WHERE action='sidebar.layout'"))

    def test_null_clears_a_list(self):
        self.put(side_layout.Layout(simple=[{"k": "nav-mos"}], user=[{"k": "nav-mos"}]), self.admin)
        self.put(side_layout.Layout(simple=None, user=[{"k": "nav-help"}]), self.admin)
        d = self.get(self.admin)
        self.assertIsNone(d["simple"]); self.assertEqual(d["user"], [{"k": "nav-help", "on": True}])

    def test_users_cannot_save(self):
        with self.assertRaises(HTTPException) as e: self.put(side_layout.Layout(simple=[]), self.user)
        self.assertEqual(e.exception.status_code, 403)
        self.assertIsNone(self.get(self.admin)["simple"])

    def test_bad_list_is_a_422(self):
        with self.assertRaises(HTTPException) as e: self.put(side_layout.Layout(user=[{"k": "bad key!"}]), self.admin)
        self.assertEqual(e.exception.status_code, 422)

    def test_damaged_setting_falls_back(self):
        self.db.setting(side_layout.KEY, v="{not json")
        self.assertIsNone(self.get(self.user)["user"])
        self.db.setting(side_layout.KEY, v=json.dumps({"simple": "oops", "user": [{"k": "nav-mos"}]}))
        d = self.get(self.user)
        self.assertIsNone(d["simple"]); self.assertEqual(d["user"], [{"k": "nav-mos", "on": True}])


if __name__ == "__main__":
    unittest.main()
