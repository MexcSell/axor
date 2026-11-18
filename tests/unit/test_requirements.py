"""Structured task requirements (Owner decision 2026-11-11, D-017): inferred, declared, confirmed and verified kept apart.

- Inference suggests and never declares; a suggestion never blocks, and a rejected one stops asking.
- "[]" is a declaration (no external dependency); NULL is undeclared.
- A confirmation holds for the exact list it confirmed; verification is the live check's record.
- Bare mentions of keys or Docker are not requirements: the Owner review's false-positive patterns are covered here."""
import json, os, sys, tempfile, time, types, unittest
from unittest import mock

from fastapi import HTTPException

from app import mission_ops as mo, orchestrator as o, task_lifecycle as tl
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, board_schema  # noqa: E402

OTHER = {"id": 8, "username": "sam", "role": "member"}


def caps(text): return {(n["cap"], n["value"]) for n in tl.infer_needs(text)}


class InferenceReview(unittest.TestCase):
    """Phrasings in the style of the 39 reviewed suggestions (paraphrased; not production text)."""
    def test_mentions_of_keys_are_not_requirements(self):
        for text in ("Check the coldkey's other two hotkeys for UIDs on every netuid",
                     "Re-check the cohort keyed on hotkey after their immunity expires",
                     "Record the previous hotkey of UID 179 from the deregistration list",
                     "Ask the user to add the miner's hotkey on My subnets",
                     "Sum stake per weight source: 44 and 187 share a coldkey",
                     "Does upload require the hotkey to be registered? Which wallet pays the fee?"):
            self.assertFalse({c for c, _ in caps(text)} & {"credential"}, text)

    def test_using_a_key_is(self):
        self.assertIn(("credential", "hotkey"), caps("Register the hotkey, push the image and submit"))
        self.assertIn(("credential", "coldkey"), caps("Sign the registration with the coldkey"))
        self.assertIn(("credential", "wallet"), caps("Unlock the wallet and transfer"))

    def test_writing_about_the_work_needs_nothing(self):
        for text in ("Add the strict mock_validator step to the live-bench/release checklist\nRun docker build first",
                     "Add commit persistence to the deploy checklist\nThe miner must keep its volume",
                     "Add the submit cutoff to the submission runbook\nPublish the new Commit before 13:40",
                     "Record slot 45's new role in the notebook / slot register\nfiltered to the owner hotkey"):
            self.assertEqual(caps(text), set(), text)

    def test_a_title_that_also_acts_is_not_a_doc_task(self):
        self.assertIn(("approval", None), caps("Add the hotkey and register the miner"))
        self.assertEqual(caps("Fix the build, docker push the image and update the README"), {("docker", None), ("registry", None)})
        self.assertIn(("docker", None), caps("Update the guide and run docker build to check it"))
        self.assertEqual(caps("Write the submit-and-deploy runbook with rollback\nSteps: push the image to Docker Hub, submit the commit"), set())

    def test_the_approval_rule_does_not_cross_lines(self):
        self.assertNotIn(("approval", None), caps("Keep the volume in the deploy\nThe miner restarts"))

    def test_docker_work_the_old_rules_missed_or_misread(self):
        self.assertEqual(caps("Run the docker steps against the built image and record the image digest"), {("docker", None)})  # not registry
        self.assertIn(("internet", None), caps("docker pull the challenge image by digest and diff three files"))
        self.assertIn(("docker", None), caps("Run the /health GETs against the built container"))


class Layers(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        board_schema(self.db.q)
        for c, d in [("needs", "TEXT"), ("hold", "TEXT")] + tl.REQ_COLS: self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {c} {d}")
        tl.ensure_req_schema(self.db)
        self.db.q("INSERT INTO mw_tasks (id, comp_id, title, detail, status, origin) VALUES (1, ?, 'Build and push the image', 'Then report the digest', 'todo', 'you')", (WID,))
        self.db.q("INSERT INTO mw_tasks (id, comp_id, title, detail, status, origin) VALUES (2, ?, 'Summarise the scoring rules', '', 'todo', 'plan:4')", (WID,))
        self.o = o.init(self.db) or o._orc
        audit = []
        self.ch = types.SimpleNamespace(db=self.db, w=None, _comps=lambda uid: {WID: {}} if uid == ME["id"] else {},
                                        _has=lambda t: bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)),
                                        _audit=lambda *a: audit.append(a))
        self.audit = audit
        mo._written.clear()

    def tearDown(self):
        o._orc = None
        self.dir.cleanup()

    def row(self, i): return self.db.q("SELECT * FROM mw_tasks WHERE id=?", (i,), one=True)
    def view(self, i): return tl.req_view(self.ch, ME, "mw", i)

    def ready(self, i, states=None, write=True, active=True):
        def fake(ch, comp, cap, value=None, fresh=False, cached_only=False):
            st = (states or {}).get(cap, "PASS")
            return {"cap": cap, "value": value, "state": st, "evidence": f"{cap} is {st}", "how": "test", "checked": time.time()}
        with mock.patch.object(mo, "probe", fake):
            return mo.task_readiness(self.ch, ME["id"], None, self.row(i), f"comp:{WID}", f"mw_task:{i}", write=write, active=active)

    def test_inference_suggests_and_never_declares(self):
        v = self.view(1)
        self.assertEqual((v["status"], v["declared"], v["external"]), ("undeclared", None, None))
        self.assertEqual({(n["cap"], n["decision"]) for n in v["inferred"]}, {("docker", None), ("registry", None)})
        self.assertEqual(v["pending"], 2)
        r = self.ready(1, {"docker": "FAIL"})
        self.assertEqual((r["state"], r["items"]), ("READY", []))                 # a suggestion never blocks
        self.assertEqual({c["cap"] for c in r["confirm"]}, {"docker", "registry"})
        self.assertIsNone(self.row(1)["needs"])                                    # and is never written as declared

    def test_every_inferred_check_failing_still_blocks_nothing(self):
        # Milestone 3 G: inferred requirements stay advisory until a person declares or confirms them, whatever their checks say
        caps_ = {n["cap"] for n in self.view(1)["inferred"]}
        r = self.ready(1, {c: "FAIL" for c in caps_} | {"live_data": "FAIL"})
        self.assertEqual((r["state"], r["items"]), ("READY", []))
        r = self.ready(1, {c: "UNKNOWN" for c in caps_})
        self.assertEqual((r["state"], r["items"]), ("READY", []))

    def test_a_storage_query_infers_chain_query_not_snapshots(self):
        # Milestone 4 (task 2732's words): a storage map is chain storage beyond the snapshots; suggesting the snapshot check would over-pass
        found = {(n["cap"], n["value"]) for n in tl.infer_needs("Query Uids[netuid, hk] on all netuids for the coldkey's hotkeys. Pace the queries.")}
        self.assertIn(("live_data", "chain/query"), found)
        self.assertNotIn(("live_data", "chain"), found)
        self.assertIn(("live_data", "chain"), {(n["cap"], n["value"]) for n in tl.infer_needs("Compare the latest chain snapshot of the metagraph.")})

    def test_declared_none_is_a_declaration(self):
        tl.req_declare(self.ch, ME, "mw", 2, tl.ReqDeclareIn(needs=[]))
        v = self.view(2)
        self.assertEqual((v["status"], v["external"], v["declared"]["needs"], v["declared"]["by"]), ("declared", False, [], ME["username"]))
        tl.req_declare(self.ch, ME, "mw", 2, tl.ReqDeclareIn(needs=None))
        self.assertEqual(self.view(2)["status"], "undeclared")

    def test_reject_stops_asking_and_accept_declares_by_the_person(self):
        tl.req_decide(self.ch, ME, "mw", 1, tl.ReqDecideIn(cap="registry", decision="rejected", note="local digest only"))
        r = self.ready(1)
        self.assertEqual({c["cap"] for c in r["confirm"]}, {"docker"})
        v = tl.req_decide(self.ch, ME, "mw", 1, tl.ReqDecideIn(cap="docker", decision="accepted"))
        self.assertEqual((v["declared"]["needs"], v["declared"]["by"]), (["docker"], ME["username"]))
        self.assertEqual(self.ready(1, {"docker": "FAIL"})["state"], "BLOCKED")    # declared now: checked for real
        self.assertEqual([a[2] for a in self.audit], ["task.requirements.rejected", "task.requirements.accepted"])

    def test_confirm_needs_a_declaration_settles_suggestions_and_holds_for_that_list_only(self):
        with self.assertRaises(HTTPException) as e: tl.req_confirm(self.ch, ME, "mw", 1, tl.ReqConfirmIn())
        self.assertEqual(e.exception.status_code, 409)
        tl.req_declare(self.ch, ME, "mw", 1, tl.ReqDeclareIn(needs=["docker"]))
        v = tl.req_confirm(self.ch, ME, "mw", 1, tl.ReqConfirmIn(note="reviewed"))
        self.assertEqual((v["status"], v["confirmed"]["by"], v["confirmed"]["current"], v["pending"]), ("confirmed", ME["username"], True, 0))
        self.assertEqual({(n["cap"], n["decision"]) for n in v["inferred"]}, {("docker", "accepted"), ("registry", "rejected")})
        tl.req_declare(self.ch, ME, "mw", 1, tl.ReqDeclareIn(needs=["docker", "registry"]))
        v = self.view(1)
        self.assertEqual((v["status"], v["confirmed"]["current"]), ("declared", False))  # an edit needs a new confirmation

    def test_verification_is_the_live_checks_record(self):
        tl.req_declare(self.ch, ME, "mw", 1, tl.ReqDeclareIn(needs=["docker"]))
        self.ready(1, active=False)                                                # a page read records nothing
        self.assertIsNone(self.row(1)["needs_verify"])
        self.ready(1, {"docker": "FAIL"})
        v = self.view(1)
        self.assertEqual((v["status"], v["verified"]["ok"], v["verified"]["items"][0]["probe"]), ("declared", False, "FAIL"))
        self.ready(1)
        self.assertEqual(self.view(1)["status"], "verified")
        tl.req_declare(self.ch, ME, "mw", 1, tl.ReqDeclareIn(needs=["docker", "gpu"]))
        self.assertEqual((self.view(1)["status"], self.view(1)["verified"]["current"]), ("declared", False))

    def test_only_the_owner_reads_or_changes_a_task(self):
        for call in (lambda: tl.req_view(self.ch, OTHER, "mw", 1), lambda: tl.req_declare(self.ch, OTHER, "mw", 1, tl.ReqDeclareIn(needs=[]))):
            with self.assertRaises(HTTPException) as e: call()
            self.assertEqual(e.exception.status_code, 404)
        with self.assertRaises(HTTPException): tl.req_view(self.ch, ME, "zz", 1)

    def test_planner_declarations_are_attributed_from_their_origin(self):
        self.db.q("UPDATE mw_tasks SET needs='[]' WHERE id=2")
        self.assertEqual(self.view(2)["declared"]["by"], "planner (board plan)")

    def test_an_unknown_capability_is_refused(self):
        with self.assertRaises(HTTPException) as e: tl.req_declare(self.ch, ME, "mw", 1, tl.ReqDeclareIn(needs=["teleporter"]))
        self.assertEqual(e.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
