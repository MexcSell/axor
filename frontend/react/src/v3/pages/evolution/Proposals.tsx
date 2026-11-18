import { useState } from "react";
import { motion } from "framer-motion";
import { BookOpen, Brain, CheckCircle2, Database, FlaskConical, Filter, RotateCcw, Rocket, ShieldCheck, X, XCircle, Code2, MessageSquareText, Wrench } from "lucide-react";
import { Btn, Panel, Pill, Progress, Time, useToast, Empty } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import { candidateAction, toastIfErr, useStore } from "../../data/store";
import type { Candidate } from "../../domain/types";
import { CandPill, RiskPill, change, vetoOf } from "./shared";

const KIND: Record<Candidate["kind"], { icon: typeof Code2; label: string }> = { code: { icon: Code2, label: "Code" }, prompt: { icon: MessageSquareText, label: "Prompt" }, skill: { icon: Wrench, label: "Skill" }, knowledge: { icon: BookOpen, label: "Knowledge" }, procedure: { icon: ShieldCheck, label: "Procedure" } };

export function Decision({ c, compact }: { c: Candidate; compact?: boolean }) {
  const toast = useToast(); const veto = vetoOf(c);
  const act = (a: "evaluate" | "promote" | "reject" | "rollback", msg: string) => { if (!toastIfErr(candidateAction(c.id, a), toast)) toast(msg, a === "reject" || a === "rollback" ? "warn" : "ok"); };
  return (
    <div className="ax-col" style={{ gap: 7 }}>
      <div className="ax-flex"><b style={{ fontSize: 15 }}>{c.id} · {c.title}</b></div>
      <div className="ax-flex" style={{ flexWrap: "wrap", gap: 5 }}><CandPill s={c.status} /><RiskPill r={c.risk} /><Pill c="var(--ax-info)">{c.from} → {c.to}</Pill>{veto && <Pill c="var(--ax-bad)" icon={ShieldCheck} solid>Security veto</Pill>}</div>
      <div className="ax-small">{c.summary}</div>
      {!compact && c.metrics.slice(0, 4).map((m) => { const ch = change(m); const col = ch.same ? "var(--ax-neutral)" : ch.better ? "var(--ax-ok)" : "var(--ax-bad)";
        return <div key={m.name} className="ax-flex ax-small"><span style={{ width: 120 }}>{m.name}</span><div style={{ flex: 1 }}><Progress value={Math.min(100, Math.abs(ch.pct) * 3 + 4)} thin c1={col} c2={col} label={m.name} /></div><b className="ax-num" style={{ color: col, width: 70, textAlign: "right" }}>{ch.pct > 0 ? "+" : ""}{ch.pct.toFixed(1)}%</b></div>; })}
      {!compact && <div className="ax-flex ax-small" style={{ flexWrap: "wrap" }}><span className="ax-muted">Independent verifier:</span><AgentTag id={c.evaluator} size={20} /><span className="ax-muted">Source instances:</span>{c.sourceInstances.map((i) => <Pill key={i} c="var(--ax-info)">{i}</Pill>)}</div>}
      <div className="ax-flex" style={{ marginTop: 2, flexWrap: "wrap" }}>
        <Btn icon={FlaskConical} disabled={c.status === "evaluating" || c.status === "promoted"} onClick={() => act("evaluate", `Independent evaluation of ${c.id} started by ${c.evaluator} (sample run, ~2 s)`)}>Evaluate</Btn>
        <Btn icon={Rocket} tone="gold" disabled={c.status !== "passed" || veto} title={c.status === "passed" ? "Promote" : "Only verified candidates can be promoted"} onClick={() => act("promote", `${c.agentId} ${c.to} promoted: used from next time (canary 10%)`)}>Promote</Btn>
        <Btn icon={X} disabled={c.status === "promoted" || c.status === "rejected" || c.status === "rolled_back"} onClick={() => act("reject", `${c.id} rejected`)}>Reject</Btn>
        <Btn icon={RotateCcw} disabled={c.status !== "promoted"} onClick={() => act("rollback", `${c.agentId} rolled back to ${c.from}`)}>Rollback</Btn>
      </div>
      {c.status !== "passed" && <span className="ax-xs ax-muted">Promote is enabled only after the independent verifier {c.evaluator} has verified the candidate as better.</span>}
    </div>
  );
}

const STEPS = [
  { icon: Database, t: "Collect Experience", d: "from mission instances", n: "exp" }, { icon: Brain, t: "Learn", d: "patterns → proposals" }, { icon: Code2, t: "Train / Update", d: "prompts, code, tools" },
  { icon: ShieldCheck, t: "Verify", d: "independent benchmark" }, { icon: Rocket, t: "Promote", d: "if verified better" },
];
export function PipelineStrip() {
  const cands = useStore((s) => s.candidates), exps = useStore((s) => s.experiences);
  const counts = [exps.filter((x) => x.eligible).length + " eligible", cands.length + " proposals", cands.filter((c) => c.status === "experiment" || c.status === "evaluating").length + " running", cands.filter((c) => c.status === "passed").length + " verified", cands.filter((c) => c.status === "promoted").length + " promoted"];
  return (
    <div style={{ display: "flex", alignItems: "stretch", gap: 6, height: "100%" }} role="list" aria-label="Evolution pipeline">
      {STEPS.map((s, i) => (
        <div key={s.t} style={{ display: "contents" }}>
          <motion.div role="listitem" className="ax-tile" style={{ flex: 1, textAlign: "center", display: "grid", placeItems: "center", alignContent: "center", gap: 2, borderColor: i === 4 ? "var(--ax-accent)" : undefined }} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 * i }} whileHover={{ y: -3 }}>
            <span className="ax-xs ax-gold">{i + 1}</span><motion.span animate={{ scale: [1, 1.12, 1] }} transition={{ repeat: Infinity, duration: 2.4, delay: i * .3 }}><s.icon size={26} className={i === 4 ? "ax-gold" : "ax-ok"} aria-hidden /></motion.span><b className="ax-small">{s.t}</b><span className="ax-xs ax-muted">{s.d}</span><b className="ax-gold ax-small">{counts[i]}</b>
          </motion.div>
          {i < STEPS.length - 1 && <motion.span style={{ alignSelf: "center", color: "var(--ax-accent)" }} animate={{ x: [0, 4, 0] }} transition={{ repeat: Infinity, duration: 1.2, delay: i * .2 }} aria-hidden>→</motion.span>}
        </div>))}
    </div>
  );
}

export function ProposalsTab({ sel, onSel }: { sel: string; onSel: (id: string) => void }) {
  const cands = useStore((s) => s.candidates), exps = useStore((s) => s.experiences);
  const [f, setF] = useState<"all" | Candidate["kind"]>("all");
  const list = cands.filter((c) => f === "all" || c.kind === f); const c = cands.find((x) => x.id === sel) ?? cands[0];
  const kinds = ["all", ...Object.keys(KIND)] as ("all" | Candidate["kind"])[];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "58fr 42fr", gridTemplateRows: "minmax(0, 1.5fr) minmax(0, 1fr)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title={`Candidate Upgrades (${cands.length})`} icon={Filter} help="Upgrades proposed by agents from their own accumulated experience (prompts, code, skills, knowledge). Each must be verified by an independent verifier before it can replace the current version."
        actions={<span className="ax-flex" style={{ gap: 4, flexWrap: "wrap" }}>{kinds.map((k) => <button key={k} type="button" className="ax-chip" aria-pressed={f === k} style={{ cursor: "pointer", border: "1px solid var(--ax-border)", background: f === k ? "color-mix(in srgb, var(--ax-accent) 22%, transparent)" : "transparent", color: "inherit" }} onClick={() => setF(k)}>{k === "all" ? `All (${cands.length})` : `${KIND[k].label} (${cands.filter((x) => x.kind === k).length})`}</button>)}</span>}>
        <table className="ax-table"><thead><tr><th>#</th><th>Type</th><th>Candidate Upgrade</th><th>Agent</th><th>Est. gain</th><th>Risk</th><th>Status</th></tr></thead>
          <tbody>{list.map((x, i) => { const K = KIND[x.kind]; return (
            <motion.tr key={x.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .04 }} onClick={() => onSel(x.id)} style={{ cursor: "pointer", background: c?.id === x.id ? "color-mix(in srgb, var(--ax-accent) 10%, transparent)" : undefined }}>
              <td className="ax-mono"><b>{x.id}</b></td><td><span className="ax-flex ax-small"><K.icon size={15} className="ax-gold" aria-hidden />{K.label}</span></td>
              <td><b className="ax-small">{x.title}</b><div className="ax-xs ax-muted">{x.summary}</div></td><td><AgentTag id={x.agentId} size={20} /></td>
              <td><b className="ax-num" style={{ color: x.delta >= 0 ? "var(--ax-ok)" : "var(--ax-bad)" }}>{x.delta >= 0 ? "+" : ""}{x.delta}%</b></td><td><RiskPill r={x.risk} /></td><td><CandPill s={x.status} /></td></motion.tr>); })}</tbody></table>
      </Panel>
      <Panel i={1} title="Decision & Promotion" icon={Rocket} hl help="Verify, then decide. Promote works only for candidates the independent verifier has passed; a security regression vetoes it. A promoted version is used from next time, and can be rolled back.">
        {c ? <Decision c={c} /> : <Empty title="Select a candidate" />}
      </Panel>
      <Panel i={2} title="Evolution Pipeline — Self-Renewal & Verified Evolution" icon={Brain} help="How agents renew themselves: collect experience, learn, update their own prompts/code/tools, verify independently, and promote only if verified better.">
        <PipelineStrip />
      </Panel>
      <Panel i={3} title="Recent experience (eligible for learning)" icon={Database} help="Lessons collected from mission instances. Mission-private and unverified items are excluded by the privacy filter.">
        <div className="ax-col" style={{ gap: 5 }}>
          {exps.slice(0, 6).map((x, i) => <motion.div key={x.id} className="ax-flex ax-small" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }}>
            {x.eligible ? <CheckCircle2 size={14} className="ax-ok" aria-label="eligible" /> : <XCircle size={14} className="ax-faint" aria-label="excluded" />}
            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={x.lesson}>{x.lesson}</span><Pill c={x.eligible ? "var(--ax-ok)" : "var(--ax-neutral)"}>{x.kind}</Pill><span className="ax-xs ax-muted"><Time iso={x.at} /></span></motion.div>)}
        </div>
      </Panel>
    </div>
  );
}
