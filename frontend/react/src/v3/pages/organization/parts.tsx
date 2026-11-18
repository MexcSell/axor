import { useMemo, type ReactNode } from "react";
import { motion } from "framer-motion";

import { Avatar } from "../../ui/Avatar";
import { Pill, Progress } from "../../ui/kit";
import { useStore } from "../../data/store";
import type { Department } from "../../domain/types";
import { SUBTITLE, type Unit } from "./data";

export const useDeptStats = () => {
  const agents = useStore((s) => s.agents), instances = useStore((s) => s.instances), departments = useStore((s) => s.departments), missions = useStore((s) => s.missions);
  return useMemo(() => {
    const dept = new Map(agents.map((a) => [a.id, a.dept]));
    const stat = (d: Department) => {
      const ms = new Set(instances.filter((i) => dept.get(i.agentId) === d.id && i.status !== "done").map((i) => i.missionId));
      return { agents: agents.filter((a) => a.dept === d.id).length, missions: ms, pct: Math.round((d.spent / d.budget) * 100) };
    };
    return { departments, stat, agents, instances, missions, dept };
  }, [agents, instances, departments, missions]);
};
export const money = (n: number) => `$${n.toLocaleString()}`;

/* Organization chart tile: one department */
export function DeptCard({ d, n, m, sel, onClick, i }: { d: Department; n: number; m: number; sel: boolean; onClick: () => void; i: number }) {
  return (
    <motion.button type="button" className={`ax-tile click ${sel ? "sel" : ""}`} onClick={onClick} aria-label={`${d.name}: ${n} agents, ${m} missions, ${d.performance}% performance`} aria-pressed={sel}
      initial={{ y: 12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: .25 + i * .05 }} whileHover={{ y: -3 }} whileTap={{ scale: .97 }}
      style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, padding: "6px 4px", borderColor: sel ? "var(--ax-accent)" : undefined, color: "inherit" }}>
      <Avatar role={d.role} size={44} name={d.name} />
      <b style={{ fontSize: 13, textAlign: "center", lineHeight: 1.1 }}>{d.name}</b>
      <span className="ax-xs ax-muted">{SUBTITLE[d.id]}</span>
      <span className="ax-xs">{n} Agents</span><span className="ax-xs ax-muted">{m} Mission{m === 1 ? "" : "s"}</span>
      <span className="ax-xs ax-ok ax-num"><b>{d.performance}%</b></span>
      <span style={{ width: "86%" }}><Progress value={d.performance} thin c1="var(--ax-accent2)" c2="var(--ax-ok)" label={`${d.name} performance`} /></span>
    </motion.button>
  );
}

/* Small before/after org chart: GM on top, units as a vertical tree (used by Reorganization) */
export function MiniOrg({ units, title, accent }: { units: Unit[]; title: ReactNode; accent?: boolean }) {
  const C = { new: "var(--ax-ok)", changed: "var(--ax-warn)", merged: "var(--ax-info)", removed: "var(--ax-bad)" } as const;
  return (
    <div className="ax-tile" style={{ minHeight: 0, height: "100%", overflow: "auto", borderColor: accent ? "var(--ax-accent)" : undefined }}>
      <b className="ax-small" style={{ display: "block", marginBottom: 6 }}>{title}</b>
      <div className="ax-flex" style={{ gap: 8 }}><Avatar role="gm" size={30} name="GM" /><b className="ax-small">General Manager</b></div>
      <div style={{ marginLeft: 14, borderLeft: "2px solid var(--ax-accent)", paddingLeft: 0 }}>
        {units.map((u, i) => (
          <motion.div key={u.id} layout initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }} className="ax-flex" style={{ gap: 6, padding: "3px 0", minWidth: 0 }}>
            <span style={{ width: 14, height: 2, background: "var(--ax-accent)", flex: "none" }} aria-hidden />
            <span className="ax-flex" style={{ gap: 6, padding: "2px 8px 2px 4px", borderRadius: 8, border: `1px solid ${u.tag ? C[u.tag] : "var(--ax-border)"}`, minWidth: 0, flex: 1, background: u.tag ? `color-mix(in srgb, ${C[u.tag]} 10%, transparent)` : undefined }}>
              <Avatar role={u.role} size={22} name={u.name} /><b className="ax-small" style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{u.name}</b>
              <span className="ax-xs ax-muted">{u.agents} agents</span>{u.tag && <Pill c={C[u.tag]}>{u.tag}</Pill>}</span>
          </motion.div>))}
      </div>
    </div>
  );
}
export const unitsOf = (deps: Department[], count: (id: string) => number): Unit[] => deps.map((d) => ({ id: d.id, name: d.name.replace(" / Verifier", "/QA"), role: d.role, agents: count(d.id) }));
