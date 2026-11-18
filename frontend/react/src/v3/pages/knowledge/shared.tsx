import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Hourglass } from "lucide-react";
import { Pill } from "../../ui/kit";
import type { KnowledgeItem } from "../../domain/types";
import { QUEUE_EXTRA, type QItem } from "./data";

export const KSTATUS = {
  verified: { c: "var(--ax-ok)", icon: CheckCircle2, label: "Verified" }, pending: { c: "var(--ax-warn)", icon: Hourglass, label: "Pending verification" },
  conflict: { c: "var(--ax-bad)", icon: AlertTriangle, label: "Conflicting evidence" }, outdated: { c: "var(--ax-neutral)", icon: Clock3, label: "Outdated" },
} as const;
export function KStatus({ s, label }: { s: KnowledgeItem["status"]; label?: string }) {
  const d = KSTATUS[s]; return <Pill c={d.c} icon={d.icon}>{label ?? d.label}</Pill>;
}
export const KIND_C: Record<string, string> = { fact: "#22d3ee", procedure: "#3b8cff", decision: "#a77bff", lesson: "#f2b53a", research: "#2fd27a", skill: "#ff7a59" };

/** Learning Queue state. Local to the page: the store has no knowledge actions yet (see report). */
export interface Learning {
  decided: Record<string, "approved" | "rejected">; dist: Record<string, string[]>;
  decide: (id: string, d: "approved" | "rejected") => void; distribute: (id: string, to: string[]) => void; revoke: (id: string) => void;
  queue: QItem[];
}
export function useLearning(knowledge: KnowledgeItem[]): Learning {
  const [decided, setDecided] = useState<Learning["decided"]>({});
  const [dist, setDist] = useState<Learning["dist"]>({});
  const queue = useMemo<QItem[]>(() => [
    ...QUEUE_EXTRA,
    ...knowledge.filter((k) => k.status !== "verified").map((k): QItem => ({
      id: k.id, title: k.title, origin: k.scope === "organization" ? "internal" : "external", source: k.scope === "organization" ? "Internal research" : `Mission ${k.scope}`,
      summary: `${k.kind} · ${k.citations} citations · owner ${k.owner}`, confidence: Math.round(k.confidence * 100), license: "Internal",
      flags: k.status === "conflict" ? ["Contradicting evidence"] : k.status === "outdated" ? ["Source older than 12 months"] : ["Awaiting human verification"], missions: k.scope.startsWith("M-") ? [k.scope] : [], base: k.status === "verified" ? undefined : k.status,
    })),
  ], [knowledge]);
  return {
    decided, dist, queue,
    decide: (id, d) => setDecided((x) => ({ ...x, [id]: d })),
    distribute: (id, to) => setDist((x) => ({ ...x, [id]: to })),
    revoke: (id) => setDist((x) => { const n = { ...x }; delete n[id]; return n; }),
  };
}
export const host = (u: string) => { try { return new URL(u).hostname; } catch { return u; } };
