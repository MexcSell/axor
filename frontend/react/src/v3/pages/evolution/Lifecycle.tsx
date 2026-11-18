import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Brain, Flag, GitBranch, GitMerge, Pause, Play, RotateCcw, Rocket, ShieldCheck, Layers, Bird, Cuboid, Users, type LucideIcon } from "lucide-react";
import { IconBtn, Panel, Pill, StatusPill } from "../../ui/kit";
import { useStore } from "../../data/store";
import { CandPill } from "./shared";

interface Stg { s: string; id: string; icon: LucideIcon; t: string; d: string; c: string }
const STAGES: Stg[] = [
  { s: "Pinned, verified, in use", id: "base", icon: Layers, t: "Baseline", d: "The current verified version of the agent is pinned. Running missions keep using it.", c: "var(--ax-ok)" },
  { s: "Parallel, isolated, own branch", id: "inst", icon: GitBranch, t: "Mission instances", d: "The same agent runs concurrently in several missions, each in an isolated instance and branch.", c: "var(--ax-info)" },
  { s: "Verified lessons only", id: "cons", icon: Brain, t: "Experience consolidation", d: "Verified, non-private lessons from all instances are merged into a candidate version (prompt, procedure, skill, code).", c: "var(--ax-accent2)" },
  { s: "Verifier ≠ author", id: "eval", icon: ShieldCheck, t: "Independent evaluation", d: "A verifier agent that did not author the change benchmarks baseline against candidate. Security regressions veto.", c: "var(--ax-warn)" },
  { s: "Better and safe → promote", id: "dec", icon: GitMerge, t: "Promote / Reject", d: "Better and safe: promote. Otherwise reject; the baseline stays in use.", c: "var(--ax-accent)" },
  { s: "10% of new work first", id: "can", icon: Rocket, t: "Canary", d: "The new version serves a small share of new work first (10%) while health and benchmarks are watched.", c: "var(--ax-ok)" },
  { s: "Back to the rollback point", id: "rb", icon: RotateCcw, t: "Rollback", d: "If a regression appears, the agent returns to the pinned rollback point immediately.", c: "var(--ax-bad)" },
];
const at: Record<string, number> = { proposed: 0, experiment: 1, evaluating: 3, passed: 4, failed: 4, rejected: 4, promoted: 5, rolled_back: 6 };

export function LifecycleTab({ sel, onSel }: { sel: string; onSel: (id: string) => void }) {
  const cands = useStore((s) => s.candidates), versions = useStore((s) => s.agentVersions), inst = useStore((s) => s.instances);
  const c = cands.find((x) => x.id === sel) ?? cands[0]; const base = at[c.status];
  const [auto, setAuto] = useState(true); const [pos, setPos] = useState(base);
  useEffect(() => setPos(base), [base, c.id]);
  useEffect(() => { if (!auto) return; const t = window.setInterval(() => setPos((p) => (p + 1) % STAGES.length), 1800); return () => clearInterval(t); }, [auto]);
  const s = STAGES[pos]; const lineage = versions.filter((v) => v.agentId === c.agentId); const mine = inst.filter((i) => i.agentId === c.agentId);
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title={`Agent Lifecycle · ${c.agentId} ${c.from} → ${c.to}`} icon={Bird} help="How one agent renews itself: baseline, concurrent isolated mission instances, experience consolidation, independent evaluation, promote or reject, canary, rollback. Highlighted = where this candidate is now; the moving marker walks the whole cycle."
        actions={<><select className="ax-select" style={{ width: 220 }} value={c.id} onChange={(e) => onSel(e.target.value)} aria-label="Candidate">{cands.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.agentId} {x.to}</option>)}</select>
          <IconBtn icon={auto ? Pause : Play} label={auto ? "Pause animation" : "Play animation"} size="sm" onClick={() => setAuto(!auto)} /></>}>
        <div style={{ position: "relative", display: "grid", gridTemplateColumns: `repeat(${STAGES.length}, 1fr)`, gap: 6, padding: "6px 0" }} role="list" aria-label="Lifecycle stages">
          <svg style={{ position: "absolute", left: 0, right: 0, top: 36, width: "100%", height: 6, overflow: "visible" }} aria-hidden><line x1="6%" x2="94%" y1="3" y2="3" stroke="var(--ax-border)" strokeWidth="3" strokeDasharray="6 5" /></svg>
          <motion.span aria-hidden style={{ position: "absolute", top: 31, width: 14, height: 14, borderRadius: 14, background: s.c, boxShadow: `0 0 14px ${s.c}`, zIndex: 2 }} animate={{ left: `calc(${(pos + .5) * (100 / STAGES.length)}% - 7px)` }} transition={{ type: "spring", stiffness: 120, damping: 18 }} />
          {STAGES.map((g, i) => { const here = i === base; const on = i === pos; const past = i < base;
            return (<motion.button key={g.id} type="button" role="listitem" onClick={() => { setAuto(false); setPos(i); }} className="ax-tile" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .07 }} whileHover={{ y: -3 }}
              style={{ textAlign: "center", cursor: "pointer", display: "grid", justifyItems: "center", gap: 3, paddingTop: 14, paddingBottom: 12, borderColor: on ? g.c : here ? "var(--ax-accent)" : undefined, boxShadow: on ? `0 0 12px ${g.c}` : undefined, color: "inherit", opacity: past || here || on ? 1 : .8 }} aria-label={`${g.t}${here ? " (current stage of this candidate)" : ""}`}>
              <motion.span style={{ width: 40, height: 40, borderRadius: 40, display: "grid", placeItems: "center", border: `2px solid ${g.c}`, color: g.c, background: "var(--ax-panel2)", marginBottom: 10 }} animate={on ? { scale: [1, 1.12, 1] } : {}} transition={{ repeat: Infinity, duration: 1.2 }}><g.icon size={19} aria-hidden /></motion.span>
              <b className="ax-small">{g.t}</b><span className="ax-xs ax-muted">{g.s}</span>{here && <Pill c="var(--ax-accent)" solid>now</Pill>}</motion.button>); })}
        </div>
        <motion.div key={s.id} className="ax-small" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} style={{ borderLeft: `3px solid ${s.c}`, paddingLeft: 10, marginTop: 4 }}><b style={{ color: s.c }}>{s.t}:</b> {s.d} <span className="ax-muted">Candidate status: </span><CandPill s={c.status} /></motion.div>
      </Panel>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title="Version lineage" icon={Flag} help="Every version of this agent, its parent, benchmark score and outcome. Rolled-back and rejected versions stay visible as evidence.">
          <div className="ax-col" style={{ gap: 6 }}>
            {lineage.map((v, i) => { const col = v.status === "baseline" ? "var(--ax-ok)" : v.status === "candidate" ? "var(--ax-info)" : v.status === "retired" ? "var(--ax-neutral)" : "var(--ax-bad)";
              return (<motion.div key={v.version} className="ax-tile ax-flex" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .06 }} style={{ borderColor: v.version === c.to ? "var(--ax-accent)" : undefined }}>
                <Cuboid size={16} style={{ color: col }} aria-hidden /><b>{v.version}</b><Pill c={col}>{v.status.replace("_", " ")}</Pill><span className="ax-small ax-muted" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={v.changes.join("; ")}>{v.changes.join("; ")}</span><b className="ax-num">{v.score}</b></motion.div>); })}
          </div>
        </Panel>
        <Panel i={2} title={`Concurrent isolated instances (${mine.length})`} icon={Users} help="Running mission instances of this agent. Each is pinned to a version: a promotion only affects new instances, running ones finish on their pinned version.">
          <div className="ax-col" style={{ gap: 6 }}>
            {mine.map((m, i) => <motion.div key={m.id} className="ax-tile ax-flex ax-small" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .06 }}><b className="ax-mono">{m.id}</b><span className="ax-muted">pinned {m.pinnedVersion}</span><span style={{ flex: 1 }} /><StatusPill s={m.status} small /><b className="ax-num">{m.progress}%</b></motion.div>)}
            {!mine.length && <span className="ax-muted ax-small">No active instances.</span>}
          </div>
        </Panel>
      </div>
    </div>
  );
}
