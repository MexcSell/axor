import { Ban, CheckCircle2, FlaskConical, Hourglass, Lightbulb, RotateCcw, Rocket, ShieldAlert, XCircle, type LucideIcon } from "lucide-react";
import { Pill } from "../../ui/kit";
import type { Candidate } from "../../domain/types";

// Sample constants for the Evolution Lab (the candidate/benchmark data itself comes from the store).
export const CS: Record<Candidate["status"], { label: string; c: string; icon: LucideIcon }> = {
  proposed: { label: "Proposed", c: "var(--ax-neutral)", icon: Lightbulb }, experiment: { label: "Experiment", c: "var(--ax-accent2)", icon: FlaskConical },
  evaluating: { label: "Evaluating", c: "var(--ax-info)", icon: Hourglass }, passed: { label: "Verified", c: "var(--ax-ok)", icon: CheckCircle2 },
  failed: { label: "Failed verification", c: "var(--ax-bad)", icon: XCircle }, promoted: { label: "Promoted", c: "var(--ax-ok)", icon: Rocket },
  rejected: { label: "Rejected", c: "var(--ax-bad)", icon: Ban }, rolled_back: { label: "Rolled back", c: "var(--ax-blocked)", icon: RotateCcw },
};
export function CandPill({ s }: { s: Candidate["status"] }) { const d = CS[s]; return <Pill c={d.c} icon={d.icon}>{d.label}</Pill>; }
export const RISK_C = { low: "var(--ax-ok)", medium: "var(--ax-warn)", high: "var(--ax-bad)" } as const;
export function RiskPill({ r }: { r: Candidate["risk"] }) { return <Pill c={RISK_C[r]} icon={r === "low" ? undefined : ShieldAlert}>{r} risk</Pill>; }

/** Direction-aware change of a metric. regression = got worse. */
export function change(m: Candidate["metrics"][number]) {
  const d = m.cand - m.base; const better = m.higherBetter ? d > 0 : d < 0; const same = d === 0;
  const pct = m.base ? (d / m.base) * 100 : 0;
  return { d, better, same, regression: !better && !same, pct };
}
export const isSecurity = (n: string) => /security/i.test(n);
/** Security veto: any security metric that got worse blocks the candidate whatever its other gains. */
export function vetoOf(c: Candidate) { return c.metrics.some((m) => isSecurity(m.name) && change(m).regression); }
export const fmt = (n: number, u: string) => `${+n.toFixed(2)}${u === "$" ? "" : u}`.replace(/^/, u === "$" ? "$" : "");
