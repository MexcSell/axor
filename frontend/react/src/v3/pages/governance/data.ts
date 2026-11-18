// SAMPLE data for the Governance page. Policies, roles and audit entries are illustrative; no policy engine is connected in sample mode.
import { at } from "../../data/sample";

export const LEVELS = [
  { k: "L0", name: "Observe", scope: "Read, summarize, report", human: "All mutations are human-executed", agents: 39 },
  { k: "L1", name: "Recommend", scope: "Draft and suggest changes", human: "Human executes", agents: 1 },
  { k: "L2", name: "Approved tasks", scope: "Execute bounded, authorized operations", human: "Approve consequential operations", agents: 4 },
  { k: "L3", name: "Workflow autonomy", scope: "Plan and run a multi-step mission within its charter", human: "Review exceptions, production and spend", agents: 18 },
  { k: "L4", name: "Controlled evolution", scope: "Propose new agents, tools and workflows; sandbox testing", human: "Approve policy-affecting or high-risk releases", agents: 12 },
  { k: "L5", name: "Charter autonomy", scope: "Continual improvement under defined budgets and immutable governance", human: "Retains strategic, financial, policy and security authority", agents: 3 },
];

export const CAPS = ["View everything", "Create missions", "Approve decisions", "Spend within caps", "Change budgets", "Change model routing", "Toggle self-renewal", "Edit policies", "Deploy to production", "Delete data"] as const;
export type Grant = "yes" | "approval" | "no";
const Y: Grant = "yes", A: Grant = "approval", N: Grant = "no";
export const RBAC: { role: string; who: string; grants: Grant[] }[] = [
  { role: "Owner / Admin", who: "Human, full authority", grants: [Y, Y, Y, Y, Y, Y, Y, Y, Y, A] },
  { role: "Member", who: "Human, mission work", grants: [Y, Y, Y, A, N, N, N, N, A, N] },
  { role: "General Manager (GM)", who: "Agent, strategy and control", grants: [Y, Y, N, Y, A, A, N, A, A, N] },
  { role: "Department lead", who: "Agent, department scope", grants: [Y, A, N, Y, N, N, N, N, A, N] },
  { role: "Agent", who: "Agent, mission scope only", grants: [Y, N, N, Y, N, N, N, N, N, N] },
  { role: "Viewer / Guest", who: "Human, read-only", grants: [Y, N, N, N, N, N, N, N, N, N] },
];
export const APPROVAL_CLASSES = [
  { k: "A0", name: "Automatic", examples: "Read data, draft documents, run tests in a sandbox", who: "No approval; logged", sla: "n/a" },
  { k: "A1", name: "Notify", examples: "Open a pull request, spend under the daily budget", who: "Owner is notified, can veto", sla: "24 h" },
  { k: "A2", name: "Approve", examples: "Merge to main, raise a cap by more than 10%, add an agent", who: "Owner or delegated admin", sla: "4 h" },
  { k: "A3", name: "Fresh approval", examples: "Public deployment, purchasing, access changes, deleting data, constitution changes, issuing credentials", who: "Owner, fresh each time, full audit trail", sla: "No auto-approve" },
];
export const ESCALATION = ["Agent raises a request with evidence", "Department lead reviews (agent)", "GM consolidates and recommends", "Human approver decides (owner or admin)", "If unanswered past the SLA: reminder, then the task pauses safely. It never proceeds on silence."];

export interface Policy { id: string; name: string; status: "Active" | "Draft" | "Review"; version: string; updated: string; owner: string; code: string }
export const POLICIES: Policy[] = [
  { id: "P-01", name: "L3 - Manage Workflows", status: "Active", version: "1.4", updated: at(-1, -2), owner: "Owner", code: "policy: l3-manage-workflows\nversion: 1.4\nscope: mission\nallow:\n  - plan_and_run_multi_step_missions\nrequire_human:\n  - production_release\n  - spend_above_daily_budget\ndeny:\n  - change_own_permissions" },
  { id: "P-02", name: "L4 - Propose Evolution", status: "Active", version: "2.1", updated: at(-2, -5), owner: "Owner", code: "policy: l4-propose-evolution\nversion: 2.1\nscope: organization\nallow:\n  - propose_agent_candidates\n  - run_sandbox_experiments\nrequire_human:\n  - promote_candidate_to_baseline\ndeny:\n  - modify_evaluation_thresholds\n  - modify_own_approver" },
  { id: "P-03", name: "L5 - Company Optimization", status: "Review", version: "0.9", updated: at(-3, -1), owner: "Owner", code: "policy: l5-company-optimization\nversion: 0.9  # draft, not enforced\nscope: organization\nallow:\n  - continuous_improvement_within_budget\nlimits:\n  max_monthly_experiment_spend: 300\n  max_concurrent_experiments: 3\nrequire_human:\n  - strategic_financial_policy_security_decisions" },
  { id: "P-04", name: "Self-Renewal", status: "Active", version: "1.2", updated: at(0, -8), owner: "Admin", code: "policy: self-renewal\nversion: 1.2\nenabled_by: admin_only\nwhen_on:\n  - continuous_proposals_and_experiments\n  - within_budget_and_safety_gates\nwhen_off:\n  - improvements_only_during_mission_work\ndeny:\n  - unrestricted_production_rewrite" },
  { id: "P-05", name: "External content handling", status: "Active", version: "1.0", updated: at(-6), owner: "Security", code: "policy: external-content\nversion: 1.0\ntreat_as: untrusted_input\nchecks:\n  - prompt_injection_scan\n  - license_check\n  - provenance_recorded\nlearn_only_after: human_verification" },
  { id: "P-06", name: "Model routing", status: "Active", version: "3.0", updated: at(-4), owner: "Admin", code: "policy: model-routing\nversion: 3.0\nroles:\n  architecture: gpt\n  code: claude-code\n  research: [gpt, claude]\nfallback: required\nno_provider_keys_in_browser: true" },
  { id: "P-07", name: "Budget caps", status: "Active", version: "2.2", updated: at(-5), owner: "Finance", code: "policy: budget-caps\nversion: 2.2\nhard_cap: department_monthly\nalert_at: [0.8, 0.95]\nraise_cap_over_10pct: requires_owner" },
];
export const CONSTITUTION = [
  "The owner retains strategic, financial, policy and security authority.",
  "No agent can grant itself permissions or approve its own change.",
  "Evaluation thresholds and governance policy are outside any candidate's reach.",
  "Effective permission is the intersection of organization, mission, agent, tool and action limits, never their union.",
  "High-risk actions always need fresh approval and a complete audit trail.",
  "Stop controls work independently of the agent runtime.",
];

export const TIMELINE = [
  { t: "Policy Update", d: "Policy (L4)", at: at(-6), k: "policy" }, { t: "Access Change", d: "Access (+3)", at: at(-5), k: "access" }, { t: "Model Route", d: "Model (Analysis)", at: at(-4), k: "model" },
  { t: "Audit Check", d: "Audit (98.4%)", at: at(-3), k: "audit" }, { t: "Policy Update", d: "Policy (L5)", at: at(-2), k: "policy" }, { t: "Access Change", d: "Access (-2)", at: at(-1), k: "access" }, { t: "Self-Renewal", d: "Self-Renewal (OK)", at: at(0, -2), k: "renewal" },
];
export const AUDIT_EXTRA = [
  { id: "G-7", at: at(0, -1.2), actor: "DEV-01", action: "Model routing updated (Analysis)", target: "routing/analysis", result: "success", cat: "model" },
  { id: "G-6", at: at(0, -1.9), actor: "RCH-01", action: "Policy L4 updated to v2.1", target: "policy/P-02", result: "success", cat: "policy" },
  { id: "G-5", at: at(0, -2.6), actor: "GM", action: "Budget reallocated (+$50 to R&D)", target: "budget/development", result: "success", cat: "budget" },
  { id: "G-4", at: at(-1, -1), actor: "thomas", action: "Autonomy level changed (L3 to L4)", target: "settings/autonomy", result: "success", cat: "autonomy" },
  { id: "G-3", at: at(-1, -4), actor: "SYS", action: "Self-renewal check completed", target: "self-renewal", result: "success", cat: "renewal" },
  { id: "G-2", at: at(-2, -3), actor: "admin", action: "Access granted: 3 viewers", target: "rbac/viewer", result: "success", cat: "access" },
  { id: "G-1", at: at(-3, -2), actor: "DEV-02", action: "Attempted to change own permissions", target: "rbac/agent", result: "blocked", cat: "access" },
];
export const VERIFIERS = [
  { id: "v1", name: "Independent QA agents (internal)", kind: "Internal", status: "Active", note: "Separate from the builders; cannot approve their own work." },
  { id: "v2", name: "External inspection company data", kind: "External", status: "Not connected (sample)", note: "Third-party inspection results used as an independent check on safety and compliance. Treated as untrusted until verified." },
  { id: "v3", name: "Security scanner (SAST / dependency)", kind: "Tool", status: "Active", note: "Runs in the sandbox before any promotion." },
];
export const GATES = ["Reproducible results", "No critical security regression", "No unapproved permission expansion", "Quality at or above the approved threshold", "Cost within budget", "Production monitoring plan"];
export const STOPS = [
  { id: "freeze", label: "Freeze evolution", detail: "Stops all candidate experiments and promotions. Running missions continue.", tone: "warn" },
  { id: "spend", label: "Suspend global spending", detail: "Blocks all new model calls and compute spend company-wide.", tone: "warn" },
  { id: "quarantine", label: "Quarantine an agent", detail: "Isolates one agent: no tools, no messages, state preserved.", tone: "warn" },
  { id: "mission", label: "Stop a mission", detail: "Pauses a mission at the next safe checkpoint.", tone: "warn" },
  { id: "kill", label: "Kill switch (all agents)", detail: "Stops every agent immediately. Needs the owner to restart. Work is kept for safe recovery.", tone: "bad" },
] as const;
