import { useState } from "react";
import { motion } from "framer-motion";
import { History as HistoryI, Cuboid } from "lucide-react";
import { Pill } from "../../ui/kit";
import { Panel, Seg, Time, Empty } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import { useStore } from "../../data/store";
import { CS, CandPill, change } from "./shared";

export function HistoryTab({ onSel }: { onSel: (id: string) => void }) {
  const cands = useStore((s) => s.candidates), versions = useStore((s) => s.agentVersions);
  const [f, setF] = useState<"all" | "promoted" | "rejected" | "rolled_back">("all");
  const done = cands.filter((c) => ["promoted", "rejected", "rolled_back", "failed"].includes(c.status)).filter((c) => f === "all" || c.status === f || (f === "rejected" && c.status === "failed"));
  const vs = [...versions].sort((a, b) => b.at.localeCompare(a.at));
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
    <Panel i={0} title="Promotion history" icon={HistoryI} sub={`${done.length} decisions`} help="Every promotion, rejection and rollback with the evidence behind it: independent verifier, benchmark deltas and regressions."
      actions={<Seg label="Outcome filter" value={f} onChange={setF} items={[{ id: "all", label: "All" }, { id: "promoted", label: "Promoted" }, { id: "rejected", label: "Rejected" }, { id: "rolled_back", label: "Rolled back" }]} />}>
      {done.length ? <table className="ax-table"><thead><tr><th>When</th><th>Candidate</th><th>Agent</th><th>Version</th><th>Outcome</th><th>Verifier</th><th>Evidence</th></tr></thead>
        <tbody>{done.map((c, i) => { const regs = c.metrics.filter((m) => change(m).regression); return (
          <motion.tr key={c.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }} onClick={() => onSel(c.id)} style={{ cursor: "pointer" }}>
            <td className="ax-small"><Time iso={c.at} withDate /></td><td><b className="ax-small">{c.id}</b><div className="ax-xs ax-muted">{c.title}</div></td><td><AgentTag id={c.agentId} size={20} /></td>
            <td className="ax-mono ax-small">{c.from} → {c.to}</td><td><CandPill s={c.status} /></td><td><AgentTag id={c.evaluator} size={20} /></td>
            <td className="ax-small"><b style={{ color: c.delta >= 0 ? "var(--ax-ok)" : "var(--ax-bad)" }}>{c.delta >= 0 ? "+" : ""}{c.delta}% overall</b>{regs.length ? <> · <span className="ax-bad">regressed: {regs.map((m) => m.name).join(", ")}</span></> : <span className="ax-muted"> · no regressions</span>}{c.canary != null && <> · canary {c.canary}%</>}</td></motion.tr>); })}</tbody></table> : <Empty title={`No ${CS[f === "all" ? "promoted" : f].label.toLowerCase()} decisions yet`} />}
    </Panel>
    <Panel i={1} title="Agent version timeline" icon={Cuboid} help="Every version of every agent that has been recorded, newest first: baselines, retired versions, and the rejected or rolled-back ones kept as evidence.">
      <div className="ax-col" style={{ gap: 5 }}>{vs.map((v, i) => { const c = v.status === "baseline" ? "var(--ax-ok)" : v.status === "candidate" ? "var(--ax-info)" : v.status === "retired" ? "var(--ax-neutral)" : "var(--ax-bad)";
        return <motion.div key={v.agentId + v.version} className="ax-tile ax-flex ax-small" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}><Cuboid size={15} style={{ color: c }} aria-hidden /><b style={{ width: 60 }}>{v.agentId}</b><b className="ax-mono">{v.version}</b><Pill c={c}>{v.status.replace("_", " ")}</Pill><span className="ax-muted" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.changes.join("; ")}</span><b className="ax-num">{v.score}</b><span className="ax-muted"><Time iso={v.at} withDate /></span></motion.div>; })}</div>
    </Panel>
    </div>
  );
}
