// SAMPLE company dataset. Every screen that renders this shows a "Sample" badge: these are illustrative values taken from
// the reference mockups (docs/ui-v3/reference), NOT live telemetry. Dates are relative to "now" so Today markers stay true.
import type {
  AgentIdentity, AgentInstance, AgentVersion, Approval, Branch, Candidate, Department, Event, Experience, KnowledgeItem, MergeRequest,
  Mentoring, Message, Mission, ModelReg, NewsItem, NewsSource, Notice, Release, Settings, Task, Thread,
} from "../domain/types";
import type { Role } from "../ui/Avatar";
import type { Status } from "../ui/kit";

const BASE = (() => { const d = new Date(); d.setSeconds(0, 0); return d.getTime(); })();
const H = 3600e3, D = 24 * H;
export const at = (days: number, hours = 0) => new Date(BASE + days * D + hours * H).toISOString();
const hex = (n: number, len = 7) => { let s = ""; let x = Math.imul(n | 0, 2654435761) >>> 0; while (s.length < len) { x = (Math.imul(x, 1103515245) + 12345) >>> 0; s += ((x >>> 16) % 16).toString(16); } return s; };
export const sha = (seed: string, len = 7) => hex([...seed].reduce((a, c) => (Math.imul(a, 31) + c.charCodeAt(0)) | 0, 7), len);

/* ---------------- departments + agents (38 active) ---------------- */
export const DEPARTMENTS: Department[] = [
  { id: "research", name: "Research", role: "research", head: "RCH-01", budget: 520, spent: 388, performance: 94.1, backlog: 6 },
  { id: "development", name: "Development", role: "developer", head: "DEV-01", budget: 980, spent: 812, performance: 96.8, backlog: 11 },
  { id: "operations", name: "Operations", role: "ops", head: "OPS-01", budget: 410, spent: 296, performance: 95.2, backlog: 5 },
  { id: "qa", name: "QA / Verifier", role: "qa", head: "QA-01", budget: 360, spent: 241, performance: 97.9, backlog: 4 },
  { id: "knowledge", name: "Knowledge", role: "knowledge", head: "KNW-01", budget: 240, spent: 163, performance: 93.6, backlog: 3 },
  { id: "finance", name: "Finance", role: "finance", head: "FIN-01", budget: 140, spent: 92, performance: 98.4, backlog: 1 },
  { id: "deployment", name: "Deployment", role: "deploy", head: "DEP-01", budget: 230, spent: 176, performance: 95.7, backlog: 2 },
];
const DEPT_SIZE: Record<string, number> = { research: 6, development: 8, operations: 7, qa: 5, knowledge: 4, finance: 3, deployment: 3 };
const PREFIX: Record<string, string> = { research: "RCH", development: "DEV", operations: "OPS", qa: "QA", knowledge: "KNW", finance: "FIN", deployment: "DEP" };
const MODELS_BY_ROLE: Partial<Record<Role, string[]>> = {
  gm: ["gpt-6.1", "claude-opus-5-5"], architect: ["gpt-6.1"], developer: ["claude-code (claude-opus-5-5)"], research: ["gpt-6.1", "claude-sonnet-5-5"],
  qa: ["claude-sonnet-5-5"], knowledge: ["claude-sonnet-5-5", "text-embedding-4"], ops: ["claude-haiku-5-5"], finance: ["claude-haiku-5-5"], deploy: ["claude-sonnet-5-5"],
  mentor: ["claude-opus-5-5"], strategist: ["gpt-6.1"], security: ["claude-opus-5-5"],
};
const TOOLS_BY_ROLE: Partial<Record<Role, string[]>> = {
  gm: ["planner", "delegate", "org-designer", "approvals"], architect: ["design-docs", "diagram", "review"], developer: ["git", "editor", "test-runner", "ci"],
  research: ["web-search", "fetch", "rag", "pdf"], qa: ["test-runner", "benchmark", "security-scan"], knowledge: ["rag", "index", "dedupe"],
  ops: ["k8s-read", "metrics", "alerts"], finance: ["ledger", "budget"], deploy: ["ci", "preview", "release"], mentor: ["curriculum", "exercise"], security: ["scanner", "policy"],
};
const SKILLS_BY_ROLE: Partial<Record<Role, string[]>> = {
  gm: ["Planning", "Delegation", "Risk triage", "Synthesis", "Org design"], developer: ["TypeScript", "Python", "Refactoring", "Testing", "CI/CD"],
  research: ["Web research", "Synthesis", "Citations", "Data analysis", "Summaries"], qa: ["Test design", "Regression", "Security", "Benchmarks", "Edge cases"],
  knowledge: ["Indexing", "Dedupe", "Provenance", "Taxonomy", "Retrieval"], ops: ["Monitoring", "Incidents", "Capacity", "Runbooks", "Cost"],
  finance: ["Budgeting", "Forecast", "Ledger", "Alerts", "Unit economics"], deploy: ["Builds", "Previews", "Canary", "Rollback", "Releases"],
  architect: ["System design", "UI design", "Specs", "Reviews", "Trade-offs"], mentor: ["Curriculum", "Coaching", "Assessment", "Feedback", "Examples"],
  strategist: ["Strategy", "Markets", "Roadmaps", "OKRs", "Pricing"], security: ["Threat models", "Secrets", "Policy", "Audit", "Pen-test"],
};
function mkAgent(id: string, name: string, role: Role, title: string, dept: string, reportsTo: string | null, baseline: string, ix: number, extra: Partial<AgentIdentity> = {}): AgentIdentity {
  const sk = SKILLS_BY_ROLE[role] ?? SKILLS_BY_ROLE.developer!;
  return {
    id, name, role, title, dept, reportsTo, baseline, models: MODELS_BY_ROLE[role] ?? ["claude-sonnet-5-5"], tools: TOOLS_BY_ROLE[role] ?? ["rag"],
    skills: sk.map((n, k) => ({ name: n, level: 62 + ((ix * 7 + k * 11) % 36) })), permissions: role === "gm" ? ["delegate", "propose-org-change", "request-approval"] : ["mission-scope"],
    status: (["active", "busy", "active", "idle"] as const)[ix % 4], successRate: 88 + ((ix * 13) % 11) + (ix % 3) * .3, tasksDone: 40 + ix * 17 % 260,
    costPerTask: +(0.18 + (ix % 7) * .07).toFixed(2), latencyS: 12 + (ix * 5) % 40, qualified: sk.slice(0, 3), created: at(-120 + ix), ...extra,
  };
}
export const AGENTS: AgentIdentity[] = (() => {
  const list: AgentIdentity[] = [
    mkAgent("GM", "General Manager", "gm", "Strategy · Planning · Control", "executive", null, "v3.2.0", 0, { status: "busy", successRate: 97.3 }),
    mkAgent("ARC-01", "Architect (GPT)", "architect", "Architecture & product design", "executive", "GM", "v1.8.2", 1, { models: ["gpt-6.1"] }),
    // The readme's "associate governor": the GM's deputy, who reviews department reports and summarises them for the GM.
    mkAgent("DGM", "Deputy General Manager", "strategist", "Associate governor · reviews & reports", "executive", "GM", "v1.4.0", 40, { status: "active", models: ["gpt-6.1", "claude-opus-5-5"] }),
  ];
  let ix = 2;
  for (const d of DEPARTMENTS) {
    for (let k = 1; k <= DEPT_SIZE[d.id]; k++) {
      const id = `${PREFIX[d.id]}-${String(k).padStart(2, "0")}`;
      const lead = k === 1;
      const name = lead ? `${d.name.replace(" / Verifier", "")} Lead` : `${d.name.replace(" / Verifier", "")} Agent ${k}`;
      const role: Role = d.id === "development" && k === 8 ? "security" : d.role;
      list.push(mkAgent(id, id === "DEV-01" ? "Development Agent" : name, role, lead ? `${d.name} department head` : `${d.name} specialist`, d.id,
        lead ? "GM" : `${PREFIX[d.id]}-01`, lead ? ["v2.1.4", "v2.3.0", "v1.9.0", "v2.0.2", "v1.6.1", "v1.2.0", "v1.4.3"][DEPARTMENTS.indexOf(d)] : `v1.${k}.${ix % 5}`, ix,
        id === "DEV-01" ? { candidate: "v2.4.0", status: "busy" } : id === "QA-01" ? { candidate: "v2.1.0" } : id === "RCH-01" ? { candidate: "v2.2.0" } : {}));
      ix++;
    }
  }
  list.push(mkAgent("MNT-01", "Mentor", "mentor", "Agent training & curriculum", "knowledge", "KNW-01", "v1.1.0", ix++));
  return list;
})(); // GM + ARC + DGM + 36 dept + mentor = 40; 38 active (two offline below)
AGENTS[AGENTS.length - 3].status = "offline";
AGENTS[AGENTS.length - 6].status = "offline";

/* ---------------- missions (12) ---------------- */
type MRow = [string, string, string, number, string, string, number, number, number, string, number, number, Status, string, string, Mission["priority"]];
// title, summary, owner dept, progress, version, nextEdition, issues, approvalsDone, approvalsTotal, ?, dueDays, decisionsPending, status, icon, color, priority
const ROWS: MRow[] = [
  ["AXoR Platform Upgrade", "Enhance core platform and AI agent OS (v2.0)", "development", 76, "v1.4.0", "v1.5.0", 1, 3, 5, "", 3, 1, "running", "star", "#f2b53a", "High"],
  ["Agent Evaluation Framework", "Build QA and performance evaluation system", "qa", 52, "v0.9.2", "v1.0.0", 0, 1, 2, "", 7, 0, "running", "box", "#a77bff", "High"],
  ["Research Knowledge Engine", "Organize and reuse research knowledge", "research", 91, "v1.3.1", "v1.4.0", 0, 2, 2, "", 1, 0, "review", "book", "#22d3ee", "Medium"],
  ["Business Opportunity Analysis", "Identify new product and revenue opportunities", "operations", 34, "v0.3.0", "v0.4.0", 2, 0, 2, "", 10, 1, "blocked", "chart", "#ff4d5e", "Medium"],
  ["Self-Evolution Engine", "Continuous agent self-improvement", "knowledge", 68, "v0.8.5", "v0.9.0", 1, 2, 3, "", 15, 1, "running", "infinity", "#3b8cff", "High"],
  ["Mobile App Development", "Build AXoR companion mobile app (iOS/Android)", "development", 42, "v0.5.0", "v0.6.0", 1, 1, 3, "", 17, 0, "running", "phone", "#2fd27a", "Medium"],
  ["Data Pipeline Enhancement", "Improve data ingestion and processing efficiency", "finance", 100, "v1.1.0", "v1.1.1", 0, 3, 3, "", -2, 0, "done", "pipe", "#2fd27a", "Low"],
  ["Company Knowledge Integration", "Unify internal and external knowledge sources", "knowledge", 57, "v0.6.2", "v0.7.0", 1, 1, 2, "", 8, 0, "running", "layers", "#a77bff", "Medium"],
  ["UI/UX Redesign", "Modernize product experience and design system", "operations", 28, "v0.4.1", "v0.5.0", 3, 0, 2, "", 12, 1, "blocked", "palette", "#e879f9", "High"],
  ["QA Automation Suite", "Automated testing and quality assurance pipeline", "qa", 83, "v1.0.3", "v1.1.0", 0, 2, 2, "", 5, 0, "review", "shield", "#2fd27a", "Medium"],
  ["Infrastructure Scalability", "Scale infrastructure for higher agent load", "operations", 99, "v1.2.0", "v1.2.1", 0, 3, 3, "", 2, 0, "review", "server", "#94a3b8", "Low"],
  ["Deployment & Release Automation", "Automate build, test, and production release", "deployment", 68, "v0.8.4", "v0.9.0", 1, 1, 2, "", 11, 0, "running", "rocket", "#fb7185", "Medium"],
];
const STAGE_FOR = (p: number): Mission["stage"] => p >= 99 ? "deploy" : p >= 85 ? "verify" : p >= 70 ? "test" : p >= 40 ? "develop" : p >= 20 ? "research" : "plan";
export const MISSIONS: Mission[] = ROWS.map((r, i) => ({
  id: `M-${String(i + 1).padStart(3, "0")}`, title: r[0], summary: r[1], workstream: r[2], progress: r[3], version: r[4],
  issuesOpen: r[6], decisionsPending: r[11], status: r[12], icon: r[13], color: r[14], priority: r[15],
  stage: STAGE_FOR(r[3]), progressBasis: "milestones", dueAt: at(r[10], 8 - (i % 3)), dueKind: i % 4 === 3 ? "estimated" : "scheduled",
  nextEditionAt: r[3] >= 100 ? null : at(Math.max(1, Math.round(r[10] / 2)), 9 - 10.4 + (i % 2)), nextEditionKind: r[3] >= 100 ? "not_scheduled" : i % 3 === 2 ? "estimated" : "scheduled",
  startedAt: at(-6 - i * 2, -1.4), lastActivityAt: at(0, -(i * .7)), owner: i % 2 ? "thomas" : "admin",
  risk: r[12] === "blocked" ? "high" : r[6] > 0 ? "medium" : "low", budget: { limit: 400 + i * 35, spent: Math.round((400 + i * 35) * r[3] / 120) },
  repo: { url: `https://github.com/axor-company/${r[0].toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-$/, "")}`, branch: `mission/M-${String(i + 1).padStart(3, "0")}/main`, created: i % 3 === 0 },
}));
// Issues/approvals (a/b) per mission for the table
export const APPROVAL_COUNTS: Record<string, [number, number]> = Object.fromEntries(ROWS.map((r, i) => [`M-${String(i + 1).padStart(3, "0")}`, [r[7], r[8]]]));
export const NEXT_EDITION_LABEL: Record<string, string> = Object.fromEntries(ROWS.map((r, i) => [`M-${String(i + 1).padStart(3, "0")}`, r[5]]));

/* ---------------- tasks (M-001 in full; other missions lighter) ---------------- */
function T(missionId: string, id: string, title: string, desc: string, status: Status, progress: number, instanceId: string, deps: string[], s: number, e: number, extra: Partial<Task> = {}): Task {
  return {
    id, missionId, title, phase: desc, desc, status, progress, instanceId, deps, start: at(s, 9 - 10.4), end: at(e, 18 - 10.4), retries: 0, priority: "Medium",
    acceptance: [`${title}: acceptance tests pass`, "Independent QA sign-off recorded", "Evidence linked to the task"],
    evidence: status === "done" || status === "passed" ? [`ci/run-${sha(id, 5)} passed`, `report-${id}.md`] : [], history: [
      { at: at(s, -1), text: `Created by GM, assigned to ${instanceId}` }, ...(status !== "queued" ? [{ at: at(s, 0), text: "Started" }] : []),
      ...(status === "done" ? [{ at: at(e, 0), text: "Verified by QA-01 and closed" }] : []),
    ], ...extra,
  };
}
const m1 = "M-001";
export const TASKS: Task[] = [
  // M-001 mirrors reference 30-3 (Task Flow — Kanban & Timeline).
  T(m1, "T-001", "Requirements & Plan", "Scope, design & milestones", "done", 100, "GM@M-001", [], -6, -5, { critical: true, priority: "High", meta: { p: "P0", hours: 0, short: "Plan" } }),
  T(m1, "T-002", "Architecture Design", "System design & review", "done", 100, "DEV-01@M-001", ["T-001"], -4.5, -3, { critical: true, priority: "High", meta: { p: "P0", hours: 0, short: "Arch" } }),
  T(m1, "T-004", "Research & Evaluation", "Solutions & benchmarking", "done", 100, "RCH-01@M-001", [], -6, -4.5, { priority: "Medium", meta: { p: "P1", hours: 0, short: "Research" } }),
  T(m1, "T-007", "Platform Core v2.4", "Refactor core services & APIs", "running", 72, "DEV-01@M-001", ["T-002"], -3, 1.5, { critical: true, priority: "High", outputVersion: "v1.5.0", meta: { p: "P0", hours: 16, short: "Core v2.4" } }),
  T(m1, "T-008", "Agent Framework", "Multi-agent orchestration", "running", 68, "OPS-01@M-001", ["T-002"], -3, 2.5, { priority: "High", meta: { p: "P0", hours: 14, short: "Agent FW" } }),
  T(m1, "T-009", "Data Pipeline Enh.", "ETL, quality & reliability", "blocked", 60, "FIN-01@M-001", ["T-002"], -2, 1, { priority: "Medium", blocker: { text: "B-001 External API rate limit" }, meta: { p: "P1", hours: 20, short: "Data Pipe" } }),
  T(m1, "T-005", "QA Automation", "Expand test coverage to 95%", "review", 91, "QA-01@M-001", ["T-007", "T-008"], 0.5, 2.5, { critical: true, priority: "Medium", blocker: { text: "B-002 Test env. capacity" }, meta: { p: "P1", hours: 4, short: "QA Auto" } }),
  T(m1, "T-006", "Performance Tuning", "Latency & throughput (≥2x)", "review", 87, "OPS-02@M-001", ["T-007"], 1, 3.5, { critical: true, priority: "Medium", meta: { p: "P1", hours: 6, short: "Perf Tune" } }),
  T(m1, "T-013", "Mobile SDK Upgrade", "Story: Cross-platform SDK v2.4", "queued", 0, "DEV-03@M-001", ["T-009"], 2, 4.5, { priority: "Low", meta: { p: "P2", hours: 8, short: "SDK Upg" } }),
  T(m1, "T-014", "Usage Analytics v2", "Event model & dashboards", "queued", 0, "RCH-02@M-001", ["T-009"], 2.5, 5, { priority: "Low", meta: { p: "P2", hours: 12, short: "Analytics" } }),
  T(m1, "T-015", "Doc Center Overhaul", "Restructure & auto-sync", "queued", 0, "KNW-01@M-001", ["T-008"], 3, 5.5, { priority: "Low", meta: { p: "P3", hours: 10, short: "Doc Center" } }),
  T(m1, "T-016", "Community Integr.", "Discourse & SSO integration", "queued", 0, "OPS-03@M-001", ["T-008"], 3.5, 6, { priority: "Low", meta: { p: "P3", hours: 12, short: "Community" } }),
  T(m1, "T-010", "Release v2.4.0", "Deploy to production (needs your approval)", "waiting_user", 0, "DEP-01@M-001", ["T-005", "T-006"], 4, 4.4, { critical: true, priority: "High", blocker: { text: "Production release needs your approval", approvalId: "A-101" }, meta: { p: "P0", hours: 2, short: "Release", milestone: true } }),
  ...MISSIONS.slice(1).flatMap((m, i) => {
    const base = -5 - i;
    const st = (k: number): Status => (m.progress >= (k + 1) * 25 ? "done" : m.progress >= k * 25 ? (m.status === "blocked" ? "blocked" : "running") : "queued");
    const lead = `${PREFIX[m.workstream] ?? "DEV"}-01@${m.id}`;
    return [
      T(m.id, `${m.id}-T1`, "Plan & charter", "1. Planning", st(0), Math.min(100, m.progress * 4), `GM@${m.id}`, [], base, base + 2, { critical: true }),
      T(m.id, `${m.id}-T2`, "Research & data", "2. Research", st(1), Math.max(0, Math.min(100, (m.progress - 25) * 4)), `RCH-0${(i % 6) + 1}@${m.id}`, [`${m.id}-T1`], base + 2, base + 5),
      T(m.id, `${m.id}-T3`, "Build", "3. Development", st(2), Math.max(0, Math.min(100, (m.progress - 50) * 4)), lead, [`${m.id}-T2`], base + 4, base + 9, { critical: true }),
      T(m.id, `${m.id}-T4`, "Verify & release", "4. Test & QA", st(3), Math.max(0, Math.min(100, (m.progress - 75) * 4)), `QA-0${(i % 5) + 1}@${m.id}`, [`${m.id}-T3`], base + 9, base + 12),
    ];
  }),
];

export const BLOCKERS = [
  { id: "B-001", missionId: "M-001", title: "External API rate limit", blocks: ["T-009", "T-014"], severity: "High" as const, owner: "OPS-01", approvalId: null as string | null },
  { id: "B-002", missionId: "M-001", title: "Test env. capacity", blocks: ["T-005"], severity: "High" as const, owner: "QA-01", approvalId: "A-102" as string | null },
];
export const RELEASE_CHECKLIST = [
  { label: "Core platform (≥ v2.4.0)", done: true, value: "" }, { label: "Agent framework (multi-agent)", done: true, value: "" },
  { label: "Data pipeline enhancement", done: true, value: "" }, { label: "QA & performance (≥ 2×)", done: false, value: "87%" },
  { label: "Documentation & release notes", done: false, value: "0%" }, { label: "Deploy to production", done: false, value: "" },
];

/* ---------------- mission instances (same agent in several missions; AG-AT-01) ---------------- */
export const INSTANCES: AgentInstance[] = (() => {
  const list: AgentInstance[] = []; const seen = new Set<string>();
  for (const t of TASKS) {
    if (seen.has(t.instanceId)) continue; seen.add(t.instanceId);
    const [agentId, missionId] = t.instanceId.split("@");
    const ag = AGENTS.find((a) => a.id === agentId); if (!ag) continue;
    const m = MISSIONS.find((x) => x.id === missionId)!;
    const mine = TASKS.filter((x) => x.instanceId === t.instanceId);
    list.push({
      id: t.instanceId, agentId, missionId, pinnedVersion: ag.baseline, branch: `agent/${agentId}/mission/${missionId}`,
      status: mine.some((x) => x.status === "blocked") ? "blocked" : mine.some((x) => x.status === "running" || x.status === "verifying") ? "running" : mine.every((x) => x.status === "done") ? "done" : "queued",
      progress: Math.round(mine.reduce((s, x) => s + x.progress, 0) / mine.length), tasks: mine.length,
      supervisor: agentId === "GM" ? null : `GM@${missionId}`, startedAt: m.startedAt, errors: mine.filter((x) => x.status === "failed").length, spend: +(mine.length * 6.4).toFixed(1),
    });
  }
  list.push({ id: "DGM@M-001", agentId: "DGM", missionId: "M-001", pinnedVersion: "v1.4.0", branch: "agent/DGM/mission/M-001", status: "running", progress: 70, tasks: 0, supervisor: "GM@M-001", startedAt: at(-6), errors: 0, spend: 12.8 });
  return list;
})();

/* ---------------- versions of agents ---------------- */
export const AGENT_VERSIONS: AgentVersion[] = [
  { agentId: "DEV-01", version: "v2.1.0", parent: "v2.0.2", at: at(-60), status: "retired", changes: ["Planner prompt v4", "pytest skill"], score: 81.2, kind: ["prompt", "skill"] },
  { agentId: "DEV-01", version: "v2.2.0", parent: "v2.1.0", at: at(-38), status: "retired", changes: ["Refactoring checklist from M-007"], score: 84.0, kind: ["procedure"] },
  { agentId: "DEV-01", version: "v2.2.1", parent: "v2.2.0", at: at(-30), status: "rolled_back", changes: ["Aggressive caching (regressed latency p95 +31%)"], score: 79.5, kind: ["code"] },
  { agentId: "DEV-01", version: "v2.3.0", parent: "v2.2.0", at: at(-14), status: "baseline", changes: ["Schema-validation routine (from M-011)", "CI fixer skill"], score: 86.9, kind: ["code", "skill"] },
  { agentId: "DEV-01", version: "v2.4.0", parent: "v2.3.0", at: at(-1), status: "candidate", changes: ["Build optimisation (24% faster, from M-001)", "Task decomposition prompt v6", "Resource efficiency heuristics"], score: 103.1, kind: ["code", "prompt", "procedure"] },
];
export const EXPERIENCES: Experience[] = [
  { id: "X-1", agentId: "DEV-01", missionId: "M-001", at: at(0, -2), lesson: "Parallelise webpack-free Vite builds per package; 24% faster CI", kind: "code", confidence: .92, generalization: .81, eligible: true, evidence: "ci/run-8812 vs run-8790" },
  { id: "X-2", agentId: "DEV-01", missionId: "M-006", at: at(-1, -5), lesson: "React Native release builds need explicit Hermes flag on Android", kind: "verified", confidence: .88, generalization: .55, eligible: true, evidence: "build log M-006#42" },
  { id: "X-3", agentId: "DEV-01", missionId: "M-001", at: at(-2), lesson: "Customer portal copy (mission-private)", kind: "private", confidence: 1, generalization: 0, eligible: false, evidence: "excluded by privacy filter (AG-004)" },
  { id: "X-4", agentId: "DEV-01", missionId: "M-012", at: at(-3), lesson: "Retry flaky e2e at most twice; quarantine after", kind: "tentative", confidence: .64, generalization: .7, eligible: false, evidence: "3 observations, needs 5" },
  { id: "X-5", agentId: "DEV-01", missionId: "M-001", at: at(-4), lesson: "Token found in fixture; rotate + redact", kind: "security", confidence: .99, generalization: .9, eligible: true, evidence: "secret-scan #77" },
];

/* ---------------- threads + messages (CTRL-002..006) ---------------- */
const th = (id: string, a: string, b: string, kind: Thread["kind"], unread: number, h: number, status: Status = "running"): Thread => ({ id, missionId: m1, a, b, kind, unread, lastAt: at(0, h), status });
export const THREADS: Thread[] = [
  th("TH-1", "GM", "DEV-01", "subordinate", 0, 0), th("TH-2", "DEV-01", "QA-01", "peer", 2, -.43), th("TH-3", "RCH-01", "KNW-01", "peer", 0, -.88),
  th("TH-4", "user", "GM", "user", 1, -1.6, "waiting_user"), th("TH-5", "GM", "ARC-01", "subordinate", 0, -2.2, "done"), th("TH-6", "DEV-02", "DEV-01", "superior", 0, -1.1),
  th("TH-7", "GM", "QA-01", "subordinate", 0, -.2), th("TH-8", "user", "DEV-01", "user", 0, -3.5, "done"), th("TH-9", "DEP-01", "GM", "superior", 1, -.9, "waiting_user"),
  th("TH-10", "DGM", "GM", "superior", 1, -.3),
];
let mid = 0;
const msg = (threadId: string, from: string, to: string, h: number, kind: Message["kind"], text: string, condensed: boolean, state?: Status, attachments?: string[]): Message =>
  ({ id: `MSG-${++mid}`, threadId, missionId: m1, from, to, at: at(0, h), kind, text, condensed, state, attachments });
export const MESSAGES: Message[] = [
  msg("TH-1", "GM", "DEV-01", -2, "instruction", "Mission M-001 assigned: own Core Integration and the build pipeline. Acceptance: CI green, build time -20%.", true, "done"),
  msg("TH-1", "DEV-01", "GM", -1.9, "plan", "Plan: 1) profile the build, 2) split vendor chunks, 3) parallelise package builds, 4) cache test fixtures.", false),
  msg("TH-1", "DEV-01", "GM", -1.2, "tool", "Ran `npm run build --profile` on branch mission/M-001/build-speed (exit 0, 182 s).", false, "done"),
  msg("TH-1", "GM", "DEV-01", -.02, "instruction", "Please optimize the build process and reduce execution time by at least 20%.", true, "done"),
  msg("TH-1", "DEV-01", "GM", .03, "report", "The build time is now 24% faster. Shall I run a full test and create a PR?", true, "passed", ["build-profile.json"]),
  msg("TH-1", "DEV-01", "GM", .04, "result", "Result: CI build 182 s → 138 s (−24.2%). Evidence: ci/run-8812.", true, "passed"),
  msg("TH-2", "DEV-01", "QA-01", -.6, "message", "PR #112 is ready for the regression suite. Focus on the agent API contracts.", true),
  msg("TH-2", "QA-01", "DEV-01", -.45, "report", "Regression 412/418 passed. 6 failures on Safari e2e (flaky). Retrying with quarantine.", true, "running"),
  msg("TH-2", "QA-01", "DEV-01", -.43, "tool", "test-runner --suite regression --browser safari --retries 2", false, "failed"),
  msg("TH-3", "RCH-01", "KNW-01", -.9, "report", "Research report #386 is updated with 14 new sources (3 contradicting). Please index and flag conflicts.", true, "done"),
  msg("TH-3", "KNW-01", "RCH-01", -.88, "result", "Indexed 14 sources; 3 conflicts sent to the Knowledge Review queue.", true, "passed"),
  msg("TH-4", "user", "GM", -1.7, "instruction", "Prioritise the UI redesign; I want to see a preview before Friday.", true, "done"),
  msg("TH-4", "GM", "user", -1.6, "report", "Re-planned: UI Redesign moved onto the critical path. Preview v1.5.0-rc is scheduled for Thursday 09:00. One decision needs you: approve the external security scan (A-104).", true, "waiting_user"),
  msg("TH-5", "GM", "ARC-01", -2.4, "instruction", "Design the v2.0 module boundaries and the theme token contract.", true, "done"),
  msg("TH-5", "ARC-01", "GM", -2.2, "report", "Architecture spec v2.0 delivered: 6 modules, token schema v1, migration plan. Reviewed by DEV-01.", true, "passed", ["arch-v2.pdf"]),
  msg("TH-6", "DEV-01", "DEV-02", -1.3, "instruction", "Take UI Redesign; use the new tokens from ARC-01's spec.", true, "done"),
  msg("TH-6", "DEV-02", "DEV-01", -1.1, "report", "UI Redesign 72%: shell, panels, tabs done; graphs in progress.", true, "running"),
  msg("TH-7", "GM", "QA-01", -.25, "instruction", "Verify v2.4.0-rc1 independently; you are the verifier, DEV-01 is the author.", true, "running"),
  msg("TH-7", "QA-01", "GM", -.2, "report", "Started test run v2.4.0-rc1 (418 cases, security suite included).", true, "running"),
  msg("TH-8", "user", "DEV-01", -3.6, "instruction", "Explain why the Safari tests fail.", true, "done"),
  msg("TH-8", "DEV-01", "user", -3.5, "report", "A timing race in the chat composer focus. Fix is in PR #113.", true, "done"),
  msg("TH-9", "DEP-01", "GM", -1, "report", "Release v1.5.0 staged. Production promotion needs the owner's approval (A-101).", true, "waiting_user"),
  msg("TH-10", "GM", "DGM", -4, "instruction", "Review every department report for M-001 and send me a consolidated risk summary twice a day.", true, "done"),
  msg("TH-10", "DGM", "GM", -2.8, "report", "Morning summary: 3 tasks in review, 2 blockers (API rate limit, test capacity). Recommend hiring 5 QA evaluation agents; drafted as A-102.", true, "done"),
  msg("TH-10", "DGM", "GM", -.3, "report", "Afternoon summary: build 24% faster (DEV-01), Safari e2e quarantined, release v2.4.0 ready pending owner approval (A-101) and security scan consent (A-104).", true, "passed"),
  msg("TH-1", "GM", "DEV-01", -1.95, "thought", "GM note: build speed is on the critical path for the v1.5.0 edition; accept DEV-01's plan, ask QA-01 for an independent check.", false),
];
export const GM_THOUGHTS = [
  { at: at(0, -2.5), text: "Mission M-001 is 76% by weighted milestones. The critical path runs through UI Redesign → QA & Test → Release v1.5.0." },
  { at: at(0, -1.95), text: "Accepting DEV-01's build plan; QA-01 verifies independently (author ≠ verifier)." },
  { at: at(0, -1.6), text: "Owner asked for a preview before Friday: moved UI Redesign up, scheduled preview rc for Thursday 09:00." },
  { at: at(0, -.5), text: "Two items need the owner: production release (A-101) and the external security scan (A-104). Everything else I resolve." },
  { at: at(0, -.1), text: "Deputy GM's afternoon summary accepted. Proposal: add 5 evaluation agents to QA for the next edition (cost +$320/mo) → sent to the owner as A-102." },
];

/* ---------------- approvals / decision inbox ---------------- */
export const APPROVALS: Approval[] = [
  { id: "A-101", missionId: m1, ref: "DEV-5879", title: "Approve v2.4.0 release to production", area: "Platform", priority: "High",
    question: "Promote release candidate v1.5.0 (with agent DEV-01 v2.4.0) to production?", context: "All 418 regression tests passed after quarantine; security suite green; canary plan 10% → 50% → 100% over 48 h.",
    impact: "Production change for all users. Rollback target: v1.4.0 (one click).", requestedBy: "DEP-01", at: at(0, -.2), dueAt: at(1, 0), risk: "high", destructive: false,
    options: [{ id: "canary", label: "Approve with canary 10% → 100%", detail: "Recommended by GM (confidence 0.86)", recommended: true }, { id: "full", label: "Approve full rollout now", detail: "Faster; higher blast radius" }, { id: "hold", label: "Hold until Monday", detail: "Keeps v1.4.0 live" }],
    evidence: ["ci/run-8812 (418/418)", "security-scan #77 (0 critical)", "benchmark v2.3.0 vs v2.4.0 (+18.6%)"], status: "pending" },
  { id: "A-102", missionId: m1, ref: "OPS-3210", title: "Add 5 evaluation agents (cost: $320/mo)", area: "Agents", priority: "Medium",
    question: "Hire 5 more QA evaluation agents for the next edition?", context: "Verification queue wait time is 3.4 h (target 1 h).", impact: "+$320 per month; QA throughput ×1.8 (estimated).",
    requestedBy: "GM", at: at(0, -.6), dueAt: at(2, 0), risk: "medium",
    options: [{ id: "5", label: "Add 5 agents", detail: "GM recommendation", recommended: true }, { id: "3", label: "Add 3 agents", detail: "$192/mo" }, { id: "0", label: "Don't add", detail: "Keep queue" }],
    evidence: ["queue metrics (7 days)", "cost model FIN-1048"], status: "pending" },
  { id: "A-103", missionId: m1, ref: "FIN-1048", title: "Update compute budget to $3,200", area: "Finance", priority: "Low",
    question: "Raise the monthly compute budget from $2,840 to $3,200?", context: "Spend is 76% of budget with 9 days left; forecast 104%.", impact: "+$360/month cap.",
    requestedBy: "FIN-01", at: at(0, -1.4), dueAt: at(3, 0), risk: "low",
    options: [{ id: "3200", label: "Raise to $3,200", detail: "Forecast covered", recommended: true }, { id: "3000", label: "Raise to $3,000", detail: "Pause non-critical research" }],
    evidence: ["forecast model v3", "spend by category"], status: "pending" },
  { id: "A-104", missionId: m1, ref: "SEC-0412", title: "Run external security scan (vendor)", area: "Security", priority: "High",
    question: "Send the M-001 build to the external inspection vendor for a security scan?", context: "Policy requires owner consent before code leaves the company.", impact: "Unblocks the security gate of Release v2.4.0 (T-010).",
    requestedBy: "DEV-08", at: at(0, -1.5), dueAt: at(0, 6), risk: "medium",
    options: [{ id: "yes", label: "Approve scan", detail: "Vendor under NDA; artifacts deleted after 7 days", recommended: true }, { id: "internal", label: "Internal scan only", detail: "Lower coverage" }],
    evidence: ["vendor DPA", "policy SEC-2"], status: "pending" },
  ...[["Approve UX research budget", "M-009", "approved"], ["Merge PR #108 into main", "M-001", "approved"], ["Create GitHub repo for M-006", "M-006", "approved"], ["Disable legacy agent v1.2", "M-005", "rejected"], ["Delete stale preview environments", "M-012", "rejected"]].map(([title, missionId, status], i) => ({
    id: `A-0${90 + i}`, missionId, ref: `HIS-${200 + i}`, title, area: "History", priority: "Low" as const, question: title + "?", context: "Resolved earlier.", impact: "—",
    options: [{ id: "y", label: "Approve", detail: "" }, { id: "n", label: "Reject", detail: "" }], evidence: [], requestedBy: "GM", at: at(-i - 1), dueAt: at(-i), risk: "low" as const,
    status: status as Approval["status"], response: { option: status === "approved" ? "y" : "n", text: status === "approved" ? "Approved, go ahead." : "No: keep it for audit.", images: [], at: at(-i - 1, 2), by: "thomas" },
  })),
];

/* ---------------- activity / events ---------------- */
const ev = (h: number, actor: string, action: string, target: string, result: Event["result"], severity: Event["severity"] = "info", missionId: string | null = m1, icon?: string): Event =>
  ({ id: `E-${Math.round((h + 50) * 1000)}`, missionId, at: at(0, h), actor, action, target, result, severity, trace: `tr-${sha(action + target, 10)}`, icon });
export const EVENTS: Event[] = [
  ev(0, "DEV-01", "completed CI build (24% faster)", "ci/run-8812", "success", "info", m1, "check"),
  ev(-.2, "QA-01", "started test run", "v2.4.0-rc1", "running", "info", m1, "flask"),
  ev(-.43, "QA-02", "test failed: Safari e2e (retry 2/2)", "T-005", "failure", "medium", m1, "x"),
  ev(-.42, "RCH-01", "updated research report #386", "knowledge/386", "success", "info", "M-003", "book"),
  ev(-.62, "GM", "scheduled deployment", "v1.5.0 · Thursday 09:00", "info", "info", m1, "rocket"),
  ev(-1.05, "GM", "added 5 evaluation agents (proposal)", "A-102", "warning", "low", m1, "users"),
  ev(-1.5, "DEV-08", "requested approval", "A-104 external security scan", "warning", "medium", m1, "shield"),
  ev(-1.6, "GM", "re-planned critical path", "M-001 plan v7", "success", "info", m1, "route"),
  ev(-2.2, "ARC-01", "delivered architecture spec", "arch-v2.pdf", "success", "info", m1, "file"),
  ev(-2.5, "DEP-01", "created preview environment", "preview/m-001-rc", "success", "info", m1, "monitor"),
  ev(-3.1, "OPS-01", "provider degraded: fallback route used", "openrouter → anthropic", "warning", "medium", null, "alert"),
  ev(-3.6, "user", "sent instruction", "DEV-01", "info", "info", m1, "message"),
  ev(-4.2, "KNW-01", "indexed 14 sources (3 conflicts)", "Knowledge Review", "success", "info", "M-008", "layers"),
  ev(-5, "DEV-03", "pushed 6 commits", "mission/M-001/agent-api", "success", "info", m1, "git"),
  ev(-6.4, "FIN-01", "budget alert: 76% used", "Compute", "warning", "low", null, "coins"),
  ev(-8, "GM", "mission started", "M-001 AXoR Platform Upgrade", "success", "info", m1, "play"),
];

/* ---------------- releases / branches / merge requests ---------------- */
const rel = (version: string, days: number, status: Release["status"], notes: string[], mergedFrom: string[], tests: [number, number], runnable = true): Release => ({
  id: `R-${version}`, missionId: m1, version, at: at(days, -1), branch: status === "candidate" ? "release/v1.5.0" : "main", commit: sha(version), notes,
  fixes: ["Fixed chat composer focus race (PR #113)", "Fixed theme token fallback in Safari"], known: status === "candidate" ? ["Safari e2e flaky (quarantined)"] : [],
  status, tests: { passed: tests[0], total: tests[1] }, security: status === "failed" ? "fail" : "pass",
  artifacts: [{ name: `axor-web-${version}.tar.gz`, size: "18.4 MB", sha256: sha(version + "a", 64) }, { name: `axor-${version}-source.zip`, size: "6.1 MB", sha256: sha(version + "s", 64) }, { name: `release-notes-${version}.md`, size: "4 KB", sha256: sha(version + "n", 64) }],
  previewUrl: runnable ? `/app#/preview/${version}` : null, author: "DEP-01", mergedFrom, runnable,
});
export const RELEASES: Release[] = [
  rel("v1.5.0", 0, "candidate", ["Merged 3 branches", "AI evaluation engine", "UX redesign", "Self-evolution update"], ["feature/ai-eval", "feature/ux-redesign", "feature/self-evolution"], [418, 418]),
  rel("v1.4.0", -4, "current", ["Agent API v2", "Mission isolation", "Approvals inbox"], ["feature/agent-api", "feature/approvals"], [402, 402]),
  rel("v1.3.1", -9, "stable", ["Hotfix: approvals double-submit"], ["hotfix/approvals"], [395, 395]),
  rel("v1.3.0", -12, "superseded", ["Knowledge library", "News sources"], ["feature/knowledge"], [380, 384]),
  rel("v1.2.0", -18, "superseded", ["Task flow board"], ["feature/task-flow"], [351, 351]),
  rel("v1.1.0-rc2", -21, "failed", ["Rejected: security regression"], ["feature/plugins"], [340, 352], false),
];
export const BRANCHES: Branch[] = [
  { name: "main", missionId: null, base: "—", head: sha("main"), status: "protected", version: "v1.5.0", kind: "main", commits: 412, ahead: 0, behind: 0 },
  { name: "feature/ai-eval", missionId: "M-002", base: sha("main0"), head: sha("aieval"), status: "merged", version: "v1.4.0", pr: 109, kind: "feature", commits: 23, ahead: 0, behind: 0 },
  { name: "feature/ux-redesign", missionId: "M-009", base: sha("main1"), head: sha("ux"), status: "merged", version: "v1.4.0", pr: 110, kind: "feature", commits: 41, ahead: 0, behind: 0 },
  { name: "feature/self-evolution", missionId: "M-005", base: sha("main2"), head: sha("evo"), status: "merged", version: "v1.3.1", pr: 111, kind: "feature", commits: 17, ahead: 0, behind: 0 },
  { name: "feature/task-flow", missionId: "M-001", base: sha("main3"), head: sha("tf"), status: "open", version: "v1.5.1-dev", pr: 112, kind: "feature", commits: 9, ahead: 9, behind: 2 },
  { name: "feature/theme-engine", missionId: "M-009", base: sha("main3"), head: sha("theme"), status: "conflict", version: "v1.5.1-dev", pr: 113, kind: "feature", commits: 14, ahead: 14, behind: 5 },
  { name: "release/v1.5.0", missionId: "M-001", base: sha("main4"), head: sha("rel150"), status: "staged", version: "v1.5.0", kind: "release", commits: 3, ahead: 3, behind: 0 },
  { name: "agent/DEV-01/candidate/v2.4.0", missionId: null, base: "v2.3.0", head: sha("dev240"), status: "open", version: "v2.4.0", kind: "agent", commits: 5, ahead: 5, behind: 0 },
];
export const MERGE_REQUESTS: MergeRequest[] = [
  { id: "PR-112", number: 112, title: "Task Flow DAG + inspector", from: "feature/task-flow", to: "main", checks: { passed: 42, total: 42 }, reviewers: ["QA-01", "ARC-01"], conflicts: 0, status: "approved", qa: "passed", at: at(0, -3) },
  { id: "PR-113", number: 113, title: "Theme engine: tokens + presets", from: "feature/theme-engine", to: "main", checks: { passed: 39, total: 42 }, reviewers: ["QA-02"], conflicts: 1, status: "blocked", qa: "pending", at: at(0, -5) },
  { id: "PR-114", number: 114, title: "Release v1.5.0", from: "release/v1.5.0", to: "main", checks: { passed: 418, total: 418 }, reviewers: ["QA-01", "GM"], conflicts: 0, status: "open", qa: "passed", at: at(0, -1) },
  { id: "PR-111", number: 111, title: "Self-evolution update", from: "feature/self-evolution", to: "main", checks: { passed: 37, total: 37 }, reviewers: ["QA-01"], conflicts: 0, status: "merged", qa: "passed", at: at(-6) },
];

/* ---------------- evolution ---------------- */
const met = (name: string, base: number, cand: number, unit = "%", higherBetter = true) => ({ name, base, cand, unit, higherBetter });
export const CANDIDATES: Candidate[] = [
  { id: "C-240", agentId: "DEV-01", from: "v2.3.0", to: "v2.4.0", title: "DEV-01 Self-Evolution (v2.4.0)", summary: "Improve code quality and task success rate.", delta: 18.6,
    metrics: [met("Task success", 86.9, 94.0), met("Code quality", 78, 83), met("Build time", 182, 138, "s", false), met("Cost / task", .52, .47, "$", false), met("Security findings", 0, 0, "", false)],
    status: "passed", evaluator: "QA-01", sourceInstances: ["DEV-01@M-001", "DEV-01@M-006"], risk: "medium", kind: "code", at: at(0, -1), canary: 0 },
  { id: "C-210", agentId: "QA-01", from: "v2.0.2", to: "v2.1.0", title: "QA-01 Testing Enhancement", summary: "Expand test coverage and detect edge cases.", delta: 12.9,
    metrics: [met("Defects found", 41, 47), met("False positives", 9, 6, "%", false), met("Run time", 22, 24, "min", false)], status: "evaluating", evaluator: "QA-03", sourceInstances: ["QA-01@M-001", "QA-01@M-010"], risk: "low", kind: "skill", at: at(0, -3) },
  { id: "C-220", agentId: "RCH-01", from: "v2.1.4", to: "v2.2.0", title: "RCH-01 Knowledge Integration", summary: "Integrate new external data sources.", delta: 15.4,
    metrics: [met("Citation accuracy", 91, 96), met("Coverage", 70, 81), met("Latency", 41, 44, "s", false)], status: "experiment", evaluator: "QA-02", sourceInstances: ["RCH-01@M-003"], risk: "low", kind: "knowledge", at: at(-1) },
  { id: "C-190", agentId: "OPS-01", from: "v1.9.0", to: "v1.9.1", title: "OPS-01 Faster incident triage", summary: "Runbook heuristics from 6 incidents.", delta: -3.1,
    metrics: [met("MTTR", 18, 19.5, "min", false), met("Correct triage", 88, 86)], status: "failed", evaluator: "QA-04", sourceInstances: ["OPS-01@M-011"], risk: "low", kind: "procedure", at: at(-2) },
  { id: "C-170", agentId: "DEV-01", from: "v2.2.0", to: "v2.2.1", title: "DEV-01 Aggressive caching", summary: "Cache all intermediate artefacts.", delta: -6.4,
    metrics: [met("p95 latency", 40, 52, "s", false)], status: "rolled_back", evaluator: "QA-01", sourceInstances: ["DEV-01@M-007"], risk: "medium", kind: "code", at: at(-30), canary: 10 },
  { id: "C-160", agentId: "KNW-01", from: "v1.6.0", to: "v1.6.1", title: "KNW-01 Dedupe v2", summary: "Semantic de-duplication of the library.", delta: 9.2,
    metrics: [met("Duplicates", 7.1, 2.3, "%", false)], status: "promoted", evaluator: "QA-02", sourceInstances: ["KNW-01@M-008"], risk: "low", kind: "skill", at: at(-9), canary: 100 },
];
export const MENTORING: Mentoring[] = [
  { id: "MT-1", mentor: "MNT-01", trainee: "DEV-04", module: "Test-first refactoring", progress: 70, assessment: null, verifier: "QA-03", status: "running", transfers: 6 },
  { id: "MT-2", mentor: "DEV-01", trainee: "DEV-05", module: "Build pipeline tuning (from v2.4.0)", progress: 35, assessment: null, verifier: "QA-01", status: "running", transfers: 3 },
  { id: "MT-3", mentor: "RCH-01", trainee: "RCH-04", module: "Citation discipline", progress: 100, assessment: 91, verifier: "QA-02", status: "passed", transfers: 9 },
  { id: "MT-4", mentor: "MNT-01", trainee: "OPS-03", module: "Incident runbooks", progress: 100, assessment: 64, verifier: "QA-04", status: "failed", transfers: 5 },
];

/* ---------------- knowledge & news ---------------- */
export const KNOWLEDGE_TILES = [
  ["Project Knowledge", 1248], ["Research Reports", 386], ["Best Practices", 129], ["External Sources", 48], ["Industry News", 320], ["Lessons Learned", 87], ["Tech Trends", 144], ["Company Memory", 2917],
] as const;
export const KNOWLEDGE: KnowledgeItem[] = [
  ["Mission isolation rules (AG-004)", "procedure", ["governance", "agents"], 6, .98, "verified"], ["Vite build parallelisation", "lesson", ["build", "ci"], 3, .92, "verified"],
  ["Agent API v2 contract", "decision", ["api"], 4, .95, "verified"], ["Competitor pricing Q4", "research", ["market"], 11, .74, "pending"],
  ["Model routing policy v3", "procedure", ["models"], 5, .9, "verified"], ["Safari focus race", "lesson", ["frontend"], 2, .81, "verified"],
  ["LLM cost per task benchmarks", "research", ["finance", "models"], 9, .77, "conflict"], ["Release canary checklist", "procedure", ["release"], 4, .96, "verified"],
  ["2024 agent framework survey", "research", ["research"], 22, .6, "outdated"], ["Prompt-injection defences", "skill", ["security"], 8, .93, "verified"],
].map(([title, kind, tags, citations, confidence, status], i) => ({ id: `K-${100 + i}`, title: title as string, kind: kind as KnowledgeItem["kind"], tags: tags as string[], citations: citations as number,
  confidence: confidence as number, status: status as KnowledgeItem["status"], updated: at(-i, -i), owner: ["KNW-01", "RCH-01", "DEV-01"][i % 3], scope: i % 4 === 0 ? "organization" : "M-00" + ((i % 9) + 1) }));
export const NEWS_SOURCES: NewsSource[] = [
  { id: "S-1", name: "Hacker News", url: "https://news.ycombinator.com/rss", cadence: "Every 30 min", trust: 72, lastFetched: at(0, -.3), status: "ok", scope: "organization", topics: ["tech", "ai"], items: 120, addedBy: "admin" },
  { id: "S-2", name: "arXiv cs.AI", url: "https://export.arxiv.org/rss/cs.AI", cadence: "Daily", trust: 90, lastFetched: at(0, -3), status: "ok", scope: "organization", topics: ["research"], items: 64, addedBy: "admin" },
  { id: "S-3", name: "GitHub Blog", url: "https://github.blog/feed/", cadence: "Every 6 h", trust: 86, lastFetched: at(0, -2), status: "ok", scope: "organization", topics: ["devtools"], items: 22, addedBy: "admin" },
  { id: "S-4", name: "Anthropic News", url: "https://www.anthropic.com/news", cadence: "Daily", trust: 92, lastFetched: at(0, -5), status: "ok", scope: "organization", topics: ["models"], items: 14, addedBy: "admin" },
  { id: "S-5", name: "OpenAI Blog", url: "https://openai.com/blog", cadence: "Daily", trust: 90, lastFetched: at(0, -5), status: "ok", scope: "organization", topics: ["models"], items: 18, addedBy: "admin" },
  { id: "S-6", name: "Competitor changelog", url: "https://example.com/changelog", cadence: "Weekly", trust: 55, lastFetched: at(-1), status: "error", scope: "mission", topics: ["market"], items: 3, addedBy: "thomas" },
];
export const NEWS: NewsItem[] = [
  ["New open benchmark for agentic coding released", "S-2", "Research", 92, ["M-002", "M-005"]], ["GitHub adds fine-grained token expiry policies", "S-3", "Security", 81, ["M-012"]],
  ["Model provider cuts batch API prices by 40%", "S-5", "Finance", 77, ["M-001"]], ["Prompt-injection attack via README files", "S-1", "Security", 88, ["M-008"]],
  ["Claude model update improves tool use", "S-4", "Models", 84, ["M-001", "M-006"]], ["Competitor ships multi-agent dashboard", "S-6", "Market", 69, ["M-004", "M-009"]],
  ["Survey: autonomous agents in production", "S-2", "Research", 73, ["M-004"]],
].map(([title, sourceId, category, relevance, missionIds], i) => ({ id: `N-${i + 1}`, title: title as string, sourceId: sourceId as string, category: category as string, relevance: relevance as number, missionIds: missionIds as string[], at: at(0, -i * 1.7), url: "#" }));

/* ---------------- models (Model Loader / routing) ---------------- */
export const MODELS: ModelReg[] = [
  { id: "mdl-1", provider: "Anthropic", model: "claude-opus-5-5", version: "2026-10", capabilities: ["code", "reasoning", "tools", "vision"], context: 1000000, costIn: 5, costOut: 25, latencyMs: 2100, health: "ok", roles: ["gm", "developer", "security", "mentor"], fallback: "mdl-2", enabled: true },
  { id: "mdl-2", provider: "Anthropic", model: "claude-sonnet-5-5", version: "2026-10", capabilities: ["code", "tools", "vision"], context: 1000000, costIn: 3, costOut: 15, latencyMs: 1200, health: "ok", roles: ["qa", "research", "knowledge", "deploy"], fallback: "mdl-3", enabled: true },
  { id: "mdl-3", provider: "Anthropic", model: "claude-haiku-5-5", version: "2026-10", capabilities: ["fast", "tools"], context: 200000, costIn: 1, costOut: 5, latencyMs: 450, health: "ok", roles: ["ops", "finance"], fallback: null, enabled: true },
  { id: "mdl-4", provider: "OpenAI", model: "gpt-6.1", version: "2026-09", capabilities: ["reasoning", "design", "creative"], context: 400000, costIn: 4, costOut: 20, latencyMs: 1900, health: "ok", roles: ["architect", "strategist", "gm", "research"], fallback: "mdl-1", enabled: true },
  { id: "mdl-5", provider: "OpenAI", model: "text-embedding-4", version: "2026-06", capabilities: ["embeddings"], context: 8192, costIn: .1, costOut: 0, latencyMs: 90, health: "ok", roles: ["knowledge"], fallback: null, enabled: true },
  { id: "mdl-6", provider: "OpenRouter", model: "open-mixture-200b", version: "2026-08", capabilities: ["fallback"], context: 128000, costIn: .6, costOut: 1.8, latencyMs: 2600, health: "down", roles: [], fallback: null, enabled: false },
];

/* ---------------- finance ---------------- */
export const SPEND_BREAKDOWN = [
  { label: "LLM / API", value: 42, c: "#3b8cff" }, { label: "Compute", value: 24, c: "#22d3ee" }, { label: "Tools & Services", value: 16, c: "#f2b53a" },
  { label: "Storage", value: 10, c: "#a77bff" }, { label: "Other", value: 8, c: "#94a3b8" },
];
export const FINANCE = { month: 2840, budget: 3740, deltaPct: 6.3, revenue: 4120, opCost: 3010, burnPerDay: 94.7, costPerSuccess: 11.8 };
export const SPEND_SERIES = Array.from({ length: 30 }, (_, i) => ({ day: at(i - 29).slice(5, 10), spend: Math.round(70 + 35 * Math.sin(i / 3.2) + i * 1.4 + (i % 4) * 6), budget: 125 }));
export const PERF_SERIES = Array.from({ length: 30 }, (_, i) => ({ day: at(i - 29).slice(5, 10), success: +(90 + 5 * Math.sin(i / 4) + i * .12).toFixed(1), autonomy: +(78 + 6 * Math.cos(i / 5) + i * .3).toFixed(1) }));

/* ---------------- notifications ---------------- */
export const NOTICES: Notice[] = [
  { id: "NT-1", at: at(0, -.2), kind: "decision", title: "Production release needs your approval", detail: "A-101 · v1.5.0", read: false, missionId: m1, severity: "high" },
  { id: "NT-2", at: at(0, -.43), kind: "failure", title: "Safari e2e failed twice", detail: "T-005 quarantined", read: false, missionId: m1, severity: "medium" },
  { id: "NT-3", at: at(0, -1.5), kind: "decision", title: "Security scan needs consent", detail: "A-104", read: false, missionId: m1, severity: "medium" },
  { id: "NT-4", at: at(0, -2.5), kind: "release", title: "Preview environment ready", detail: "preview/m-001-rc", read: true, missionId: m1, severity: "info" },
  { id: "NT-5", at: at(0, -3.1), kind: "system", title: "Provider degraded: fallback used", detail: "gpt-6.1 → claude-opus-5-5", read: true, missionId: null, severity: "medium" },
  { id: "NT-6", at: at(0, -4.2), kind: "agent", title: "Candidate DEV-01 v2.4.0 passed evaluation", detail: "+18.6% vs v2.3.0", read: true, missionId: null, severity: "info" },
];

export const SETTINGS: Settings = {
  selfRenewal: true, autonomy: { L0: true, L1: true, L2: true, L3: true, L4: true, L5: false }, verificationProvider: "Independent QA (internal) + external vendor on approval",
  quietHours: false, aiRoles: { architecture: "GPT (ARC-01)", code: "Claude Code (DEV agents)", research: "GPT + Claude (joint synthesis)", creative: "GPT proposes, Claude reviews" },
  notifications: { decisions: true, failures: true, releases: true, digest: true },
};
