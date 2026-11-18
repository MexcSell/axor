// Helpers + SAMPLE derivations for the Agents page. Anything not in the store (load, health score, per-agent series,
// version history for agents the sample store does not cover) is generated deterministically and labelled "Sample" in the UI.
import type { AgentIdentity, AgentVersion, Experience } from "../../domain/types";
import type { State } from "../../data/store";
import { at } from "../../data/sample";

export type Health = "healthy" | "degraded" | "at_risk" | "no_data";
// successRate 0 = no verified results recorded yet (e.g. live agents): that is "no data", not "degraded".
export const healthOf = (a: AgentIdentity): Health => a.status === "offline" || a.status === "error" ? "at_risk" : a.successRate <= 0 ? "no_data" : a.successRate < 90 ? "degraded" : "healthy";
export const HEALTH_LABEL: Record<Health, string> = { healthy: "Healthy", degraded: "Degraded", at_risk: "At risk", no_data: "No data yet" };
export const HEALTH_C: Record<Health, string> = { healthy: "var(--ax-ok)", degraded: "var(--ax-warn)", at_risk: "var(--ax-bad)", no_data: "var(--ax-neutral)" };
const seed = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);

export const skillScore = (a: AgentIdentity) => +(a.skills.reduce((s, k) => s + k.level, 0) / Math.max(1, a.skills.length)).toFixed(1);
export const loadOf = (a: AgentIdentity) => 40 + (seed(a.id) % 48); // SAMPLE capacity utilisation
export const activeInstances = (s: State, id: string) => s.instances.filter((i) => i.agentId === id && i.status !== "done" && i.status !== "cancelled");
export const deptName = (s: State, id: string) => id === "executive" ? "Executive" : s.departments.find((d) => d.id === id)?.name ?? id;
export const verifierOf = (a: AgentIdentity) => a.dept === "qa" ? (a.id === "QA-01" ? "QA-02" : "QA-01") : "QA-01";
export const mentorOf = (a: AgentIdentity) => a.role === "mentor" ? "GM" : a.reportsTo && a.reportsTo !== "GM" && a.id !== a.reportsTo ? a.reportsTo : "MNT-01";

export function versionsFor(s: State, a: AgentIdentity): AgentVersion[] {
  const real = s.agentVersions.filter((v) => v.agentId === a.id);
  if (real.length) return real;
  const [M, m, p] = a.baseline.replace("v", "").split(".").map(Number);
  const mk = (version: string, parent: string | null, days: number, status: AgentVersion["status"], score: number, changes: string[], kind: AgentVersion["kind"]): AgentVersion =>
    ({ agentId: a.id, version, parent, at: at(days), status, score, changes, kind });
  const prev = `v${M}.${Math.max(0, m - 1)}.${p}`, pp = `v${M}.${Math.max(0, m - 2)}.0`;
  const list = [
    mk(pp, null, -90, "retired", +(skillScore(a) - 7).toFixed(1), ["Initial role template"], ["prompt"]),
    mk(prev, pp, -45, "retired", +(skillScore(a) - 3).toFixed(1), ["Procedure from two verified missions"], ["procedure"]),
    mk(a.baseline, prev, -12, "baseline", skillScore(a), ["Verified lessons merged (QA gate passed)"], ["knowledge"]),
  ];
  if (a.candidate) list.push(mk(a.candidate, a.baseline, -1, "candidate", +(skillScore(a) + 4).toFixed(1), ["Candidate built from eligible experience"], ["procedure"]));
  return list;
}
export function experiencesFor(s: State, a: AgentIdentity): { list: Experience[]; sample: boolean } {
  const real = s.experiences.filter((x) => x.agentId === a.id);
  if (real.length) return { list: real, sample: false };
  const mids = s.instances.filter((i) => i.agentId === a.id).map((i) => i.missionId); const m0 = mids[0] ?? "M-001", m1 = mids[1] ?? m0;
  const sk = a.skills.map((k) => k.name);
  return { sample: true, list: [
    { id: `${a.id}-x1`, agentId: a.id, missionId: m0, at: at(-1), lesson: `${sk[0]}: reuse the verified checklist before hand-off`, kind: "verified", confidence: .9, generalization: .72, eligible: true, evidence: "QA run (sample)" },
    { id: `${a.id}-x2`, agentId: a.id, missionId: m1, at: at(-3), lesson: `${sk[1] ?? sk[0]}: cite evidence ids in every report`, kind: "verified", confidence: .84, generalization: .66, eligible: true, evidence: "review log (sample)" },
    { id: `${a.id}-x3`, agentId: a.id, missionId: m0, at: at(-4), lesson: "Customer-specific wording (mission-private)", kind: "private", confidence: 1, generalization: 0, eligible: false, evidence: "excluded by privacy filter (AG-004)" },
    { id: `${a.id}-x4`, agentId: a.id, missionId: m1, at: at(-6), lesson: `${sk[2] ?? sk[0]}: shortcut seen twice, not yet confirmed`, kind: "tentative", confidence: .58, generalization: .6, eligible: false, evidence: "2 observations, needs 5" },
  ] };
}
// SAMPLE 30-day verified metric series for one agent
export function perfSeries(a: AgentIdentity) {
  const s0 = seed(a.id) % 7;
  return Array.from({ length: 30 }, (_, i) => ({
    day: at(i - 29).slice(5, 10),
    success: +(a.successRate - 4 + i * .13 + 1.6 * Math.sin((i + s0) / 3)).toFixed(1),
    cost: +(a.costPerTask * (1.15 - i * .005) + .03 * Math.cos(i / 2 + s0)).toFixed(2),
    latency: +(a.latencyS * (1.1 - i * .003) + 2 * Math.sin(i / 3 + s0)).toFixed(1),
    tasks: 3 + ((i * 5 + s0 * 3) % 9),
  }));
}
export const sampleXp = (a: AgentIdentity) => 6000 + (seed(a.id) % 9000);
