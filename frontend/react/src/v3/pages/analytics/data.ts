// Analytics helpers. Everything derived from the store is marked "derived"; series that are pure illustration are SAMPLE data
// (deterministic, generated here, never claimed live).
import { PERF_SERIES, SPEND_SERIES, FINANCE } from "../../data/sample";
import type { AgentIdentity, Mission } from "../../domain/types";
import { ROLES, type Role } from "../../ui/Avatar";

export type Range = "7" | "14" | "30";
export const RANGES = [{ id: "7", label: "Last 7 Days" }, { id: "14", label: "Last 14 Days" }, { id: "30", label: "Last 30 Days" }];
export const tail = <T,>(a: T[], r: Range) => a.slice(-Number(r));

export const avg = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);

export interface RoleStat { role: Role; label: string; c: string; n: number; success: number; tasks: number; cost: number; latency: number }
// Fleet grouped by role (derived from the agent registry).
export function roleStats(agents: AgentIdentity[]): RoleStat[] {
  const m = new Map<Role, AgentIdentity[]>();
  agents.forEach((a) => m.set(a.role, [...(m.get(a.role) ?? []), a]));
  return [...m.entries()].map(([role, l]) => ({ role, label: ROLES[role]?.label ?? role, c: ROLES[role]?.c ?? "#94a3b8", n: l.length, success: avg(l.map((a) => a.successRate)), tasks: l.reduce((s, a) => s + a.tasksDone, 0), cost: avg(l.map((a) => a.costPerTask)), latency: avg(l.map((a) => a.latencyS)) }))
    .sort((a, b) => b.n - a.n || b.success - a.success);
}

export interface Bucket { label: string; value: number; c: string }
export function missionBuckets(ms: Mission[]): Bucket[] {
  const c = (f: (m: Mission) => boolean) => ms.filter(f).length;
  return [
    { label: "Completed", value: c((m) => m.status === "done" || m.status === "passed"), c: "var(--ax-ok)" },
    { label: "In Progress", value: c((m) => ["running", "ready", "queued", "paused", "blocked", "waiting_user", "waiting_agent", "awaiting_approval", "draft"].includes(m.status)), c: "var(--ax-info)" },
    { label: "Reviews", value: c((m) => m.status === "review" || m.status === "verifying"), c: "var(--ax-warn)" },
    { label: "Failed", value: c((m) => m.status === "failed" || m.status === "rolled_back"), c: "var(--ax-bad)" },
  ];
}

// SAMPLE: daily throughput bars (illustration, seeded; scaled to the number of missions in the store).
export const throughput = (r: Range, scale: number) => Array.from({ length: Number(r) }, (_, i) => ({ day: PERF_SERIES.slice(-Number(r))[i]?.day ?? String(i), v: Math.max(1, Math.round((3 + 2.5 * Math.sin(i / 2.3) + i * 0.18 + (i % 3)) * Math.max(0.4, scale))) }));

export type Metric = "success" | "throughput" | "cost" | "value";
export interface Line { key: string; name: string; c: string }
export function trendSeries(metric: Metric, r: Range) {
  const p = tail(PERF_SERIES, r), s = tail(SPEND_SERIES, r);
  if (metric === "success") return { unit: "%", dom: [88, 100] as [number, number], lines: [{ key: "a", name: "Missions", c: "#a77bff" }, { key: "b", name: "Agents", c: "#22d3ee" }, { key: "c", name: "Organization", c: "#3b8cff" }] as Line[],
    rows: p.map((x) => ({ day: x.day, a: x.success, b: +Math.min(99.5, x.autonomy + 10).toFixed(1), c: +Math.min(99.5, (x.success + x.autonomy + 10) / 2 - 0.9).toFixed(1) })) };
  if (metric === "throughput") return { unit: "", dom: ["auto", "auto"] as [string, string], lines: [{ key: "a", name: "Tasks / day", c: "#22d3ee" }, { key: "b", name: "Missions / day", c: "#a77bff" }] as Line[],
    rows: p.map((x, i) => ({ day: x.day, a: Math.round(14 + 6 * Math.sin(i / 2.7) + i * 0.4), b: +(1.4 + 0.7 * Math.cos(i / 3) + i * 0.03).toFixed(1) })) };
  if (metric === "cost") return { unit: "$", dom: ["auto", "auto"] as [string, string], lines: [{ key: "a", name: "Spend / day", c: "#f2b53a" }, { key: "b", name: "Daily budget", c: "#94a3b8" }] as Line[], rows: s.map((x) => ({ day: x.day, a: x.spend, b: x.budget })) };
  return { unit: "$", dom: ["auto", "auto"] as [string, string], lines: [{ key: "a", name: "Value / day", c: "#2fd27a" }, { key: "b", name: "Cost / day", c: "#f2b53a" }] as Line[], rows: s.map((x) => ({ day: x.day, a: Math.round(x.spend * (FINANCE.revenue / FINANCE.month) * 1.1), b: x.spend })) };
}

// SAMPLE: resource mix over time (percent stack).
export const RESOURCES = [{ k: "compute", n: "Compute", c: "#22d3ee", w: 42 }, { k: "memory", n: "Memory", c: "#a77bff", w: 24 }, { k: "storage", n: "Storage", c: "#2fd27a", w: 16 }, { k: "tools", n: "Tools & API", c: "#f2b53a", w: 10 }, { k: "other", n: "Other", c: "#94a3b8", w: 8 }];
export const resourceSeries = (r: Range) => Array.from({ length: Number(r) }, (_, i) => {
  const row: Record<string, number | string> = { day: PERF_SERIES.slice(-Number(r))[i]?.day ?? String(i) };
  const raw = RESOURCES.map((x, j) => x.w * (1 + 0.18 * Math.sin(i / 2 + j * 1.7)));
  const sum = raw.reduce((a, b) => a + b, 0);
  RESOURCES.forEach((x, j) => { row[x.k] = +((raw[j] / sum) * 100).toFixed(1); });
  return row;
});

// Linear regression forecast over a series.
export function forecast(values: number[], ahead: number) {
  const n = values.length; if (n < 2) return { slope: 0, next: [] as number[] };
  const mx = (n - 1) / 2, my = avg(values);
  const slope = values.reduce((s, v, i) => s + (i - mx) * (v - my), 0) / values.reduce((s, _, i) => s + (i - mx) ** 2, 0);
  return { slope, next: Array.from({ length: ahead }, (_, k) => my + slope * (n + k - mx)) };
}
export const fmt$ = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
export const ago = (iso: string) => { const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

// Short-horizon projection: slope of the last `win` points, anchored at the latest value.
export function project(values: number[], ahead: number, win = 7) {
  const last = values[values.length - 1] ?? 0, w = values.slice(-win), f = forecast(w, 0);
  const slope = w.length > 1 ? (w[w.length - 1] - w[0]) / (w.length - 1) : 0; void f;
  return { slope, next: Array.from({ length: ahead }, (_, k) => last + slope * (k + 1)) };
}
