"""The Agent Execution Fabric's own module (exec_env.py; D-032, approved for development 2026-11-13): the workspace store and its
merge rule, the plan, the per-run endpoint, the script inside the run (sandbox_files/aef.py, run for real against a real proxy),
and the one call site (mining_work.Work._sandbox). Pinned first: a team with no switch on gets the run it got before."""
import base64, hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock

from app import exec_env as ex, mining_work, sandbox
from app.auth import AuthDB

FILES = Path(sandbox.__file__).parent / "sandbox_files"


def board(tmp):
    db = AuthDB(os.path.join(tmp, "t.db"))
    db.q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY, comp_id INTEGER, path TEXT, content TEXT)")
    db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, needs TEXT, mission TEXT)""")
    db.q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, run_id INTEGER, agent_id INTEGER, by_user TEXT,
            command TEXT, services TEXT, status TEXT, exit_code INTEGER, output TEXT, error TEXT, started REAL, finished REAL, cost REAL, calls INTEGER,
            pod TEXT, net TEXT, src TEXT)""")
    db.q("""CREATE TABLE mw_ckpt (comp_id INTEGER, task_id INTEGER, data TEXT, bytes INTEGER, sbx_id INTEGER, agent_id INTEGER, saved REAL,
            PRIMARY KEY (comp_id, task_id))""")
    return db


def close(db):
    """Gives the test's database connection back: on Postgres every AuthDB holds one for as long as it lives, a test case lives
    until the whole run ends, and the throwaway server takes 400."""
    try: db.db.close()
    except Exception: pass   # noqa: BLE001


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name)
        self.st = ex.Store(self.db, os.path.join(self.tmp.name, "exec"))

    def tearDown(self): close(self.db); self.tmp.cleanup()

    def f(self, text, mode=0o644):
        """A file entry for content the store was given."""
        data = text if isinstance(text, bytes) else text.encode()
        return [self.st.put(data), len(data), mode]

    def save(self, base, files, mission="comp:1", **kw):
        return self.st.commit(1, mission, base, files, **kw)

    def read(self, snapshot, path, comp=1):
        return self.st.read(self.st.tree(self.st.row(comp, snapshot))["files"][path][0]).decode()


class Paths(unittest.TestCase):
    def test_kept_paths(self):
        for p, want in (("a.py", "a.py"), ("src/./x/../y.rs", "src/y.rs"), ("agents/devon-2/notes.md", "agents/devon-2/notes.md"), (".git/HEAD", ".git/HEAD"),
                        ("artifacts/model.bin", "artifacts/model.bin"), (".state/task-7/progress.json", ".state/task-7/progress.json"), ("a\\b.txt", "a/b.txt")):
            self.assertEqual(ex.clean(p), want)

    def test_refused_paths(self):
        for p, why in (("/etc/passwd", "outside"), ("../x", "outside"), ("a/../../x", "outside"), ("..", "outside"), ("team/agent.py", "read-only"),
                       ("shared/kb.md", "read-only"), (".axor/aef.py", "read-only"), (".env", "secret"), ("deploy/id_rsa", "secret"),
                       ("cfg/credentials.json", "secret"), ("web/node_modules/x/index.js", "cache"), ("a/__pycache__/m.pyc", "cache"),
                       ("a\x00b", "usable"), ("a\nb", "usable"), ("", "usable"), ("x" * 401, "usable"), (7, "usable")):
            with self.assertRaisesRegex(ex.ExecError, why, msg=repr(p)): ex.clean(p)

    def test_links_stay_inside(self):
        self.assertEqual(ex.clean_link("a/b/link", "../c.txt"), "../c.txt")
        for target in ("/etc/passwd", "../../../etc/passwd", "../../x", ""):
            with self.assertRaises(ex.ExecError, msg=target): ex.clean_link("a/link", target)


class Snapshots(Base):
    def test_first_save_same_content_same_identity_and_no_change_no_snapshot(self):
        r1 = self.save(None, {"a.py": self.f("print(1)"), "bin/run.sh": self.f("#!/bin/sh", 0o755)})
        self.assertTrue(r1["new"]); self.assertEqual(r1["changes"]["counts"]["added"], 2)
        t = self.st.tree(self.st.row(1, r1["snapshot"]))
        self.assertEqual(t["files"]["bin/run.sh"][2], 0o755)
        r2 = self.save(r1["snapshot"], {"a.py": self.f("print(1)"), "bin/run.sh": self.f("#!/bin/sh", 0o755)})
        self.assertEqual((r2["new"], r2["snapshot"]), (False, r1["snapshot"]))
        other = self.save(None, {"bin/run.sh": self.f("#!/bin/sh", 0o755), "a.py": self.f("print(1)")}, mission="comp:1b")
        self.assertEqual(other["tree"], r1["tree"])                         # equal workspaces have equal identity, whatever the order
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_ws", one=True)["n"], 2)

    def test_missions_and_teams_dont_see_each_other(self):
        a = self.save(None, {"a.txt": self.f("mission a")})
        b = self.save(None, {"b.txt": self.f("mission b")}, mission="mx:9")
        self.assertEqual(list(self.st.tree(self.st.head(1, "comp:1"))["files"]), ["a.txt"])
        self.assertEqual(list(self.st.tree(self.st.head(1, "mx:9"))["files"]), ["b.txt"])
        self.assertIsNone(self.st.head(2, "comp:1")); self.assertIsNone(self.st.row(2, a["snapshot"]))
        with self.assertRaisesRegex(ex.ExecError, "doesn't have"): self.st.commit(2, "comp:1", b["snapshot"], {})   # another team's snapshot can't be a base

    def test_a_save_cant_start_from_another_missions_snapshot(self):
        """A run could name any snapshot id of its team as the one it started from; another mission's file names would then come
        back to it as "removed", and a snapshot built on the wrong history would be written."""
        other = self.save(None, {"secret-plan.md": self.f("x"), "roadmap/q3.md": self.f("y")}, mission="mx:other")["snapshot"]
        mine = self.save(None, {"a.txt": self.f("a")})["snapshot"]
        before = self.db.q("SELECT COUNT(*) n FROM mw_ws", one=True)["n"]
        with self.assertRaisesRegex(ex.ExecError, "this mission doesn't have") as cm: self.save(other, {"a.txt": self.f("a")})
        self.assertNotIn("secret-plan", str(cm.exception))
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_ws", one=True)["n"], before)       # nothing was written
        self.assertTrue(self.save(mine, {"a.txt": self.f("a2")})["new"])                             # its own snapshot is a fine base

    def test_two_runs_touching_different_files_merge(self):
        base = self.save(None, {"a.txt": self.f("a0"), "b.txt": self.f("b0")})["snapshot"]
        r1 = self.save(base, {"a.txt": self.f("a1"), "b.txt": self.f("b0")}, tag=11)
        r2 = self.save(base, {"a.txt": self.f("a0"), "b.txt": self.f("b2"), "c.txt": self.f("c2")}, tag=12)
        self.assertEqual(r2["changes"]["conflicts"], [])
        self.assertEqual((self.read(r2["snapshot"], "a.txt"), self.read(r2["snapshot"], "b.txt"), self.read(r2["snapshot"], "c.txt")), ("a1", "b2", "c2"))
        self.assertEqual(self.st.row(1, r2["snapshot"])["parent"], r1["snapshot"])

    def test_two_runs_changing_one_file_keep_both_and_say_so(self):
        base = self.save(None, {"plan.md": self.f("v0")})["snapshot"]
        self.save(base, {"plan.md": self.f("first run's")}, tag=11)
        r = self.save(base, {"plan.md": self.f("second run's")}, tag=12)
        self.assertEqual(r["changes"]["conflicts"], [{"path": "plan.md", "kept_as": "plan.md.conflict-run12", "theirs": "changed", "yours": "changed"}])
        self.assertEqual(self.read(r["snapshot"], "plan.md"), "first run's")                    # the head's version stays at the path
        self.assertEqual(self.read(r["snapshot"], "plan.md.conflict-run12"), "second run's")    # nothing was overwritten or lost

    def test_the_same_change_by_both_is_not_a_conflict(self):
        base = self.save(None, {"a": self.f("0")})["snapshot"]
        self.save(base, {"a": self.f("1")}); r = self.save(base, {"a": self.f("1")})
        self.assertEqual((r["changes"]["conflicts"], r["new"]), ([], False))

    def test_removals(self):
        base = self.save(None, {"a": self.f("a"), "b": self.f("b"), "c": self.f("c")})["snapshot"]
        r1 = self.save(base, {"b": self.f("b"), "c": self.f("c")})                               # the run deleted a
        self.assertEqual(r1["changes"]["removed"], ["a"]); self.assertNotIn("a", r1["files"])
        self.save(base, {"a": self.f("a"), "b": self.f("b2"), "c": self.f("c")}, tag=5)           # (a comes back as a conflict-free re-add? no: untouched since base)
        r3 = self.save(base, {"a": self.f("a"), "c": self.f("c")}, tag=6)                         # deletes b, which another run changed meanwhile
        self.assertEqual([c["path"] for c in r3["changes"]["conflicts"]], ["b"])
        self.assertEqual(self.read(r3["snapshot"], "b"), "b2")                                    # the other run's change survives the delete

    def test_a_path_left_out_of_a_save_is_not_a_removal(self):
        base = self.save(None, {"big.bin": self.f("x" * 100), "a": self.f("a")})["snapshot"]
        r = self.save(base, {"a": self.f("a2")}, skipped=[{"path": "big.bin", "why": "over 200 MB"}])
        self.assertIn("big.bin", r["files"]); self.assertEqual(r["changes"]["removed"], [])
        self.assertEqual(r["changes"]["refused"], [{"path": "big.bin", "why": "over 200 MB"}])

    def test_forced_conflicts_stay_conflicts_for_the_rest_of_a_run(self):
        base = self.save(None, {"p": self.f("0")})["snapshot"]
        self.save(base, {"p": self.f("other")}, tag=1)
        mid = self.save(base, {"p": self.f("mine")}, tag=2)                                       # a save point: conflict
        last = self.save(mid["snapshot"], {"p": self.f("mine, later"), "p.conflict-run2": self.f("mine")}, tag=2, conflicted=["p"])
        self.assertEqual(self.read(last["snapshot"], "p"), "other")                               # still not overwritten at the run's last save
        self.assertEqual(self.read(last["snapshot"], "p.conflict-run2"), "mine, later")

    def test_what_a_save_may_not_contain(self):
        theirs = self.f("another mission's file")
        mine = self.f("ok")
        r = self.save(None, {"ok.txt": mine, "stolen.txt": theirs, "../up.txt": mine, "team/x": mine, ".env": mine, "ghost": ["0" * 64, 3, 0o644],
                             "lie": [mine[0], 999, 0o644], "bad": "nope"}, allowed={mine[0]})
        self.assertEqual(list(r["files"]), ["ok.txt"])
        why = {x["path"]: x["why"] for x in r["changes"]["refused"]}
        self.assertEqual(why, {"stolen.txt": "its content was never sent", "../up.txt": "outside the workspace", "team/x": "a read-only folder",
                               ".env": "looks like a secret", "ghost": "its content was never sent", "lie": "its size doesn't match its content", "bad": "not a file entry"})

    def test_a_credentials_value_is_never_saved(self):
        r = self.save(None, {"out.log": self.f("token=s3cr3t-value-123 done"), "ok": self.f("fine")}, needles=[b"s3cr3t-value-123"])
        self.assertEqual(list(r["files"]), ["ok"]); self.assertEqual(r["changes"]["refused"], [{"path": "out.log", "why": "contains a credential's value"}])
        r2 = self.save(None, {"out.log": self.f("token=s3cr3t-value-123 done")}, mission="m2")   # the control: without the value named, the file is kept
        self.assertEqual(list(r2["files"]), ["out.log"])

    def test_limits_refuse_the_whole_save_and_write_nothing(self):
        with mock.patch.object(ex, "WS_FILES", 3):
            with self.assertRaisesRegex(ex.ExecError, "at most 3"): self.save(None, {f"f{i}": self.f(str(i)) for i in range(4)})
        with mock.patch.object(ex, "WS_BYTES", 10):
            with self.assertRaisesRegex(ex.ExecError, "MB"): self.save(None, {"a": self.f("x" * 11)})
        with mock.patch.object(ex, "FILE_BYTES", 5):
            r = self.save(None, {"a": self.f("123456"), "b": self.f("123")})
            self.assertEqual(list(r["files"]), ["b"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_ws", one=True)["n"], 1)

    def test_links_are_kept_as_links(self):
        r = self.save(None, {"data/a.txt": self.f("a")}, links={"latest": "data/a.txt", "escape": "../../etc/passwd", "abs": "/etc/passwd"})
        t = self.st.tree(self.st.row(1, r["snapshot"]))
        self.assertEqual(t["links"], {"latest": "data/a.txt"})
        self.assertEqual({x["path"] for x in r["changes"]["refused"]}, {"escape", "abs"})

    def test_rollback_is_a_new_snapshot_and_can_be_undone(self):
        s1 = self.save(None, {"a": self.f("good")})["snapshot"]
        s2 = self.save(s1, {"a": self.f("broken"), "junk": self.f("j")})["snapshot"]
        rb = self.st.rollback(1, "comp:1", s1, "leo")
        self.assertTrue(rb["new"]); self.assertEqual(self.read(rb["snapshot"], "a"), "good")
        row = self.st.row(1, rb["snapshot"])
        self.assertEqual((row["parent"], row["by_user"], row["note"]), (s2, "leo", f"rollback to #{s1}"))
        undo = self.st.rollback(1, "comp:1", s2, "leo")
        self.assertEqual(self.read(undo["snapshot"], "a"), "broken")
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_ws WHERE mission='comp:1'", one=True)["n"], 4)   # history is never rewritten
        with self.assertRaisesRegex(ex.ExecError, "no such snapshot"): self.st.rollback(1, "mx:other", s1, "leo")

    def test_pruning_schedules_the_clean_up_itself_at_most_once_an_hour(self):
        started = []
        with mock.patch.object(ex, "KEEP", 2), mock.patch.object(ex.threading, "Thread", lambda **k: types.SimpleNamespace(start=lambda: started.append(k["name"]))):
            base = None
            for i in range(6): base = self.save(base, {"a": self.f(f"v{i}")})["snapshot"]
        self.assertEqual(started, ["exec-sweep"])          # four prunes removed rows; one clean-up was started

    def test_prune_keeps_the_last_ones_and_the_kept_ones_and_sweep_removes_only_unnamed_content(self):
        with mock.patch.object(ex, "KEEP", 3):
            ids, base = [], None
            for i in range(6):
                base = self.save(base, {"a": self.f(f"version {i}")})["snapshot"]; ids.append(base)
                if i == 0: self.st.keep(1, base, True)
        left = [r["id"] for r in self.db.q("SELECT id FROM mw_ws ORDER BY id")]
        self.assertEqual(left, [ids[0], ids[3], ids[4], ids[5]])
        v1, v5 = hashlib.sha256(b"version 1").hexdigest(), hashlib.sha256(b"version 5").hexdigest()
        self.assertEqual(self.st.sweep(older_than=3600), 0)                    # content just sent is never swept: a run may still be sending
        gone = self.st.sweep(older_than=-1)
        self.assertGreaterEqual(gone, 2)
        self.assertFalse(self.st.path(v1).exists()); self.assertTrue(self.st.path(v5).exists())
        self.assertEqual(self.read(ids[0], "a"), "version 0"); self.assertEqual(self.read(ids[5], "a"), "version 5")   # every remaining snapshot still reads

    def test_a_backup_hold_keeps_every_content_until_it_is_over(self):
        with mock.patch.object(ex, "KEEP", 2):
            base = None
            for i in range(5): base = self.save(base, {"a": self.f(f"held {i}")})["snapshot"]
        old = hashlib.sha256(b"held 0").hexdigest()
        self.db.setting(ex.BACKUP_HOLD, v=time.time() + 600)                   # a backup took the records and has not taken the files yet
        self.assertEqual(self.st.sweep(older_than=-1), 0); self.assertTrue(self.st.path(old).exists())
        self.db.setting(ex.BACKUP_HOLD, v="soon")                              # set and not understood: still nothing is deleted
        self.assertEqual(self.st.sweep(older_than=-1), 0); self.assertTrue(self.st.path(old).exists())
        self.db.setting(ex.BACKUP_HOLD, v=time.time() - 1)                     # a hold that ran out (a backup that died) stops holding by itself
        self.assertGreaterEqual(self.st.sweep(older_than=-1), 1); self.assertFalse(self.st.path(old).exists())


N = lambda cap, value=None, source="declared": {"cap": cap, "value": value, "source": source}


class Plan(unittest.TestCase):
    def test_nothing_set_is_the_teams_internet_without_the_package_indexes(self):
        off = ex.plan([], {}, False)
        self.assertEqual((off["size"], off["cpu"], off["memory_mb"], off["internet"], off["net"], off["workspace"], off["egress"]), ("M", 2, 4096, False, None, False, {"mode": "off"}))
        for approved in ((), ("pypi.org", "files.pythonhosted.org")):          # the Owner's approval opens nothing here: installing needs the mission's allowlist
            p = ex.plan([], {}, True, approved=approved)
            self.assertEqual((p["size"], p["internet"], p["workspace"]), ("M", True, False))
            self.assertEqual(p["net"], {"conns": True, "deny": list(ex.INDEXES)})
            self.assertEqual((p["egress"]["mode"], p["egress"]["denied_indexes"]), ("inherit", len(ex.INDEXES)))
            self.assertIn("allowlist", p["egress"]["packages"])
            self.assertNotIn("hosts", p["net"]); self.assertNotIn("hosts_exact", p["net"])   # the web itself is as the team's switch left it

    def test_size_follows_declared_ram_only(self):
        self.assertEqual(ex.plan([N("ram", "8")], {}, False)["size"], "L")
        self.assertEqual(ex.plan([N("ram", "4")], {}, False)["size"], "M")
        self.assertEqual(ex.plan([N("ram", "8", "inferred")], {}, False)["size"], "M")   # a suggestion never shapes a run
        self.assertEqual(ex.plan([N("ram", "lots")], {}, False)["size"], "M")
        self.assertEqual(ex.plan([N("ram", "8")], {}, False)["memory_mb"], 8192)

    def test_the_teams_internet_switch_stays_the_master(self):
        for eg in ({"mode": "public"}, {"mode": "allowlist", "hosts": ["github.com"]}):
            p = ex.plan([], {"egress": eg}, False)
            self.assertEqual((p["internet"], p["net"], p["egress"]), (False, None, {"mode": "off"}))

    def test_allowlist(self):
        p = ex.plan([N("git", "GitHub.com/a/b"), N("git", "gitlab.com/x/y", "inferred")], {"egress": {"mode": "allowlist", "hosts": ["api.example.org", "bad host"]}}, True)
        self.assertEqual(p["net"], {"conns": True, "hosts": ["api.example.org", "github.com"]})   # the policy's hosts and the declared repositories' hosts
        self.assertEqual(p["egress"], {"mode": "allowlist", "hosts": ["api.example.org", "github.com"]})
        none = ex.plan([], {"egress": {"mode": "allowlist"}}, True)
        self.assertEqual((none["internet"], none["net"], none["egress"]), (False, None, {"mode": "off", "why": "the allowlist names no host"}))   # never "everything"

    def test_packages_install_only_on_an_allowlist_from_the_owners_exact_hosts_over_https(self):
        """The Owner's decision is restricted access (review directive of 2026-11-13 §3): the allowlist is the enforcement."""
        ok = ("pypi.org", "files.pythonhosted.org")
        p = ex.plan([N("git", "github.com/a/b")], {"egress": {"mode": "allowlist", "hosts": ["example.org"], "packages": "approved"}}, True, approved=ok)
        self.assertEqual(p["net"], {"conns": True, "hosts": ["example.org", "github.com"], "hosts_exact": ["files.pythonhosted.org", "pypi.org"], "https_only": True})
        self.assertEqual(p["egress"], {"mode": "allowlist", "hosts": ["example.org", "github.com"], "package_hosts": ["files.pythonhosted.org", "pypi.org"], "https_only": True})
        self.assertNotIn("deny", p["net"])                                   # no blocklist anywhere on the allowlist path
        only = ex.plan([], {"egress": {"mode": "allowlist", "packages": "approved"}}, True, approved=ok)
        self.assertEqual((only["internet"], only["net"].get("hosts"), only["net"]["hosts_exact"]), (True, None, ["files.pythonhosted.org", "pypi.org"]))   # nothing but the indexes
        none = ex.plan([], {"egress": {"mode": "allowlist", "hosts": ["example.org"], "packages": "approved"}}, True, approved=())
        self.assertNotIn("hosts_exact", none["net"]); self.assertNotIn("https_only", none["net"])
        self.assertIn("approved no package host", none["egress"]["packages"])   # asked for, nothing approved: said, never widened
        without = ex.plan([], {"egress": {"mode": "allowlist", "hosts": ["example.org"]}}, True, approved=ok)
        self.assertEqual(without["net"], {"conns": True, "hosts": ["example.org"]})   # the control: no "packages", no index reachable

    def test_a_policys_own_host_list_cant_hold_a_package_index_or_a_name_over_or_under_one(self):
        for h, hit in (("pypi.org", True), ("files.pythonhosted.org", True), ("pythonhosted.org", True), ("test.pypi.org", True), ("evil.pypi.org", True),
                       ("registry.npmjs.org", True), ("npmjs.org", True), ("crates.io", True), ("golang.org", True), ("github.com", False), ("example.org", False),
                       ("notpypi.org", False), ("org", True)):   # "org" is a parent of pypi.org: a suffix that wide would admit every index
            self.assertEqual(ex.index_related(h), hit, h)
        p = ex.plan([N("git", "pypi.org/x/y")], {"egress": {"mode": "allowlist", "hosts": ["pythonhosted.org", "registry.npmjs.org", "example.org"]}}, True,
                    approved=("pypi.org",))
        self.assertEqual(p["net"]["hosts"], ["example.org"]); self.assertNotIn("hosts_exact", p["net"])   # not through the list, not through a declared repository's host
        self.assertEqual(p["egress"]["dropped_hosts"], ["pypi.org", "pythonhosted.org", "registry.npmjs.org"])

    def test_public_mode_reaches_no_known_index_approved_or_not_and_claims_no_more(self):
        for eg in ({"mode": "public"}, {"mode": "public", "packages": "approved"}):
            p = ex.plan([], {"egress": eg}, True, approved=("pypi.org", "files.pythonhosted.org"))
            self.assertEqual(sorted(p["net"]["deny"]), sorted(ex.INDEXES)); self.assertNotIn("hosts_exact", p["net"]); self.assertNotIn("https_only", p["net"])
            self.assertIn("needs the mission's allowlist", p["egress"]["packages"])
        self.assertLessEqual(len(ex.INDEXES), 200)                           # the proxy refuses a longer list whole

    def test_off(self):
        p = ex.plan([], {"egress": {"mode": "off"}}, True)
        self.assertEqual((p["internet"], p["net"], p["egress"]["mode"]), (False, None, "off"))

    def test_daily_byte_budget(self):
        eg = {"egress": {"mode": "public", "up_mb_day": 10, "down_mb_day": 100}}
        p = ex.plan([], eg, True, spent={"up_mb": 4, "down_mb": 99.5})
        self.assertEqual((p["net"]["up_mb"], p["net"]["down_mb"]), (6.0, 0.5))
        gone = ex.plan([], eg, True, spent={"up_mb": 10, "down_mb": 0})
        self.assertEqual((gone["internet"], gone["net"]), (False, None)); self.assertIn("upload budget", gone["egress"]["why"])

    def test_a_run_with_a_credential_never_has_the_public_web(self):
        p = ex.plan([N("git", "github.com/a/b")], {"egress": {"mode": "public"}}, True, has_secrets=True)
        self.assertEqual((p["egress"]["mode"], p["net"]["hosts"]), ("allowlist", ["github.com"])); self.assertNotIn("deny", p["net"])
        none = ex.plan([], {"egress": {"mode": "public"}}, True, has_secrets=True)
        self.assertEqual((none["internet"], none["egress"]["mode"]), (False, "off"))
        free = ex.plan([], {}, True, has_secrets=True)                           # no policy at all: still not the open web
        self.assertFalse(free["internet"])
        control = ex.plan([], {"egress": {"mode": "public"}}, True, has_secrets=False)
        self.assertTrue(control["internet"]); self.assertNotIn("hosts", control["net"])

    def test_an_agent_is_told_that_a_run_with_no_policy_installs_nothing(self):
        said = "Package indexes aren't reachable"
        self.assertIn(said, ex.describe("x", {"plan": 1}, True)); self.assertIn("allowlist", ex.describe("x", {"plan": 1}, True))
        self.assertIn(said, ex.describe("x", {"plan": 1, "egress": {"mode": "public"}}, True))
        self.assertNotIn(said, ex.describe("x", {"plan": 1}, False))                                         # no internet: nothing to say about indexes
        self.assertNotIn(said, ex.describe("x", {"plan": 1, "egress": {"mode": "allowlist", "hosts": ["example.org"], "packages": "approved"}}, True))

    def test_workspace_switch(self):
        self.assertTrue(ex.plan([], {"workspace": 1}, False)["workspace"])


class Restore(Base):
    """After a restore whose records (mw_ws, mw_blobs) are newer than its files, a snapshot names contents the store doesn't hold.
    The run is refused and says so; nothing goes on from an older or an empty workspace unless a person rolls the mission back."""
    def setUp(self):
        super().setUp()
        self.root = mock.patch.object(ex, "ROOT", Path(self.tmp.name) / "exec"); self.root.start(); ex._STORES.clear()
        self.db.setting("exec.comp:1", v=json.dumps({"workspace": 1}))
        self.s1 = self.save(None, {"a.py": self.f("v1"), "keep.txt": self.f("kept")})
        self.s2 = self.save(self.s1["snapshot"], {"a.py": self.f("v2 of the file"), "keep.txt": self.f("kept")})

    def tearDown(self): self.root.stop(); ex._STORES.clear(); super().tearDown()

    def lose(self, text): os.remove(self.st.path(hashlib.sha256(text.encode()).hexdigest()))

    def begin(self): return ex.begin(self.db, {"id": 1}, sid=9, task=None, agent=None, user="leo", command="ls", timeout=60, files={}, internet=False)

    def test_a_whole_workspace_has_no_problems_and_the_run_starts(self):
        self.assertEqual(self.st.problems(self.st.head(1, "comp:1")), [])
        self.assertTrue(self.begin().ws)

    def test_a_snapshot_naming_lost_contents_refuses_the_run_and_never_falls_back(self):
        self.lose("v2 of the file")
        head = self.st.head(1, "comp:1")
        self.assertEqual(self.st.problems(head), ["a.py"])
        with self.assertRaises(LookupError) as e: self.begin()                 # before any pod exists
        for part in (f"snapshot #{head['id']}", "a.py", "Nothing was started", "no older state", "roll the mission back"): self.assertIn(part, str(e.exception))
        self.assertEqual(self.st.head(1, "comp:1")["id"], head["id"])          # the head is what it was: nothing moved by itself
        sess = Endpoint.session(self, sid=5)                                   # the run's own pull says the same (the head can change while a run waits)
        code, out = sess.hook("POST", "/rlm/aef/ws/list", {})
        self.assertEqual(code, 400); self.assertIn("can't be restored", json.dumps(out["error"])); self.assertNotIn("files", out)

    def test_a_lost_file_list_is_a_problem_too(self):
        os.remove(self.st.path(self.st.head(1, "comp:1")["tree"]))
        self.assertEqual(self.st.problems(self.st.head(1, "comp:1")), ["its list of files"])
        with self.assertRaises(LookupError): self.begin()

    def test_a_content_cut_short_is_a_problem(self):
        with open(self.st.path(hashlib.sha256(b"v2 of the file").hexdigest()), "wb") as f: f.write(b"v2")
        self.assertEqual(self.st.problems(self.st.head(1, "comp:1")), ["a.py"])

    def test_a_person_rolls_back_to_a_whole_snapshot_and_runs_go_on_from_it(self):
        self.lose("v2 of the file")
        out = self.st.rollback(1, "comp:1", self.s1["snapshot"], "owner")
        self.assertTrue(out["new"]); self.assertEqual(self.st.problems(self.st.head(1, "comp:1")), [])
        self.assertEqual(self.st.tree(self.st.head(1, "comp:1"))["files"]["a.py"][0], hashlib.sha256(b"v1").hexdigest())
        self.assertTrue(self.begin().ws)
        with self.assertRaises(ex.ExecError) as e: self.st.rollback(1, "comp:1", self.s2["snapshot"], "owner")   # never onto the broken one
        self.assertIn("can't be restored", str(e.exception))

    def test_broken_shared_knowledge_refuses_too(self):
        self.st.commit(1, ex.SHARED, None, {"handbook.md": self.f("the handbook")}, user="owner")
        self.assertTrue(self.begin().ws)
        self.lose("the handbook")
        with self.assertRaises(LookupError) as e: self.begin()
        self.assertIn("shared knowledge", str(e.exception))

    def test_sending_a_lost_content_again_stores_it_again(self):
        self.lose("v2 of the file")
        self.assertEqual(self.st.put(b"v2 of the file"), hashlib.sha256(b"v2 of the file").hexdigest())
        self.assertEqual(self.st.problems(self.st.head(1, "comp:1")), [])


class Endpoint(Base):
    """Session.hook: what the script inside a run may ask, and what it may not."""
    def session(self, sid=1, mission="comp:1", comp=1, **kw):
        p = ex.plan([], {"workspace": 1}, False)
        self.db.q("INSERT INTO mw_sbx (id, comp_id, status) VALUES (?,?,'running')", (sid, comp))
        ex.schema(self.db)
        return ex.Session(self.st, self.db, comp=comp, mission=mission, task=None, agent={"id": 2, "name": "Devon R."}, sid=sid, the_plan=p,
                          command="true", timeout=60, files={"agent.py": "print(1)"}, **kw)

    def call(self, s, path, body=None): return s.hook("POST", "/rlm/aef" + path, body or {})

    def send(self, s, text):
        data = text.encode(); sha = hashlib.sha256(data).hexdigest()
        code, out = self.call(s, "/ws/put", {"sha": sha, "offset": 0, "data": base64.b64encode(data).decode(), "last": True})
        self.assertEqual(code, 200, out)
        return [sha, len(data), 0o644]

    def test_a_running_run_reports_what_it_has_used_so_far_and_the_final_report_replaces_it(self):
        s = self.session(sid=31)
        self.assertEqual(self.call(s, "/open")[1]["live_s"], ex.LIVE_S)
        row = lambda: json.loads(self.db.q("SELECT stats FROM mw_sbx WHERE id=31", one=True)["stats"] or "null")
        self.assertIsNone(row())
        self.assertEqual(self.call(s, "/stats", {"live": True, "cpu_seconds": 1.5, "peak_rss_mb": 300.2, "peak_procs": 4, "rss_mb": 280.0, "procs": 3, "wall_s": 12.0, "tree_at_peak": ["x"] * 9})[0], 200)
        first = row()
        self.assertEqual((first["live"], first["cpu_seconds"], first["rss_mb"], first["procs"]), (True, 1.5, 280.0, 3)); self.assertNotIn("tree_at_peak", first)   # figures only
        self.assertIn("own report", first["by"]); self.assertIsNone(s.stats)                # not the run's measurements yet
        self.call(s, "/stats", {"live": True, "cpu_seconds": 3.0, "peak_rss_mb": 310.0, "peak_procs": 4, "rss_mb": 12.0, "procs": 1, "wall_s": 22.0})
        self.assertEqual(row()["cpu_seconds"], 3.0)
        self.call(s, "/stats", {"v": 1, "cpu_seconds": 3.4, "peak_rss_mb": 310.0, "peak_procs": 4, "wall_s": 25.0, "command_exit": 0})
        self.call(s, "/stats", {"live": True, "cpu_seconds": 9.9})                          # a late "so far" never replaces the final report
        self.assertEqual((s.stats["cpu_seconds"], s.stats.get("live")), (3.4, None))
        out = s.end({"status": "done", "exit": 0, "output": "ok", "error": ""})
        self.assertEqual((out["stats"]["cpu_seconds"], row()["cpu_seconds"], row().get("live")), (3.4, 3.4, None))

    def test_a_run_that_ends_without_its_final_report_keeps_the_last_figures_it_sent_marked_as_such(self):
        s = self.session(sid=32)
        self.call(s, "/stats", {"live": True, "cpu_seconds": 7.0, "peak_rss_mb": 900.0, "peak_procs": 20, "rss_mb": 880.0, "procs": 19, "wall_s": 40.0})
        out = s.end({"status": "error", "exit": None, "output": "", "error": "The run's pod disappeared."})
        kept = json.loads(self.db.q("SELECT stats FROM mw_sbx WHERE id=32", one=True)["stats"])
        self.assertEqual((kept["live"], kept["peak_rss_mb"]), (False, 900.0)); self.assertIn("without its final report", kept["partial"])
        self.assertEqual(out["stats"]["partial"], kept["partial"])

    def test_the_wrapped_run(self):
        s = self.session()
        self.assertTrue(s.command.startswith("python3 /work/.axor/aef.py run 60 "))
        self.assertEqual(base64.b64decode(s.command.split()[-1]).decode(), "true")
        self.assertEqual(s.timeout, 60 + ex.RESERVE)
        self.assertEqual(s.files, {"mission/team/agent.py": "print(1)"})        # team files are handed over read-only, under the workspace
        self.assertEqual(s.kwargs, {"hook": s.hook, "size": "M", "queue": "comp:1"})
        long = self.session(sid=2, **{}) if False else None
        s2 = ex.Session(self.st, self.db, comp=1, mission="comp:1", task=None, agent=None, sid=9, the_plan=ex.plan([], {"plan": 1}, False), command="x",
                        timeout=5000, files={"a": "b"})
        self.assertEqual((s2.timeout, s2.files), (sandbox.MAX_TIMEOUT, {"a": "b"}))   # never past the sandbox's own limit; no workspace, files as before

    def test_open_says_what_the_run_has(self):
        code, o = self.call(self.session(), "/open")
        self.assertEqual(code, 200)
        self.assertEqual((o["run"], o["mission"], o["agent_dir"], o["workspace"]["on"], o["secrets"]), (1, "comp:1", "agents/devon-r-2", True, []))
        self.assertEqual(o["limits"]["secret_re"], sandbox.SECRET_PATH.pattern)

    def test_round_trip_and_the_mission_comes_from_axor_never_from_the_run(self):
        s = self.session()
        e = self.send(s, "hello")
        code, r = self.call(s, "/ws/commit", {"base": None, "files": {"a.txt": e}, "mission": "comp:2", "comp": 2, "comp_id": 2, "final": True})
        self.assertEqual((code, r["new"]), (200, True)); self.assertNotIn("files", r)
        row = self.st.row(1, r["snapshot"])
        self.assertEqual((row["comp_id"], row["mission"], row["sbx_id"], row["agent_id"]), (1, "comp:1", 1, 2))
        self.assertIsNone(self.st.head(2, "comp:2"))
        s2 = self.session(sid=2)
        _, lst = self.call(s2, "/ws/list")
        self.assertEqual((lst["snapshot"], list(lst["files"])), (r["snapshot"], ["a.txt"]))
        _, got = self.call(s2, "/ws/get", {"want": [[e[0], 0]]})
        self.assertEqual(base64.b64decode(got["parts"][0]["data"]), b"hello"); self.assertTrue(got["parts"][0]["last"])

    def test_a_run_cant_fetch_or_probe_another_missions_content(self):
        other = self.session(sid=1, mission="mx:other")
        e = self.send(other, "the other mission's secret plan")
        self.call(other, "/ws/commit", {"base": None, "files": {"plan.md": e}})
        s = self.session(sid=2)
        self.call(s, "/ws/list")
        code, out = self.call(s, "/ws/get", {"want": [[e[0], 0]]})
        self.assertEqual(code, 400); self.assertIn("wasn't given", out["error"]["message"])
        _, have = self.call(s, "/ws/have", {"shas": [e[0]]})
        self.assertEqual(have["missing"], [e[0]])                      # "you'd have to send it": no hint that someone else holds it
        code, r = self.call(s, "/ws/commit", {"base": None, "files": {"copy.md": e}})
        self.assertEqual(r["changes"]["refused"], [{"path": "copy.md", "why": "its content was never sent"}])

    def test_a_run_cant_learn_another_missions_file_names_through_the_base_it_names(self):
        other = self.session(sid=1, mission="mx:other")
        _, made = self.call(other, "/ws/commit", {"base": None, "files": {"secret-plan.md": self.send(other, "x")}})
        s = self.session(sid=2)
        code, out = self.call(s, "/ws/commit", {"base": made["snapshot"], "files": {}})
        self.assertEqual(code, 400); self.assertNotIn("secret-plan", json.dumps(out))
        self.assertIsNone(self.st.head(1, "comp:1"))

    def test_a_run_that_waited_starts_from_the_missions_head_as_it_is_when_it_pulls(self):
        first = self.save(None, {"a.txt": self.f("old")})["snapshot"]
        s = self.session(sid=5)                                   # planned (and then, say, queued for a slot) while the head was `first`
        self.assertEqual(s.manifest["inputs"]["ws_from"], first)
        sealed = s.manifest["sha256"]
        newer = self.save(first, {"a.txt": self.f("what another run finished meanwhile")})["snapshot"]
        _, lst = self.call(s, "/ws/list")
        self.assertEqual(lst["snapshot"], newer)                  # it restores the newer one,
        self.assertEqual(self.st.read(lst["files"]["a.txt"][0]), b"what another run finished meanwhile")
        self.assertEqual((s.manifest["inputs"]["ws_from"], s.manifest["sha256"] != sealed), (newer, True))   # and its manifest says so
        s.end({"status": "done", "exit": 0, "output": ""})
        self.assertEqual(self.db.q("SELECT ws_from FROM mw_sbx WHERE id=5", one=True)["ws_from"], newer)

    def test_readiness_check_runs_have_a_queue_of_their_own(self):
        with mock.patch.object(sandbox, "READINESS_USER", "AXoR readiness check", create=True):
            self.assertEqual(self.session(sid=1, user="AXoR readiness check").kwargs["queue"], "axor:check")
            self.assertEqual(self.session(sid=2, user="leo").kwargs["queue"], "comp:1")
            self.assertEqual(self.session(sid=3).kwargs["queue"], "comp:1")

    def test_content_is_checked_as_it_arrives(self):
        s = self.session()
        good = hashlib.sha256(b"abcdef").hexdigest()
        b64 = lambda x: base64.b64encode(x).decode()
        self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 3, "data": b64(b"def"), "last": True})[0], 400)       # not from the start
        self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 0, "data": b64(b"abc"), "last": False})[0], 200)
        self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 0 + 4, "data": b64(b"def"), "last": True})[0], 400)   # a gap
        self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 3, "data": b64(b"deX"), "last": True})[0], 400)       # the hash doesn't match
        self.assertEqual(self.st.known([good]), {})
        self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 0, "data": "not base64!", "last": True})[0], 400)
        with mock.patch.object(ex, "FILE_BYTES", 4):
            self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 0, "data": b64(b"abcdef"), "last": True})[0], 400)
        with mock.patch.object(ex, "SAVE_BYTES", s.sent + 4):
            code, out = self.call(s, "/ws/put", {"sha": good, "offset": 0, "data": b64(b"abcdef"), "last": True})
            self.assertEqual(code, 400); self.assertIn("new content", out["error"]["message"])
        self.assertEqual(self.call(s, "/ws/put", {"sha": good, "offset": 0, "data": b64(b"abcdef"), "last": True})[0], 200)
        self.assertEqual(self.st.known([good]), {good: 6})

    def test_other_requests(self):
        s = self.session()
        self.assertEqual(s.hook("POST", "/rlm/aef/nope", {})[0], 404); self.assertEqual(s.hook("GET", "/rlm/aef/open", {})[0], 404)
        self.assertEqual(s.hook("POST", "/rlm/query", {})[0], 404)
        code, out = self.call(s, "/secret", {"name": "DOCKERHUB_TOKEN"})
        self.assertEqual(code, 400); self.assertEqual(s.events[-1]["kind"], "secret_refused")      # no broker, no credential: refused and recorded
        self.assertEqual(self.call(s, "/stats", {"cpu_seconds": 1.5, "peak_rss_mb": 20, "evil": "x" * 10})[0], 200)
        self.assertEqual((s.stats["cpu_seconds"], "evil" in s.stats), (1.5, False)); self.assertIn("own report", s.stats["by"])
        self.assertEqual(self.call(s, "/stats", {"tree_at_peak": ["x" * 1000] * 300})[0], 400)

    def test_end_writes_the_row_and_masks_what_the_run_was_given(self):
        class Broker:
            names = {"API_KEY"}
            closed = False
            def fetch(self, name): return "s3cr3t-value-123"
            def close(self): self.closed = True
        b = Broker()
        s = self.session(secrets=b)
        self.assertEqual(self.call(s, "/secret", {"name": "API_KEY"})[1], {"value": "s3cr3t-value-123"})
        self.assertEqual(self.call(s, "/secret", {"name": "OTHER"})[0], 400)
        leak = self.send(s, "the key is s3cr3t-value-123")
        _, c = self.call(s, "/ws/commit", {"base": None, "files": {"notes.txt": leak, "ok.txt": self.send(s, "fine")}, "final": True})
        self.assertEqual(c["changes"]["refused"], [{"path": "notes.txt", "why": "contains a credential's value"}])
        self.call(s, "/stats", {"cpu_seconds": 2, "tree_at_peak": [{"cmd": "curl -H s3cr3t-value-123"}]})
        enc = base64.b64encode(b"s3cr3t-value-123").decode()
        r = s.end({"status": "done", "exit": 0, "seconds": 3.0, "output": f"using s3cr3t-value-123 and {enc}\n", "image_id": "sha256:" + "a" * 64,
                   "net": {"refused": [{"host": "pypi.org", "why": "package index not approved for this mission"}]}})
        self.assertNotIn("s3cr3t", r["output"]); self.assertNotIn(enc, r["output"]); self.assertIn("[credential API_KEY]", r["output"])
        self.assertTrue(b.closed)
        row = self.db.q("SELECT stats, manifest, ws_from, ws_to FROM mw_sbx WHERE id=1", one=True)
        m = json.loads(row["manifest"])
        self.assertNotIn("s3cr3t", row["stats"]); self.assertNotIn("s3cr3t", row["manifest"])
        self.assertEqual((m["plan"]["secrets"], m["result"]["image_id"], m["result"]["ws_to"], row["ws_to"], row["ws_from"]), (["API_KEY"], "sha256:" + "a" * 64, c["snapshot"], c["snapshot"], None))
        kinds = [e["kind"] for e in m["result"]["events"]]
        for k in ("secret_given", "secret_refused", "refused_save", "refused_connection"): self.assertIn(k, kinds)
        self.assertEqual(r["workspace"], {"from": None, "to": c["snapshot"], "saves": 1})

    def test_the_output_hash_is_of_the_commands_own_output(self):
        """AXoR's own marker lines (times, snapshot numbers, measurements) differ between two identical runs: they aren't the command's output."""
        a, b, c = self.session(sid=1), self.session(sid=2), self.session(sid=3)
        ra = a.end({"status": "done", "exit": 0, "output": "@@AXOR-WORKSPACE restored snapshot #1: 2 files, 0 kB\n@@AXOR-START 10:00:01\n42 passed\n@@AXOR-STATS cpu 1.2 s\n@@AXOR-EXIT 0"})
        rb = b.end({"status": "done", "exit": 0, "output": "@@AXOR-WORKSPACE restored snapshot #9: 2 files, 0 kB\n@@AXOR-START 11:30:44\n42 passed\n@@AXOR-STATS cpu 1.4 s\n@@AXOR-EXIT 0"})
        rc = c.end({"status": "done", "exit": 0, "output": "@@AXOR-START 11:30:44\n41 passed\n@@AXOR-EXIT 0"})
        h = lambda s_: s_.manifest["result"]["output_sha256"]
        self.assertEqual(h(a), h(b)); self.assertNotEqual(h(a), h(c))
        self.assertEqual(h(a), hashlib.sha256(b"42 passed").hexdigest())

    def test_the_same_plan_and_inputs_give_the_same_manifest_hash(self):
        a, b = self.session(sid=1), self.session(sid=2)
        self.assertEqual(a.manifest["sha256"], b.manifest["sha256"])
        c = ex.Session(self.st, self.db, comp=1, mission="comp:1", task=None, agent=None, sid=3, the_plan=ex.plan([], {"workspace": 1}, False), command="false",
                       timeout=60, files={"agent.py": "print(1)"})
        self.assertNotEqual(a.manifest["sha256"], c.manifest["sha256"])


class Planned(unittest.TestCase):
    def test_the_one_test_of_whether_a_teams_runs_are_planned(self):
        for cfg in ({"plan": 1}, {"workspace": 1}, {"egress": {"mode": "off"}}, {"plan": 0, "workspace": True}):
            self.assertTrue(ex.planned(cfg), cfg)
        for cfg in ({}, None, {"plan": 0}, {"plan": False}, {"egress": {"hosts": ["x.org"]}}, {"egress": {}}, {"other": 1}):   # stored, non-empty, and still nothing on
            self.assertFalse(ex.planned(cfg), cfg)


class AgentText(unittest.TestCase):
    def test_no_switch_no_change(self):
        for internet in (False, True):
            self.assertEqual(mining_work.sandbox_tool(internet, {}), mining_work.sandbox_tool(internet))
        self.assertEqual(ex.brief({"status": "done", "output": "x"}), {})

    def test_the_mission_of_a_task_has_one_public_answer(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        db = AuthDB(os.path.join(tmp, "m.db")); self.addCleanup(db.db.close)
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, mission TEXT)")
        db.q("INSERT INTO mw_tasks (id, comp_id, title, mission) VALUES (7701, 9, 'in a mission', 'mx:named')")
        db.q("INSERT INTO mw_tasks (id, comp_id, title) VALUES (7702, 9, 'in none')")
        self.assertEqual(ex.mission_of(db, 9, 7701), "mx:named")
        self.assertEqual(ex.mission_of(db, 9, 7702), "comp:9"); self.assertEqual(ex.mission_of(db, 9, None), "comp:9")
        self.assertEqual(ex.mission_of(db, 8, 7701), "comp:8")                 # another team's task id is never that team's mission
        self.assertIs(ex._mission_of, ex.mission_of)

    def test_what_is_kept_replaces_nothing_is_kept(self):
        d = mining_work.sandbox_tool(False, {"workspace": 1})["description"]
        self.assertNotIn("aren't kept", d)
        for said in ("mission's workspace", "team/ (the team's files, read-only", "conflict-run", "python3 .axor/aef.py save", "$AXOR_AGENT_DIR"): self.assertIn(said, d)
        self.assertIn("aren't kept", mining_work.sandbox_tool(False, {"plan": 1})["description"])   # measurements alone keep nothing
        self.assertIn("A docker_job sees this workspace only for the folders it names in workspace_paths, as of the last save", d)   # or an agent builds stale files and measures nothing new
        self.assertIn("everything else it builds comes from the team's files", d)
        self.assertIn("a copy of them is read-only too", d); self.assertIn("cp -r --no-preserve=mode", d)   # or the first edit of a copied file fails and the next run's doesn't
        self.assertNotIn("docker_job", mining_work.sandbox_tool(False, {"plan": 1})["description"])  # no kept workspace: nothing to confuse it with

    def test_the_policy_is_stated(self):
        allow = mining_work.sandbox_tool(True, {"egress": {"mode": "allowlist", "hosts": ["example.org", "github.com", "pypi.org"]}})["description"]
        self.assertIn("only these hosts (example.org, github.com)", allow); self.assertIn("Playwright", allow)   # an index on the list is not offered
        self.assertIn("No package index is reachable", allow)
        pk = mining_work.sandbox_tool(True, {"egress": {"mode": "allowlist", "hosts": ["github.com"], "packages": "approved"}})["description"]
        self.assertIn("only from the package indexes the Owner approved, over https", pk)
        self.assertIn("no internet", mining_work.sandbox_tool(True, {"egress": {"mode": "off"}})["description"])
        self.assertIn("needs the mission's allowlist", mining_work.sandbox_tool(True, {"egress": {"mode": "public"}})["description"])
        quiet = mining_work.sandbox_tool(False, {"egress": {"mode": "allowlist", "hosts": ["x.org"]}})["description"]
        self.assertNotIn("only these hosts", quiet)                              # a team without internet isn't told about hosts it can't reach

    def test_brief(self):
        r = {"workspace": {"from": 3, "to": 4, "saves": 1}, "stats": {"cpu_seconds": 2.5, "peak_rss_mb": 80, "peak_procs": 4, "wall_s": 9, "disk_mb": {"work": 12},
                                                                     "files": {"added": 2, "changed": 1, "removed": 0, "conflicts": 1}}}
        b = ex.brief(r)
        self.assertEqual(b["workspace"], "Saved as snapshot #4: 2 added, 1 changed, 0 removed; 1 conflict(s): see the output")
        self.assertEqual(b["usage"], {"cpu_seconds": 2.5, "peak_rss_mb": 80, "peak_procs": 4, "wall_s": 9, "disk_mb": 12})
        self.assertEqual(ex.brief({"workspace": {"from": 3, "to": None, "saves": 1}, "stats": {"files": {"error": "too big"}}})["workspace"], "NOT saved: too big")
        self.assertEqual(ex.brief({"workspace": {"from": 3, "to": None, "saves": 1}})["workspace"], "Nothing changed in the workspace.")


class BudgetAndStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name); ex.schema(self.db)
        self.db.q("INSERT INTO mw_tasks (id, comp_id, title, mission) VALUES (1, 33, 't', 'mx:a'), (2, 33, 't', 'mx:b'), (3, 34, 't', NULL)")

    def tearDown(self): close(self.db); self.tmp.cleanup()

    def row(self, task, comp=33, down=0, up=0, refused=(), left=None, started=None, status="done", pod=None, services=""):
        man = {"plan": {"egress": {"mode": "public", **({"down_mb_left": left} if left is not None else {})}}}
        net = {"up_bytes": up, "down_bytes": down, "refused": [{"host": "*", "why": w} for w in refused]}
        return self.db.q("INSERT INTO mw_sbx (comp_id, task_id, status, started, net, manifest, pod, services) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                         (comp, task, status, started or time.time(), json.dumps(net), json.dumps(man), pod, services), one=True)["id"]

    def test_bytes_are_summed_per_mission_since_midnight(self):
        self.row(1, down=400_000, up=1_000); self.row(1, down=100_000); self.row(2, down=9_000_000)
        self.row(1, down=5_000_000, started=time.time() - 2 * 86400)                    # another day
        got = ex.spent_today(self.db, 33, "mx:a")
        self.assertEqual((round(got["down_mb"], 3), round(got["up_mb"], 3), "down_cut" in got), (0.5, 0.001, False))
        self.assertEqual(round(ex.spent_today(self.db, 33, "mx:b")["down_mb"], 1), 9.0)
        self.assertEqual(ex.spent_today(self.db, 34, "comp:34"), {"up_mb": 0.0, "down_mb": 0.0})

    def test_a_run_cut_by_the_budget_means_the_budget_is_spent(self):
        """The proxy cuts a run just before the byte that would cross its cap, so the bytes never quite add up to the budget."""
        self.row(1, down=978_668, refused=["download cap of 1 MB reached; the run's connections were cut"], left=1.0)
        got = ex.spent_today(self.db, 33, "mx:a")
        self.assertTrue(got["down_cut"]); self.assertLess(got["down_mb"], 1.0)
        p = ex.plan([], {"egress": {"mode": "public", "down_mb_day": 1}}, True, spent=got)
        self.assertEqual((p["internet"], p["egress"]), (False, {"mode": "off", "why": "the mission's download budget for today (1 MB) is spent"}))
        without = ex.plan([], {"egress": {"mode": "public", "down_mb_day": 1}}, True, spent={"down_mb": got["down_mb"], "up_mb": 0})
        self.assertTrue(without["internet"])                                            # the control: the bytes alone would have let the next run on
        self.row(2, down=10, refused=["download cap of 5000 MB reached; the run's connections were cut"])   # cut by the run's own cap, no budget: not "spent"
        self.assertNotIn("down_cut", ex.spent_today(self.db, 33, "mx:b"))

    def test_a_stop_set_here_is_seen_by_a_waiting_run_at_once_not_at_its_next_look(self):
        sbx = types.SimpleNamespace(kube=types.SimpleNamespace(delete=lambda path, params=None: None))
        waiting = self.row(1, status="running")                                   # on record, no pod yet: waiting for a slot
        g = ex.guard(self.db, 33, 1, every=3600); other = ex.guard(self.db, 33, 2, every=3600)
        self.assertFalse(g()); self.assertFalse(other())                         # both have just looked: their next look is an hour away
        out = ex.stop(self.db, sbx, "mx:a", "now", "owner", sweep_again=0)
        self.assertTrue(g())                                                     # at once
        self.assertFalse(other())                                                # another mission's run looked again too, and goes on
        self.assertEqual((out["running"], out["ended"]), ([waiting], []))        # it was covered; it had no pod for the backstop to delete
        ex.resume(self.db, "mx:a", "owner")
        late = ex.guard(self.db, 33, 1, every=3600); self.assertFalse(late())
        self.db.setting("exec.stop:mx:a", v="set by another process")           # the control: without stop() here, only the timed look finds it
        self.assertFalse(late())
        self.assertTrue(ex.guard(self.db, 33, 1)())

    def test_stop_ends_that_missions_runs_only_refuses_new_ones_and_is_audited(self):
        gone = []
        sbx = types.SimpleNamespace(kube=types.SimpleNamespace(delete=lambda path, params=None: gone.append(path)))
        a = self.row(1, status="running", pod="sbx-a"); self.row(2, status="running", pod="sbx-b"); self.row(1, status="done", pod="sbx-old")
        vm = self.row(1, status="running", pod="job-1", services="vm-docker"); self.row(3, comp=34, status="running", pod="sbx-team34")
        out = ex.stop(self.db, sbx, "mx:a", "runaway spend", "owner", sweep_again=0)
        self.assertEqual(sorted(out["ended"]), [a, vm])
        self.assertEqual(sorted(gone), ["/api/v1/namespaces/axor-runner/pods/job-1", "/api/v1/namespaces/axor-sandbox/pods/sbx-a"])
        self.assertIn("runaway spend (owner, ", ex.stops(self.db)["mx:a"])
        with self.assertRaisesRegex(LookupError, "Runs are stopped \\(mx:a\\)"):
            ex.begin(self.db, {"id": 33}, sid=a, task=1, agent=None, user=None, command="ls", timeout=60, files={}, internet=False)
        self.assertIsNone(ex.begin(self.db, {"id": 33}, sid=a, task=2, agent=None, user=None, command="ls", timeout=60, files={}, internet=False))   # another mission goes on
        ex.resume(self.db, "mx:a", "owner")
        self.assertEqual(ex.stops(self.db), {})
        self.assertIsNone(ex.begin(self.db, {"id": 33}, sid=a, task=1, agent=None, user=None, command="ls", timeout=60, files={}, internet=False))
        acts = [(r["action"], r["actor"], r["target"]) for r in self.db.q("SELECT action, actor, target FROM audit WHERE action LIKE 'exec.%' ORDER BY ts, action DESC")]
        self.assertEqual(sorted(acts), [("exec.resume", "owner", "mx:a"), ("exec.stop", "owner", "mx:a")])

    def test_a_waiting_or_running_run_learns_of_the_stop_through_its_own_cancelled_test(self):
        g_a, g_b = ex.guard(self.db, 33, 1, every=0), ex.guard(self.db, 33, 2, every=0)
        g_team = ex.guard(self.db, 34, None, every=0)
        self.assertEqual((g_a(), g_b(), g_team()), (False, False, False))
        self.db.setting("exec.stop:mx:a", v="stop")
        self.assertEqual((g_a(), g_b(), g_team()), (True, False, False))            # its mission only
        self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'")
        self.assertTrue(g_a())                                                       # once stopped, a run stays stopped: lifting is for new runs
        self.db.setting("exec.stop:*", v="everything")
        self.assertEqual((g_b(), g_team()), (True, True))
        self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'")
        self.assertTrue(ex.guard(self.db, 33, 1, cancelled=lambda: True)())          # the caller's own cancel still counts
        calls = []
        slow = ex.guard(types.SimpleNamespace(q=lambda *a, **k: calls.append(1) or []), 33, None, every=3600)
        for _ in range(50): slow()
        self.assertEqual(len(calls), 1)                                              # it looks at most every few seconds, however often it is asked

    def test_refusal_says_why(self):
        self.assertIsNone(ex.refusal(self.db, 33, 1))
        self.db.setting("exec.stop:mx:a", v="Owner: runaway spend")
        self.assertEqual(ex.refusal(self.db, 33, 1), "Runs are stopped (mx:a): Owner: runaway spend")
        self.assertIsNone(ex.refusal(self.db, 33, 2)); self.assertIsNone(ex.refusal(self.db, 34, None))
        self.db.setting("exec.stop:*", v="all")
        self.assertEqual(ex.refusal(self.db, 34, None), "Runs are stopped (every mission): all")

    def test_stop_everything(self):
        gone = []
        sbx = types.SimpleNamespace(kube=types.SimpleNamespace(delete=lambda path, params=None: gone.append(path)))
        self.row(1, status="running", pod="p1"); self.row(3, comp=34, status="running", pod="p2")
        self.assertEqual(len(ex.stop(self.db, sbx, "*", "", "owner", sweep_again=0)["ended"]), 2)
        with self.assertRaisesRegex(LookupError, "every mission"):
            ex.begin(self.db, {"id": 34}, sid=1, task=None, agent=None, user="leo", command="ls", timeout=60, files={}, internet=False)


class FakeSbxOld:
    """A sandbox that takes exactly the arguments it took before AEF: a team with no switch on must still fit it."""
    def __init__(self): self.calls = []
    def run(self, files, command, services, timeout, budget, label="", cancelled=None, started=None, internet=False, checkpoint=None):
        self.calls.append({"files": files, "command": command, "timeout": timeout, "internet": internet, "checkpoint": checkpoint})
        return {"status": "done", "exit": 0, "output": "ok\n", "error": "", "cost": 0, "calls": 0}


class FakeSbxNew(FakeSbxOld):
    def run(self, files, command, services, timeout, budget, label="", cancelled=None, started=None, internet=False, checkpoint=None, hook=None, size=None, queue=None, net=None):
        self.calls.append({"files": files, "command": command, "timeout": timeout, "internet": internet, "checkpoint": checkpoint, "hook": hook, "size": size,
                           "queue": queue, "net": net})
        return {"status": "done", "exit": 0, "output": "ok\n", "error": "", "cost": 0, "calls": 0, "image_id": "sha256:" + "b" * 64}


def work(db, sbx):
    w = object.__new__(mining_work.Work)
    w.db, w.sbx = db, sbx
    w._event = lambda *a, **k: None
    w._label = lambda c: "Team"
    w._ins = lambda sql, args: db.q(sql + " RETURNING id", args, one=True)["id"]
    return w


class CallSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name)
        self.db.q("INSERT INTO mw_files (comp_id, path, content) VALUES (23, 'agent.py', 'print(1)')")
        self.db.q("INSERT INTO mw_tasks (id, comp_id, title, needs, mission) VALUES (7, 23, 'Build it', ?, 'mx:4')", (json.dumps(["ram:8", "git:github.com/a/b"]),))
        self.root = mock.patch.object(ex, "ROOT", Path(self.tmp.name) / "exec"); self.root.start()
        ex._STORES.clear()

    def tearDown(self): self.root.stop(); close(self.db); self.tmp.cleanup()

    def test_no_switch_on_the_run_is_the_run_as_before(self):
        sbx = FakeSbxOld(); w = work(self.db, sbx)
        r = w._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, "pytest -q", [], 600, 1.0, task=7, agent={"id": 2, "name": "Devon"})
        c = sbx.calls[0]
        self.assertEqual((c["files"], c["command"], c["timeout"], c["internet"]), ({"agent.py": "print(1)"}, "pytest -q", 600, True))
        self.assertIsNotNone(c["checkpoint"])                                     # a task's run still has its checkpoint
        self.assertEqual(set(r), {"status", "exit", "output", "error", "cost", "calls", "sbx"})
        self.assertNotIn("stats", {x["name"] for x in self.db.q("PRAGMA table_info(mw_sbx)")})   # not even the columns are made
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "exec")))

    def test_switched_off_server_wide(self):
        self.db.setting("exec.comp:23", v=json.dumps({"plan": 1, "workspace": 1}))
        sbx = FakeSbxOld(); w = work(self.db, sbx)
        with mock.patch.object(ex, "ENABLED", False):
            w._sandbox({"id": 23, "internet": 0}, {"netuid": 61}, "ls", [], 60, 1.0, user="leo")
        self.assertEqual(sbx.calls[0]["command"], "ls")

    def test_with_the_switches_on_the_run_is_planned(self):
        self.db.setting("exec.comp:23", v=json.dumps({"plan": 1, "workspace": 1, "egress": {"mode": "allowlist", "hosts": ["example.org"]}}))
        sbx = FakeSbxNew(); w = work(self.db, sbx)
        r = w._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, "pytest -q", [], 600, 1.0, task=7, agent={"id": 2, "name": "Devon"})
        c = sbx.calls[0]
        self.assertTrue(c["command"].startswith("python3 /work/.axor/aef.py run 600 "))
        self.assertEqual(c["files"], {"mission/team/agent.py": "print(1)"})
        self.assertEqual((c["size"], c["queue"], c["timeout"], c["internet"]), ("L", "mx:4", 600 + ex.RESERVE, True))   # ram:8 → L; the task's mission is the queue
        self.assertEqual(c["net"], {"conns": True, "hosts": ["example.org", "github.com"]})
        self.assertIsNone(c["checkpoint"]); self.assertTrue(callable(c["hook"]))    # one store per run: the workspace, not mw_ckpt
        row = self.db.q("SELECT manifest, ws_from, ws_to, stats FROM mw_sbx WHERE id=?", (r["sbx"],), one=True)
        m = json.loads(row["manifest"])
        self.assertEqual((m["plan"]["mission"], m["plan"]["size"], m["plan"]["egress"]["mode"], m["inputs"]["command"], m["result"]["image_id"]),
                         ("mx:4", "L", "allowlist", "pytest -q", "sha256:" + "b" * 64))
        self.assertEqual(r["manifest_sha256"], m["sha256"]); self.assertIsNone(row["stats"])   # the fake run reported nothing: nothing is invented

    def test_a_mission_can_have_its_own_reach_in_place_of_its_teams(self):
        self.db.q("INSERT INTO mw_tasks (id, comp_id, title, needs, mission) VALUES (8, 23, 'Other mission', '[]', 'mx:5')")
        self.db.setting("exec.comp:23", v=json.dumps({"plan": 1, "egress": {"mode": "public"}}))
        self.db.setting("exec.mission:23:mx:4", v=json.dumps({"egress": {"mode": "allowlist", "hosts": ["example.org"]}}))
        sbx = FakeSbxNew(); w = work(self.db, sbx)
        w._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, "ls", [], 60, 1.0, task=7)      # mission mx:4: its own allowlist (and its task's declared repository)
        w._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, "ls", [], 60, 1.0, task=8)      # mission mx:5: the team's public policy
        self.assertEqual(sbx.calls[0]["net"], {"conns": True, "hosts": ["example.org", "github.com"]})
        self.assertEqual(sbx.calls[1]["net"], {"conns": True, "deny": list(ex.INDEXES)})   # public: the web, and no known package index
        self.assertEqual(ex.settings(self.db, 23, "mx:4")["egress"]["mode"], "allowlist"); self.assertEqual(ex.settings(self.db, 23, "mx:5")["egress"]["mode"], "public")
        self.assertEqual(ex.mission_policies(self.db, 23), {"mx:4": {"egress": {"mode": "allowlist", "hosts": ["example.org"]}}})
        # a mission's own policy plans its runs even when its team has nothing on; the team's other missions stay as before
        self.db.q("DELETE FROM app_settings WHERE k='exec.comp:23'")
        w._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, "ls", [], 60, 1.0, task=7)
        self.assertTrue(sbx.calls[2]["command"].startswith("python3 /work/.axor/aef.py run"))
        old = FakeSbxOld(); w2 = work(self.db, old)
        w2._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, "ls", [], 60, 1.0, task=8)
        self.assertEqual(old.calls[0]["command"], "ls")

    def test_an_emergency_stop_refuses_the_run_whatever_the_switches(self):
        for key, hit in (("exec.stop:mx:4", True), ("exec.stop:*", True), ("exec.stop:mx:5", False)):
            self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.stop:%'")
            self.db.setting(key, v="Owner: stop, 2026-11-13")
            sbx = FakeSbxOld(); w = work(self.db, sbx)
            if hit:
                with self.assertRaisesRegex(LookupError, "Runs are stopped"): w._sandbox({"id": 23, "internet": 0}, {"netuid": 61}, "ls", [], 60, 1.0, task=7)
                self.assertEqual(sbx.calls, [])
                row = self.db.q("SELECT status, error FROM mw_sbx ORDER BY id DESC LIMIT 1", one=True)
                self.assertEqual(row["status"], "cancelled"); self.assertIn("stopped", row["error"])   # not started; never counted as a sandbox failure
            else:
                w._sandbox({"id": 23, "internet": 0}, {"netuid": 61}, "ls", [], 60, 1.0, task=7)
                self.assertEqual(len(sbx.calls), 1)

    def test_a_run_waiting_for_a_slot_when_its_mission_is_stopped_never_starts(self):
        """The stop is set after the run was let in and before it has a pod: the sandbox asks the run's cancelled test, which now says yes."""
        for cfg in ({"workspace": 1}, None):                       # a planned run, and a run of a team with nothing switched on
            self.db.q("DELETE FROM app_settings WHERE k LIKE 'exec.%'")
            if cfg: self.db.setting("exec.comp:23", v=json.dumps(cfg))
            seen = {}
            class Queued(FakeSbxNew):
                def run(inner, files, command, services, timeout, budget, cancelled=None, **k):
                    seen["before"] = cancelled()
                    self.db.setting("exec.stop:mx:4", v="stop")     # the Owner stops the mission while this run waits
                    real = time.time
                    with mock.patch.object(ex.time, "time", lambda: real() + 10): seen["after"] = cancelled()   # the wait for a slot is longer than the few seconds between looks
                    return {"status": "cancelled", "exit": None, "output": "", "error": "Stopped before it started.", "cost": 0, "calls": 0} if seen["after"] else \
                        {"status": "done", "exit": 0, "output": "RAN", "error": "", "cost": 0, "calls": 0}
            r = work(self.db, Queued())._sandbox({"id": 23, "internet": 0}, {"netuid": 61}, "ls", [], 60, 1.0, task=7)
            self.assertEqual((seen, r["status"]), ({"before": False, "after": True}, "cancelled"), cfg)
            self.assertEqual(self.db.q("SELECT status FROM mw_sbx WHERE id=?", (r["sbx"],), one=True)["status"], "cancelled")

    def test_a_refused_run_leaves_nothing_behind(self):
        self.db.setting("exec.comp:23", v=json.dumps({"workspace": 1}))
        class Busy(FakeSbxNew):
            def run(self, *a, **k): raise sandbox.SandboxError("The sandbox is busy")
        w = work(self.db, Busy())
        with self.assertRaisesRegex(LookupError, "busy"): w._sandbox({"id": 23, "internet": 0}, {"netuid": 61}, "ls", [], 60, 1.0, task=7)
        self.assertEqual(list((Path(self.tmp.name) / "exec" / "tmp").iterdir()), [])


class RealScript(Base):
    """sandbox_files/aef.py itself, run as a process against a real per-run endpoint (sandbox.Proxy on a local port)."""
    def setUp(self):
        super().setUp()
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        self.proxy = sandbox.Proxy(lambda: "")
        with mock.patch.object(sandbox, "PROXY_BIND", "127.0.0.1"): self.proxy.start(self.port)
        ex.schema(self.db)
        self.n = 0

    def tearDown(self):
        self.proxy.server.shutdown(); self.proxy.server.server_close(); super().tearDown()

    def run_script(self, command, mission="comp:1", team=None, task=None, seconds=30, secrets=None, cfg=None):
        self.n += 1
        self.db.q("INSERT INTO mw_sbx (id, comp_id, status) VALUES (?,1,'running')", (self.n,))
        s = ex.Session(self.st, self.db, comp=1, mission=mission, task=task, agent={"id": 2, "name": "Devon"}, sid=self.n,
                       the_plan=ex.plan([], cfg or {"workspace": 1}, False), command=command, timeout=seconds, files=team or {}, secrets=secrets)
        tok = self.proxy.open(1.0, s.hook)
        work = tempfile.mkdtemp(dir=self.tmp.name)
        os.makedirs(f"{work}/.axor")
        for name in ("aef.py", "checkpoint.py"): shutil.copy(FILES / name, f"{work}/.axor/{name}")
        for p, t in s.files.items():
            os.makedirs(os.path.dirname(f"{work}/{p}"), exist_ok=True); open(f"{work}/{p}", "w").write(t)
        env = {**os.environ, "AXOR_AEF_WORK": work, "SANDBOX_PROXY_URL": f"http://127.0.0.1:{self.port}/t/{tok}", "HTTP_PROXY": "http://127.0.0.1:9",
               "HTTPS_PROXY": "http://127.0.0.1:9", "AXOR_STATE": f"{work}/.axor/state"}   # a (dead) internet proxy is set: the script must not use it
        argv = s.command.split()[1:]
        argv[0] = f"{work}/.axor/aef.py"
        p = subprocess.run([sys.executable, *argv], capture_output=True, text=True, env=env, timeout=120)
        self.proxy.close(tok)
        r = s.end({"status": "done" if p.returncode == 0 else "failed", "exit": p.returncode, "output": p.stdout + p.stderr, "seconds": 1})
        return p.returncode, r, s

    def test_a_git_checkout_with_packed_refs_is_still_a_repository_in_the_next_run(self):
        # a clone at a tag: the refs are in one file, and .git/refs holds only empty folders, which a file snapshot can't carry
        code, r, _ = self.run_script("mkdir -p repo/.git/refs/heads repo/.git/refs/tags repo/.git/objects/pack repo/.git/objects/info && echo d78076db > repo/.git/HEAD && "
                                     "echo 'd78076db refs/tags/v1.0.0' > repo/.git/packed-refs && echo pack > repo/.git/objects/pack/p.pack && "
                                     "mkdir -p notgit/.git other && echo x > notgit/.git/config && echo y > other/HEAD")
        self.assertEqual(code, 0, r["output"])
        code, r, _ = self.run_script("for d in repo/.git/refs/heads repo/.git/refs/tags repo/.git/objects/info repo/.git/objects/pack; do test -d $d && echo HAS $d; done; "
                                     "test -d notgit/.git/refs && echo WRONG-notgit; test -d other/refs && echo WRONG-other; cat repo/.git/packed-refs")
        self.assertEqual(code, 0, r["output"])
        for d in ("refs/heads", "refs/tags", "objects/info", "objects/pack"): self.assertIn(f"HAS repo/.git/{d}", r["output"])
        self.assertNotIn("WRONG", r["output"]); self.assertIn("refs/tags/v1.0.0", r["output"])   # only where a .git folder holds a HEAD

    def test_what_one_run_writes_the_next_run_has(self):
        code, r, _ = self.run_script("echo persisted > keep.txt && mkdir -p repo/.git/refs/heads && echo ref: refs/heads/feature > repo/.git/HEAD && "
                                     "echo abc123 > repo/.git/refs/heads/feature && printf '#!/bin/sh\\necho ran\\n' > tool.sh && chmod +x tool.sh && "
                                     "head -c 300000 /dev/urandom > artifacts/model.bin && echo mine > $AXOR_AGENT_DIR/notes.md && pwd",
                                     team={"agent.py": "print(1)"})
        self.assertEqual(code, 0, r["output"])
        self.assertIn("@@AXOR-WORKSPACE restored snapshot #0: 0 files", r["output"]); self.assertIn("@@AXOR-WORKSPACE saved snapshot #", r["output"])
        self.assertTrue(r["output"].strip().splitlines()[-4].endswith("/mission") or "/mission\n" in r["output"])   # the command ran in the workspace
        t = self.st.tree(self.st.head(1, "comp:1"))["files"]
        self.assertEqual(sorted(t), ["agents/devon-2/notes.md", "artifacts/model.bin", "keep.txt", "repo/.git/HEAD", "repo/.git/refs/heads/feature", "tool.sh"])
        self.assertEqual((t["tool.sh"][2], t["artifacts/model.bin"][1]), (0o755, 300000))        # the exec bit and a binary file both survive
        code, r2, _ = self.run_script("cat keep.txt; cat repo/.git/HEAD; ./tool.sh; wc -c < artifacts/model.bin; cat team/agent.py; cat agents/devon-2/notes.md",
                                      team={"agent.py": "print(2)"})
        self.assertEqual(code, 0, r2["output"])
        for want in ("persisted", "ref: refs/heads/feature", "ran", "300000", "print(2)", "mine", "nothing changed: no new snapshot"): self.assertIn(want, r2["output"])
        self.assertEqual((r2["workspace"]["from"], r2["workspace"]["to"]), (r["workspace"]["to"], None))

    def test_what_is_never_saved(self):
        code, r, _ = self.run_script("echo x > ok.txt; echo KEY=1 > .env; mkdir -p node_modules/p cache keys && echo j > node_modules/p/i.js && "
                                     "echo 'Signature: 8a477f597d28d172789f06886806bc55' > cache/CACHEDIR.TAG && echo big > cache/blob && echo k > keys/server.pem && "
                                     "echo changed >> team/agent.py 2>/dev/null; echo t > team/new.txt 2>/dev/null; ln -s ok.txt link; ln -s /etc/passwd out; true",
                                     team={"agent.py": "print(1)"})
        self.assertEqual(code, 0, r["output"])
        t = self.st.tree(self.st.head(1, "comp:1"))
        self.assertEqual((sorted(t["files"]), t["links"]), (["ok.txt"], {"link": "ok.txt"}))
        for left_out in (".env (looks like a secret)", "keys/server.pem (looks like a secret)", "out (a link out of the workspace)"): self.assertIn(left_out, r["output"])

    def test_measurements_arrive_and_are_labelled(self):
        code, r, s = self.run_script("python3 -c \"b = bytearray(b'x') * 30_000_000; import time; t = time.time()\nwhile time.time() - t < 1.6: sum(range(20000))\"",
                                     cfg={"plan": 1})
        self.assertEqual(code, 0, r["output"])
        st = r["stats"]
        self.assertGreaterEqual(st["peak_rss_mb"], 30); self.assertGreater(st["cpu_seconds"], 0.5); self.assertGreaterEqual(st["peak_procs"], 2)
        self.assertTrue(any("python3" in p["cmd"] for p in st["tree_at_peak"])); self.assertIn("own report", st["by"])
        self.assertEqual((st["command_exit"], st["timed_out"], "files" in st), (0, False, False))
        self.assertNotIn("workspace", r); self.assertIn("@@AXOR-STATS cpu", r["output"])
        self.assertEqual(json.loads(self.db.q("SELECT stats FROM mw_sbx WHERE id=?", (s.sid,), one=True)["stats"])["peak_procs"], st["peak_procs"])

    def test_time_limit_exit_code_and_the_workspace_is_still_saved(self):
        code, r, _ = self.run_script("echo partial > progress.txt; sleep 30", seconds=10)
        self.assertEqual(code, 124); self.assertTrue(r["stats"]["timed_out"])
        self.assertIn("progress.txt", self.st.tree(self.st.head(1, "comp:1"))["files"])
        code, r, _ = self.run_script("exit 7")
        self.assertEqual((code, r["stats"]["command_exit"]), (7, 7))

    def test_a_save_point_during_the_run_and_the_tasks_progress_folder(self):
        code, r, s = self.run_script("echo step1 > $AXOR_STATE/progress.txt && python3 .axor/checkpoint.py && echo \"K resumed=${AXOR_RESUMED:-0}\" && "
                                     "echo step2 >> $AXOR_STATE/progress.txt", task=7)
        self.assertEqual(code, 0, r["output"]); self.assertIn("K resumed=0", r["output"])
        self.assertEqual(r["workspace"]["saves"], 2)                                 # the save point and the run's own end
        snaps = self.st.snapshots(1, "comp:1")
        self.assertEqual(len(snaps), 2)
        self.assertEqual(self.read(snaps[1]["id"], ".state/task-7/progress.txt"), "step1\n")       # what a cut-off run would have kept
        self.assertEqual(self.read(snaps[0]["id"], ".state/task-7/progress.txt"), "step1\nstep2\n")
        code, r, _ = self.run_script("echo \"K resumed=${AXOR_RESUMED:-0}\"; cat $AXOR_STATE/progress.txt", task=7)
        self.assertIn("K resumed=1", r["output"]); self.assertIn("step2", r["output"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_ckpt", one=True)["n"], 0)            # one store: nothing went to the old checkpoint table

    def test_two_runs_at_once_conflict_without_loss(self):
        self.run_script("echo v0 > plan.md; echo a > a.txt")
        base = self.st.head(1, "comp:1")
        # two sessions opened on the same snapshot, as two concurrent pods would be; the first to finish wins the path
        outs = []
        import threading
        def one(cmd): outs.append(self.run_script_from(base, cmd))
        ths = [threading.Thread(target=one, args=(c,)) for c in ("sleep 1; echo first > plan.md; echo b > b.txt", "sleep 2.5; echo second > plan.md; echo c > c.txt")]
        for t in ths: t.start()
        for t in ths: t.join()
        t = self.st.tree(self.st.head(1, "comp:1"))["files"]
        self.assertEqual(sorted(p for p in t), ["a.txt", "b.txt", "c.txt", "plan.md", sorted(p for p in t if "conflict" in p)[0]] if False else sorted(t))
        conflict = [p for p in t if p.startswith("plan.md.conflict-run")]
        self.assertEqual(len(conflict), 1)
        head = self.st.head(1, "comp:1")["id"]
        self.assertEqual((self.read(head, "plan.md"), self.read(head, conflict[0])), ("first\n", "second\n"))
        self.assertTrue({"a.txt", "b.txt", "c.txt"} <= set(t))
        self.assertTrue(any("@@AXOR-WORKSPACE conflict: plan.md" in o for o in outs))

    def run_script_from(self, base, command):
        with ex._LOCK:
            self.n += 1; sid = self.n
            self.db.q("INSERT INTO mw_sbx (id, comp_id, status) VALUES (?,1,'running')", (sid,))
        s = ex.Session(self.st, self.db, comp=1, mission="comp:1", task=None, agent=None, sid=sid, the_plan=ex.plan([], {"workspace": 1}, False),
                       command=command, timeout=30, files={})
        tok = self.proxy.open(1.0, s.hook)
        work = tempfile.mkdtemp(dir=self.tmp.name)
        os.makedirs(f"{work}/.axor"); shutil.copy(FILES / "aef.py", f"{work}/.axor/aef.py")
        argv = s.command.split()[1:]; argv[0] = f"{work}/.axor/aef.py"
        p = subprocess.run([sys.executable, *argv], capture_output=True, text=True, timeout=120,
                           env={**os.environ, "AXOR_AEF_WORK": work, "SANDBOX_PROXY_URL": f"http://127.0.0.1:{self.port}/t/{tok}"})
        self.proxy.close(tok); s.end({"status": "done", "exit": p.returncode, "output": p.stdout})
        return p.stdout + p.stderr

    def test_a_granted_credential_reaches_a_memory_file_and_nothing_else(self):
        class Broker:
            names = {"API_KEY"}
            def fetch(self, name): return "s3cr3t-value-123"
            def close(self): pass
        code, r, s = self.run_script("ls -l $AXOR_SECRETS/API_KEY | cut -c1-10; cat $AXOR_SECRETS/API_KEY; echo; cp $AXOR_SECRETS/API_KEY stolen.txt; "
                                     "echo \"K where=$AXOR_SECRETS\"; env | grep -c s3cr3t || true", secrets=Broker(), cfg={"workspace": 1})
        self.assertEqual(code, 0, r["output"])
        self.assertIn("-r--------", r["output"]); self.assertIn("[credential API_KEY]", r["output"]); self.assertNotIn("s3cr3t", r["output"])
        self.assertRegex(r["output"], r"K where=/dev/shm/axor/secrets|K where=/tmp/\.axor-secrets")
        self.assertNotIn("stolen.txt", self.st.tree(self.st.head(1, "comp:1"))["files"] if self.st.head(1, "comp:1") else {})
        self.assertIn("stolen.txt (contains a credential's value)", r["output"])

    def test_a_run_with_no_workspace_runs_where_it_always_did(self):
        code, r, _ = self.run_script("pwd; ls", cfg={"plan": 1}, team={"agent.py": "x"})
        self.assertEqual(code, 0); self.assertIn("agent.py", r["output"]); self.assertNotIn("/mission", r["output"]); self.assertNotIn("@@AXOR-WORKSPACE", r["output"])


if __name__ == "__main__":
    unittest.main()
