import { useState } from "react";
import { motion } from "framer-motion";
import { Activity, Award, BarChart3, BookOpen, Box, CheckCircle2, ClipboardList, Code2, FileText, FlaskConical, History, Lightbulb, MessageSquareText, Percent, Play, RefreshCw, Rocket, RotateCcw, ShieldCheck, Sparkles, Users, Wrench, X, XCircle } from "lucide-react";
import { Avatar, type Role } from "../../ui/Avatar";
import { Btn, Donut, IconBtn, Panel, Pill, Switch, Time, useToast } from "../../ui/kit";
import { candidateAction, toastIfErr, setSettings, useStore } from "../../data/store";
import { roleOf } from "../../ui/widgets";
import type { Candidate } from "../../domain/types";
import { CandPill, RISK_C, change, vetoOf } from "./shared";
import { PipelineStrip } from "./Proposals";

// Sample layout of the 30-7 reference: every number below comes from the store (candidates / versions / experiences), none is live telemetry.
const KIND: Record<string, { icon: typeof Code2; label: string }> = { code: { icon: Code2, label: "Code" }, prompt: { icon: MessageSquareText, label: "Prompt" }, skill: { icon: Wrench, label: "Skill" }, knowledge: { icon: BookOpen, label: "Knowledge" }, procedure: { icon: ClipboardList, label: "Procedure" } };
const PRI = { low: "Low", medium: "Medium", high: "High" } as const;
export const VERIFIERS: [Role, string][] = [["research", "Research"], ["developer", "Development"], ["ops", "Operations"], ["qa", "QA / Verifier"], ["knowledge", "Knowledge"], ["finance", "Finance"], ["deploy", "Deployment"]];
const bump = (v: string) => v.replace(/^v(\d+)\.(\d+)\.(\d+)$/, (_m, a, b) => `v${a}.${+b + 1}.0`);

export function CandidatesPanel({ sel, onSel, i = 0 }: { sel: string; onSel: (id: string) => void; i?: number }) {
  const cands = useStore((s) => s.candidates); const [f, setF] = useState("all");
  const kinds = ["all", ...Object.keys(KIND).filter((k) => cands.some((c) => c.kind === k))];
  const list = cands.filter((c) => f === "all" || c.kind === f);
  return (
    <Panel i={i} title={`Candidate Upgrades (${cands.length})`} icon={Sparkles} help="Upgrades proposed by agents from their own experience (prompts, code, skills, knowledge). Each needs independent verification before it can replace the current version. Tick rows to select several."
      tabs={<div className="ax-flex" style={{ gap: 4, flexWrap: "wrap", padding: "0 2px" }}>{kinds.map((k) => <button key={k} type="button" className="ax-chip" aria-pressed={f === k} style={{ cursor: "pointer", border: "1px solid var(--ax-border)", background: f === k ? "color-mix(in srgb, var(--ax-accent) 22%, transparent)" : "transparent", color: "inherit" }} onClick={() => setF(k)}>{k === "all" ? `All (${cands.length})` : `${KIND[k].label} (${cands.filter((c) => c.kind === k).length})`}</button>)}</div>}>
      <table className="ax-table"><thead><tr><th>#</th><th>Type</th><th>Candidate Upgrade</th><th>Status</th><th>Est. Gain</th><th>Priority</th></tr></thead>
        <tbody>{list.map((c, k) => { const K = KIND[c.kind]; return (
          <motion.tr key={c.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .04 }} onClick={() => onSel(c.id)} style={{ cursor: "pointer", background: sel === c.id ? "color-mix(in srgb, var(--ax-accent) 10%, transparent)" : undefined }}>
            <td className="ax-mono" style={{ whiteSpace: "nowrap" }}><b>{c.id}</b></td><td><K.icon size={16} className="ax-gold" aria-label={K.label} /></td>
            <td><b className="ax-xs" style={{ display: "block", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={c.title}>{c.title}</b></td><td><CandPill s={c.status} /></td>            <td><b className="ax-num" style={{ color: c.delta >= 0 ? "var(--ax-ok)" : "var(--ax-bad)" }}>{c.delta >= 0 ? "+" : ""}{c.delta}%</b></td><td><Pill c={RISK_C[c.risk]}>{PRI[c.risk]}</Pill></td></motion.tr>); })}</tbody></table>
    </Panel>
  );
}

export function VerifiersPanel({ i = 1, big }: { i?: number; big?: boolean }) {
  return (
    <Panel i={i} title={`Agent Verifiers (${VERIFIERS.length})`} icon={Users} help="Independent verifier agents, one per discipline. A verifier never evaluates a change it helped author, and a mentor never verifies their own trainee.">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, justifyItems: "center" }}>
        {VERIFIERS.map(([r, n], k) => <motion.div key={r} style={{ textAlign: "center" }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .05 }} whileHover={{ y: -3 }}><Avatar role={r} size={big ? 54 : 40} name={n} /><div className="ax-xs">{n}</div><CheckCircle2 size={14} className="ax-ok" aria-label="available" /></motion.div>)}
      </div>
    </Panel>
  );
}

export function AssignmentPanel({ i = 2 }: { i?: number }) {
  const cands = useStore((s) => s.candidates); const toast = useToast();
  const res = (c: Candidate) => c.status === "passed" || c.status === "promoted" ? ["Verified", "var(--ax-ok)"] : c.status === "failed" || c.status === "rejected" || c.status === "rolled_back" ? ["Failed", "var(--ax-bad)"] : c.status === "evaluating" ? ["In review", "var(--ax-info)"] : ["Pending", "var(--ax-neutral)"];
  return (
    <Panel i={i} title="Verifier Assignment & Reviews" icon={ClipboardList} help="Which verifier agents review which upgrade, and the result. The primary verifier is independent of the agent that authored the upgrade.">
      <table className="ax-table"><thead><tr><th>Upgrade</th><th>Assigned Verifiers</th><th>Review Result</th><th>Score</th><th>Details</th></tr></thead>
        <tbody>{cands.slice(0, 6).map((c, k) => { const [t, col] = res(c); const extra = (["qa", "knowledge", "ops", "finance"] as Role[]).filter((r) => r !== roleOf(c.evaluator)).slice(k % 2, (k % 2) + 2); return (
          <motion.tr key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: k * .05 }}>
            <td className="ax-mono"><b>{c.id}</b></td><td><span className="ax-flex" style={{ gap: 2 }}><Avatar role={roleOf(c.evaluator)} size={18} name={c.evaluator} />{extra.map((r) => <Avatar key={r} role={r} size={18} />)}</span></td>
            <td><Pill c={col} icon={t === "Verified" ? CheckCircle2 : t === "Failed" ? XCircle : undefined}>{t}</Pill></td><td><b className="ax-num" style={{ color: c.delta >= 0 ? "var(--ax-ok)" : "var(--ax-bad)" }}>{c.delta >= 0 ? "+" : ""}{c.delta}%</b></td>
            <td><IconBtn icon={FileText} size="sm" label={`Review report for ${c.id}`} onClick={() => toast(`Review of ${c.id} by ${c.evaluator}: ${t}, ${c.metrics.filter((m) => change(m).regression).length} regression(s) (sample report)`, "info")} /></td></motion.tr>); })}</tbody></table>
    </Panel>
  );
}

export function DecisionPanel({ sel, i = 3 }: { sel: string; i?: number }) {
  const cands = useStore((s) => s.candidates); const toast = useToast(); const c = cands.find((x) => x.id === sel) ?? cands[0]; const veto = vetoOf(c); const K = KIND[c.kind];
  const act = (a: "evaluate" | "promote" | "reject" | "rollback", m: string) => { if (!toastIfErr(candidateAction(c.id, a), toast)) toast(m, a === "reject" || a === "rollback" ? "warn" : "ok"); };
  return (
    <Panel i={i} title="Decision & Promotion" icon={ClipboardList} hl help="Verify, then decide. Promote works only for candidates the independent verifier has passed; a security regression vetoes it. A promoted version is used from next time and can be rolled back."
      actions={<IconBtn icon={Play} size="sm" label={`Evaluate ${c.id} (independent verifier ${c.evaluator})`} disabled={c.status === "evaluating" || c.status === "promoted"} onClick={() => act("evaluate", `Independent evaluation of ${c.id} started by ${c.evaluator} (sample run, ~2 s)`)} />}>
      <div className="ax-flex" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}><b style={{ fontSize: 15 }}>{c.id} — {K.label} Upgrade</b><div className="ax-flex" style={{ marginTop: 3 }}><CandPill s={c.status} />{veto && <Pill c="var(--ax-bad)" solid icon={ShieldCheck}>Security veto</Pill>}</div><div className="ax-xs" style={{ marginTop: 3 }}>{c.title}. {c.summary}</div></div>
        <div className="ax-flex" style={{ gap: 4, flex: "none" }}>{[[c.from, "Current"], [c.to, "Candidate"]].map(([v, l], k) => <div key={l} className="ax-flex" style={{ gap: 4 }}>{k === 1 && <span aria-hidden className="ax-gold">→</span>}<div className="ax-tile" style={{ textAlign: "center", padding: "2px 8px", borderColor: k ? "var(--ax-accent)" : undefined }}><Box size={14} className={k ? "ax-gold" : "ax-ok"} aria-hidden /><div><b className="ax-xs">{v}</b></div><div className="ax-xs ax-muted">({l})</div></div></div>)}</div>
      </div>
      <div className="ax-tile" style={{ marginTop: 5, padding: "4px 8px" }}><b className="ax-xs">Evaluation (vs. {c.from})</b>
        {c.metrics.filter((m) => m.base > 0 || m.cand > 0).slice(0, 4).map((m) => { const ch = change(m); const col = ch.same ? "var(--ax-neutral)" : ch.better ? "var(--ax-ok)" : "var(--ax-bad)"; return <div key={m.name} className="ax-flex ax-xs"><span style={{ width: 96 }}>{m.name}</span><div className="ax-bar thin" style={{ flex: 1 }}><motion.i initial={{ width: 0 }} animate={{ width: `${Math.min(100, Math.abs(ch.pct) * 3 + 8)}%` }} transition={{ duration: .8 }} style={{ background: `linear-gradient(90deg, var(--ax-info), ${col})` }} /></div><b className="ax-num" style={{ color: col, width: 54, textAlign: "right" }}>{ch.pct > 0 ? "+" : ""}{ch.pct.toFixed(1)}%</b></div>; })}</div>
      <div className="ax-flex" style={{ marginTop: 6 }}>
        <Btn icon={Rocket} style={{ flex: 1, borderColor: "var(--ax-ok)", color: "var(--ax-ok)" }} disabled={c.status !== "passed" || veto} title={c.status === "passed" ? "Promote" : "Only verified candidates can be promoted"} onClick={() => act("promote", `${c.agentId} ${c.to} promoted: used from next time (canary 10%)`)}>Promote</Btn>
        <Btn icon={X} style={{ flex: 1, borderColor: "var(--ax-bad)", color: "var(--ax-bad)" }} disabled={["promoted", "rejected", "rolled_back"].includes(c.status)} onClick={() => act("reject", `${c.id} rejected`)}>Reject</Btn>
        <Btn icon={RotateCcw} tone="gold" style={{ flex: 1 }} disabled={c.status !== "promoted"} onClick={() => act("rollback", `${c.agentId} rolled back to ${c.from}`)}>Rollback</Btn>
      </div>
    </Panel>
  );
}

export function BenchPanel({ sel, i = 5 }: { sel: string; i?: number }) {
  const cands = useStore((s) => s.candidates); const c = cands.find((x) => x.id === sel) ?? cands[0];
  const ms = c.metrics.filter((m) => m.base > 0).slice(0, 5); const max = Math.max(110, ...ms.map((m) => Math.max(m.base, m.cand) / m.base * 100));
  return (
    <Panel i={i} title={`Benchmark Comparison (${c.from} → ${c.to})`} icon={BarChart3} help="Baseline and candidate on the same tasks. Bars are scaled to the baseline (=100%); the pill shows the change, green when better (lower is better for time and cost), red for a regression."
      actions={<span className="ax-flex ax-xs"><i style={{ width: 10, height: 10, background: "var(--ax-info)", borderRadius: 2 }} aria-hidden />{c.from} (Old)<i style={{ width: 10, height: 10, background: "var(--ax-accent2)", borderRadius: 2 }} aria-hidden />{c.to} (New)</span>}>
      <div style={{ height: "100%", display: "grid", gridTemplateColumns: `repeat(${ms.length}, 1fr)`, gap: 10, alignItems: "end" }}>
        {ms.map((m, k) => { const ch = change(m); const col = ch.better ? "var(--ax-ok)" : ch.same ? "var(--ax-neutral)" : "var(--ax-bad)"; const hb = 100 / max * 100, hc = (m.cand / m.base * 100) / max * 100;
          return (<div key={m.name} style={{ height: "100%", display: "grid", gridTemplateRows: "1fr auto auto", gap: 3, minHeight: 0, textAlign: "center" }}>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 6, borderBottom: "1px solid var(--ax-border)", minHeight: 0 }}>
              {[[m.base, hb, "var(--ax-info)"], [m.cand, hc, ch.regression ? "var(--ax-bad)" : "var(--ax-accent2)"]].map(([v, h, bg], j) => <div key={j} style={{ width: 30, height: `${h}%`, display: "flex", flexDirection: "column", justifyContent: "flex-end", alignItems: "center" }}><span className="ax-xs ax-num"><b>{v}{m.unit === "$" ? "" : m.unit}</b></span><motion.div initial={{ height: 0 }} animate={{ height: "100%" }} transition={{ duration: .8, delay: k * .08 }} style={{ width: "100%", background: bg as string, borderRadius: "4px 4px 0 0", flex: "1 1 auto", minHeight: 2 }} /></div>)}
            </div>
            <span className="ax-xs">{m.name}</span><Pill c={col}>{ch.pct > 0 ? "+" : ""}{ch.pct.toFixed(1)}%</Pill></div>); })}
      </div>
    </Panel>
  );
}

export function StatusPanel({ i = 6 }: { i?: number }) {
  const cands = useStore((s) => s.candidates), renewal = useStore((s) => s.settings.selfRenewal); const toast = useToast();
  const [auto, setAuto] = useState<Record<string, boolean>>({ Proposal: true, Training: true, Evaluation: true, Promotion: true });
  const n = (...s: string[]) => cands.filter((c) => s.includes(c.status)).length;
  const rows: [string, typeof RefreshCw, boolean, ((v: boolean) => void) | null][] = [["Self-Renewal", RefreshCw, renewal, (v) => { setSettings({ selfRenewal: v }); toast(`Self-renewal ${v ? "enabled" : "disabled"}`, "info"); }], ["Verified Evolution", ShieldCheck, true, null],
    ...["Proposal", "Training", "Evaluation", "Promotion"].map((k) => [`Auto ${k}`, k === "Promotion" ? Rocket : k === "Evaluation" ? ClipboardList : k === "Training" ? Wrench : Lightbulb, auto[k], (v: boolean) => { setAuto({ ...auto, [k]: v }); toast(`Auto ${k.toLowerCase()} ${v ? "on" : "off"} (sample setting)`, "info"); }] as [string, typeof RefreshCw, boolean, (v: boolean) => void])];
  return (
    <Panel i={i} title="Evolution Status & Self-Renewal" icon={BarChart3} help="Whether the self-renewal loop is on and which stages run automatically. Verified Evolution cannot be turned off: nothing is promoted without independent verification.">
      <div className="ax-flex" style={{ gap: 8 }}>
        <Donut label="Candidates by outcome" size={96} stroke={11} parts={[{ label: "Promoted", value: n("promoted"), c: "var(--ax-ok)" }, { label: "Verified", value: n("passed"), c: "var(--ax-info)" }, { label: "Running", value: n("experiment", "evaluating"), c: "var(--ax-accent)" }, { label: "Closed", value: n("failed", "rejected", "rolled_back"), c: "var(--ax-bad)" }]} center={<div style={{ textAlign: "center" }}><b style={{ fontSize: 22 }}>{n("promoted")}</b><div className="ax-xs">Promoted</div></div>} />
        <div className="ax-col" style={{ gap: 2, flex: 1 }}>{rows.map(([l, I, on, f]) => <div key={l} className="ax-flex ax-xs"><I size={13} className="ax-muted" aria-hidden /><span style={{ flex: 1 }}>{l}</span><Switch on={on} onChange={(v) => f?.(v)} label={l} disabled={!f} /><b className={on ? "ax-ok" : "ax-muted"} style={{ width: 22 }}>{on ? "ON" : "OFF"}</b></div>)}</div>
      </div>
    </Panel>
  );
}

export function ActivityPanel({ i = 7 }: { i?: number }) {
  const cands = useStore((s) => s.candidates);
  const ev = (c: Candidate): [string, typeof Rocket, string, string] => ({ promoted: ["Verified Evolution", Rocket, "Promoted", "var(--ax-ok)"], passed: ["Evaluation Complete", ShieldCheck, "Verified", "var(--ax-ok)"], evaluating: ["Evaluation Running", FlaskConical, "Running", "var(--ax-info)"], experiment: ["Experiment Started", FlaskConical, "Running", "var(--ax-info)"], proposed: ["Proposal Generated", Lightbulb, "Created", "var(--ax-ok)"], failed: ["Evaluation Complete", ShieldCheck, "Failed", "var(--ax-bad)"], rejected: ["Upgrade Rejected", X, "Rejected", "var(--ax-bad)"], rolled_back: ["Rolled Back", RotateCcw, "Rolled back", "var(--ax-blocked)"] } as const)[c.status] as [string, typeof Rocket, string, string];
  return (
    <Panel i={i} title="Recent Evolution Activity" icon={History} help="The latest evolution events derived from the candidates' status (sample).">
      <table className="ax-table"><thead><tr><th>Time</th><th>Event</th><th>Details</th><th>Result</th></tr></thead>
        <tbody>{[...cands].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 6).map((c, k) => { const [e, I, r, col] = ev(c); return <motion.tr key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: k * .05 }}><td className="ax-xs"><Time iso={c.at} /></td><td className="ax-xs"><span className="ax-flex" style={{ gap: 4 }}><I size={13} style={{ color: col }} aria-hidden />{e}</span></td><td className="ax-xs">{c.id} ({c.kind}) · {c.delta >= 0 ? "+" : ""}{c.delta}%</td><td><Pill c={col}>{r}</Pill></td></motion.tr>; })}</tbody></table>
    </Panel>
  );
}

export function VersionEvoPanel({ sel, i = 8 }: { sel: string; i?: number }) {
  const cands = useStore((s) => s.candidates), versions = useStore((s) => s.agentVersions); const c = cands.find((x) => x.id === sel) ?? cands[0];
  const parent = versions.find((v) => v.agentId === c.agentId && v.version === c.from)?.parent;
  const nodes: [string, string, string][] = [[parent ?? "—", "Previous", "var(--ax-neutral)"], [c.from, "Current", "var(--ax-ok)"], [c.to, c.status === "promoted" ? "Promoted" : "Candidate", "var(--ax-accent2)"], [bump(c.to), "Planned", "var(--ax-faint)"]];
  const ok = cands.filter((x) => x.status === "passed" || x.status === "promoted").length;
  const avg = cands.filter((x) => x.delta > 0).reduce((s, x, _k, a) => s + x.delta / a.length, 0);
  return (
    <Panel i={i} title="Version Evolution" icon={Box} help={`Lineage of ${c.agentId}: previous, current, candidate and the planned next version. Rollback always returns to the pinned current version.`}>
      <div className="ax-flex" style={{ justifyContent: "space-between" }}>{nodes.map(([v, l, col], k) => <div key={l} style={{ display: "contents" }}><motion.div className="ax-tile" style={{ textAlign: "center", padding: "3px 6px", borderColor: k === 2 ? "var(--ax-accent)" : undefined }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .1 }}><Box size={15} style={{ color: col }} aria-hidden /><div><b className="ax-xs">{v}</b></div><div className="ax-xs ax-muted">({l})</div></motion.div>{k < 3 && <span aria-hidden className="ax-gold">→</span>}</div>)}</div>
      <div className="ax-col" style={{ gap: 3, marginTop: 5 }}>{[[`All Verifiers Passed (${ok}/${cands.length})`, ok > 0], [`Benchmarks Improved (+${avg.toFixed(1)}% avg)`, avg > 0], [`Safe Rollback (${c.from})`, true]].map(([t, good]) => <div key={t as string} className="ax-tile ax-flex ax-xs" style={{ padding: "2px 8px" }}>{good ? <CheckCircle2 size={14} className="ax-ok" aria-label="yes" /> : <XCircle size={14} className="ax-bad" aria-label="no" />}{t as string}</div>)}</div>
    </Panel>
  );
}

export function MetricsPanel({ i = 9 }: { i?: number }) {
  const cands = useStore((s) => s.candidates);
  const pr = cands.filter((c) => c.status === "promoted"), closed = cands.filter((c) => ["promoted", "rejected", "failed", "rolled_back"].includes(c.status));
  const rows: [typeof Award, string, string, string?][] = [[Award, "Avg. Improvement (promoted)", pr.length ? `+${(pr.reduce((s, c) => s + c.delta, 0) / pr.length).toFixed(1)}%` : "n/a", "var(--ax-ok)"], [Percent, "Promotion Rate", closed.length ? `${Math.round(pr.length / closed.length * 100)}%` : "n/a", "var(--ax-ok)"], [RefreshCw, "Self-Renewal Cycle", "6.4 hours (sample)"],
    [FlaskConical, "Experiments (30d)", String(cands.filter((c) => c.status !== "proposed").length)], [ShieldCheck, "Verified Upgrades (30d)", String(cands.filter((c) => c.status === "passed" || c.status === "promoted").length)], [RotateCcw, "Rollback Rate", cands.length ? `${(cands.filter((c) => c.status === "rolled_back").length / cands.length * 100).toFixed(1)}%` : "0%"]];
  return (
    <Panel i={i} title="Key Metrics (Evolution)" icon={Activity} help="Headline evolution numbers computed from the candidate list (sample data; the self-renewal cycle time is a sample constant).">
      <div className="ax-col" style={{ gap: 3 }}>{rows.map(([I, l, v, c], k) => <motion.div key={l} className="ax-flex ax-xs" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .05 }}><I size={14} className="ax-gold" aria-hidden /><span style={{ flex: 1 }}>{l}</span><b className="ax-num" style={{ color: c }}>{v}</b></motion.div>)}</div>
    </Panel>
  );
}

export function EvoDashboard({ sel, onSel }: { sel: string; onSel: (id: string) => void }) {
  return (
    <div style={{ display: "grid", gridTemplateRows: "36fr 20fr 21fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateColumns: "36fr 32fr 30fr", gap: "var(--ax-gap)", minHeight: 0 }}><CandidatesPanel sel={sel} onSel={onSel} /><div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 }}><VerifiersPanel /><AssignmentPanel /></div><DecisionPanel sel={sel} /></div>
      <div style={{ display: "grid", gridTemplateColumns: "54fr 46fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={4} title="Evolution Pipeline — Self-Renewal & Verified Evolution" icon={RefreshCw} help="How agents renew themselves: collect experience, learn, update their own prompts/code/tools, verify independently, and promote only if verified better."><PipelineStrip /></Panel><BenchPanel sel={sel} /></div>
      <div style={{ display: "grid", gridTemplateColumns: "24fr 28fr 24fr 22fr", gap: "var(--ax-gap)", minHeight: 0 }}><StatusPanel /><ActivityPanel /><VersionEvoPanel sel={sel} /><MetricsPanel /></div>
    </div>
  );
}
