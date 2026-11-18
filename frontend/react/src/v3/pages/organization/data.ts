// SAMPLE data for the Organization page: department charters, the GM's restructuring proposals, protected governance roles.
// Nothing here is live; approving or rejecting a proposal only changes local page state (see final report: needs a store action).
import type { Role } from "../../ui/Avatar";

export const SUBTITLE: Record<string, string> = { research: "R&D · Exploration", development: "Build · Integrate", operations: "Run · Orchestrate", qa: "Test · Validate", knowledge: "Organize · Retrieve", finance: "Budget · Cost · ROI", deployment: "Release · Scale" };
export const CHARTER: Record<string, string> = {
  research: "Investigate markets, technologies and sources; deliver cited, verifiable research reports to every mission.",
  development: "Build, integrate and deliver AI capabilities, agents and platform features to support company missions and evolution.",
  operations: "Run the company runtime: scheduling, incident response, capacity and observability.",
  qa: "Independently verify outputs, benchmarks and candidates. Verifiers never review their own work.",
  knowledge: "Organize company memory, deduplicate and index knowledge, and keep provenance and privacy rules.",
  finance: "Track budgets, spend and unit economics; raise alerts before a limit is reached.",
  deployment: "Package, release and roll back versions; run previews and canaries.",
};
export const EFFICIENCY: Record<string, number> = { research: 15.2, development: 24.1, operations: 13.7, qa: 20.5, knowledge: 12.9, finance: 11.6, deployment: 18.9 };

export interface Unit { id: string; name: string; role: Role; agents: number; tag?: "new" | "changed" | "removed" | "merged" }
export interface Proposal {
  id: string; title: string; priority: "High" | "Medium" | "Low"; summary: string; benefit: string; gain: number; risks: string[];
  changes: { role: string; from: string; to: string; agents: number; protectedRole?: boolean }[];
  after: (before: Unit[]) => Unit[]; protectedHit?: string;
}
export const PROPOSALS: Proposal[] = [
  { id: "RP-1", title: "Split Development into Core & Platform Teams", priority: "High", gain: 22.7,
    summary: "Development has the largest backlog (11) and 8 agents under one head. Two teams with their own head reduce review queues.",
    benefit: "Backlog -35% and faster reviews; +22.7% capability (GM estimate, to be verified).",
    risks: ["Two heads must share one baseline of coding standards", "Temporary dip while DEV-05..08 move teams (1 week)", "Cross-team merges need a new reviewer rule"],
    changes: [{ role: "DEV-01", from: "Development lead", to: "Core Dev lead", agents: 4 }, { role: "DEV-05", from: "Developer", to: "Platform Dev lead (new head)", agents: 4 }, { role: "DEV-08", from: "Security", to: "Security (unchanged, still independent)", agents: 1 }],
    after: (b) => b.flatMap((u) => u.id === "development" ? [{ ...u, id: "core", name: "Core Dev", agents: 4, tag: "changed" as const }, { id: "platform", name: "Platform Dev", role: "developer" as Role, agents: 4, tag: "new" as const }] : [u]) },
  { id: "RP-2", title: "Create AI Safety & Alignment Department", priority: "Medium", gain: 16.4,
    summary: "A dedicated department that red-teams agent versions and owns the privacy filter rules, independent of Development.",
    benefit: "Fewer unsafe candidates reach QA; +16.4% verification coverage.",
    risks: ["Overlaps with QA / Verifier scope until the charters are split", "Needs 3 agents (2 moved from QA, 1 new)", "Adds monthly budget of $140"],
    changes: [{ role: "SAF-01", from: "(none)", to: "Safety lead (new)", agents: 1 }, { role: "QA-04, QA-05", from: "QA specialist", to: "Safety analyst", agents: 2 }],
    after: (b) => [...b.map((u) => u.id === "qa" ? { ...u, agents: u.agents - 2, tag: "changed" as const } : u), { id: "safety", name: "AI Safety", role: "security" as Role, agents: 3, tag: "new" as const }] },
  { id: "RP-3", title: "Merge Finance & Operations (Cost Optimization)", priority: "Low", gain: 14.9, protectedHit: "FIN-01 (budget guard)",
    summary: "Merge the two small departments to cut overhead. Touches the Finance lead, whose independence guards the budget.",
    benefit: "-1 head count of management; +14.9% efficiency.",
    risks: ["Removes separation between spending and budget control (governance risk)", "FIN-01 is a protected governance role", "Needs Governance approval, not only the user"],
    changes: [{ role: "FIN-01", from: "Finance lead", to: "Merged Finance & Ops lead", agents: 3, protectedRole: true }, { role: "OPS-01", from: "Operations lead", to: "Deputy", agents: 7 }],
    after: (b) => [...b.filter((u) => u.id !== "finance" && u.id !== "operations"), { id: "finops", name: "Finance & Ops", role: "finance" as Role, agents: 10, tag: "merged" as const }] },
];
export const PROTECTED = [
  { id: "GM", label: "General Manager", why: "Single accountable planner; cannot be reassigned by itself" },
  { id: "QA-01", label: "Verifier lead", why: "Independent verification must stay independent" },
  { id: "FIN-01", label: "Budget guard", why: "Separates spending from budget control" },
  { id: "DEV-08", label: "Security lead", why: "Owns secrets and policy checks" },
];
