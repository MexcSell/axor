// AXoR UI v3 domain model (docs/ui-v3/ROADMAP.md; Detailed UI v3 §5 and §7; Homepage spec §9; GPT architecture review #1).
// Stable agent identity is separate from its mission-scoped instances; the project's Git versions are separate from agent versions.
import type { Status } from "../ui/kit";
import type { Role } from "../ui/Avatar";

export type ID = string;
export type ISO = string;
export type Source = "sample" | "live";
export type ScheduleKind = "scheduled" | "estimated" | "not_scheduled";

export interface Mission {
  id: ID; title: string; summary: string; status: Status; stage: Stage; progress: number; progressBasis: "milestones" | "tasks" | "calculating";
  issuesOpen: number; decisionsPending: number; version: string; dueAt: ISO; dueKind: ScheduleKind; nextEditionAt: ISO | null; nextEditionKind: ScheduleKind;
  startedAt: ISO; lastActivityAt: ISO; owner: string; workstream: string; icon: string; color: string; risk: "low" | "medium" | "high";
  budget: { limit: number; spent: number }; tokenBudget?: { perDay: number; usedToday: number }; repo: { url: string; branch: string; created: boolean; pending?: boolean } | null; archived?: boolean;
  priority: "High" | "Medium" | "Low"; autonomy?: string; inputs?: { text: string; files: string[]; images: string[]; githubUrls: string[]; webUrls?: string[] };
}
export type Stage = "plan" | "research" | "develop" | "test" | "verify" | "deploy";
export const STAGES: { id: Stage; label: string }[] = [
  { id: "plan", label: "Plan" }, { id: "research", label: "Research" }, { id: "develop", label: "Develop" },
  { id: "test", label: "Test" }, { id: "verify", label: "Verify" }, { id: "deploy", label: "Deploy" },
];

export interface Task {
  hubRoute?: string; hubRef?: string | null; // live: where AXoR runs it (agent | board | mission) and what it is linked to
  id: ID; missionId: ID; title: string; phase: string; desc?: string; meta?: { p: "P0" | "P1" | "P2" | "P3"; hours: number; short: string; milestone?: boolean }; status: Status; progress: number; instanceId: ID; deps: ID[];
  start: ISO; end: ISO; acceptance: string[]; evidence: string[]; blocker?: { text: string; approvalId?: ID }; outputVersion?: string;
  retries: number; priority: "High" | "Medium" | "Low"; critical?: boolean; history: { at: ISO; text: string }[]; dueUnknown?: boolean;
}

export interface Skill { name: string; level: number }
export interface AgentIdentity {
  id: ID; name: string; role: Role; title: string; dept: ID; reportsTo: ID | null; baseline: string; candidate?: string;
  models: string[]; tools: string[]; skills: Skill[]; permissions: string[]; status: "active" | "idle" | "busy" | "offline" | "error";
  successRate: number; tasksDone: number; costPerTask: number; latencyS: number; qualified: string[]; created: ISO;
  hubId?: number; hubStatus?: string; // live: the company agent's numeric id and raw status (for POST /api/company/agents/{id}/chat)
}
export interface AgentInstance {
  id: ID; agentId: ID; missionId: ID; pinnedVersion: string; branch: string; status: Status; progress: number;
  tasks: number; supervisor: ID | null; startedAt: ISO; errors: number; spend: number;
  derived?: "company-lead"; // live: AXoR has no per-mission GM; the company's lead is shown on every live mission
}
export interface AgentVersion {
  agentId: ID; version: string; parent: string | null; at: ISO; status: "baseline" | "candidate" | "retired" | "rejected" | "rolled_back";
  changes: string[]; score: number; kind: ("knowledge" | "procedure" | "prompt" | "skill" | "code")[];
}
export interface Experience {
  id: ID; agentId: ID; missionId: ID; at: ISO; lesson: string; kind: "verified" | "tentative" | "code" | "security" | "private";
  confidence: number; generalization: number; eligible: boolean; evidence: string;
}

export type Participant = ID; // "user" or an agent id
export interface Thread {
  id: ID; missionId: ID; a: Participant; b: Participant; kind: "user" | "superior" | "subordinate" | "peer"; unread: number; lastAt: ISO; status: Status;
}
export type MsgKind = "instruction" | "report" | "message" | "plan" | "tool" | "result" | "system" | "thought";
export interface Message {
  id: ID; threadId: ID; missionId: ID; from: Participant; to: Participant; at: ISO; kind: MsgKind; text: string;
  state?: Status; attachments?: string[]; condensed: boolean;
}

export interface Approval {
  id: ID; missionId: ID; ref: string; title: string; area: string; priority: "High" | "Medium" | "Low"; question: string; context: string; impact: string;
  options: { id: string; label: string; detail: string; recommended?: boolean }[]; evidence: string[]; requestedBy: ID; at: ISO; dueAt: ISO;
  status: "pending" | "approved" | "rejected" | "changes" | "answered"; response?: { option?: string; text: string; images: string[]; at: ISO; by: string };
  risk: "low" | "medium" | "high"; destructive?: boolean;
}

export interface Event {
  id: ID; missionId: ID | null; at: ISO; actor: Participant | "system"; action: string; target: string;
  result: "success" | "failure" | "running" | "info" | "warning"; trace: string; severity: "info" | "low" | "medium" | "high"; detail?: string; icon?: string;
}

export interface Release {
  id: ID; missionId: ID; version: string; at: ISO; branch: string; commit: string; notes: string[]; fixes: string[]; known: string[];
  status: "current" | "stable" | "candidate" | "superseded" | "failed"; tests: { passed: number; total: number }; security: "pass" | "warn" | "fail";
  artifacts: { name: string; size: string; sha256: string }[]; previewUrl: string | null; author: ID; mergedFrom: string[]; runnable: boolean;
}
export interface Branch {
  name: string; missionId: ID | null; base: string; head: string; status: "protected" | "open" | "merged" | "staged" | "conflict"; version: string;
  pr?: number; kind: "main" | "feature" | "release" | "agent"; commits: number; ahead: number; behind: number;
}
export interface MergeRequest {
  id: ID; number: number; title: string; from: string; to: string; checks: { passed: number; total: number }; reviewers: ID[];
  conflicts: number; status: "open" | "approved" | "merged" | "blocked"; qa: "pending" | "passed" | "failed"; at: ISO;
}

export interface Candidate {
  id: ID; agentId: ID; from: string; to: string; title: string; summary: string; delta: number;
  metrics: { name: string; base: number; cand: number; unit: string; higherBetter: boolean }[];
  status: "proposed" | "experiment" | "evaluating" | "passed" | "failed" | "promoted" | "rejected" | "rolled_back";
  evaluator: ID; sourceInstances: ID[]; risk: "low" | "medium" | "high"; kind: AgentVersion["kind"][number]; at: ISO; canary?: number; permissionApproved?: boolean;
}
export interface Mentoring {
  id: ID; mentor: ID; trainee: ID; module: string; progress: number; assessment: number | null; verifier: ID; status: Status; transfers: number;
}

export interface Department { id: ID; name: string; role: Role; head: ID; budget: number; spent: number; performance: number; backlog: number }
export interface NewsSource {
  id: ID; name: string; url: string; cadence: string; trust: number; lastFetched: ISO | null; status: "ok" | "error" | "pending" | "disabled";
  scope: "organization" | "mission"; missionId?: ID; topics: string[]; items: number; addedBy: string;
}
export interface NewsItem { id: ID; sourceId: ID; title: string; at: ISO; category: string; relevance: number; missionIds: ID[]; url: string }
export interface KnowledgeItem {
  id: ID; title: string; kind: "fact" | "procedure" | "decision" | "lesson" | "research" | "skill"; tags: string[]; citations: number;
  confidence: number; updated: ISO; owner: ID; status: "verified" | "pending" | "conflict" | "outdated"; scope: string;
}
export interface ModelReg {
  id: ID; provider: string; model: string; version: string; capabilities: string[]; context: number; costIn: number; costOut: number;
  latencyMs: number; health: "ok" | "degraded" | "down"; roles: Role[]; fallback: ID | null; enabled: boolean;
}
export interface Notice { id: ID; at: ISO; kind: "decision" | "failure" | "release" | "agent" | "system" | "mission"; title: string; detail: string; read: boolean; missionId: ID | null; severity: "info" | "low" | "medium" | "high" }

export interface Settings {
  selfRenewal: boolean; autonomy: Record<string, boolean>; verificationProvider: string; quietHours: boolean; quietFrom?: string; quietTo?: string;
  aiRoles: { architecture: string; code: string; research: string; creative: string };
  notifications: Record<string, boolean>;
}
