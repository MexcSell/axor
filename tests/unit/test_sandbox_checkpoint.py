"""Sandbox checkpoints (sandbox.py + .axor/checkpoint.py + mining_work.mw_ckpt): a run saves $AXOR_STATE through the model
proxy whenever it likes and once more at the end; a team task's next sandbox run starts from the last save, so a restart, a
timeout or a lost pod doesn't throw the work away."""
import base64, io, json, os, socket, subprocess, sys, tarfile, tempfile, time, unittest
from unittest import mock

from app import mining_work, sandbox
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_sandbox_input import Kube  # noqa: E402


def tgz(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, text in files.items():
            raw = text.encode(); info = tarfile.TarInfo(name); info.size = len(raw); t.addfile(info, io.BytesIO(raw))
    return base64.b64encode(buf.getvalue()).decode()


def untgz(data):
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(data)), mode="r:gz") as t:
        return {m.name: t.extractfile(m).read().decode() for m in t.getmembers() if m.isfile()}


class Proxy(unittest.TestCase):
    def setUp(self):
        self.p = sandbox.Proxy(lambda: "")
        self.kept = []
        self.tok = self.p.open(1.0, save=self.kept.append)

    def post(self, body, tok=None):
        return self.p.handle("POST", f"/t/{tok or self.tok}/checkpoint", json.dumps(body).encode())

    def test_a_save_reaches_the_store_at_once_and_is_counted(self):
        code, out = self.post({"data": tgz({"progress.json": '{"step": 3}'})})
        self.assertEqual((code, out["saves"]), (200, 1))
        self.assertEqual(untgz(self.kept[0]), {"progress.json": '{"step": 3}'})
        self.post({"data": tgz({"progress.json": '{"step": 4}'})})
        use = self.p.close(self.tok)
        self.assertEqual((use["saves"], len(self.kept)), (2, 2))

    def test_too_big_not_base64_and_no_store_are_refused(self):
        self.assertEqual(self.post({"data": "A" * (sandbox.CKPT_BYTES + 4)})[0], 413)
        self.assertEqual(self.post({"data": "not base64!"})[0], 400)
        other = self.p.open(1.0)  # a run without a store (a manual run)
        self.assertEqual(self.post({"data": tgz({"a": "b"})}, other)[0], 409)
        self.assertEqual(self.kept, [])
        self.assertEqual(self.p.handle("POST", "/t/" + "x" * 30 + "/checkpoint", b"{}")[0], 404)  # another run's token can't write


class HelperScript(unittest.TestCase):
    """The script the pod runs, against a real proxy on a local port: what it sends unpacks to the state folder."""
    def test_checkpoint_py_round_trip(self):
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        p = sandbox.Proxy(lambda: "")
        with mock.patch.object(sandbox, "PROXY_BIND", "127.0.0.1"): p.start(port)
        try:
            kept = []
            tok = p.open(1.0, save=kept.append)
            with tempfile.TemporaryDirectory() as d:
                os.makedirs(f"{d}/state/cache")
                open(f"{d}/state/progress.json", "w").write('{"done": [1, 2]}')
                open(f"{d}/state/cache/rows.csv", "w").write("a,b\n1,2\n")
                env = {**os.environ, "AXOR_STATE": f"{d}/state", "SANDBOX_PROXY_URL": f"http://127.0.0.1:{port}/t/{tok}"}
                script = os.path.join(os.path.dirname(sandbox.__file__), "sandbox_files", "checkpoint.py")
                r = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("@@AXOR-CHECKPOINT saved", r.stdout)
                self.assertEqual(untgz(kept[-1]), {"progress.json": '{"done": [1, 2]}', "cache/rows.csv": "a,b\n1,2\n"})
                for f in os.listdir(f"{d}/state"): os.system(f"rm -rf {d}/state/{f}")
                r = subprocess.run([sys.executable, script, "--final"], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual((r.returncode, r.stdout), (0, ""))  # nothing in the state at the end: quiet, nothing sent
                self.assertEqual(len(kept), 1)
        finally:
            p.server.shutdown()


class Run(unittest.TestCase):
    def setUp(self):
        self.s = sandbox.Sandbox(None, lambda: "")
        self.s.ready = lambda: (True, "")
        self.s.kube = self.k = Kube()

    def sent(self):
        m = json.loads(self.k.maps[0]["data"]["manifest.json"])
        data = {k: v for cm in self.k.maps for k, v in cm["data"].items()}
        return {path: data[key] for key, path in m.items()}

    def test_a_run_starts_from_the_checkpoint_and_reports_its_saves(self):
        state = tgz({"progress.json": '{"step": 7}'})
        with mock.patch.object(sandbox.time, "sleep", lambda n: None):
            r = self.s.run({"main.py": "print(1)"}, "python3 main.py", checkpoint={"load": state, "save": lambda d: None})
        self.assertEqual(self.sent()[sandbox.CKPT_FILE], state)
        self.assertIn(".axor/checkpoint.py", self.sent())
        env = {e["name"]: e["value"] for e in self.k.pod["spec"]["containers"][0]["env"]}
        self.assertEqual(env["AXOR_STATE"], "/work/.axor/state")
        self.assertEqual(r["checkpoint"], {"resumed": True, "saves": 0, "saved_bytes": 0})
        self.assertIn("checkpoint.py --final", sandbox.RUNNER)       # saved once more when the command ends, timed out or not
        self.assertLess(sandbox.RUNNER.index("AXOR_RESUMED=1"), sandbox.RUNNER.index("@@AXOR-START"))

    def test_without_one_nothing_changes(self):
        with mock.patch.object(sandbox.time, "sleep", lambda n: None):
            r = self.s.run({"main.py": "print(1)"}, "python3 main.py")
        self.assertNotIn(sandbox.CKPT_FILE, self.sent()); self.assertNotIn("checkpoint", r)

    def test_the_checkpoint_survives_packing(self):
        big = {f"data/blob{i}.bin": "y" * 800_000 for i in range(8)}
        state = tgz({"p": "x" * 1000})
        with mock.patch.object(sandbox.time, "sleep", lambda n: None):
            r = self.s.run(big | {"main.py": "print(1)"}, "python3 main.py", checkpoint={"load": state, "save": lambda d: None})
        self.assertTrue(r["omitted"]); self.assertEqual(self.sent()[sandbox.CKPT_FILE], state)


class FakeSbx:
    """Stands in for Sandbox.run: records what it got and saves what the "pod" saved."""
    def __init__(self): self.got, self.save_as = [], None
    def run(self, files, command, services, timeout, budget, label="", cancelled=None, started=None, internet=False, checkpoint=None):
        self.got.append(checkpoint)
        if checkpoint and self.save_as: checkpoint["save"](self.save_as)
        return {"status": "timeout", "exit": 124, "output": "", "error": "", "cost": 0, "calls": 0,
                **({"checkpoint": {"resumed": bool(checkpoint.get("load")), "saves": 1 if self.save_as else 0, "saved_bytes": len(self.save_as or "")}} if checkpoint else {})}


class TeamTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        db.q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY, comp_id INTEGER, path TEXT, content TEXT)")
        db.q("""CREATE TABLE mw_sbx (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, run_id INTEGER, agent_id INTEGER, by_user TEXT,
                command TEXT, services TEXT, status TEXT, exit_code INTEGER, output TEXT, error TEXT, started REAL, finished REAL, cost REAL, calls INTEGER, pod TEXT, net TEXT)""")
        db.q("""CREATE TABLE mw_ckpt (comp_id INTEGER, task_id INTEGER, data TEXT, bytes INTEGER, sbx_id INTEGER, agent_id INTEGER, saved REAL,
                PRIMARY KEY (comp_id, task_id))""")
        w = object.__new__(mining_work.Work)
        w.db, w.sbx = db, FakeSbx()
        w._event = lambda *a, **k: None
        w._label = lambda c: "Competition 28"
        w._ins = lambda sql, args: db.q(sql + " RETURNING id", args, one=True)["id"]
        self.w, self.comp, self.c = w, {"id": 5, "internet": 0}, {"netuid": 62}

    def tearDown(self): self.tmp.cleanup()

    def run_(self, task=11):
        return self.w._sandbox(self.comp, self.c, "python3 long.py", [], 600, 1.0, task=task, agent={"id": 2, "name": "Devon"})

    def test_a_tasks_next_run_resumes_from_its_last_save(self):
        self.w.sbx.save_as = tgz({"progress.json": '{"step": 40}'})
        self.run_()                                                    # timed out at step 40, but saved it
        self.assertIsNone(self.w.sbx.got[0]["load"])
        row = self.db.q("SELECT * FROM mw_ckpt WHERE comp_id=5 AND task_id=11", one=True)
        self.assertEqual((row["agent_id"], row["sbx_id"]), (2, 1))
        self.w.sbx.save_as = None
        r = self.run_()
        self.assertEqual(untgz(self.w.sbx.got[1]["load"]), {"progress.json": '{"step": 40}'})
        self.assertEqual(r["checkpoint"]["from"]["sbx"], 1)
        self.run_(task=12)                                             # another task starts clean
        self.assertIsNone(self.w.sbx.got[2]["load"])
        self.w._sandbox(self.comp, self.c, "ls", [], 60, 1.0, user="leo")  # a manual run keeps no checkpoint
        self.assertIsNone(self.w.sbx.got[3])

    def test_an_old_checkpoint_isnt_used(self):
        self.db.q("INSERT INTO mw_ckpt VALUES (5, 11, ?, 10, 1, 2, ?)", (tgz({"a": "b"}), time.time() - (mining_work.CKPT_DAYS + 1) * 86400))
        self.run_()
        self.assertIsNone(self.w.sbx.got[0]["load"])

    def test_the_agent_is_told_how_to_checkpoint(self):
        self.assertIn("python3 .axor/checkpoint.py", mining_work.SANDBOX_TOOL["description"])
        self.assertIn("$AXOR_STATE", mining_work.sandbox_tool(internet=True)["description"])


if __name__ == "__main__":
    unittest.main()
