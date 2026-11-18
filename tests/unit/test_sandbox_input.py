"""sandbox.py input packaging: a run's files over one ConfigMap go in several (one projected volume, under the namespace's
ConfigMap quota); over all of them, the files the command names and code go first and the rest is listed in .axor/omitted.txt
instead of the run failing; every map is deleted afterwards."""
import json, unittest
from unittest import mock

from app import sandbox


class Kube:
    enabled = True
    def __init__(self): self.maps, self.pod, self.deleted = [], None, []
    def call(self, method, path, params=None, body=None, **k):
        if path.endswith("/configmaps"): self.maps.append(body)
        else: self.pod = body
    def get(self, path): return {"status": {"phase": "Running", "containerStatuses": [{"name": "runner", "state": {"terminated": {"exitCode": 0}}}]}}
    def logs(self, *a, **k): return "@@AXOR-EXIT 0"
    def delete(self, path, *a, **k): self.deleted.append(path)


class Input(unittest.TestCase):
    def setUp(self):
        self.s = sandbox.Sandbox(None, lambda: "")
        self.s.ready = lambda: (True, "")
        self.s.kube = self.k = Kube()

    def run_(self, files, command="python3 main.py"):
        with mock.patch.object(sandbox.time, "sleep", lambda n: None):
            return self.s.run(files, command)

    def sent(self):
        m = json.loads(self.k.maps[0]["data"]["manifest.json"])
        data = {k: v for cm in self.k.maps for k, v in cm["data"].items()}
        return {path: data[key] for key, path in m.items()}

    def test_small_input_is_one_map(self):
        r = self.run_({"main.py": "print(1)"})
        self.assertEqual(r["status"], "done")
        self.assertEqual(len(self.k.maps), 1)
        self.assertEqual(self.k.pod["spec"]["volumes"][0]["projected"]["sources"], [{"configMap": {"name": r["pod"]}}])
        self.assertNotIn("omitted", r)

    def test_over_one_map_spreads_over_several_and_cleans_them_all_up(self):
        files = {f"data/part{i}.csv": "x" * 400_000 for i in range(5)} | {"main.py": "print(1)"}  # 2 MB: was "the files come to … kB"
        r = self.run_(files)
        self.assertEqual(r["status"], "done")
        self.assertGreater(len(self.k.maps), 1)
        self.assertLessEqual(len(self.k.maps), sandbox.INPUT_CHUNKS)
        self.assertTrue(all(sum(len(v) for v in cm["data"].values()) <= sandbox.INPUT_BYTES for cm in self.k.maps))
        self.assertEqual(set(self.sent()) - {p for p in self.sent() if p.startswith(".axor/")}, set(files))  # every file went
        names = [cm["metadata"]["name"] for cm in self.k.maps]
        self.assertEqual([s["configMap"]["name"] for s in self.k.pod["spec"]["volumes"][0]["projected"]["sources"]], names)
        self.assertEqual(sorted(p.rsplit("/", 1)[1] for p in self.k.deleted if "/configmaps/" in p), sorted(names))

    def test_over_every_map_packs_named_and_code_files_first(self):
        big = {f"data/blob{i}.bin": "y" * 800_000 for i in range(8)}  # 6.4 MB of data
        files = big | {"main.py": "import lib", "lib.py": "x = 1", "inputs/needed.bin": "z" * 500_000}
        r = self.run_(files, "python3 main.py inputs/needed.bin")
        self.assertEqual(r["status"], "done")
        got = self.sent()
        for p in ("main.py", "lib.py", "inputs/needed.bin"): self.assertIn(p, got)  # code, and the file the command names
        self.assertTrue(r["omitted"]); self.assertTrue(set(r["omitted"]) <= set(big))
        self.assertIn(r["omitted"][0], got[".axor/omitted.txt"])
        self.assertTrue(r["output"].startswith("@@AXOR-PACKED"))

    def test_a_file_is_named_by_a_whole_word_not_a_substring(self):
        kept, omitted = sandbox.pack({"a.py": "x" * 50, "data.py": "y" * 50, "src/big.bin": "z" * 500, "cfg/run.toml": "w" * 500}, "python3 data.py --config=cfg/run.toml", 700)
        self.assertIn("data.py", kept); self.assertIn("cfg/run.toml", kept)  # named: full path, or after "="
        self.assertEqual([p for p, _ in omitted], ["src/big.bin"])

    def test_named_files_over_the_limit_still_refuse(self):
        with self.assertRaisesRegex(sandbox.SandboxError, "the ones the command names don't fit"):
            self.run_({"huge.bin": "q" * 2_000_000}, "python3 run.py huge.bin")

    def test_the_quota_holds(self):
        self.assertLessEqual(sandbox.AT_ONCE * sandbox.INPUT_CHUNKS + 1, 30)


if __name__ == "__main__":
    unittest.main()
