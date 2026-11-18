"""A job's two hashes, pinned as literal values (D-034): job_sha256 (the job as validated) and the measuring-job hash a release
freezes. A release frozen yesterday must still recognize its measuring job after any later change to the runner: a new job
field that lands in every job, even as an empty default, would silently make every frozen release unmeasurable.

If one of these values changes, the change moved every existing job's hash. That is never an accident to "fix" by updating the
literal: it needs a decision, and every frozen release needs a new reference run."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))
import test_vm_runner as tv  # noqa: E402  (as a module, so its own tests don't run again here)
from app import runner as V  # noqa: E402

REGISTRY_BENCH = dict(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", artifacts=["out/log.txt"])
BUILD_BENCH = dict(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json", network="build")
NONE_FILES = {"Dockerfile": "FROM scratch\nCOPY app.py /\n", "app.py": ""}
PINS = {"registry bench": "356b8d8b0fba8a494d7dc4bc5245a78c28c701c53728926a45c732d4ab7b93c4",
        "build bench": "56c40255e15847cd30731a9c1df684ee2da1ff6f08e06fea7b0b96fcea9a4c80",
        "no-network build": "f0bc1a4618da82aa71d5cb4121df187bf4c0a5d5e114c7dc514b19ff1464c025"}


def jobs(**extra):
    return {"registry bench": V.validate(tv.spec(**REGISTRY_BENCH, **extra), tv.FILES)[0],
            "build bench": V.validate(tv.spec(**BUILD_BENCH, **extra), tv.FILES, ["pypi.org", "files.pythonhosted.org"])[0],
            "no-network build": V.validate(tv.spec(network="none", **extra), NONE_FILES)[0]}


class Pinned(unittest.TestCase):
    def test_three_reference_jobs_keep_their_hashes(self):
        for name, job in jobs().items():
            self.assertEqual(V.job_sha(job), PINS[name], name)
            self.assertEqual(V.measure_sha(job), PINS[name], name)   # no id, token, source or secret in these: the two hashes agree

    def test_the_files_hash_of_the_reference_files(self):
        rec = V.inputs(jobs()["registry bench"], tv.FILES)
        self.assertEqual(rec["files_sha256"], "b9a884e30e3cdb32d241085a8f68effc7c505cfeb7b2e26d5c83a8747369f1bb")
        self.assertEqual(sorted(rec), ["files", "files_sha256", "job_sha256", "tree"])

    def test_a_field_a_job_does_not_use_never_reaches_its_hash(self):
        """The tool is strict: an agent sends every field, empty when unused. Empty must hash exactly like absent."""
        empty = dict(images=[], compose="", context="", secrets=[], paths=[], source_repo="", source_commit="", check_git="")
        for name, job in jobs(**empty).items():
            self.assertEqual((V.job_sha(job), V.measure_sha(job)), (PINS[name], PINS[name]), name)

    def test_the_control_a_field_a_job_does_use_changes_its_hash(self):
        job = V.validate(tv.spec(**{**REGISTRY_BENCH, "timeout_s": 601}), tv.FILES)[0]
        self.assertNotEqual(V.job_sha(job), PINS["registry bench"]); self.assertNotEqual(V.measure_sha(job), PINS["registry bench"])


@tv.own_tests
class WhatWasSent(tv.Running):
    """The job's record lists the files the VM got. A file left out because the input was too large is named in `omitted` and is
    not in the record's file list, so it can't count as part of a frozen harness the job never had."""
    def run_files(self, files):
        self.proxy, self.egress = tv.FakeProxy(), tv.FakeEgress()
        self.kube = tv.FakeKube(report=lambda pod: tv.vm_report(self.job), proxy=self.proxy)
        return V.Runner(self.kube, self.proxy, self.egress).run({**self.job, "id": 9}, files)

    def test_a_job_within_the_cap_records_every_file_as_before(self):
        r = self.run_files(tv.FILES)
        self.assertEqual((r["inputs"]["files_sha256"], r["inputs"]["files"], "omitted" in r), ("b9a884e30e3cdb32d241085a8f68effc7c505cfeb7b2e26d5c83a8747369f1bb", len(tv.FILES), False))
        self.assertEqual(sorted(r["inputs"]["tree"]), sorted(tv.FILES))

    def test_a_file_left_out_is_named_and_is_not_in_the_record(self):
        big = {**tv.FILES, "bench/data/cases.jsonl": "x" * V.INPUT_BYTES}                     # over one input file's size: it can't go
        r = self.run_files(big)
        self.assertEqual(r["omitted"], ["bench/data/cases.jsonl"])
        self.assertNotIn("bench/data/cases.jsonl", r["inputs"]["tree"]); self.assertEqual(sorted(r["inputs"]["tree"]), sorted(tv.FILES))
        self.assertEqual(r["inputs"]["files"], len(tv.FILES))
        sent = {b["metadata"]["name"]: b for b in self.kube.maps()}
        names = set()
        for cm in sent.values(): names |= set(__import__("json").loads(cm["data"].get("manifest.json", "{}")).values())
        self.assertEqual(names - {V.JOB_FILE}, set(r["inputs"]["tree"]))                       # the record is exactly what went in

    def test_a_harness_file_that_was_left_out_changes_the_harness_hash(self):
        """D-034: the frozen harness is every file outside the candidate root. A job that didn't get one of them isn't that job."""
        whole = self.run_files({**tv.FILES, "bench/data/cases.jsonl": "small"})
        cut = self.run_files({**tv.FILES, "bench/data/cases.jsonl": "x" * V.INPUT_BYTES})
        root = "miner"
        self.assertNotEqual(V.harness_sha(whole["inputs"]["tree"], root), V.harness_sha(cut["inputs"]["tree"], root))
        self.assertEqual(V.harness_sha(cut["inputs"]["tree"], root), V.harness_sha(self.run_files(tv.FILES)["inputs"]["tree"], root))  # it is the job without that file


if __name__ == "__main__":
    unittest.main()
