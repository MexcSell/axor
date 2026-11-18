import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Beaker, Eye, EyeOff, FlaskConical, GitBranch, ShieldCheck } from "lucide-react";
import { Panel, Pill, Progress, Row, StatusPill, Empty } from "../../ui/kit";
import { useStore } from "../../data/store";
import { CandPill } from "./shared";

export function ExperimentsTab({ sel, onSel }: { sel: string; onSel: (id: string) => void }) {
  const cands = useStore((s) => s.candidates), inst = useStore((s) => s.instances), exps = useStore((s) => s.experiences);
  const active = cands.filter((c) => ["experiment", "evaluating", "passed", "proposed"].includes(c.status));
  const c = cands.find((x) => x.id === sel) ?? active[0] ?? cands[0];
  const [tick, setTick] = useState(0); useEffect(() => { const t = window.setInterval(() => setTick((n) => n + 1), 1200); return () => clearInterval(t); }, []);
  const mine = inst.filter((i) => i.agentId === c.agentId); const ex = exps.filter((x) => x.agentId === c.agentId);
  const prog = (status: string, i: number) => status === "passed" ? 100 : status === "evaluating" ? Math.min(96, 55 + ((tick * 4 + i * 11) % 40)) : status === "experiment" ? Math.min(60, 20 + ((tick * 3 + i * 7) % 35)) : 5;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "38fr 62fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title={`Running experiments (${active.length})`} icon={FlaskConical} help="Each experiment runs the candidate version in isolated mission instances next to the baseline (A/B). Nothing touches the live baseline until verification passes.">
        <div className="ax-rows" style={{ display: "grid", gap: 6 }}>
          {active.map((x, i) => (
            <Row key={x.id} i={i} sel={x.id === c.id} onClick={() => onSel(x.id)} label={x.title}>
              <span className="grow"><b className="t">{x.id} · {x.title}</b><span className="s">{x.from} → {x.to} · {x.sourceInstances.length} instance(s) · evaluator {x.evaluator}</span><Progress value={prog(x.status, i)} thin label="Experiment progress" /></span>
              <CandPill s={x.status} />
            </Row>))}
          {!active.length && <Empty title="No running experiments" />}
        </div>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title={`Isolated instances · ${c.agentId}`} icon={GitBranch} help="Mission instances of the same agent run concurrently, each in its own branch and sandbox. Their results are merged into the agent's experience only through verified, privacy-filtered consolidation.">
          <table className="ax-table"><thead><tr><th>Instance</th><th>Mission</th><th>Pinned version</th><th>Branch</th><th>Progress</th><th>Status</th></tr></thead>
            <tbody>{mine.map((m, i) => <motion.tr key={m.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * .05 }}><td className="ax-mono">{m.id}</td><td>{m.missionId}</td><td className="ax-mono">{m.pinnedVersion}</td><td className="ax-mono ax-xs">{m.branch}</td><td style={{ minWidth: 90 }}><Progress value={m.progress} thin label="Instance progress" /></td><td><StatusPill s={m.status} small /></td></motion.tr>)}
              {!mine.length && <tr><td colSpan={6} className="ax-muted">No instances for {c.agentId}.</td></tr>}</tbody></table>
        </Panel>
        <Panel i={2} title="Experience consolidation" icon={Beaker} help="Lessons from the instances. Only verified, non-private, sufficiently general lessons are eligible to become part of the next version.">
          <div className="ax-col" style={{ gap: 5 }}>
            {ex.map((x, i) => <motion.div key={x.id} className="ax-tile ax-flex ax-small" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }}>
              {x.eligible ? <Eye size={14} className="ax-ok" aria-label="eligible" /> : <EyeOff size={14} className="ax-faint" aria-label="excluded" />}
              <span style={{ flex: 1, minWidth: 0 }}><b>{x.lesson}</b><div className="ax-xs ax-muted">{x.missionId} · {x.evidence}</div></span>
              <Pill c="var(--ax-info)">conf {Math.round(x.confidence * 100)}%</Pill><Pill c="var(--ax-accent2)">gen {Math.round(x.generalization * 100)}%</Pill><Pill c={x.eligible ? "var(--ax-ok)" : "var(--ax-neutral)"} icon={x.kind === "security" ? ShieldCheck : undefined}>{x.eligible ? "eligible" : x.kind === "private" ? "private, excluded" : "needs evidence"}</Pill></motion.div>)}
            {!ex.length && <span className="ax-muted ax-small">No experiences recorded yet for {c.agentId}.</span>}
          </div>
        </Panel>
      </div>
    </div>
  );
}
