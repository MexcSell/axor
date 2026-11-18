import { motion } from "framer-motion";
import { CheckCircle2, Circle, KeyRound, Percent, RotateCcw, Rocket, ShieldCheck, Flag, X, AlertTriangle } from "lucide-react";
import { Btn, Panel, Progress, Row, Switch, useToast, Empty } from "../../ui/kit";
import { approveCandidateGate, candidateAction, promotionBlockers, toastIfErr, useStore } from "../../data/store";
import { CandPill, RiskPill, change, vetoOf } from "./shared";

export function QueueTab({ sel, onSel }: { sel: string; onSel: (id: string) => void }) {
  const toast = useToast();
  const cands = useStore((s) => s.candidates), versions = useStore((s) => s.agentVersions);
  const state = useStore((s) => s); // promotion gates read agents, versions, identity and errors
  const queue = cands.filter((c) => ["passed", "promoted", "evaluating"].includes(c.status));
  const c = queue.find((x) => x.id === sel) ?? queue[0];
  if (!c) return <Empty title="Nothing waiting for promotion" />;
  const rp = versions.some((v) => v.agentId === c.agentId && v.version === c.from);
  const veto = vetoOf(c);
  const gates = [
    { l: "QA sign-off", icon: ShieldCheck, ok: c.status === "passed" || c.status === "promoted", d: `${c.evaluator} ${c.status === "evaluating" ? "is still evaluating" : "verified it better"}` },
    { l: "Security veto clear", icon: ShieldCheck, ok: !veto, d: veto ? "security regression" : "no new findings" },
    { l: "Permission gate", icon: KeyRound, ok: c.risk === "low" || !!c.permissionApproved || c.status === "promoted", d: c.risk === "low" ? "low risk: automatic" : `${c.risk} risk: needs your approval` },
    { l: "Rollback point", icon: RotateCcw, ok: rp, d: rp ? `${c.from} pinned` : "missing" },
    { l: "Canary plan", icon: Percent, ok: true, d: "10% → 50% → 100%" },
  ];
  const blockers = promotionBlockers(state, c); // enforced again inside candidateAction
  const can = gates.every((g) => g.ok) && !blockers.length;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "44fr 56fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title={`Promotion Queue (${queue.length})`} icon={Flag} help="Candidates waiting for, or in, promotion. Only verified candidates can be promoted, and only when every gate is green. Promoted versions are used from next time, via canary.">
        <div className="ax-rows" style={{ display: "grid", gap: 6 }}>
          {queue.map((x, i) => <Row key={x.id} i={i} sel={x.id === c.id} onClick={() => onSel(x.id)} label={x.title}>
            <span className="grow"><b className="t">{x.id} · {x.title}</b><span className="s">{x.from} → {x.to} · +{x.delta}% est.</span></span><RiskPill r={x.risk} /><CandPill s={x.status} /></Row>)}
        </div>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
      <Panel i={1} title={`Gates · ${c.agentId} ${c.to}`} icon={ShieldCheck} hl help="Every gate must be green before Promote is enabled. After promotion a canary share of new work uses the new version; Rollback returns to the pinned rollback point at any time.">
        <div className="ax-col" style={{ gap: 6 }}>
          {gates.map((g, i) => <motion.div key={g.l} className="ax-tile ax-flex" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .06 }}>
            {g.ok ? <CheckCircle2 size={17} className="ax-ok" aria-label="passed" /> : <Circle size={17} className="ax-bad" aria-label="not met" />}<g.icon size={15} className="ax-muted" aria-hidden /><b className="ax-small" style={{ flex: 1 }}>{g.l}</b><span className="ax-small ax-muted">{g.d}</span>
            {g.l === "Permission gate" && c.risk !== "low" && c.status === "passed" && <Switch on={!!c.permissionApproved} onChange={(v) => toastIfErr(approveCandidateGate(c.id, v), toast)} label="Approve permission gate" />}</motion.div>)}
          <div className="ax-tile"><div className="ax-flex ax-small"><Percent size={14} aria-hidden /><b>Canary rollout</b><span className="ax-spacer" /><b className="ax-num">{c.canary ?? 0}%</b></div><Progress value={c.canary ?? 0} thin label="Canary share" /></div>
          <div className="ax-flex" style={{ flexWrap: "wrap" }}>
            <Btn icon={Rocket} tone="gold" disabled={!can} title={can ? "Promote" : "Needs a verified candidate and all gates green"} onClick={() => { if (!toastIfErr(candidateAction(c.id, "promote"), toast)) toast(`${c.agentId} ${c.to} promoted: used from next time, canary 10% (sample, in-memory)`, "ok"); }}>Promote</Btn>
            <Btn icon={X} disabled={c.status === "promoted"} onClick={() => { if (!toastIfErr(candidateAction(c.id, "reject"), toast)) toast(`${c.id} rejected, baseline ${c.from} stays in use`, "warn"); }}>Reject</Btn>
            <Btn icon={RotateCcw} disabled={c.status !== "promoted"} onClick={() => { if (!toastIfErr(candidateAction(c.id, "rollback"), toast)) toast(`Rolled back to ${c.from}`, "warn"); }}>Rollback</Btn>
          </div>
          {!can && c.status !== "promoted" && <span className="ax-small ax-warn ax-flex"><AlertTriangle size={13} aria-hidden />Promote is disabled: {blockers.length ? blockers.join("; ") : "every gate must be green"}.</span>}
        </div>
      </Panel>
      <Panel i={2} title="Evidence" icon={Flag} help="The benchmark evidence the verifier signed off on (see the Benchmarks tab for the full comparison).">
        <div className="ax-col" style={{ gap: 4 }}>{c.metrics.map((m) => { const ch = change(m); const col = ch.same ? "var(--ax-neutral)" : ch.better ? "var(--ax-ok)" : "var(--ax-bad)"; return <div key={m.name} className="ax-flex ax-small"><span style={{ flex: 1 }}>{m.name}</span><span className="ax-num ax-muted">{m.base}{m.unit} → {m.cand}{m.unit}</span><b className="ax-num" style={{ color: col, width: 60, textAlign: "right" }}>{ch.same ? "±0" : `${ch.pct > 0 ? "+" : ""}${ch.pct.toFixed(1)}%`}</b></div>; })}</div>
      </Panel>
      </div>
    </div>
  );
}
