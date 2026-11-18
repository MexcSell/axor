import { motion } from "framer-motion";
import { GitBranch, GitMerge, ShieldCheck, TrendingUp } from "lucide-react";
import { Avatar } from "../../ui/Avatar";
import { Empty, Pill, StatusPill } from "../../ui/kit";
import { useStore } from "../../data/store";
import { missionColor } from "./util";

// Branch & merge of one agent's experience: stable identity (stem) -> isolated mission instances (branches, each pinned to a version)
// -> independent verification -> merge into the baseline ONLY if verified better (AG-005/AG-006).
export function BranchMerge({ agentId, compact, max = 3 }: { agentId: string; compact?: boolean; max?: number }) {
  const agent = useStore((s) => s.agents.find((a) => a.id === agentId));
  const instances = useStore((s) => s.instances), experiences = useStore((s) => s.experiences), missions = useStore((s) => s.missions), candidates = useStore((s) => s.candidates);
  if (!agent) return null;
  const all = instances.filter((i) => i.agentId === agentId);
  const mine = all.slice(0, max); const n = mine.length;
  const cand = candidates.find((c) => c.agentId === agentId && c.status !== "rolled_back" && c.status !== "rejected" && c.status !== "promoted");
  const xp = (mid: string) => experiences.filter((e) => e.agentId === agentId && e.missionId === mid);
  const totalXp = mine.reduce((s, i) => s + xp(i.missionId).filter((e) => e.eligible).length, 0);
  const sz = compact ? 26 : 34, fs = compact ? 10 : 11.5;
  const node: React.CSSProperties = { border: "1px solid var(--ax-border)", background: "var(--ax-panel2)", borderRadius: 10, padding: compact ? "4px 8px" : "6px 10px" };
  if (!n) return <Empty title="Not mobilized">{agentId} is working on the stem only: no mission instance exists, so there is nothing to merge back.</Empty>;
  const line = (d: string, delay = 0) => <motion.path d={d} stroke="var(--ax-accent)" strokeWidth=".7" fill="none" vectorEffect="non-scaling-stroke" className="ax-flow-dash" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay, duration: .5 }} />;
  const cx = (i: number) => ((i + .5) / n) * 100;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0, height: "100%", minHeight: 0, fontSize: fs }}>
      <motion.div style={{ ...node, display: "flex", gap: 8, alignItems: "center", borderColor: "var(--ax-accent)", boxShadow: "0 0 12px var(--ax-glow)" }} initial={{ y: -8, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
        <Avatar role={agent.role} size={sz} name={agent.id} />
        <span><b>{agent.id} (Baseline {agent.baseline})</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{agent.title}</span></span>
      </motion.div>
      <svg width="100%" height={compact ? 16 : 24} viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden style={{ flex: "none" }}>
        {line("M50 0 V6")}{n > 1 && line(`M${cx(0)} 6 H${cx(n - 1)}`, .1)}{mine.map((_, i) => <g key={i}>{line(`M${cx(i)} 6 V20`, .2 + i * .05)}</g>)}
      </svg>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${n}, minmax(0,1fr))`, gap: 6, width: "100%" }}>
        {mine.map((ins, i) => {
          const m = missions.find((x) => x.id === ins.missionId); const lessons = xp(ins.missionId);
          return (
            <motion.div key={ins.id} style={{ ...node, display: "flex", flexDirection: "column", gap: 3, alignItems: "center", textAlign: "center", borderColor: missionColor(ins.missionId), minWidth: 0 }}
              initial={{ y: 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: .25 + i * .06 }} whileHover={{ y: -2 }}
              aria-label={`${ins.id}, ${m?.title ?? ins.missionId}, pinned to ${ins.pinnedVersion}`}>
              <b style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{ins.missionId}</b>
              <span className="ax-xs ax-muted" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{m?.title ?? "Mission"}</span>
              <span className="ax-flex" style={{ gap: 4 }}><GitBranch size={11} aria-hidden /><span className="ax-xs">{ins.pinnedVersion} isolated copy</span></span>
              {!compact && <code className="ax-xs" style={{ maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ins.branch}</code>}
              <StatusPill s={ins.status} small />
              <span className="ax-xs" style={{ color: "var(--ax-ok)" }}>EXP +{lessons.filter((e) => e.eligible).length} <span className="ax-muted">({lessons.filter((e) => !e.eligible).length} excluded)</span></span>
            </motion.div>);
        })}
      </div>
      {all.length > n && <span className="ax-xs ax-muted" style={{ marginTop: 2 }}>+{all.length - n} more instance{all.length - n > 1 ? "s" : ""}</span>}
      <svg width="100%" height={compact ? 16 : 24} viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden style={{ flex: "none" }}>
        {mine.map((_, i) => <g key={i}>{line(`M${cx(i)} 0 V14`, .5 + i * .05)}</g>)}{n > 1 && line(`M${cx(0)} 14 H${cx(n - 1)}`, .6)}{line("M50 14 V20", .7)}
      </svg>
      <motion.div style={{ ...node, display: "flex", gap: 8, alignItems: "center", borderColor: "var(--ax-ok)" }} initial={{ opacity: 0, scale: .9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: .7 }}>
        <GitMerge size={sz - 6} className="ax-ok" aria-hidden />
        <span><b>Merge &amp; Verify <ShieldCheck size={12} className="ax-ok" aria-label="independently verified" style={{ verticalAlign: -2 }} /></b>
          <span className="ax-xs ax-muted" style={{ display: "block" }}>{totalXp} eligible lessons from {n} mission{n > 1 ? "s" : ""}; promoted only if verified better</span></span>
      </motion.div>
      <svg width="30" height="12" aria-hidden style={{ flex: "none" }}><path d="M15 0 V12" stroke="var(--ax-accent)" strokeWidth="1.2" className="ax-flow-dash" /></svg>
      <motion.div style={{ ...node, display: "flex", gap: 8, alignItems: "center" }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .85 }}>
        <Avatar role={agent.role} size={sz} name={agent.id} status={agent.status} />
        <span><b>{agent.id} ({cand ? `Candidate ${cand.to}` : `Baseline ${agent.baseline}`})</b>
          <span className="ax-xs ax-muted" style={{ display: "block" }}>{cand ? `Awaiting verification: ${cand.status}` : "No pending candidate; baseline unchanged"}</span></span>
        {cand && <Pill c={cand.delta >= 0 ? "var(--ax-ok)" : "var(--ax-bad)"} icon={TrendingUp}>{cand.delta >= 0 ? "+" : ""}{cand.delta}%</Pill>}
      </motion.div>
    </div>
  );
}
