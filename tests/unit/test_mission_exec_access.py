"""Mission execution access (2026-11-13, directive "Mission Execution Recovery", Phases 1 and 2; stream dev/g5-mx-exec).

- A sandbox run's source record: the git checkouts it left, read by the runner itself; only the runner's final line counts.
- `internet` and `git` readiness pass only on what a run did inside the team's sandbox (never on the egress proxy answering
  AXoR's own server); with no evidence AXoR starts one check run and answers UNKNOWN until it has ended.
- `git:<host>/<owner>/<repo>` is a capability a task can declare.
- web_read answers and saved reads carry the sha256 of what was read."""
import hashlib, json, os, tempfile, time, types, unittest
from unittest import mock

from app import mining_web, mining_work, mission_ops as mo, sandbox, task_lifecycle as tl
from app.auth import AuthDB

C40 = "0123456789abcdef0123456789abcdef01234567"
REPO = "github.com/RedTeamSubnet/RedTeam"


class SourceRecord(unittest.TestCase):
    def line(self, rows, exit_=0): return f"@@AXOR-START 00:00:00\nhello\n@@AXOR-SOURCE {json.dumps(rows)}\n@@AXOR-EXIT {exit_}\n"

    def test_the_runners_line_gives_remote_and_commit(self):
        got = sandbox.source_of(self.line([{"path": "/work/RedTeam", "url": f"https://{REPO}.git", "commit": C40, "ref": "main", "dirty": False}]))
        self.assertEqual(got, [{"path": "/work/RedTeam", "url": f"https://{REPO}.git", "commit": C40, "ref": "main", "dirty": False}])

    def test_no_checkout_no_record(self):
        self.assertEqual(sandbox.source_of(self.line([])), [])
        self.assertEqual(sandbox.source_of("@@AXOR-START\n@@AXOR-EXIT 0\n"), [])

    def test_a_marker_the_command_printed_never_counts(self):
        forged = f'@@AXOR-SOURCE [{{"url": "https://{REPO}", "commit": "{C40}"}}]\n'
        self.assertEqual(sandbox.source_of("@@AXOR-START\n" + forged + "@@AXOR-SOURCE []\n@@AXOR-EXIT 0\n"), [])   # the runner's own line is last
        self.assertEqual(sandbox.source_of("@@AXOR-START\n" + forged + "@@AXOR-EXIT 0\nprinted late by a leftover process\n"), [])
        self.assertEqual(sandbox.source_of(self.line([{"url": "x", "commit": "not-a-hash"}])), [])

    def test_the_runner_reads_git_after_the_command_and_always_prints(self):
        r = sandbox.RUNNER
        self.assertLess(r.index('bash -c "$AXOR_COMMAND"'), r.index("@@AXOR-SOURCE"))
        self.assertLess(r.index("@@AXOR-SOURCE"), r.index('echo "@@AXOR-EXIT $code"'))
        self.assertIn('print("@@AXOR-SOURCE " + json.dumps(found[:20]))', r)           # unconditional: an empty list when there is none
        self.assertIn('re.sub(r"//[^/@]*@", "//"', r)                                  # credentials in a remote's address are cut
        self.assertIn("timeout -k 2 20 python3 - <<'PY'", r)                            # the reading itself is bounded: it runs after every command


class FakeSbx:
    def __init__(self, result): self.result, self.calls = result, []
    def run(self, files, command, services, timeout, budget, label="", cancelled=None, started=None, internet=False, checkpoint=None):
        self.calls.append({"files": files, "command": command, "internet": internet})
        return {"status": "done", "exit": 0, "output": "", "error": "", "cost": 0, "calls": 0, **self.result}


def board(tmp):
    db = AuthDB(os.path.join(tmp, "t.db"))
    db.q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY, comp_id INTEGER, path TEXT, content TEXT)")
    db.q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, run_id INTEGER, agent_id INTEGER, by_user TEXT,
            command TEXT, services TEXT, status TEXT, exit_code INTEGER, output TEXT, error TEXT, started REAL, finished REAL, cost REAL, calls INTEGER,
            pod TEXT, net TEXT, src TEXT)""")
    db.q("""CREATE TABLE mw_ckpt (comp_id INTEGER, task_id INTEGER, data TEXT, bytes INTEGER, sbx_id INTEGER, agent_id INTEGER, saved REAL,
            PRIMARY KEY (comp_id, task_id))""")
    return db


def work(db, sbx):
    w = object.__new__(mining_work.Work)
    w.db, w.sbx = db, sbx
    w._event = lambda *a, **k: None
    w._label = lambda c: "Competition 1"
    w._ins = lambda sql, args: db.q(sql + " RETURNING id", args, one=True)["id"]
    w.m = types.SimpleNamespace(_campaign=lambda cid: {"id": 1, "netuid": 61})
    return w


class RunKeepsItsSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name)
        self.src = [{"path": "/work/RedTeam", "url": f"https://{REPO}", "commit": C40, "ref": "main", "dirty": False}]

    def tearDown(self): self.tmp.cleanup()

    def test_the_run_row_holds_the_checkouts_and_the_result_names_the_run(self):
        w = work(self.db, FakeSbx({"source": self.src, "net": {"hosts": {"github.com": 1}}}))
        r = w._sandbox({"id": 23, "internet": 1}, {"netuid": 61}, f"git clone https://{REPO}", [], 600, 1.0, task=7, agent={"id": 2, "name": "Devon"})
        row = self.db.q("SELECT * FROM mw_sbx WHERE id=?", (r["sbx"],), one=True)
        self.assertEqual(json.loads(row["src"]), self.src)
        self.assertEqual((row["status"], row["task_id"], row["agent_id"]), ("done", 7, 2))

    def test_the_agent_gets_the_run_and_the_commits_not_the_paths(self):
        many = [{"path": f"/work/r{i}", "url": f"https://github.com/o/r{i}", "commit": C40, "ref": "main", "dirty": bool(i % 2)} for i in range(12)]
        b = mining_work.source_brief({"sbx": 41, "source": many})
        self.assertEqual((b["run"], len(b["checkouts"])), ("sbx:41", 8))
        self.assertEqual(b["checkouts"][1], {"url": "https://github.com/o/r1", "commit": C40, "ref": "main", "dirty": True})

    def test_a_run_without_checkouts_leaves_the_column_empty(self):
        w = work(self.db, FakeSbx({}))
        r = w._sandbox({"id": 23, "internet": 0}, {"netuid": 61}, "ls", [], 60, 1.0, user="leo")
        self.assertIsNone(self.db.q("SELECT src FROM mw_sbx WHERE id=?", (r["sbx"],), one=True)["src"])


class FakeEgress:
    def __init__(self, ready=True): self.ready = ready
    def status(self, fresh=False): return {"ready": self.ready, "why": "" if self.ready else "The egress proxy doesn't answer", "gvisor": True}


class ReachProbes(unittest.TestCase):
    def setUp(self):
        mo._probe_cache.clear(); mo._net_checks.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name)
        self.sbx = types.SimpleNamespace(kube=None, egress=FakeEgress(True), ready=lambda: (True, ""))
        self.started = []
        self.ch = types.SimpleNamespace(db=self.db, w=types.SimpleNamespace(sbx=self.sbx), _has=lambda t: True)
        self.comp = {"id": 23, "campaign_id": 1, "internet": 1}
        p = mock.patch.object(mo, "_start_net_check", lambda ch, comp, cmd: self.started.append(cmd) or True)
        p.start(); self.addCleanup(p.stop)

    def tearDown(self): self.tmp.cleanup()

    def probe(self, cap, value=None, comp=None): return mo.probe(self.ch, comp or self.comp, cap, value, fresh=True)

    def run_row(self, by="Devon", command="pip install x", status="done", net=None, src=None, output="", age=60, comp=23):
        self.db.q("""INSERT INTO mw_sbx (comp_id, by_user, command, status, exit_code, output, started, finished, net, src) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (comp, by, command, status, 0 if status == "done" else 1, output, time.time() - age - 5, time.time() - age,
                   json.dumps(net) if net is not None else None, json.dumps(src) if src is not None else None))

    # ---- internet
    def test_a_healthy_proxy_alone_is_not_proof(self):
        p = self.probe("internet")
        self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("isn't proof for a run", p["evidence"])
        self.assertEqual(self.started, [mo.NET_CHECK_CMD])                           # AXoR starts its own check inside the sandbox

    def test_passes_on_a_run_that_reached_a_host_from_inside(self):
        self.run_row(net={"hosts": {"github.com": 2, "pypi.org": 1}, "connections": 3})
        p = self.probe("internet")
        self.assertEqual(p["state"], "PASS"); self.assertIn("github.com", p["evidence"]); self.assertIn("inside the sandbox", p["evidence"])
        self.assertEqual(self.started, [])

    def test_a_run_that_reached_nothing_or_another_teams_run_or_an_old_run_is_no_evidence(self):
        self.run_row(net={"hosts": {}, "connections": 0})                            # had internet, used none
        self.run_row(net={"hosts": {"github.com": 1}}, comp=22)                      # another team's sandbox
        self.run_row(net={"hosts": {"github.com": 1}}, age=mo.PROBE_RECENT + 3600)   # too long ago
        self.assertEqual(self.probe("internet")["state"], "UNKNOWN")

    def test_the_check_run_reaching_nothing_is_a_measured_failure(self):
        self.run_row(by=mo.NET_CHECK_USER, command=mo.NET_CHECK_CMD, status="failed", net={"hosts": {}},
                     output="@@AXOR-NETCHECK internet\nhttps://github.com FAILED curl: (56) CONNECT tunnel failed, response 403\n")
        p = self.probe("internet")
        self.assertEqual(p["state"], "FAIL"); self.assertIn("reached no host", p["evidence"]); self.assertIn("CONNECT tunnel failed", p["evidence"])
        self.assertEqual(self.started, [])                                           # it has its answer: no second run

    def test_a_check_run_that_never_ran_is_no_answer(self):
        for status in ("error", "timeout", "cancelled"):                             # sandbox busy, a restart, the cluster refused it
            self.run_row(by=mo.NET_CHECK_USER, command=mo.NET_CHECK_CMD, status=status, net=None, output="")
            self.run_row(by=mo.NET_CHECK_USER, command=mo._git_check_cmd(REPO), status=status, net=None, output="")
        self.assertEqual(self.probe("internet")["state"], "UNKNOWN")                 # not "reached no host"
        self.assertEqual(self.probe("git", REPO)["state"], "UNKNOWN")
        self.assertEqual(self.started, [mo.NET_CHECK_CMD, mo._git_check_cmd(REPO)])  # and it measures again

    def test_a_failed_check_stands_for_a_while_then_is_measured_again(self):
        old = mo.NET_FAIL_HOLD + 60
        self.run_row(by=mo.NET_CHECK_USER, command=mo.NET_CHECK_CMD, status="failed", net={"hosts": {}}, output="https://github.com FAILED x\n", age=old)
        self.run_row(by=mo.NET_CHECK_USER, command=mo._git_check_cmd(REPO), status="failed", output="fatal: unable to access: 503\n", age=old)
        self.assertEqual(self.probe("internet")["state"], "UNKNOWN")                 # a blip an hour ago doesn't hold the team for days
        self.assertEqual(self.probe("git", REPO)["state"], "UNKNOWN")
        self.assertEqual(len(self.started), 2)
        self.run_row(by=mo.NET_CHECK_USER, command=mo._git_check_cmd(REPO), status="failed", output="fatal: unable to access: 503\n", age=30)
        self.assertEqual(self.probe("git", REPO)["state"], "FAIL")                   # the new measurement is the answer again

    def test_the_switch_and_the_proxy_still_come_first(self):
        self.run_row(net={"hosts": {"github.com": 1}})
        self.assertEqual(self.probe("internet", comp={"id": 23, "internet": 0})["state"], "FAIL")
        self.sbx.egress = FakeEgress(False)
        self.assertEqual(self.probe("internet")["state"], "FAIL")                    # past evidence doesn't outlive a proxy that is down now

    # ---- git
    def test_git_names_one_repository(self):
        self.assertEqual(self.probe("git", "github.com/only-owner")["state"], "FAIL")
        self.assertEqual(self.probe("git", None)["state"], "FAIL")

    def test_git_unknown_starts_ls_remote_inside_the_sandbox(self):
        p = self.probe("git", REPO)
        self.assertEqual(p["state"], "UNKNOWN")
        self.assertEqual(self.started, [f'echo "@@AXOR-NETCHECK git {REPO}"; git ls-remote https://{REPO} HEAD'])

    def test_git_passes_on_a_run_that_checked_it_out_with_the_commit(self):
        self.run_row(command=f"git clone https://{REPO}.git", net={"hosts": {"github.com": 1}},
                     src=[{"path": "/work/RedTeam", "url": f"https://{REPO}.git", "commit": C40, "ref": "main", "dirty": False}])
        p = self.probe("git", REPO)
        self.assertEqual(p["state"], "PASS"); self.assertIn(C40[:12], p["evidence"])
        self.assertEqual(self.probe("git", "github.com/other/repo")["state"], "UNKNOWN")   # evidence is per repository

    def test_a_declared_source_is_not_proof_of_reach(self):
        # a Docker job (V4.2) writes the commit its submitter declared into the same column, marked basis "declared": nobody read it from git
        self.run_row(command="docker_job build", src=[{"path": "", "url": f"https://{REPO}", "commit": C40, "ref": None, "dirty": None, "basis": "declared"}])
        self.assertEqual(self.probe("git", REPO)["state"], "UNKNOWN")
        self.run_row(command=f"git clone https://{REPO}", src=[{"path": "/work/x", "url": f"https://{REPO}", "commit": C40, "ref": "main", "dirty": False}])
        self.assertEqual(self.probe("git", REPO)["state"], "PASS")

    def test_git_passes_or_fails_on_the_check_runs_own_output(self):
        cmd = mo._git_check_cmd(REPO)
        self.run_row(by=mo.NET_CHECK_USER, command=cmd, status="done", output=f"@@AXOR-NETCHECK git {REPO}\n{C40}\tHEAD\n@@AXOR-SOURCE []\n@@AXOR-EXIT 0\n")
        p = self.probe("git", REPO)
        self.assertEqual(p["state"], "PASS"); self.assertIn(C40[:12], p["evidence"])
        private = "github.com/owner/private-repo"
        self.run_row(by=mo.NET_CHECK_USER, command=mo._git_check_cmd(private), status="failed",
                     output="fatal: could not read Username for 'https://github.com': terminal prompts disabled\n@@AXOR-EXIT 128\n")
        p = self.probe("git", private)
        self.assertEqual(p["state"], "FAIL"); self.assertIn("no repository credentials", p["evidence"])

    def test_git_needs_the_teams_internet(self):
        self.assertEqual(self.probe("git", REPO, comp={"id": 23, "internet": 0})["state"], "FAIL")


class CheckRun(unittest.TestCase):
    """The real _start_net_check: one background run in the team's sandbox, by AXoR, without the team's files, at most once per window."""
    def setUp(self):
        mo._net_checks.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name)
        self.db.q("INSERT INTO mw_files (comp_id, path, content) VALUES (23, 'miner/app.py', 'x')")
        self.fake = FakeSbx({"net": {"hosts": {"github.com": 1}}})
        self.ch = types.SimpleNamespace(db=self.db, w=work(self.db, self.fake), _has=lambda t: True)
        self.comp = {"id": 23, "campaign_id": 1, "internet": 1}

    def tearDown(self): self.tmp.cleanup()

    def wait(self):
        for _ in range(100):
            if self.db.q("SELECT 1 FROM mw_sbx WHERE status='done' LIMIT 1", one=True): return
            time.sleep(0.02)

    def test_one_run_by_axor_with_no_team_files_then_none_for_a_while(self):
        self.assertTrue(mo._start_net_check(self.ch, self.comp, mo.NET_CHECK_CMD)); self.wait()
        row = self.db.q("SELECT * FROM mw_sbx", one=True)
        self.assertEqual((row["by_user"], row["command"], row["comp_id"], row["status"]), (mo.NET_CHECK_USER, mo.NET_CHECK_CMD, 23, "done"))
        self.assertEqual(self.fake.calls[0]["files"], {}); self.assertTrue(self.fake.calls[0]["internet"])
        self.assertFalse(mo._start_net_check(self.ch, self.comp, mo.NET_CHECK_CMD))  # started lately here
        mo._net_checks.clear()
        self.assertFalse(mo._start_net_check(self.ch, self.comp, mo.NET_CHECK_CMD))  # another replica sees the row
        self.assertEqual(len(self.fake.calls), 1)

    def test_switched_off_or_no_board_starts_nothing(self):
        with mock.patch.object(mo, "NET_CHECK", False): self.assertFalse(mo._start_net_check(self.ch, self.comp, mo.NET_CHECK_CMD))
        self.assertFalse(mo._start_net_check(types.SimpleNamespace(db=self.db, w=types.SimpleNamespace(sbx=None)), self.comp, mo.NET_CHECK_CMD))
        self.assertEqual(self.fake.calls, [])

    def test_the_probe_reads_the_check_runs_result_on_the_next_pass(self):
        mo._probe_cache.clear()
        self.ch.w.sbx.egress, self.ch.w.sbx.kube = FakeEgress(True), None
        self.assertEqual(mo.probe(self.ch, self.comp, "internet", fresh=True)["state"], "UNKNOWN"); self.wait()
        self.assertEqual(mo.probe(self.ch, self.comp, "internet", fresh=True)["state"], "PASS")


class GitNeed(unittest.TestCase):
    def test_declared_git_names_host_owner_repo(self):
        self.assertEqual(tl.parse_needs([f"git:{REPO}", "internet"]), [f"git:{REPO}", "internet"])
        for bad in ("git", "git:github.com/owner", "git:not a repo"):
            with self.assertRaises(ValueError): tl.parse_needs([bad])
        self.assertEqual(tl.git_repo("GitHub.com/Owner/Repo.git"), "github.com/Owner/Repo")
        self.assertIsNone(tl.git_repo("github.com/owner/../etc"))

    def test_a_clone_in_the_words_suggests_its_repository(self):
        got = {(n["cap"], n["value"]) for n in tl.infer_needs(f"Build the miner\nRun git clone --depth 1 https://{REPO}.git and run its tests")}
        self.assertIn(("git", REPO), got); self.assertIn(("internet", None), got)
        self.assertNotIn("git", {n["cap"] for n in tl.infer_needs("Tidy the notes\nUse git to see what changed")})

    def test_planners_may_declare_it_and_there_is_a_probe_and_a_remedy(self):
        self.assertEqual(tl.planner_needs({"needs": [f"git:{REPO}"]}), (json.dumps([f"git:{REPO}"]), 2))
        self.assertIn("git", mo._PROBES); self.assertIn("git", mo.REMEDY); self.assertIn("git:<host>/<owner>/<repo>", tl.NEEDS_RULE)


class WebReadHash(unittest.TestCase):
    def test_saved_reads_carry_the_hash_of_what_was_read(self):
        body = b'{"rows": [1, 2, 3]}'
        page = {"url": "https://example.org/a.json", "final": "https://example.org/a.json", "fetched_at": "2026-11-13 05:00:00 UTC",
                "sha256": hashlib.sha256(body).hexdigest()}
        web = object.__new__(mining_web.Web)
        doc = json.loads(web._file(page, "a", "", text="hello"))
        self.assertEqual((doc["sha256"], doc["fetched_at"], doc["source"]), (page["sha256"], page["fetched_at"], page["final"]))
        doc = json.loads(web._file(page, "a", "rows", rows=[{"a": 1}]))
        self.assertEqual(doc["sha256"], page["sha256"])

    def test_fetch_hashes_the_bytes_it_read(self):
        import inspect
        src = inspect.getsource(mining_web.fetch)
        self.assertIn('"sha256": hashlib.sha256(data[:PAGE_BYTES]).hexdigest()', src)


class ReachClasses(unittest.TestCase):
    """Consolidated directive C1: what failed is one of separate classes. A private repository is not a broken git."""
    CASES = [
        (128, "fatal: could not read Username for 'https://github.com': No such device or address", "failed", "private"),
        (128, "fatal: could not read Username for 'https://github.com': terminal prompts disabled", "failed", "private"),
        (128, "remote: Repository not found.\nfatal: repository 'https://github.com/o/r/' not found", "failed", "private"),
        (128, "fatal: Authentication failed for 'https://github.com/o/r/'", "failed", "credentials"),
        (128, "fatal: unable to access 'https://10.0.0.5/o/r/': CONNECT tunnel failed, response 403", "failed", "policy"),
        (1, "https://github.com FAILED curl: (56) CONNECT tunnel failed, response 407", "failed", "no_internet"),
        (128, "fatal: unable to access 'https://github.com/o/r/': Could not resolve host: github.com", "failed", "dns"),
        (128, "fatal: unable to access 'https://x.invalid/o/r/': CONNECT tunnel failed, response 502", "failed", "connection"),
        (1, "curl: (7) Failed to connect to github.com port 443 after 3 ms: Connection refused", "failed", "connection"),
        (127, "bash: line 1: git: command not found", "failed", "no_executable"),
        (124, "", "timeout", "timeout"),
        (2, "make: *** No rule to make target 'all'.  Stop.", "failed", "failed"),      # a real execution failure, nothing to do with reach
        (0, f"{C40}\tHEAD", "done", "ok"),
    ]

    def test_each_failure_has_its_own_class(self):
        for code, out, status, want in self.CASES:
            self.assertEqual(sandbox.reach_class(code, out, status), want, out)
        self.assertEqual(set(c[3] for c in self.CASES), set(sandbox.REACH))             # every class is exercised and described

    def test_a_clean_exit_is_ok_whatever_it_printed(self):
        self.assertEqual(sandbox.reach_class(0, "warning: could not read Username (ignored)", "done"), "ok")

    def test_the_check_runs_user_is_one_name(self):
        self.assertEqual(mo.NET_CHECK_USER, sandbox.READINESS_USER)


class ProbeSaysWhatFailed(ReachProbes):
    def fail(self, repo, output, code=128):
        self.run_row(by=mo.NET_CHECK_USER, command=mo._git_check_cmd(repo), status="failed", output=output + f"\n@@AXOR-EXIT {code}\n", age=30)
        self.db.q("UPDATE mw_sbx SET exit_code=? WHERE id=(SELECT max(id) FROM mw_sbx)", (code,))
        return self.probe("git", repo)

    def test_a_private_repository_is_not_a_broken_git(self):
        p = self.fail("github.com/owner/private-repo", "fatal: could not read Username for 'https://github.com': terminal prompts disabled")
        self.assertEqual((p["state"], p["reach"]), ("FAIL", "private"))
        self.assertIn("Git and the network work", p["evidence"]); self.assertIn("no repository credentials", p["evidence"])

    def test_a_refused_host_a_dead_connection_and_a_missing_git_each_say_so(self):
        p = self.fail("github.com/o/policy", "fatal: unable to access 'https://github.com/o/policy/': CONNECT tunnel failed, response 403")
        self.assertEqual(p["reach"], "policy"); self.assertIn("egress proxy refused", p["evidence"])
        p = self.fail("github.com/o/conn", "fatal: unable to access 'https://github.com/o/conn/': CONNECT tunnel failed, response 502")
        self.assertEqual(p["reach"], "connection"); self.assertNotIn("private", p["evidence"])
        p = self.fail("github.com/o/nogit", "bash: line 1: git: command not found", code=127)
        self.assertEqual(p["reach"], "no_executable"); self.assertIn("isn't in the sandbox image", p["evidence"])

    def test_success_is_marked_too(self):
        self.run_row(by=mo.NET_CHECK_USER, command=mo._git_check_cmd(REPO), status="done", output=f"{C40}\tHEAD\n")
        self.assertEqual(self.probe("git", REPO)["reach"], "ok")

    def test_the_internet_check_says_why_nothing_was_reached(self):
        self.run_row(by=mo.NET_CHECK_USER, command=mo.NET_CHECK_CMD, status="failed", net={"hosts": {}},
                     output="https://github.com FAILED curl: (56) CONNECT tunnel failed, response 407\nhttps://pypi.org FAILED curl: (56) CONNECT tunnel failed, response 407\n")
        p = self.probe("internet")
        self.assertEqual((p["state"], p["reach"]), ("FAIL", "no_internet"))


class ExecutionRecord(unittest.TestCase):
    """Consolidated directive C2: one run's record keeps requested, declared and really accessed source apart, with the commit,
    the network evidence, the job id and the result."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = board(self.tmp.name)
        self.db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, needs TEXT)")
        self.db.q("INSERT INTO mw_tasks (id, comp_id, needs) VALUES (7, 23, ?)", (json.dumps([f"git:{REPO}", "internet"]),))
        self.db.q("INSERT INTO mw_tasks (id, comp_id, needs) VALUES (8, 23, NULL)")

    def tearDown(self): self.tmp.cleanup()

    def row(self, **kw):
        base = {"comp_id": 23, "task_id": 7, "run_id": 3, "agent_id": 2, "by_user": None, "status": "done", "exit_code": 0, "output": "",
                "command": f"git clone https://tok3n@github.com/RedTeamSubnet/RedTeam.git a && git clone --depth 1 https://github.com/other/thing b",
                "started": 100.0, "finished": 104.0,
                "net": json.dumps({"hosts": {"github.com": {"conns": 2}}, "refused": [{"host": "10.0.0.5", "why": "points inside"}], "down_bytes": 9, "up_bytes": 1}),
                "src": json.dumps([{"path": "/work/a", "url": f"https://{REPO}.git", "commit": C40, "ref": "main", "dirty": False}])} | kw
        cols = ", ".join(base)
        self.db.q(f"INSERT INTO mw_sbx ({cols}) VALUES ({', '.join('?' * len(base))})", tuple(base.values()))
        return self.db.q("SELECT max(id) n FROM mw_sbx", one=True)["n"]

    def test_requested_declared_and_accessed_are_three_things(self):
        w = work(self.db, FakeSbx({}))
        r = w.sbx_record(self.row())
        self.assertEqual(r["requested"]["repositories"], [REPO, "github.com/other/thing"])      # what the command asked for (credentials cut)
        self.assertEqual(r["declared"], [f"git:{REPO}", "internet"])                              # what the task said it needs
        self.assertEqual([(c["url"], c["commit"], c["basis"]) for c in r["accessed"]["checkouts"]],
                         [(f"https://{REPO}.git", C40, "read from git by the runner")])            # what the run really checked out
        self.assertEqual((r["accessed"]["hosts"], r["accessed"]["refused"]), (["github.com"], ["10.0.0.5"]))
        self.assertEqual((r["job"], r["team"], r["task"], r["run"], r["agent"]), (f"sbx:{r['job'].split(':')[1]}", 23, 7, 3, 2))
        self.assertEqual((r["result"]["status"], r["result"]["exit"], r["result"]["class"]), ("done", 0, "ok"))

    def test_a_task_that_declared_nothing_and_a_failed_run(self):
        w = work(self.db, FakeSbx({}))
        r = w.sbx_record(self.row(task_id=8, status="failed", exit_code=128, src=None, net=json.dumps({"hosts": {"github.com": {}}}),
                                  output="fatal: could not read Username for 'https://github.com': terminal prompts disabled"))
        self.assertIsNone(r["declared"]); self.assertEqual(r["accessed"]["checkouts"], [])
        self.assertEqual(r["result"]["class"], "private")                                         # the host was reached; the repository wants a login

    def test_a_docker_jobs_declared_source_is_marked_as_such_and_a_check_run_is_a_check(self):
        w = work(self.db, FakeSbx({}))
        mixed = [{"url": f"https://{REPO}", "commit": C40, "ref": None, "dirty": None, "basis": "declared"},
                 {"path": "/work/b", "url": "https://github.com/other/thing", "commit": C40[::-1], "ref": "main", "dirty": False}]
        r = w.sbx_record(self.row(src=json.dumps(mixed)))
        self.assertEqual(r["declared_source"], [{"url": f"https://{REPO}", "commit": C40, "basis": "declared"}])   # what the submitter stated
        self.assertEqual([c["url"] for c in r["accessed"]["checkouts"]], ["https://github.com/other/thing"])        # what the runner read: never the stated one
        self.assertNotIn(REPO, json.dumps(r["accessed"]))
        self.assertEqual(w.sbx_record(self.row())["declared_source"], [])
        self.assertEqual(w.sbx_record(self.row(by_user=sandbox.READINESS_USER, task_id=None))["kind"], "check")
        self.assertIsNone(w.sbx_record(99999))


class PlannerDeclaresReach(unittest.TestCase):
    """Consolidated directive C4: planners declare git and internet needs; inferred, declared, confirmed and verified stay apart."""
    def test_the_planners_rule_names_git_and_internet_and_keeps_web_reads_out(self):
        self.assertIn("declares git:<host>/<owner>/<repo> for each one and internet", tl.NEEDS_RULE.replace('" "', ""))
        self.assertIn("web_read is live_data, not internet", tl.NEEDS_RULE)

    def test_a_planned_tasks_git_need_is_declared_and_what_its_words_add_is_only_suggested(self):
        needs, version = tl.planner_needs({"title": "Build the miner", "needs": [f"git:{REPO}", "internet"]})
        self.assertEqual((json.loads(needs), version), ([f"git:{REPO}", "internet"], 2))
        t = {"id": 5, "title": "Build the miner", "detail": f"git clone https://{REPO} and git clone https://github.com/other/thing, then docker build .",
             "needs": needs, "needs_by": "planner", "needs_at": 1.0}
        got = tl.needs_of(t)
        self.assertEqual([(n["cap"], n["value"], n["source"]) for n in got if n["source"] == "declared"], [("git", REPO, "declared"), ("internet", None, "declared")])
        self.assertIn(("docker", "inferred"), {(n["cap"], n["source"]) for n in got})             # suggested by the words, never a requirement
        r = tl.requirements(None, "mw", t, decided={})
        self.assertEqual((r["status"], r["declared"]["needs"], r["confirmed"], r["verified"]), ("declared", [f"git:{REPO}", "internet"], None, None))
        t2 = t | {"needs_confirm": json.dumps({"by": "owner", "at": 2.0, "hash": tl.needs_hash(json.loads(needs))})}
        self.assertEqual(tl.requirements(None, "mw", t2, decided={})["status"], "confirmed")
        t3 = t2 | {"needs_verify": json.dumps({"at": 3.0, "hash": tl.needs_hash(json.loads(needs)), "ok": True, "items": []})}
        self.assertEqual(tl.requirements(None, "mw", t3, decided={})["status"], "verified")
        t4 = t3 | {"needs": json.dumps([f"git:{REPO}"])}                                           # the list changed: the confirmation and the check no longer hold
        self.assertEqual(tl.requirements(None, "mw", t4, decided={})["status"], "declared")

    def test_an_undeclared_task_is_undeclared_whatever_its_words_say(self):
        r = tl.requirements(None, "mw", {"id": 6, "title": "Clone it", "detail": f"git clone https://{REPO}", "needs": None}, decided={})
        self.assertEqual((r["status"], r["declared"]), ("undeclared", None))
        self.assertIn(("git", REPO), {(n["cap"], n["value"]) for n in r["inferred"]})

    def test_what_a_command_requests(self):
        self.assertEqual(tl.git_requested(f"git clone https://user:pw@{REPO}.git x; git ls-remote https://{REPO} HEAD; git fetch origin"), [REPO])


class RamFollowsTheSandboxSizes(unittest.TestCase):
    """The ram probe reads what sandbox runs can really get: 4 GB today; where sandbox sizes exist (S / M / L), the default is M
    and a larger one counts only once a run can ask for it."""
    def setUp(self):
        mo._probe_cache.clear()
        self.ch = types.SimpleNamespace(db=None, w=None, _has=lambda t: False)

    def state(self, gb): return mo.probe(self.ch, {"id": 23}, "ram", str(gb), fresh=True)

    def test_without_sizes_it_is_the_fixed_limit(self):
        with mock.patch.object(sandbox, "SIZES", None, create=True):
            self.assertEqual([self.state(g)["state"] for g in (2, 4, 8, 16)], ["PASS", "PASS", "FAIL", "FAIL"])

    def test_with_sizes_the_default_passes_a_larger_one_is_unproven_and_beyond_the_largest_fails(self):
        sizes = {"S": ("1", "2Gi", 1), "M": ("2", "4Gi", 1), "L": ("4", "8Gi", 2)}
        with mock.patch.object(sandbox, "SIZES", sizes, create=True):
            self.assertEqual([self.state(g)["state"] for g in (2, 4, 8, 16)], ["PASS", "PASS", "UNKNOWN", "FAIL"])
            p = self.state(8)
            self.assertIn("L, 8 GB", p["evidence"]); self.assertIn("isn't available to this task today", p["evidence"])
            self.assertIn("at most 8 GB", self.state(16)["evidence"])

    def test_a_size_that_isnt_a_number_fails(self):
        self.assertEqual(self.state("lots")["state"], "FAIL")

    SIZES = {"S": ("1", "2Gi", 1), "M": ("2", "4Gi", 1), "L": ("4", "8Gi", 2)}

    def test_a_larger_size_passes_only_when_the_planner_would_give_it_to_this_team(self):
        with mock.patch.object(sandbox, "SIZES", self.SIZES, create=True):
            with mock.patch.object(mo, "_ram_planned", return_value=8):
                p = self.state(8)
                self.assertEqual(p["state"], "PASS"); self.assertIn("declares ram:8", p["evidence"]); self.assertIn("not a measurement", p["evidence"])
                self.assertEqual(self.state(6)["state"], "PASS")
                self.assertEqual(self.state(16)["state"], "FAIL")      # beyond the largest size the planner isn't asked
            with mock.patch.object(mo, "_ram_planned", return_value=0):
                p = self.state(8)
                self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("aren't planned", p["evidence"])
            with mock.patch.object(mo, "_ram_planned", return_value=4):   # a planner that would still give the default
                self.assertEqual(self.state(8)["state"], "UNKNOWN")
            with mock.patch.object(mo, "_ram_planned", return_value=None):
                self.assertIn("nothing asks for a size here", self.state(8)["evidence"])

    def planned(self, cfg, boom=False):
        """mo._ram_planned against a stand-in planner with exec_env's two functions (the real one is on another branch)."""
        import sys, app
        def settings(db, comp_id):
            if boom: raise RuntimeError("no settings")
            return cfg
        def plan(needs, cfg, internet):
            ram = max([float(n["value"]) for n in needs if n["cap"] == "ram" and n.get("source") == "declared"] or [0])
            return {"size": "L" if ram > 4 else "M", "memory_mb": 8192 if ram > 4 else 4096}
        fake = types.SimpleNamespace(settings=settings, plan=plan)
        with mock.patch.dict(sys.modules, {"app.exec_env": fake}), mock.patch.object(app, "exec_env", fake, create=True):
            return mo._ram_planned(self.ch, {"id": 23}, 8)

    def test_the_switch_test_is_the_planners_own(self):
        for cfg in ({"plan": True}, {"workspace": True}, {"egress": {"mode": "allowlist", "hosts": ["github.com"]}}):
            self.assertEqual(self.planned(cfg), 8, cfg)
        for cfg in ({}, {"plan": False}, {"egress": {"hosts": ["github.com"]}}, {"note": "stored, but no switch"}):
            self.assertEqual(self.planned(cfg), 0, cfg)        # stored settings that plan nothing: the run still gets the default
        self.assertIsNone(self.planned({"plan": True}, boom=True))

    def test_a_planner_that_cant_be_read_proves_nothing(self):
        with mock.patch.object(sandbox, "SIZES", self.SIZES, create=True):
            self.assertEqual(self.state(8)["state"], "UNKNOWN")   # no database behind this probe: whatever planner is here can't be read

    def test_a_mission_only_policy_has_its_own_sentence(self):
        with mock.patch.object(sandbox, "SIZES", self.SIZES, create=True), mock.patch.object(mo, "_ram_planned", return_value=0):
            with mock.patch.object(mo, "_ram_mission_policies", return_value=True):
                p = self.state(8)
                self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("can't tell which mission", p["evidence"]); self.assertNotIn("a run gets 4 GB", p["evidence"])
            self.assertIn("a run gets 4 GB", self.state(8)["evidence"])

    def test_the_planners_exported_switch_test_is_used_when_it_exists(self):
        import sys, app
        fake = types.SimpleNamespace(settings=lambda db, cid: {"plan": True}, planned=lambda cfg: False,
                                     plan=lambda needs, cfg, internet: {"memory_mb": 8192})
        with mock.patch.dict(sys.modules, {"app.exec_env": fake}), mock.patch.object(app, "exec_env", fake, create=True):
            self.assertEqual(mo._ram_planned(self.ch, {"id": 23}, 8), 0)      # its word, not the copied line's
            fake.planned = lambda cfg: True
            self.assertEqual(mo._ram_planned(self.ch, {"id": 23}, 8), 8)


class VaultHeldCredential(unittest.TestCase):
    """PX-B16: a person's verification of a credential Vault holds is tied to the secret a run would be given (its path and
    version, as the Vault stream's own lookup names it), so a rotation voids it. The stand-in below has that lookup's contract:
    vault.fingerprint(team, mission, name) -> identity | None, raising when Vault is on but can't be read."""
    ME = {"id": 1, "username": "owner", "role": "admin"}

    def setUp(self):
        import sys, app
        from app import orchestrator as o
        self.o_mod = o
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, mission TEXT, title TEXT, detail TEXT, needs TEXT)")
        self.o = o.init(self.db)
        self.ch = types.SimpleNamespace(db=self.db, w=None, _has=lambda t: bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        mo._written.clear(); mo._probe_cache.clear(); mo._fp_cache.clear()
        self.held, self.calls, self.down = {}, [], False      # {(scope path): version}
        def fingerprint(team, mission, name):
            self.calls.append((team, mission, name))
            if self.down: raise RuntimeError("Vault is sealed")
            for path in (f"missions/{mission}/{name}", f"teams/{team}/{name}"):
                if path in self.held: return f"{path}@v{self.held[path]}"
            return None
        fake = types.SimpleNamespace(fingerprint=fingerprint)
        for p in (mock.patch.dict(sys.modules, {"app.vault": fake}), mock.patch.object(app, "vault", fake, create=True)):
            p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        self.o_mod._orc = None
        os.environ.pop("MX_TEST_KEY", None)
        self.dir.cleanup()

    def task(self, tid=1, team=23):
        self.db.q("INSERT OR REPLACE INTO mw_tasks (id, comp_id, title, detail, needs) VALUES (?,?,?,?,?)", (tid, team, f"Task {tid}", "Call the API", json.dumps(["credential:MX_TEST_KEY"])))
        return dict(self.db.q("SELECT * FROM mw_tasks WHERE id=?", (tid,), one=True))

    def ready(self, t, active=True):
        return mo.task_readiness(self.ch, self.ME["id"], {"id": t["comp_id"]}, t, f"comp:{t['comp_id']}", f"mw_task:{t['id']}", active=active)["state"]

    def risk(self): return next(r for r in self.o.risks(self.ME["id"]) if r["source_ref"] == "probe:credential")

    def later(self): mo._fp_cache.clear()      # as if UNREADABLE_HOLD had passed

    def verify(self, t):
        self.assertEqual(self.ready(t), "BLOCKED")
        return self.o.risk_verify(self.ME, self.risk()["id"], "the API answered 200 with it")["verification"]

    def test_a_rotation_in_vault_voids_the_verification(self):
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task()
        v = self.verify(t)
        self.assertEqual(v["fingerprint"], "vault:teams/23/MX_TEST_KEY@v1")
        self.assertAlmostEqual(v["expires"] - v["at"], mo.CRED_VAULT_HOURS * 3600, delta=5)     # not widened to VERIFY_DAYS
        self.assertEqual(self.ready(t), "READY")
        self.held["teams/23/MX_TEST_KEY"] = 2                                                 # rotated: seen by the very next check, no wait
        self.assertEqual(self.ready(t), "BLOCKED")
        self.assertIsNone(mo._verified(self.ch, self.ME["id"], mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY"), "MX_TEST_KEY"))   # the run's grant asks this

    def test_a_mission_secret_added_later_is_a_different_secret(self):
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task(); self.verify(t)
        self.held["missions/comp:23/MX_TEST_KEY"] = 1       # same version number, another path: what a run would now be given
        self.assertEqual(self.ready(t), "BLOCKED")

    def test_vault_wins_over_an_environment_variable_of_the_same_name(self):
        os.environ["MX_TEST_KEY"] = "a-value"
        self.assertEqual(len(mo.credential_fingerprint("MX_TEST_KEY", 23, "comp:23")), 16)      # Vault holds none: the server's own
        self.held["teams/23/MX_TEST_KEY"] = 4
        self.assertEqual(mo.credential_fingerprint("MX_TEST_KEY", 23, "comp:23"), "vault:teams/23/MX_TEST_KEY@v4")
        self.assertEqual(len(mo.credential_fingerprint("MX_TEST_KEY")), 16)                    # no team: Vault isn't asked
        self.assertEqual(mo.credential_fingerprint("MX_TEST_KEY", 7, "comp:7")[:6] != "vault:", True)   # another team's secret isn't this one's

    def test_an_unreadable_vault_matches_nothing_and_records_nothing(self):
        from fastapi import HTTPException
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task(); self.verify(t)
        self.down = True
        self.assertEqual(self.ready(t), "BLOCKED")                         # not "absent", not the old answer
        t2 = self.task(2); self.assertEqual(self.ready(t2), "BLOCKED")
        rid = next(r for r in self.o.risks(self.ME["id"]) if r["source_ref"] == "probe:credential" and r["task_ref"] == "mw_task:2")["id"]
        with self.assertRaises(HTTPException) as e: self.o.risk_verify(self.ME, rid, "checked")
        self.assertEqual(e.exception.status_code, 503)
        self.assertIsNone(self.db.q("SELECT verification FROM io_risks WHERE id=?", (rid,), one=True)["verification"])
        self.down, n = False, len(self.calls)
        self.assertEqual(self.ready(t), "BLOCKED"); self.assertEqual(len(self.calls), n)      # "didn't answer" is held a few seconds: no call per pass
        self.later(); self.assertEqual(self.ready(t), "READY")                               # the record was never replaced

    def test_a_recorded_verification_is_of_the_secret_as_it_is_at_that_moment(self):
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task(); self.assertEqual(self.ready(t), "BLOCKED")        # the gate has just asked Vault about version 1
        self.held["teams/23/MX_TEST_KEY"] = 2                              # rotated a moment before the person verifies
        v = self.o.risk_verify(self.ME, self.risk()["id"], "checked the new key")["verification"]
        self.assertEqual(v["fingerprint"], "vault:teams/23/MX_TEST_KEY@v2")

    def test_a_grant_is_checked_against_the_secret_the_caller_is_about_to_hand_over(self):
        """PX-B16's residual: the run's grant passes the identity from its own lookup, so nothing can change between check and grant."""
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task(); self.verify(t)                                    # a person verified version 1
        key = mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY")
        ask = lambda **kw: mo._verified(self.ch, self.ME["id"], key, "MX_TEST_KEY", **kw)
        self.calls.clear()
        # the caller's lookup saw version 2 (a rotation landed just before it); a lookup of mine a moment earlier would still say 1
        self.assertIsNone(ask(identity="vault:teams/23/MX_TEST_KEY@v2"))
        self.assertIsNotNone(ask(identity="vault:teams/23/MX_TEST_KEY@v1"))
        self.assertIsNotNone(ask(identity="teams/23/MX_TEST_KEY@v1"))       # the prefix is the same either way
        self.assertIsNone(ask(identity="vault:teams/7/MX_TEST_KEY@v1"))     # another team's secret is not the one that was verified
        self.assertEqual(self.calls, [])                                   # one reading of Vault, the caller's: none here
        self.held["teams/23/MX_TEST_KEY"] = 2                              # Vault has moved on; the caller holds version 1's reading
        self.assertIsNotNone(ask(identity="vault:teams/23/MX_TEST_KEY@v1")); self.assertIsNone(ask())
        self.down = True
        self.assertIsNone(ask(identity="vault:teams/23/MX_TEST_KEY@v2"))
        self.db.q("UPDATE io_risks SET verification=? WHERE rkey=?", (json.dumps({**json.loads(self.db.q("SELECT verification FROM io_risks WHERE rkey=?", (key,), one=True)["verification"]), "expires": time.time() - 1}), key))
        self.assertIsNone(ask(identity="vault:teams/23/MX_TEST_KEY@v1"))    # an identity never revives an expired verification

    def test_an_identity_never_stands_in_for_an_approval_or_another_account(self):
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task(); self.verify(t)
        key = mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY")
        self.assertIsNone(mo._verified(self.ch, 99, key, "MX_TEST_KEY", identity="vault:teams/23/MX_TEST_KEY@v1"))
        self.assertIsNone(mo._verified(self.ch, self.ME["id"], mo._rkey("comp:23", "mw_task:2", "credential", "MX_TEST_KEY"), "MX_TEST_KEY", identity="vault:teams/23/MX_TEST_KEY@v1"))

    def test_a_long_identity_is_never_cut(self):
        long = "missions/" + "m" * 400 + "/MX_TEST_KEY"
        with mock.patch.object(mo, "_vault_identity", side_effect=[(True, long + "@v1"), (True, long + "@v2")]):
            a, b = mo.credential_fingerprint("MX_TEST_KEY", 23, "x"), mo.credential_fingerprint("MX_TEST_KEY", 23, "x")
        self.assertNotEqual(a, b); self.assertTrue(a.startswith("vault:sha256:"))

    def test_a_page_read_never_calls_vault(self):
        self.held["teams/23/MX_TEST_KEY"] = 1
        t = self.task(); self.verify(t)
        self.assertEqual(self.ready(t), "READY")
        mo._fp_cache.clear(); self.calls.clear(); mo._probe_cache.clear()
        mo.task_readiness(self.ch, self.ME["id"], {"id": 23}, t, "comp:23", "mw_task:1", active=False)
        self.assertEqual(self.calls, [])                                   # no earlier answer to show, and still no call
        self.assertIsNotNone(mo._verified(self.ch, self.ME["id"], mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY"), "MX_TEST_KEY", live=False))
        self.assertEqual(self.calls, [])
        self.held["teams/23/MX_TEST_KEY"] = 2
        self.assertIsNone(mo._verified(self.ch, self.ME["id"], mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY"), "MX_TEST_KEY"))   # live: asked, voided
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(mo._verified(self.ch, self.ME["id"], mo._rkey("comp:23", "mw_task:1", "credential", "MX_TEST_KEY"), "MX_TEST_KEY", live=False))  # the page now shows the last answer
        self.assertEqual(len(self.calls), 1)

    def test_the_scope_is_read_from_the_key(self):
        self.task(1, team=23); self.task(2, team=None)
        k = lambda mission, ref: mo._rkey(mission, ref, "credential", "MX_TEST_KEY")
        self.assertEqual(mo.cred_scope(self.db, k("comp:23", "mw_task:1")), (23, "comp:23"))
        self.assertEqual(mo.cred_scope(self.db, k("mx:4", "mw_task:1")), (23, "mx:4"))
        self.assertEqual(mo.cred_scope(self.db, k(None, "mw_task:1")), (23, None))
        self.assertEqual(mo.cred_scope(self.db, k("comp:23", "mw_task:2")), (None, "comp:23"))     # a board task without a team
        self.assertEqual(mo.cred_scope(self.db, k("comp:23", "mw_task:99")), (None, "comp:23"))    # no such task
        self.assertEqual(mo.cred_scope(self.db, k("comp:23", "ctl:t7")), (None, "comp:23"))        # not on a board: Vault isn't asked
        self.assertEqual(mo.cred_scope(self.db, "readiness:comp:23:mw_task:1:internet:"), (None, None))
        self.assertEqual(mo.cred_scope(self.db, None), (None, None))

    def test_without_vault_code_or_a_vault_secret_everything_is_as_before(self):
        os.environ["MX_TEST_KEY"] = "first"
        t = self.task()
        v = self.verify(t)
        self.assertEqual(len(v["fingerprint"]), 16); self.assertAlmostEqual(v["expires"] - v["at"], mo.VERIFY_DAYS * 86400, delta=5)
        self.assertEqual(self.ready(t), "READY")
        os.environ["MX_TEST_KEY"] = "rotated"
        self.assertEqual(self.ready(t), "BLOCKED")
        self.assertEqual(mo.credential_ttl("absent"), mo.CRED_ABSENT_HOURS * 3600)


if __name__ == "__main__":
    unittest.main()
