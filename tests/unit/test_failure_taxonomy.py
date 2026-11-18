"""orchestrator.FAILURE_CLASSES (G5 Phase 1, D-014, gap G-26): one failure taxonomy behind every loop's classes and policies.

Phase 1 must not change a decision any loop makes. The pinned tables below are the literal values the consumers held in
d57098e (key order too); the consumers now derive them from the taxonomy, and these tests hold them to those values.
failure() adds the canonical class on top, and says where it disagrees with the legacy one about whose fault it is."""
import os, tempfile, time, unittest

from app import control_dispatch, intel_layers, mining_autoloop, mission_ops, orchestrator as o
from app.auth import AuthDB

# ---- pinned: the consumers' tables as they were in d57098e (extracted from that commit's source, not from the new code)
RECOVERY = {'restart': (True, 'Run it again: a deploy or restart cut it off. Mission Control and Autoloop requeue their own work by themselves.'),
 'quota': (True, "Wait for the plan's usage window to reset, or route the work to another login or provider (Agents → My logins)."),
 'budget': (True, 'Raise the budget that stopped it (Agent Operations → Budget, or the scoped limit), or wait for the next day.'),
 'provider': (False, "Fix the provider first: a key, credit or permission was refused (Agents → Models). Retrying won't help until then."),
 'rate': (True, 'Retry with backoff; lower the runs at once per login if it keeps happening.'),
 'transient': (True, 'Retry: a timeout or a network error.'),
 'cap': (False, 'Split the task: it needs more than its token cap.'),
 'sandbox': (True, "See the sandbox diagnosis below: most sandbox failures are the environment's, not the code's."),
 'tool': (False, 'Fix or re-grant the tool the error names (Agents → Tools & MCP).'),
 'task': (False, 'Read the error: the work itself failed. Repeated failures of one agent become an Evolution proposal.')}
OWN_FAULT = ('task', 'cap')
OPS_RECOVERY = {'quota': ('provider',
           "The plan's usage limit lasts hours: its work waits in the queue and resumes at the reset. Retrying now is pointless.",
           'AXoR'),
 'rate': ('provider', 'Rate limited: retried with backoff while the team cools down.', 'AXoR'),
 'provider': ('provider',
              'The model provider refused the key or the account is out of credit: fix the key or the credit in Agents → Models.',
              'you'),
 'budget': ('budget',
            "Out of budget: the work waits in the queue. Raise the budget or wait for the window; it is not the task's fault.",
            'you'),
 'restart': ('environment', 'Cut off by a restart: back in the queue, not counted against the task.', 'AXoR'),
 'transient': ('environment', 'A timeout or network error: retried with backoff.', 'AXoR'),
 'sandbox': ('environment',
             "The sandbox couldn't run it: repair the sandbox (pod, image, input size), not the agent's instructions.",
             'AXoR'),
 'tool': ('environment', "A tool or MCP server failed: check the tool's grant and its server, then retry.", 'you'),
 'cap': ('task_failure', "Over the task's token cap without filing: split the task into smaller ones.", 'the team lead'),
 'task': ('task_failure',
          'The work itself failed: diagnose the approach, change the engineering strategy, then try the changed plan.',
          'the team lead'),
 'low': ('task_failure', 'Finished but scored low: compare with the acceptance criteria and test an alternative.', 'the team lead')}
FAIL_LABEL = {'restart': 'Cut off by a restart',
 'quota': 'Plan usage limit',
 'budget': 'Out of budget',
 'provider': 'Model provider refused',
 'rate': 'Rate limited',
 'transient': 'Timeout or network',
 'cap': "Over the task's cap",
 'sandbox': 'Sandbox',
 'tool': 'Tool or MCP',
 'task': 'The task itself',
 'low': 'Finished, scored under 50'}
AUTOLOOP_LABEL = {'restart': 'Cut off by a restart',
 'quota': 'Plan usage limit',
 'budget': 'Out of budget',
 'provider': 'Model provider refused',
 'rate': 'Rate limited',
 'transient': 'Transient',
 'cap': "Over the task's cap",
 'task': 'The task itself'}
AUTOLOOP_POLICY = {'restart': 'Back in the queue on autopilot, not counted',
 'quota': 'Back in the queue, not counted; every team on that plan (Terminal or Codex) waits for its reset',
 'budget': 'Back in the queue, not counted',
 'provider': 'Back in the queue; the team cools down',
 'rate': 'Retried with backoff; the team cools down',
 'transient': 'Retried with backoff',
 'cap': 'Counted; split the task',
 'task': 'Counted; twice and it waits for you'}
AUTOLOOP_CLASSES = (('quota', 'plan rate limit reached|usage limit'),
 ('budget', 'token budget'),
 ('provider',
  'credit|insufficient|quota|billing|payment|\\b401\\b|\\b403\\b|unauthori[sz]ed|invalid.{0,12}key|authentication|no model is connected|'
  "rejected the server's .{0,40}login|login doesn't work|expired or was revoked"),  # 2026-11-17 Owner-approved hotfix: login refusals
 ('rate', 'rate.?limit|\\b429\\b|too many requests|overloaded|\\b529\\b'),
 ('cap', 'token cap'),
 ('transient', 'timed? ?out|timeout|deadline|server restart|connection|temporar|\\b50[0234]\\b|unavailable|reset by peer|\\beof\\b'))
MISSION_FAILURES = [('cancelled', '\\bcancel'),
 ('budget', 'budget|used up|out of tokens|token limit|credit balance|no credits'),
 ('deadline', 'deadline|timed? ?out|took too long'),
 ('api', "rate.?limit|429|503|502|overloaded|couldn't reach|connection|unavailable"),
 ('model', 'model|claude|openai|openrouter|declined|refus'),
 ('invalid_output', 'invalid|malformed|json|schema|parse|unexpected output'),
 ('test', 'tests? fail|assert|benchmark fail'),
 ('environment', 'sandbox|pod|container|not (set up|configured|connected)|no such|missing|turned off|paused'),
 ('infrastructure', 'restart|server|database|disk|memory|killed'),
 ('strategy', "no task|nothing to|couldn't plan|approach|strategy|scope")]
MISSION_RECOVERY = {'budget': 'pause',
 'deadline': 'deliver',
 'api': 'retry',
 'model': 'retry',
 'infrastructure': 'retry',
 'unknown': 'retry',
 'invalid_output': 'replan',
 'test': 'replan',
 'strategy': 'replan',
 'environment': 'stop',
 'cancelled': 'stop'}
DISPATCH_RETRY = {"restart", "quota", "provider", "rate", "transient", "sandbox", "tool"}
DISPATCH_NEVER = {"budget", "cap"}
LAYERS = {"mission", "workforce", "execution", "evaluation", "adaptive", "knowledge"}


class Pinned(unittest.TestCase):
    def same(self, got, want):
        self.assertEqual(list(got.items()) if isinstance(got, dict) else got, list(want.items()) if isinstance(want, dict) else want)

    def test_every_consumer_table_keeps_its_values_and_order(self):
        self.same(o.RECOVERY, RECOVERY)
        self.assertEqual(o.OWN_FAULT, OWN_FAULT)
        self.same(mission_ops.RECOVERY, OPS_RECOVERY)
        self.same(intel_layers.FAIL_LABEL, FAIL_LABEL)
        self.same(mining_autoloop.LABEL, AUTOLOOP_LABEL)
        self.same(mining_autoloop.POLICY, AUTOLOOP_POLICY)
        self.assertEqual(control_dispatch.RETRY, DISPATCH_RETRY)
        self.assertEqual(control_dispatch.NEVER, DISPATCH_NEVER)

    def test_every_pattern_list_keeps_its_patterns_and_order(self):  # B5: the recognizer moved to orchestrator, unchanged
        from app import missions
        self.assertEqual(list(mining_autoloop.CLASSES), list(AUTOLOOP_CLASSES))
        self.assertEqual(missions.FAILURES, MISSION_FAILURES)
        self.same(missions.RECOVERY, MISSION_RECOVERY)
        self.assertIs(mining_autoloop.CLASSES, o.AUTOLOOP_PATTERNS)
        self.assertIs(missions.FAILURES, o.MISSION_PATTERNS)
        self.assertIs(missions.RECOVERY, o.MISSION_ACTIONS)
        for e in ("timed out", "model refused", "invalid json in the output", "", "cancelled", "rate limit 429"):
            self.assertEqual(missions.classify(e), o.mission_class(e))
            self.assertEqual(mining_autoloop.classify(e), o.autoloop_class(e))

    def test_recognize_reads_one_error_in_every_vocabulary(self):
        r = o.recognize("failed", "Request timed out after 60 s")
        self.assertEqual((r["fail_class"], r["autoloop"], r["missions"], r["mission_action"]), ("transient", "transient", "deadline", "deliver"))
        self.assertTrue(o.recognize("failed", "Claude Code on the server isn't signed in")["credential"])

    def test_the_consumers_read_the_one_table(self):
        self.assertIs(intel_layers.fail_class, o.fail_class)
        self.assertIs(mission_ops.RECOVERY, o.OPS_RECOVERY)
        self.assertIs(mining_autoloop.LABEL, o.AUTOLOOP_LABEL)
        self.assertIs(control_dispatch.RETRY, o.DISPATCH_RETRY)

    def test_the_legacy_classifier_is_unchanged(self):
        for status, err, want in [("lost", "", "restart"), ("failed", "server restart", "restart"), ("failed", "plan rate limit reached", "quota"),
                                  ("failed", "token budget", "budget"), ("failed", "401 unauthorized", "provider"), ("failed", "429", "rate"),
                                  ("failed", "token cap", "cap"), ("failed", "connection reset", "transient"), ("failed", "the pod died", "sandbox"),
                                  ("failed", "mcp server error", "tool"), ("failed", "boom", "task"), ("timeout", "", "task")]:
            self.assertEqual(o.fail_class(status, err), want, err)


class Canonical(unittest.TestCase):
    def test_every_class_is_complete(self):
        for k, d in o.FAILURE_CLASSES.items():
            self.assertTrue(d["label"], k)
            self.assertIn(d["family"], ("environment", "limit", "provider", "work", "control"), k)
            self.assertIn(d["layer"], LAYERS, k)
            self.assertIsInstance(d["own"], bool, k)
        for k in o.LEGACY_CLASSES: self.assertIn(k, o.FAILURE_CLASSES)
        for c in o.CONFLICTS:
            for k in c["classes"]: self.assertIn(k, o.FAILURE_CLASSES)

    def test_refinements_never_change_the_legacy_reading(self):
        for st, e in [("failed", "Claude Code on the server isn't signed in. Run `claude setup-token`"), ("error", "The files come to 1200 kB; a run takes at most 900 kB."),
                      ("timeout", ""), ("failed", "Devon finished without filing the work."), ("failed", "invalid json in the output"),
                      ("failed", "Docker is not set up on this server"), ("cancelled", "stopped by you"), ("failed", "plan rate limit reached")]:
            f = o.failure(st, e)
            self.assertEqual(f["legacy"]["fail_class"], o.fail_class(st, e))

    def test_a_missing_login_is_a_credential_failure_not_the_work(self):
        f = o.failure("failed", "Claude Code on the server isn't signed in. Run `claude setup-token` on any machine")
        self.assertEqual((f["cls"], f["family"], f["own"], f["legacy"]["fail_class"], f["conflict"]), ("credential", "provider", False, "task", True))

    def test_refinements(self):
        self.assertEqual(o.failure("error", "The files come to 1200 kB; a run takes at most 900 kB.", "sandbox")["cls"], "input_too_large")
        self.assertEqual(o.failure("timeout", "", "sandbox")["cls"], "timeout")
        self.assertEqual(o.failure("failed", "Kai finished without filing the work.")["cls"], "no_deliverable")
        self.assertEqual(o.failure("failed", "invalid json in the output")["cls"], "invalid_output")
        miss = o.failure("failed", "Docker is not set up on this server")
        self.assertEqual((miss["cls"], miss["own"], miss["conflict"]), ("capability", False, True))
        for code_error in ("FileNotFoundError: No such file or directory: 'bench.py'", "KeyError: 'missing'", "the field is missing from the reply"):
            self.assertEqual(o.failure("failed", code_error)["cls"], "task", code_error)  # ordinary code errors stay the work's
        self.assertEqual(o.failure("cancelled", "stopped by you")["cls"], "cancelled")
        q = o.failure("failed", "plan rate limit reached")
        self.assertEqual((q["cls"], q["conflict"]), ("quota", False))
        for f in (o.failure("timeout", "", "sandbox"), o.failure("failed", "Kai finished without filing the work.")):
            self.assertFalse(f["conflict"])  # both sides call it the work's own

    def test_sandbox_reading_names_the_sandbox_class(self):
        self.assertEqual(o.failure("error", "The sandbox is busy (2 runs at once)")["legacy"]["sandbox"], "busy")


class Diagnosis(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.db.q("""CREATE TABLE ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, system TEXT, kind TEXT, ref TEXT, corr TEXT,
                     agent_key TEXT, status TEXT, error TEXT, score REAL, tokens INTEGER, started REAL, finished REAL)""")
        self.o = o.Orchestrator(self.db)

    def tearDown(self): self.dir.cleanup()

    def test_diagnosis_records_the_canonical_class_beside_the_legacy_one(self):
        now = time.time()
        for err in ("Claude Code on the server isn't signed in.", "plan rate limit reached", "boom"):
            self.db.q("INSERT INTO ac_runs (owner_id, system, kind, ref, status, error, started) VALUES (7, 'teams', 'task', 'mw:1', 'failed', ?, ?)", (err, now))
        self.o.diagnose()
        got = {r["evidence"][:12]: (r["cls"], r["canon"]) for r in self.db.q("SELECT evidence, cls, canon FROM io_diag")}
        self.assertEqual(got["Claude Code "], ("task", "credential"))   # decisions still read cls
        self.assertEqual(got["plan rate li"], ("quota", "quota"))
        self.assertEqual(got["boom"], ("task", "task"))
        t = self.o.taxonomy(7)
        cred = next(x for x in t["counts"] if x["canon"] == "credential")
        self.assertEqual((cred["legacy"], cred["n"], cred["conflict"]), ("task", 1, True))
        self.assertFalse(next(x for x in t["counts"] if x["canon"] == "quota")["conflict"])
        self.assertEqual({c["key"] for c in t["classes"]}, set(o.FAILURE_CLASSES))
        self.assertTrue(t["conflicts"])


if __name__ == "__main__":
    unittest.main()
