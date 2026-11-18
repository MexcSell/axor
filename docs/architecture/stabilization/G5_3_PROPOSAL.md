# G5-3 Proposal: one Risk Intelligence register for every risk source

**Status:** In progress since 2026-11-13 on `dev/g5-3-risk`, in parallel with D-004 D4.3 (R3.1, R3.2, R3.4 now; R3.3 after D4.3). Decisions: `owner-decisions/g5-plan/g53/DECISIONS_20261113.md`.

## Goal
`orchestrator.io_risks` (D-012) becomes the single register that every existing risk signal feeds. No new database,
dashboard or orchestrator. The sources keep their tables as raw evidence (D-012: "existing diagnostics remain the source of
raw evidence").

## Sources and how each feeds the register

| Source (existing) | What becomes a risk | Key (stable, deduplicating) | Resolved when |
|---|---|---|---|
| `hq_issues` (Agent HQ patrols) | Each open issue with severity ≥ warn | `hq:<key>` | the issue's `status` leaves open (its resolution and verdict become the verification) |
| `io_diag` (failed runs) | A failure class recurring on one team or mission: ≥ 3 runs in 24 h whose canonical class isn't the work's own (credential, provider, sandbox, tool, capability) | `diag:<mission>:<canonical class>` | no run of that class for 24 h, or the class's readiness probe passes |
| `io_sbx` (the orchestrator's diagnosis of failed sandbox runs), joined to `mw_sbx` (the runs themselves) for evidence | The same, per sandbox class (busy, image, egress, gvisor, too_large) | `sbx:<comp>:<class>` | as above |
| `ac_alerts` (budget thresholds) | A limit crossed at warn or stop level | `budget:<scope>:<period>` | the next period starts or the limit is raised |
| `mo_alerts`, `mh_alerts` (mining ops, campaigns) | Open alerts of level warn or bad | `mo:<key>` / `mh:<key>` | the alert's own `resolved` |
| `alerts` (subnet news and risk flags) | Not imported. These are market signals, not operational risks. They stay in `risk.py` / Alerts (name kept apart from Risk Intelligence). | — | — |

## Sandbox tables: which one is authoritative (verified 2026-11-11)

Both tables exist. They are not two names for one thing:

| Table | Owner | Schema (from source) | What it is |
|---|---|---|---|
| `mw_sbx` | `mining_work.py:421-425` | `id, comp_id, task_id, run_id, agent_id, by_user, command, services, status, exit_code, output, error, started, finished, cost, calls, pod`, plus `net` | **The sandbox runs**: one row per run, the raw record (authoritative for what ran) |
| `io_sbx` | `orchestrator.py:521-522` | `sbx_id (= mw_sbx.id), comp_id, cls, recoverable, recovery, retried_as, ts` | **The orchestrator's diagnosis** of `mw_sbx` runs that ended in `error` or `timeout` (`diagnose_sandbox`, `orchestrator.py:1216-1220`); pruned with the other diagnoses |

- **G5-2 probes read `mw_sbx`.** "A run used postgres successfully" is a fact about runs, and that table has it.
- **G5-3's feed reads `io_sbx`.** "This team's sandbox fails as 'image' repeatedly" is a diagnosis, and that table has it. It
  joins `mw_sbx` on `sbx_id = id` for the evidence: the error text, when, which task.
- Neither table is new or duplicated.
- `io_risks` stays the only canonical risk register.

## Mechanism
- **One function per source, `orchestrator.risk_feed_<source>()`, run in the orchestrator's existing `tick()`.** No new
  thread or service. Each reads only rows changed since its last pass (a watermark kept in `io_risks` itself or the existing
  `alert_state`) and calls the existing `risk_upsert` / `risk_resolve`.
- **Field mapping** per source: severity, detection ("hq patrol <agent>", "diagnosis of run #n"), countermeasure (the source's
  own recommendation or the taxonomy's recovery), responsible (the source's owner, or `FAILURE_CLASSES` → who), mission
  (`corr` / team ref) and layer (from the canonical class).
- **Lifecycle unchanged:** open, accepted (Owner, non-critical), resolved (evidence), reopened. Approvals and credential
  verifications keep their G5-2 rules.
- **Read side:** the Overview's Mission readiness card already lists the register. It gains a filter by source; no new page.
  `GET /api/g5/risks` gains `source=`.

## Acceptance (to be detailed before implementation)
1. Every open `hq_issue` (warn+), every recurring non-own failure class, every crossed budget limit and every open ops or
   campaign alert has exactly one register row; replaying the restored backup gives counts equal to direct SQL.
2. Re-running the feeds changes nothing (idempotent).
3. Closing the source closes the risk, with evidence.
4. No source table is altered beyond read access; removing the feeds leaves the sources working as before.
5. Full suite green on SQLite and Postgres; Overview browser-checked.

## Risks of the change
- **Volume.** Diagnoses can be noisy; the recurrence threshold (3 in 24 h) keeps one row per pattern, not per run.
- **Overlap with readiness rows** (a sign-in FAIL from both a probe and diagnoses): linked by `mission` and canonical class
  and shown together. Merging them under one key is decided when the feed is built.
