"""The execution API (exec_env.build, /api/exec; AEF_05 §6): the searchable run history, a run's record, security events,
workspace snapshots and rollback, a team's policy, the Owner's concurrency setting, the emergency stop, and who may do what."""
import json, os, tempfile, time, types, unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import exec_env as ex, sandbox
from app.auth import AuthDB

USERS = {"ann": {"id": 1, "username": "ann", "role": "user"}, "bob": {"id": 2, "username": "bob", "role": "user"}, "root": {"id": 9, "username": "root", "role": "admin"}}


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = self.db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        db.q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER)")
        db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, name TEXT)")
        db.q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT)")
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, needs TEXT, mission TEXT)")
        db.q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, run_id INTEGER, agent_id INTEGER, by_user TEXT,
                command TEXT, services TEXT, status TEXT, exit_code INTEGER, output TEXT, error TEXT, started REAL, finished REAL, cost REAL, calls INTEGER,
                pod TEXT, net TEXT, src TEXT)""")
        db.q("INSERT INTO mh_campaigns (id, user_id) VALUES (1, 1), (2, 2)")
        db.q("INSERT INTO mw_comps (id, campaign_id, name) VALUES (10, 1, 'Ann team'), (20, 2, 'Bob team')")
        db.q("INSERT INTO mw_tasks (id, comp_id, title, mission) VALUES (1, 10, 't', 'mx:a'), (2, 20, 't', 'mx:b')")
        self.root = mock.patch.object(ex, "ROOT", __import__("pathlib").Path(self.tmp.name) / "exec"); self.root.start()
        ex._STORES.clear()
        self.st = ex.store(db)
        self.deleted = []

        def own(me, team):
            r = db.q("SELECT c.user_id FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE w.id=?", (team,), one=True)
            if not r or r["user_id"] != me["id"]: raise HTTPException(404, "There's no such workspace.")
        self.work = types.SimpleNamespace(db=db, m=types.SimpleNamespace(hub=None), _own=own,
                                          sbx=types.SimpleNamespace(slots=sandbox.Slots(2), egress=types.SimpleNamespace(status=lambda: {"ready": True}),
                                                                    kube=types.SimpleNamespace(delete=lambda path, params=None: self.deleted.append(path))))

        def require(req):
            u = USERS.get(req.headers.get("x-user", ""))
            if not u: raise HTTPException(401, "Sign in.")
            return u
        app = FastAPI(); app.include_router(ex.build(self.work, require))
        self.c = TestClient(app)
        net = lambda hosts, refused=(): json.dumps({"up_bytes": 10, "down_bytes": 2000, "hosts": {h: {"conns": 1, "up": 5, "down": 1000} for h in hosts},
                                                    "refused": [{"host": h, "why": w, "at": time.time()} for h, w in refused]})
        man = lambda **res: json.dumps({"v": 1, "sha256": "f" * 64, "plan": {"size": "M", "mission": "mx:a", "egress": {"mode": "allowlist"}, "secrets": []},
                                        "inputs": {"command": "pytest -q", "image": "axor/sandbox:x"}, "result": {"image_id": "sha256:" + "a" * 64, "events": [], **res}})
        self.r1 = self.ins(10, 1, "pytest -q tests/", "done", output="42 passed", net=net(["github.com", "pypi.org"]), manifest=man(),
                           stats=json.dumps({"cpu_seconds": 3.5, "peak_rss_mb": 210, "peak_procs": 6, "disk_mb": {"work": 12}}))
        self.r2 = self.ins(10, 1, "curl https://registry.npmjs.org/x", "failed", exit=7, net=net([], [("registry.npmjs.org", "package index not approved for this mission")]),
                           manifest=man(events=[{"at": time.time(), "kind": "conflict", "path": "plan.md", "kept_as": "plan.md.conflict-run2"}]))
        self.r3 = self.ins(20, 2, "make build", "done", output="bob's secret build log")
        self.r4 = self.ins(10, None, "old style run", "done")

    def tearDown(self):
        self.root.stop()
        try: self.db.db.close()   # on Postgres every AuthDB holds a connection for as long as it lives
        except Exception: pass    # noqa: BLE001
        self.tmp.cleanup()

    def ins(self, comp, task, command, status, exit=0, output="", net=None, manifest=None, stats=None, pod=None):
        return self.db.q("""INSERT INTO mw_sbx (comp_id, task_id, command, services, status, exit_code, output, started, finished, net, manifest, stats, pod)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""", (comp, task, command, "", status, exit, output, time.time() - 60, time.time(), net, manifest, stats, pod), one=True)["id"]

    def get(self, who, path): return self.c.get("/api/exec" + path, headers={"x-user": who})
    def send(self, who, method, path, body=None): return self.c.request(method, "/api/exec" + path, headers={"x-user": who}, json=body)

    def test_signed_out_gets_nothing(self):
        for path in ("/status", "/runs", f"/runs/{self.r1}", "/events", "/workspaces/10", "/policy/10"):
            self.assertEqual(self.c.get("/api/exec" + path).status_code, 401, path)

    def test_a_member_sees_their_teams_runs_only_an_administrator_all(self):
        ids = lambda who, qs="": [r["id"] for r in self.get(who, "/runs" + qs).json()["runs"]]
        self.assertEqual(ids("ann"), [self.r4, self.r2, self.r1])
        self.assertEqual(ids("bob"), [self.r3])
        self.assertEqual(ids("root"), [self.r4, self.r3, self.r2, self.r1])
        self.assertEqual(self.get("ann", f"/runs/{self.r3}").status_code, 404)           # another team's run doesn't exist for her
        self.assertEqual(ids("ann", "?q=secret+build"), [])                              # nor can a search reach into it
        self.assertEqual(ids("ann", "?team=20"), [])

    def test_search(self):
        ids = lambda qs: [r["id"] for r in self.get("ann", "/runs" + qs).json()["runs"]]
        self.assertEqual(ids("?q=pytest"), [self.r1]); self.assertEqual(ids("?q=42+passed"), [self.r1])   # the command, and the output
        self.assertEqual(ids("?host=github.com"), [self.r1])
        self.assertEqual(ids("?host=registry.npmjs.org"), [self.r2])                                        # a refused host is found too
        self.assertEqual(ids("?status=failed"), [self.r2]); self.assertEqual(ids("?mission=mx:a"), [self.r2, self.r1])
        self.assertEqual(ids("?mission=comp:10"), [self.r4])                                                # a run with no task belongs to the team's own mission
        self.assertEqual(ids("?q=100%25"), []); self.assertEqual(ids("?q=_"), [])                           # % and _ are text, not wildcards
        self.assertEqual(ids(f"?since={time.time() + 10}"), [])
        r = self.get("ann", "/runs?q=pytest").json()["runs"][0]
        self.assertEqual((r["cpu_seconds"], r["peak_rss_mb"], r["hosts"], r["size"], r["egress"], r["planned"], r["mission"]), (3.5, 210, 2, "M", "allowlist", True, "mx:a"))
        self.assertNotIn("output", r)

    def test_a_runs_record(self):
        rec = self.get("ann", f"/runs/{self.r1}").json()
        self.assertEqual((rec["output"], rec["stats"]["peak_procs"], rec["manifest"]["sha256"], sorted(rec["net"]["hosts"])), ("42 passed", 6, "f" * 64, ["github.com", "pypi.org"]))
        going = self.ins(10, 1, "cargo bench", "running", stats=json.dumps({"live": True, "at": time.time(), "cpu_seconds": 4.5, "peak_rss_mb": 300.0, "peak_procs": 5, "rss_mb": 280.0, "procs": 4}), pod="sbx-going")
        g = self.get("ann", f"/runs/{going}").json()
        self.assertEqual((g["planned"], g["live"], g["stats"]["rss_mb"], g["manifest"]), (True, True, 280.0, None))   # still running: figures so far, no manifest yet
        self.assertFalse(rec["live"])
        old = self.get("ann", f"/runs/{self.r4}").json()
        self.assertEqual((old["planned"], old["stats"], old["manifest"]), (False, None, None))             # a run from before AEF reads as it is: nothing invented

    def test_security_events(self):
        ev = self.get("ann", "/events").json()["events"]
        kinds = {(e["kind"], e["run"]) for e in ev}
        self.assertEqual(kinds, {("refused_connection", self.r2), ("conflict", self.r2)})
        self.assertIn("registry.npmjs.org: package index not approved", next(e["detail"] for e in ev if e["kind"] == "refused_connection"))
        self.db.log("secret.refused", "run:77", "API_KEY", "", "mission mx:z; no person's current verification")
        self.assertNotIn("secret.refused", {e["kind"] for e in self.get("ann", "/events").json()["events"]})   # server-wide rows are the administrators'
        self.assertIn("secret.refused", {e["kind"] for e in self.get("root", "/events").json()["events"]})

    def test_workspaces_snapshots_files_and_rollback(self):
        f = lambda t: [self.st.put(t.encode()), len(t.encode()), 0o644]
        s1 = self.st.commit(10, "mx:a", None, {"app.py": f("good"), "data.bin": [self.st.put(b"\xff\xfe\x00"), 3, 0o644]})["snapshot"]
        s2 = self.st.commit(10, "mx:a", s1, {"app.py": f("broken"), "data.bin": [self.st.put(b"\xff\xfe\x00"), 3, 0o644]})["snapshot"]
        self.st.commit(20, "mx:b", None, {"bob.txt": f("bob's")})
        ms = self.get("ann", "/workspaces/10").json()["missions"]
        self.assertEqual([(m["mission"], m["head"], m["snapshots"], m["files"]) for m in ms], [("mx:a", s2, 2, 2)])
        snaps = self.get("ann", "/workspaces/10?mission=mx:a").json()["snapshots"]
        self.assertEqual([s["id"] for s in snaps], [s2, s1]); self.assertEqual(snaps[0]["counts"]["changed"], 1)
        files = self.get("ann", f"/workspaces/10/snapshots/{s1}").json()["files"]
        self.assertEqual([x["path"] for x in files], ["app.py", "data.bin"])
        self.assertEqual(self.get("ann", f"/workspaces/10/snapshots/{s1}?path=app.py").json()["text"], "good")
        self.assertTrue(self.get("ann", f"/workspaces/10/snapshots/{s1}?path=data.bin").json()["binary"])
        self.assertEqual(self.get("ann", f"/workspaces/10/snapshots/{s1}?path=../x").status_code, 404)
        self.assertEqual(self.get("bob", "/workspaces/10").status_code, 404)                              # not his team
        self.assertEqual(self.get("bob", f"/workspaces/10/snapshots/{s1}").status_code, 404)
        bobs = self.st.head(20, "mx:b")["id"]
        self.assertEqual(self.get("ann", f"/workspaces/10/snapshots/{bobs}").status_code, 404)            # nor another team's snapshot through her own team's address
        self.assertEqual(self.send("bob", "POST", "/workspaces/10/rollback", {"mission": "mx:a", "snapshot": s1}).status_code, 404)
        out = self.send("ann", "POST", "/workspaces/10/rollback", {"mission": "mx:a", "snapshot": s1}).json()
        self.assertTrue(out["new"])
        self.assertEqual(self.get("ann", f"/workspaces/10/snapshots/{out['snapshot']}?path=app.py").json()["text"], "good")
        self.assertEqual(self.send("ann", "POST", "/workspaces/10/rollback", {"mission": "mx:zzz", "snapshot": s1}).status_code, 400)
        self.assertEqual(self.send("ann", "POST", "/workspaces/10/keep", {"snapshot": s1}).json(), {"snapshot": s1, "kept": True})
        self.assertEqual(self.db.q("SELECT kept FROM mw_ws WHERE id=?", (s1,), one=True)["kept"], 1)
        self.assertEqual([r["action"] for r in self.db.q("SELECT action FROM audit WHERE action='exec.rollback'")], ["exec.rollback"])

    def test_policy_is_read_by_members_and_set_by_administrators_only(self):
        body = {"plan": True, "workspace": True, "egress": {"mode": "allowlist", "hosts": ["GitHub.com", "example.org"], "down_mb_day": 500}}
        self.assertEqual(self.send("ann", "PUT", "/policy/10", body).status_code, 403)
        self.assertEqual(self.send("root", "PUT", "/policy/10", body).json()["policy"],
                         {"plan": 1, "workspace": 1, "egress": {"mode": "allowlist", "hosts": ["example.org", "github.com"], "down_mb_day": 500}})
        # package installs: only on an allowlist, only through the Owner's list; an index can't be put on a host list by any spelling
        for bad in ({"egress": {"mode": "allowlist", "hosts": ["pypi.org"]}}, {"egress": {"mode": "allowlist", "hosts": ["github.com", "pythonhosted.org"]}},
                    {"egress": {"mode": "allowlist", "hosts": ["mirror.registry.npmjs.org"]}}, {"egress": {"mode": "public", "packages": "approved"}},
                    {"egress": {"mode": "allowlist", "hosts": ["github.com"], "packages": "everything"}}):
            r = self.send("root", "PUT", "/policy/10", bad)
            self.assertEqual(r.status_code, 400, bad)
        self.assertIn("Owner's approved list", self.send("root", "PUT", "/policy/10", {"egress": {"mode": "allowlist", "hosts": ["pypi.org"]}}).json()["detail"])
        self.assertEqual(self.send("root", "PUT", "/policy/10", {"egress": {"mode": "allowlist", "packages": "approved"}}).json()["policy"],
                         {"egress": {"mode": "allowlist", "packages": "approved"}})          # an allowlist of the approved indexes and nothing else
        self.assertEqual(self.send("root", "PUT", "/policy/10", body).status_code, 200)
        self.assertEqual(self.get("ann", "/policy/10").json()["policy"]["egress"]["mode"], "allowlist")
        self.assertEqual(self.get("bob", "/policy/10").status_code, 404)
        self.assertEqual(ex.settings(self.db, 10)["workspace"], 1)
        for bad in ({"egress": {"mode": "everything"}}, {"egress": {"mode": "allowlist"}}, {"egress": {"mode": "allowlist", "hosts": ["https://x.org/path"]}},
                    {"egress": {"mode": "public", "up_mb_day": -1}}, {"egress": {"mode": "allowlist", "hosts": ["10.0.0.1:80"]}}):
            self.assertEqual(self.send("root", "PUT", "/policy/10", bad).status_code, 400, bad)
        self.assertEqual(self.send("root", "PUT", "/policy/999", body).status_code, 404)
        own = {"egress": {"mode": "allowlist", "hosts": ["example.org"]}}
        self.assertEqual(self.send("ann", "PUT", "/policy/10?mission=mx:a", own).status_code, 403)
        self.assertEqual(self.send("root", "PUT", "/policy/10?mission=mx:a", own).json(), {"team": 10, "mission": "mx:a", "policy": own})
        self.assertEqual(self.get("ann", "/policy/10").json()["missions"], {"mx:a": own})
        self.assertEqual(self.send("root", "PUT", "/policy/10?mission=mx:a", {"egress": {"hosts": ["x.org"]}}).status_code, 400)   # a mission's policy needs a mode
        self.assertEqual(self.send("root", "PUT", "/policy/10?mission=bad%20ref", own).status_code, 400)
        self.assertEqual(self.send("root", "PUT", "/policy/10?mission=mx:a", {}).json()["policy"], {})     # removed: the team's policy applies again
        self.assertEqual(self.get("ann", "/policy/10").json()["missions"], {})
        self.assertEqual(ex.settings(self.db, 10)["workspace"], 1)                                         # the team's own policy was never touched by it
        self.assertEqual(self.send("root", "PUT", "/policy/10", {}).json()["policy"], {})                 # everything off again: the setting is gone
        self.assertEqual(ex.settings(self.db, 10), {})
        self.assertEqual(len(self.db.q("SELECT 1 FROM audit WHERE action='exec.policy'")), 6)

    def test_the_number_of_runs_at_once_is_the_owners(self):
        self.assertEqual(self.send("root", "PUT", "/slots", {"slots": 4}).status_code, 403)               # an administrator who isn't the Owner
        with mock.patch("app.missions.is_owner", lambda db, me: me["username"] == "root"):
            self.assertEqual(self.send("ann", "PUT", "/slots", {"slots": 4}).status_code, 403)
            self.assertEqual(self.send("root", "PUT", "/slots", {"slots": 4}).json(), {"slots": 4})
            self.assertEqual(self.work.sbx.slots.total, 4)
            self.assertEqual(self.send("root", "PUT", "/slots", {"slots": ex.SLOTS_MAX + 1}).status_code, 400)
            self.assertEqual(self.send("root", "PUT", "/slots", {"slots": 0}).status_code, 400)
        self.assertEqual(self.get("ann", "/status").json()["slots"]["total"], 4)
        self.db.q("DELETE FROM app_settings WHERE k='exec.slots'")
        self.assertEqual(ex.slots(self.db, self.work.sbx), sandbox.AT_ONCE); self.assertEqual(self.work.sbx.slots.total, sandbox.AT_ONCE)   # unset: the server's default again

    def test_stop_and_resume_are_administrators(self):
        run = self.ins(10, 1, "sleep 999", "running", pod="sbx-live")
        self.assertEqual(self.send("ann", "POST", "/stop", {"mission": "mx:a"}).status_code, 403)
        self.assertEqual(self.send("root", "POST", "/stop", {}).status_code, 400)
        with mock.patch.object(ex.time, "sleep", lambda n: None):
            out = self.send("root", "POST", "/stop", {"mission": "mx:a", "why": "test"}).json()
        self.assertEqual(out["ended"], [run]); self.assertEqual(self.deleted, [f"/api/v1/namespaces/{sandbox.NS}/pods/sbx-live"] * 2 if len(self.deleted) == 2 else self.deleted)
        self.assertIn("mx:a", self.get("ann", "/status").json()["stops"])                                 # a member sees that it is stopped, and why
        self.assertEqual(self.send("ann", "DELETE", "/stop?mission=mx:a").status_code, 403)
        self.assertEqual(self.send("root", "DELETE", "/stop?mission=mx:a").json()["stopped"], False)
        self.assertEqual(self.get("ann", "/status").json()["stops"], {})

    def test_a_stop_of_everything_gates_every_caller_of_the_sandbox(self):
        gate = self.work.sbx.gate                                   # set when the API is built
        self.assertIsNone(gate())
        self.db.setting("exec.stop:mx:a", v="one mission")
        self.assertIsNone(gate())                                   # a stop of one mission isn't the sandbox's business: the run's own path refuses it
        self.db.setting("exec.stop:*", v="everything")
        self.assertEqual(gate(), "Runs are stopped (every mission): everything")

    def test_status_shows_a_member_their_own_teams_and_only_an_administrator_the_servers(self):
        self.db.setting("exec.comp:10", v=json.dumps({"plan": 1})); self.db.setting("exec.comp:20", v=json.dumps({"workspace": 1}))
        a = self.get("ann", "/status").json()
        self.assertEqual(a["teams"], {"10": {"plan": 1}}); self.assertNotIn("vault", a); self.assertNotIn("egress", a)
        r = self.get("root", "/status").json()
        self.assertEqual(set(r["teams"]), {"10", "20"}); self.assertEqual(r["vault"]["set"], False); self.assertEqual(r["sizes"]["L"], {"cpu": "4", "memory": "8Gi", "slots": 2})

    def test_replay_is_an_administrators_and_only_of_a_planned_run(self):
        self.assertEqual(self.send("ann", "POST", f"/runs/{self.r1}/replay").status_code, 403)
        self.assertEqual(self.send("root", "POST", f"/runs/{self.r4}/replay").status_code, 400)           # no manifest: nothing to run again
        self.assertEqual(self.send("root", "POST", "/runs/99999/replay").status_code, 404)

    def test_a_stopped_missions_run_is_not_run_again(self):
        self.db.setting("exec.stop:mx:a", v="Owner: stop")
        r = self.send("root", "POST", f"/runs/{self.r1}/replay")
        self.assertEqual(r.status_code, 400); self.assertIn("Runs are stopped (mx:a)", r.text)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_sbx WHERE by_user LIKE 'replay of%'", one=True)["n"], 0)   # nothing was started for it
        self.db.q("DELETE FROM app_settings WHERE k='exec.stop:mx:a'"); self.db.setting("exec.stop:mx:another", v="x")
        with mock.patch.object(ex, "Session", side_effect=ex.ExecError("the control got past the stop")):                 # another mission's stop isn't this run's
            self.assertIn("the control got past the stop", self.send("root", "POST", f"/runs/{self.r1}/replay").text)


class Panel(unittest.TestCase):
    """The Unified Agent Control Panel's graph (topology.py): a planned run's measurements are on its sandbox node."""
    def test_a_planned_runs_measurements_size_and_snapshots_are_on_its_node_and_an_older_run_is_unchanged(self):
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        import test_topology as tt
        g = tt.Graph("test_a_sandbox_is_one_node_in_execution_infrastructure_and_network"); g.setUp()
        try:
            _, before, _ = g.graph()
            ex.schema(g.db)
            man = lambda events=(): json.dumps({"plan": {"size": "L", "mission": "mx:4", "egress": {"mode": "allowlist"}}, "result": {"events": list(events)}})
            ins = """INSERT INTO mw_sbx (id, comp_id, run_id, agent_id, command, status, exit_code, started, finished, pod, stats, manifest, ws_from, ws_to)
                     VALUES (?, 1, 9, 1, 'cargo test', 'done', 0, ?, ?, ?, ?, ?, ?, ?)"""
            stats = json.dumps({"cpu_seconds": 12.5, "peak_rss_mb": 800.0, "peak_procs": 14, "disk_mb": {"work": 310.0}})
            g.db.q(ins, (4, tt.NOW - 100, tt.NOW - 50, "sbx-4", stats, man(), 7, 8))
            g.db.q(ins, (5, tt.NOW - 90, tt.NOW - 40, "sbx-5", None, man([{"kind": "refused_save", "path": "../x"}, {"kind": "refused_connection", "host": "x"}]), 8, None))
            g.db.q("""INSERT INTO mw_sbx (id, comp_id, run_id, agent_id, command, status, started, pod, stats) VALUES (6, 1, 9, 1, 'cargo bench', 'running', ?, 'sbx-6', ?)""",
                   (tt.NOW - 20, json.dumps({"live": True, "at": tt.NOW - 3, "cpu_seconds": 4.5, "peak_rss_mb": 300.0, "peak_procs": 5, "rss_mb": 280.0, "procs": 4})))
            _, N, _ = g.graph()
            live = N["sbx:6"]                                              # a run that is still going: its figures so far, no manifest yet
            self.assertEqual(({k: live["m"][k] for k in ("cpu_s", "mem_mb", "procs")}, live.get("live"), live.get("status")), ({"cpu_s": 4.5, "mem_mb": 300.0, "procs": 5}, True, "busy"))
            n = N["sbx:4"]
            self.assertIsNone(n.get("live"))
            self.assertEqual({k: n["m"][k] for k in ("cpu_s", "mem_mb", "procs", "disk_mb")}, {"cpu_s": 12.5, "mem_mb": 800.0, "procs": 14, "disk_mb": 310.0})
            self.assertEqual((n["size"], n["mission"], n["egress"], n["ws"], n["status"], n["run"]), ("L", "mx:4", "allowlist", "#7 → #8", "ok", 4))
            self.assertEqual((N["sbx:5"]["ws"], N["sbx:5"]["status"], N["sbx:5"]["m"]["events"]), ("#8 (unchanged)", "warn", 2))   # a refused save is worth a look
            self.assertEqual({k: v for k, v in N["sbx:3"].items()}, {k: v for k, v in before["sbx:3"].items()})                  # the run from before AEF: the same node
        finally: g.tearDown()


if __name__ == "__main__":
    unittest.main()
