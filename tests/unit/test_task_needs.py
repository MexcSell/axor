"""Task capability requirements (G5 Phase 1, D-014, gap G-27): task_lifecycle.CAPABILITIES, infer_needs, needs_of, and the
declared needs on board tasks (mw_tasks.needs) and Control Hub tasks (ctl_tasks.needs). Phase 1 records and shows them;
nothing is gated on them (Phase 2). The phrasings below are written for the tests, in the style SN61's board uses."""
import json, os, sys, unittest

from fastapi import HTTPException

import types

from app import control_dispatch as cd, control_missions, mining_work, task_lifecycle as tl

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402
from test_task_lifecycle import Lifecycle  # noqa: E402


def caps(text): return {(n["cap"], n["value"]) for n in tl.infer_needs(text)}


class Inference(unittest.TestCase):
    def test_actions_that_need_a_docker_engine(self):
        for text in ("Run the docker build and docker push commands, then send the sha256 digest back.",
                     "Start the challenge container and take one live score.",
                     "Measure the challenge container's peak RAM: run docker stats during one bench round.",
                     "Build and push the image on your machine once the PRs pass.",
                     "Run --image mode against repo@sha256:abc once the image exists.",
                     "docker compose up the mock stack"):
            self.assertIn(("docker", None), caps(text), text)

    def test_mentions_and_writing_about_docker_need_no_engine(self):
        for text in ("Add a --check build line to the Dockerfile.", "Confirm MINER_DOCKER_PORT (10002 vs 10001).",
                     "Document how a submitted Docker Hub image is pulled and scored.", "Read docker_utils.is_container_alive in the validator.",
                     "Write the runbook: the Docker image pull and the rollback thresholds."):
            self.assertNotIn("docker", {c for c, _ in caps(text)}, text)

    def test_registry_credentials_ram_approval(self):
        self.assertIn(("registry", None), caps("push the image to Docker Hub and record the image digest"))
        self.assertIn(("credential", "BEX_CHALLENGE_API_KEY"), caps("export KEY=$BEX_CHALLENGE_API_KEY first"))
        self.assertIn(("credential", "hotkey"), caps("Register the hotkey on SN61"))  # D-017: a key is needed to sign or register
        self.assertIn(("credential", "coldkey"), caps("Sign the transfer with the coldkey"))
        self.assertIn(("ram", "16"), caps("The challenge needs 16 GB of RAM"))
        self.assertIn(("approval", None), caps("Register the hotkey, publish the image and submit the commit"))
        self.assertIn(("internet", None), caps("pip install -r requirements.txt, then git clone the validator"))
        self.assertEqual(caps("Summarise the scoring rules"), set())

    def test_each_inferred_need_says_which_words_inferred_it(self):
        n = next(x for x in tl.infer_needs("Start the challenge container now") if x["cap"] == "docker")
        self.assertEqual((n["source"], n["why"]), ("inferred", "Start the challenge container"))


class Declared(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(tl.parse_needs(["docker", "RAM:16", "credential:BEX_CHALLENGE_API_KEY", "Docker", ""]),
                         ["docker", "ram:16", "credential:BEX_CHALLENGE_API_KEY"])
        for bad in (["dockerd"], ["ram:lots"], ["docker; rm -rf /"]):
            with self.assertRaises(ValueError): tl.parse_needs(bad)

    def test_declared_first_and_it_replaces_what_the_text_suggests_for_that_capability(self):
        r = {"title": "Start the challenge container", "detail": "needs 8 GB of RAM", "needs": json.dumps(["ram:16"])}
        got = [(n["cap"], n["value"], n["source"]) for n in tl.needs_of(r)]
        self.assertEqual(got[0], ("ram", "16", "declared"))
        self.assertIn(("docker", None, "inferred"), got)
        self.assertNotIn(("ram", "8", "inferred"), got)


class BoardTasks(BoardBase):
    def setUp(self):
        super().setUp()
        self.db.q("ALTER TABLE mw_tasks ADD COLUMN needs TEXT")
        self.w._open = lambda wid: 0

    def test_a_board_task_keeps_its_declared_needs(self):
        tid = self.w._add_task(ME, WID, mining_work.TaskIn(title="Live bench", needs=["docker", "ram:16"]))
        self.assertEqual(json.loads(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (tid,), one=True)["needs"]), ["docker", "ram:16"])
        plain = self.w._add_task(ME, WID, mining_work.TaskIn(title="Read the rules"))
        self.assertIsNone(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (plain,), one=True)["needs"])

    def test_an_unknown_capability_is_refused(self):
        with self.assertRaises(HTTPException) as e: self.w._add_task(ME, WID, mining_work.TaskIn(title="Bench", needs=["teleporter"]))
        self.assertEqual(e.exception.status_code, 422)

    def test_a_patch_sets_and_clears_needs(self):
        tid = self.task("Bench the candidate")
        self.w._task = lambda me, t: (self.db.q("SELECT * FROM mw_tasks WHERE id=?", (t,), one=True), self.w._comp(WID), None)
        self.w.update_task(ME, tid, mining_work.TaskPatch(needs=["docker", "ram:8"]))
        self.assertEqual(json.loads(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (tid,), one=True)["needs"]), ["docker", "ram:8"])
        self.w.update_task(ME, tid, mining_work.TaskPatch(needs=[]))  # D-017: [] = declared none, not undeclared
        self.assertEqual(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (tid,), one=True)["needs"], "[]")
        self.w.update_task(ME, tid, mining_work.TaskPatch(needs=None))  # null = undeclared again
        self.assertIsNone(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (tid,), one=True)["needs"])

    def test_a_control_hub_task_carries_its_declared_needs_to_the_board(self):
        ch = types.SimpleNamespace(w=self.w, _view=lambda me: {"units": [{"id": 1}]}, _comps=lambda uid: {WID: {}}, _comp_of=lambda u: WID)
        r = {"unit_id": 1, "mission": f"comp:{WID}", "title": "Live bench", "detail": "", "priority": "high", "needs": json.dumps(["docker"])}
        bid = control_missions._to_board(ch, ME, r)
        self.assertEqual(json.loads(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (bid,), one=True)["needs"]), ["docker"])
        plain = control_missions._to_board(ch, ME, dict(r, title="Read the rules", needs=None))
        self.assertIsNone(self.db.q("SELECT needs FROM mw_tasks WHERE id=?", (plain,), one=True)["needs"])

    def test_tasks_without_the_column_still_add(self):
        self.db.q("ALTER TABLE mw_tasks DROP COLUMN needs")
        self.assertTrue(self.w._add_task(ME, WID, mining_work.TaskIn(title="Plain task")))


class ControlHubTasks(Lifecycle):
    def test_the_contract_carries_declared_and_inferred_needs(self):
        t = self.agent_task("Start the challenge container and score one commit")
        tl.set_contract(self.ch, ME, t, tl.ContractIn(needs=["credential:BEX_CHALLENGE_API_KEY"]))
        got = {(n["cap"], n["value"], n["source"]) for n in tl.contract(self.ch, ME, self.row(t))["needs"]}
        self.assertIn(("credential", "BEX_CHALLENGE_API_KEY", "declared"), got)
        self.assertIn(("docker", None, "inferred"), got)
        tl.set_contract(self.ch, ME, t, tl.ContractIn(accept="Scores one commit"))  # needs=None leaves them
        self.assertEqual(json.loads(self.row(t)["needs"]), ["credential:BEX_CHALLENGE_API_KEY"])
        with self.assertRaises(HTTPException): tl.set_contract(self.ch, ME, t, tl.ContractIn(needs=["warp-drive"]))

    def test_g5_2_declared_needs_hold_the_task_and_inferred_ones_dont(self):
        # G5-1 recorded needs without gating; G5-2 (D-011, Owner D4/F) holds a task whose declared needs fail their probes
        t2 = self.agent_task("Build the miner image")
        tl.set_contract(self.ch, ME, t2, tl.ContractIn(needs=["docker"]))            # declared: no Docker for agents here, so held
        self.assertTrue(tl.contract(self.ch, ME, self.row(t2))["ok"])
        out = cd.dispatch(self.ch, ME)
        self.assertEqual((out["agent"], out.get("readiness_held")), (0, 1), out)
        self.assertEqual(self.row(t2)["status"], "todo")
        self.assertIn("Held by readiness: docker FAIL", self.row(t2)["summary"])
        self.agent_task("Start the challenge container and score one commit")       # inferred docker only: dispatched
        self.assertEqual(cd.dispatch(self.ch, ME)["agent"], 1)


if __name__ == "__main__":
    unittest.main()
