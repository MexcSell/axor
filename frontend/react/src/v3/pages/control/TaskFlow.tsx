import { useMemo, useState, type CSSProperties, type DragEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle, CheckCircle2, Circle, ClipboardList, Clock3, Diamond, Eye, Flag, Gauge, ListTodo, Maximize2, Network, Plus, Route, Table2, Timer, TriangleAlert, Users, Rocket, Kanban,
} from "lucide-react";
import { Empty, IconBtn, Modal, Panel, Pill, Progress, StatusPill, Time, progressColors, statusInfo, useToast, Seg } from "../../ui/kit";
import { Avatar, type Role } from "../../ui/Avatar";
import { Dropdown } from "../../ui/widgets";
import { liveMode, getState, moveTask, useStore } from "../../data/store";
import { BLOCKERS, RELEASE_CHECKLIST } from "../../data/sample";
import type { Task } from "../../domain/types";
import { useTheme } from "../../theme/ThemeContext";
import { useQueryParam } from "../../app/router";
import { TaskInspector } from "./TaskInspector";

const PCOL: Record<string, string> = { P0: "var(--ax-bad)", P1: "var(--ax-warn)", P2: "var(--ax-blocked)", P3: "var(--ax-neutral)" };
const COLS: { id: string; label: string; icon: typeof ListTodo; c: string; match: (t: Task) => boolean; to: Task["status"] }[] = [
  { id: "todo", label: "To Do", icon: ListTodo, c: "#3b8cff", match: (t) => ["queued", "ready", "draft"].includes(t.status), to: "queued" },
  { id: "doing", label: "In Progress", icon: ClipboardList, c: "#22d3ee", match: (t) => ["running", "blocked", "paused", "failed", "waiting_agent"].includes(t.status), to: "running" },
  { id: "review", label: "Review", icon: Eye, c: "#a77bff", match: (t) => ["review", "verifying", "waiting_user"].includes(t.status), to: "review" },
  { id: "done", label: "Done", icon: CheckCircle2, c: "#2fd27a", match: (t) => ["done", "passed"].includes(t.status), to: "done" },
];
const roleOfInstance = (id: string): Role => getState().agents.find((a) => a.id === id.split("@")[0])?.role ?? "developer";
const shortAgent = (id: string) => id.split("@")[0].split("-")[0].replace("RCH", "RES");

export function TaskFlowTab({ missionId }: { missionId: string }) {
  const all = useStore((s) => s.tasks);
  const tasks = useMemo(() => all.filter((t) => t.missionId === missionId), [all, missionId]);
  const [view, setView] = useQueryParam("view", "kanban");
  const [group, setGroup] = useState("stage"), [filter, setFilter] = useState("all");
  const [sel, setSel] = useQueryParam("task", "");
  const selected = tasks.find((t) => t.id === sel) ?? null;
  const shown = tasks.filter((t) => filter === "all" || (filter === "critical" ? t.critical : filter === "blocked" ? !!t.blocker : filter === "p0" ? t.meta?.p === "P0" : true));
  return (
    <div style={{ display: "grid", gridTemplateRows: "62fr 38fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateColumns: view === "kanban" ? "58fr 42fr" : "1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title={view === "kanban" ? "Task Flow — Kanban & Timeline" : view === "flow" ? "Task Flow — Dependency graph" : "Task Flow — Table"} icon={Kanban}
          help={{ body: "Every task, not just a percentage. Drag a card between columns; a task can only be Done with acceptance evidence, and can't start before its dependencies are done. Click a card for details.", policy: "Moves are audited." }}
          actions={<>
            <span className="ax-xs ax-muted">View</span><Seg label="Task view" value={view} onChange={setView} items={[{ id: "kanban", label: "Kanban + Timeline", icon: Kanban }, { id: "flow", label: "Dependency graph (DAG)", icon: Network }, { id: "table", label: "Table", icon: Table2 }]} />
            <span className="ax-xs ax-muted">Group</span><Dropdown label="Group" value={group} onChange={setGroup} options={[{ id: "stage", label: "Stage" }, { id: "agent", label: "Agent" }, { id: "priority", label: "Priority" }]} />
            <span className="ax-xs ax-muted">Filter</span><Dropdown label="Filter" value={filter} onChange={setFilter} options={[{ id: "all", label: "All Tasks" }, { id: "critical", label: "Critical path" }, { id: "blocked", label: "Blocked" }, { id: "p0", label: "P0 only" }]} />
          </>} flush={view !== "table"}>
          {view === "kanban" && <Board tasks={shown.filter((t) => !t.meta?.milestone)} group={group} onOpen={(t) => setSel(t.id)} />}
          {view === "flow" && <Dag tasks={shown} onOpen={(t) => setSel(t.id)} selected={sel} />}
          {view === "table" && <TaskTable tasks={shown} onOpen={(t) => setSel(t.id)} />}
        </Panel>
        {view === "kanban" && <DepGantt tasks={shown} onOpen={(t) => setSel(t.id)} selected={sel} />}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "31fr 19fr 17fr 19fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Assignment missionId={missionId} />
        <CriticalPath tasks={tasks} onOpen={(t) => setSel(t.id)} />
        <Blockers missionId={missionId} onOpen={(id) => setSel(id)} />
        <NextRelease releaseAt={tasks.find((t) => t.meta?.milestone)?.end} sample={missionId === "M-001"} />
      </div>
      <TaskInspector task={selected} onClose={() => setSel("")} />
    </div>
  );
}

function Board({ tasks, group, onOpen }: { tasks: Task[]; group: string; onOpen: (t: Task) => void }) {
  const toast = useToast(); const [over, setOver] = useState<string | null>(null);
  const drop = (e: DragEvent, to: Task["status"]) => { e.preventDefault(); setOver(null); const id = e.dataTransfer.getData("text/task"); const err = moveTask(id, to); if (err) toast(err, "warn"); else if (!liveMode()) toast(`${id} → ${statusInfo(to).label}`); };
  const sortKey = (t: Task) => group === "priority" ? (t.meta?.p ?? "P9") : group === "agent" ? t.instanceId : t.start;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8, height: "100%", padding: "4px 10px 10px", minHeight: 0 }}>
      {COLS.map((c, ci) => { const list = tasks.filter(c.match).sort((a, b) => (sortKey(a) > sortKey(b) ? 1 : -1)); const I = c.icon; return (
        <motion.section key={c.id} aria-label={`${c.label} column, ${list.length} tasks`} onDragOver={(e) => { e.preventDefault(); setOver(c.id); }} onDragLeave={() => setOver(null)} onDrop={(e) => drop(e, c.to)}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: ci * .06 }}
          style={{ display: "flex", flexDirection: "column", minHeight: 0, borderRadius: 10, border: `1px solid color-mix(in srgb, ${c.c} ${over === c.id ? 90 : 45}%, transparent)`,
            background: `linear-gradient(180deg, color-mix(in srgb, ${c.c} 16%, transparent), color-mix(in srgb, ${c.c} 4%, transparent))`, boxShadow: over === c.id ? `0 0 16px ${c.c}` : "none" }}>
          <header className="ax-flex" style={{ padding: "6px 8px", borderBottom: `1px solid color-mix(in srgb, ${c.c} 40%, transparent)` }}>
            <I size={15} style={{ color: c.c }} aria-hidden /><b className="ax-small">{c.label} ({list.length})</b><span className="ax-spacer" />
            <IconBtn icon={Plus} label={`Add task to ${c.label}`} size="sm" tone="ghost" onClick={() => toast("Ask the GM in Conversations to add a task; it plans and assigns it", "info")} />
          </header>
          <div style={{ overflow: "auto", padding: 6, display: "flex", flexDirection: "column", gap: 6, minHeight: 0 }}>
            <AnimatePresence>{list.map((t) => <Card key={t.id} t={t} onOpen={onOpen} c={c.c} />)}</AnimatePresence>
            {!list.length && <span className="ax-xs ax-muted" style={{ textAlign: "center", padding: 10 }}>Drop tasks here</span>}
          </div>
        </motion.section>); })}
    </div>
  );
}
function Card({ t, onOpen, c }: { t: Task; onOpen: (t: Task) => void; c: string }) {
  const [c1, c2] = progressColors(t.progress, t.status); const st = statusInfo(t.status); const done = t.status === "done";
  return (
    <motion.div layout layoutId={`card-${t.id}`} draggable onDragStart={(e) => (e as unknown as DragEvent).dataTransfer.setData("text/task", t.id)}
      onClick={() => onOpen(t)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") onOpen(t); }} aria-label={`${t.id} ${t.title}, ${st.label}, ${t.progress}%`}
      initial={{ opacity: 0, scale: .95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: .9 }} whileHover={{ y: -2, boxShadow: `0 6px 18px color-mix(in srgb, ${c} 35%, transparent)` }}
      style={{ padding: "6px 8px", borderRadius: 9, cursor: "grab", background: "var(--ax-panel2)", border: `1px solid ${t.blocker ? "var(--ax-blocked)" : "var(--ax-border)"}` }}>
      <div className="ax-flex" style={{ gap: 5 }}>
        <b className="ax-small" style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.id} {t.title}</b>
        {t.meta && <span className="ax-pill" style={{ "--c": PCOL[t.meta.p], fontSize: 10, padding: "0 5px" } as CSSProperties}>{t.meta.p}</span>}
      </div>
      <div className="ax-xs ax-muted" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.desc}</div>
      <div className="ax-flex ax-xs" style={{ marginTop: 3, gap: 6 }}>
        <Avatar role={roleOfInstance(t.instanceId)} size={16} animate={false} /><span>{shortAgent(t.instanceId)}</span>
        {t.blocker && <span className="ax-flex" style={{ color: "var(--ax-blocked)", gap: 2 }}><AlertTriangle size={11} aria-hidden />Blocked</span>}
        <span className="ax-spacer" />
        {done ? <span className="ax-ok ax-flex" style={{ gap: 2 }}><CheckCircle2 size={12} aria-hidden />100%</span> : t.progress > 0 ? <><b className="ax-num">{t.progress}%</b>{t.meta && <span className="ax-muted">{t.meta.hours}h left</span>}</> : (t.meta ? <span className="ax-muted ax-flex" style={{ gap: 2 }}><Clock3 size={11} aria-hidden />{t.meta.hours}h</span> : <span className="ax-muted">not started</span>)}
      </div>
      {!done && t.progress > 0 && <div style={{ marginTop: 3 }}><Progress value={t.progress} thin c1={c1} c2={c2} label={`${t.id} progress`} /></div>}
    </motion.div>
  );
}

const ZOOM: Record<string, number> = { "1W": 7, "2W": 14, "1M": 30, "3M": 90 };
function DepGantt({ tasks, onOpen, selected }: { tasks: Task[]; onOpen: (t: Task) => void; selected?: string }) {
  const [zoom, setZoom] = useState("2W"), [full, setFull] = useState(false);
  const body = <GanttBody tasks={tasks} onOpen={onOpen} selected={selected} days={ZOOM[zoom]} />;
  return (
    <Panel i={1} title="Timeline / Gantt" icon={Timer} help="Bars by status; gold outline = critical path; ◆ = milestone; the purple line is now. Deps lists what each task waits for."
      actions={<><span className="ax-xs ax-muted">Zoom</span><Seg label="Zoom" value={zoom} onChange={setZoom} items={Object.keys(ZOOM).map((z) => ({ id: z, label: z }))} /><IconBtn icon={Maximize2} label="Full screen" size="sm" onClick={() => setFull(true)} /></>}>
      <div className="ax-col" style={{ height: "100%", gap: 6 }}>
        <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>{body}</div>
        <div className="ax-flex ax-xs" style={{ flexWrap: "wrap", gap: 10 }}>
          <span className="ax-flex" style={{ gap: 4 }}><i style={{ width: 18, height: 3, background: "var(--ax-accent)", display: "inline-block" }} />Critical Path</span>
          <span className="ax-flex" style={{ gap: 4 }}><Diamond size={11} className="ax-gold" aria-hidden />Milestone</span>
          <span className="ax-flex" style={{ gap: 4 }}><i style={{ width: 16, borderTop: "2px dashed var(--ax-blocked)", display: "inline-block" }} />Today</span>
          <span className="ax-spacer" />
          <Pill c="var(--ax-bad)">Issues: {tasks.filter((t) => t.status === "failed" || t.status === "blocked").length}</Pill>
          <Pill c="var(--ax-bad)" icon={TriangleAlert}>Blockers: {tasks.filter((t) => t.blocker || t.status === "blocked").length}</Pill>
          <Pill c="var(--ax-warn)" icon={AlertTriangle}>At Risk: {tasks.filter((t) => t.critical && t.status !== "done" && t.progress < 50 && !t.meta?.milestone).length}</Pill>
        </div>
      </div>
      <Modal open={full} onClose={() => setFull(false)} title="Timeline / Gantt" icon={Timer} width={1400}>{body}</Modal>
    </Panel>
  );
}
function GanttBody({ tasks, onOpen, selected, days }: { tasks: Task[]; onOpen: (t: Task) => void; selected?: string; days: number }) {
  const now = Date.now(), D = 864e5; const from = now - Math.floor(days * .45) * D, to = now + Math.ceil(days * .55) * D, span = to - from;
  const pct = (x: number) => Math.max(0, Math.min(100, ((x - from) / span) * 100));
  const ticks: number[] = []; const d0 = new Date(from); d0.setHours(0, 0, 0, 0); for (let t = +d0 + D; t < to; t += D) ticks.push(t);
  const step = Math.ceil(ticks.length / 14);
  const rowH = 19;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "116px 56px 1fr", fontSize: 11, minWidth: 420 }} role="table" aria-label="Gantt chart">
      <b className="ax-muted" style={{ fontSize: 10.5 }}>Task</b><b className="ax-muted" style={{ fontSize: 10.5 }}>Deps</b>
      <div style={{ position: "relative", height: 18, borderBottom: "1px solid var(--ax-border)" }}>
        {ticks.map((t, i) => i % step === 0 && <span key={t} className="ax-muted ax-num" style={{ position: "absolute", left: `${pct(t)}%`, transform: "translateX(-50%)", fontSize: 10, whiteSpace: "nowrap" }}>{new Date(t).getDate() === 1 || i === 0 ? new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : new Date(t).getDate()}</span>)}
        <span style={{ position: "absolute", left: `${pct(now)}%`, top: 0, transform: "translateX(-50%)", padding: "0 5px", borderRadius: 4, background: "var(--ax-blocked)", color: "#fff", fontSize: 9.5, fontWeight: 700 }}>Today</span>
      </div>
      {tasks.map((t, i) => { const s = statusInfo(t.status); const L = pct(+new Date(t.start)), R = pct(+new Date(t.end)); const I = s.icon; const ms = t.meta?.milestone; return (
        <div key={t.id} role="row" style={{ display: "contents" }}>
          <button type="button" onClick={() => onOpen(t)} className="ax-flex" style={{ height: rowH, border: 0, background: selected === t.id ? "color-mix(in srgb, var(--ax-accent) 14%, transparent)" : "transparent", padding: 0, gap: 4, cursor: "pointer", textAlign: "left", whiteSpace: "nowrap", overflow: "hidden" }} aria-label={`${t.id} ${t.title}`}>
            <I size={11} style={{ color: s.c, flex: "none" }} aria-hidden /><b>{t.id}</b><span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{t.meta?.short ?? t.title}</span></button>
          <span className="ax-muted ax-num" style={{ height: rowH, lineHeight: `${rowH}px`, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontSize: 10 }} title={t.deps.join(", ")}>{t.deps.join(",") || "–"}</span>
          <div style={{ position: "relative", height: rowH }}>
            {i === 0 && <div style={{ position: "absolute", left: `${pct(now)}%`, top: 0, height: rowH * tasks.length, borderLeft: "1.5px dashed var(--ax-blocked)", zIndex: 1 }} aria-hidden />}
            {ms ? <motion.span initial={{ scale: 0, rotate: 45 }} animate={{ scale: 1, rotate: 45 }} onClick={() => onOpen(t)} data-tip={`${t.title} (milestone)`}
              style={{ position: "absolute", left: `calc(${L}% - 6px)`, top: 4, width: 11, height: 11, background: "var(--ax-accent)", boxShadow: "0 0 10px var(--ax-glow)", cursor: "pointer" }} />
              : R > 0 && L < 100 && <motion.div onClick={() => onOpen(t)} data-tip={`${t.id} ${t.title} · ${s.label} · ${t.progress}%`} initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ delay: i * .03, duration: .5 }}
                style={{ position: "absolute", left: `${L}%`, width: `${Math.max(1.2, R - L)}%`, top: 4, height: rowH - 8, borderRadius: 999, originX: 0, cursor: "pointer",
                  background: `linear-gradient(90deg, ${s.c}, color-mix(in srgb, ${s.c} 55%, #fff))`, opacity: t.status === "queued" ? .5 : 1,
                  outline: t.critical ? "1.5px solid var(--ax-accent)" : selected === t.id ? "1.5px solid var(--ax-text)" : "none", boxShadow: `0 0 calc(8px * var(--ax-glow-k)) ${s.c}` }}>
                {t.status === "done" && <CheckCircle2 size={10} style={{ position: "absolute", left: "45%", top: 0, color: "#fff" }} aria-hidden />}
              </motion.div>}
          </div>
        </div>); })}
    </div>
  );
}

type DData = { t: Task; selected: boolean };
function DagNode({ data }: NodeProps<Node<DData>>) {
  const { t } = data; const s = statusInfo(t.status); const I = s.icon;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} whileHover={{ scale: 1.04 }} style={{ width: 170, padding: "6px 8px", borderRadius: 10, background: "var(--ax-panel2)", cursor: "pointer",
      border: `1.5px solid ${data.selected ? "var(--ax-accent)" : t.critical ? "color-mix(in srgb, var(--ax-accent) 60%, transparent)" : s.c}`, boxShadow: `0 0 calc(10px * var(--ax-glow-k)) color-mix(in srgb, ${s.c} 50%, transparent)` }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="ax-flex" style={{ gap: 4 }}><I size={12} style={{ color: s.c }} className={s.spin ? "ax-spin" : ""} aria-hidden /><b style={{ fontSize: 11 }}>{t.id}</b><span className="ax-spacer" />{t.meta && <span className="ax-pill" style={{ "--c": PCOL[t.meta.p], fontSize: 9, padding: "0 4px" } as CSSProperties}>{t.meta.p}</span>}</div>
      <div style={{ fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
      <div className="ax-flex" style={{ fontSize: 10, gap: 4 }}><Avatar role={roleOfInstance(t.instanceId)} size={14} animate={false} />{t.instanceId.split("@")[0]}<span className="ax-spacer" /><span style={{ color: s.c }}>{s.label}</span></div>
      <Progress value={t.progress} thin label={`${t.id} progress`} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </motion.div>
  );
}
const dagTypes = { task: DagNode };
function Dag({ tasks, onOpen, selected }: { tasks: Task[]; onOpen: (t: Task) => void; selected?: string }) {
  const { mode } = useTheme();
  const { nodes, edges } = useMemo(() => {
    const ids = new Set(tasks.map((t) => t.id)); const depth = new Map<string, number>();
    const dep = (t: Task): number => { if (depth.has(t.id)) return depth.get(t.id)!; const d = Math.max(-1, ...t.deps.filter((x) => ids.has(x)).map((x) => dep(tasks.find((y) => y.id === x)!))) + 1; depth.set(t.id, d); return d; };
    tasks.forEach(dep);
    const cols = new Map<number, Task[]>(); tasks.forEach((t) => cols.set(depth.get(t.id)!, [...(cols.get(depth.get(t.id)!) ?? []), t]));
    const ns: Node<DData>[] = []; for (const [d, list] of cols) list.forEach((t, k) => ns.push({ id: t.id, type: "task", position: { x: d * 210, y: k * 86 - (list.length - 1) * 43 }, data: { t, selected: selected === t.id } }));
    const es: Edge[] = tasks.flatMap((t) => t.deps.filter((d) => ids.has(d)).map((d) => { const src = tasks.find((x) => x.id === d)!; const crit = !!(t.critical && src.critical); return {
      id: `${d}-${t.id}`, source: d, target: t.id, animated: src.status === "done" && t.status !== "done", type: "smoothstep",
      style: { stroke: crit ? "var(--ax-accent)" : "var(--ax-faint)", strokeWidth: crit ? 2.2 : 1.3 }, markerEnd: { type: MarkerType.ArrowClosed, color: crit ? "var(--ax-accent)" : "var(--ax-faint)" } } as Edge; }));
    return { nodes: ns, edges: es };
  }, [tasks, selected]);
  return (
    <div className="ax-react-flow" style={{ height: "100%", minHeight: 260 }} role="figure" aria-label="Task dependency graph">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={dagTypes} fitView minZoom={.3} nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onOpen((n.data as DData).t)} colorMode={mode}>
        <Background color="var(--ax-border)" gap={20} size={1} /><Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      <ul className="sr-only">{tasks.map((t) => <li key={t.id}><button type="button" onClick={() => onOpen(t)}>{t.id} {t.title}: {statusInfo(t.status).label}; depends on {t.deps.join(", ") || "nothing"}</button></li>)}</ul>
    </div>
  );
}
function TaskTable({ tasks, onOpen }: { tasks: Task[]; onOpen: (t: Task) => void }) {
  return (
    <table className="ax-table"><thead><tr><th>ID</th><th>Task</th><th>Priority</th><th>Agent</th><th>Status</th><th>Progress</th><th>Deps</th><th>Start</th><th>Due</th><th>Retries</th></tr></thead>
      <tbody>{tasks.map((t) => <tr key={t.id} className="click" onClick={() => onOpen(t)}><td className="ax-num">{t.id}</td><td><b>{t.title}</b><div className="ax-xs ax-muted">{t.desc}</div></td><td>{t.meta && <Pill c={PCOL[t.meta.p]}>{t.meta.p}</Pill>}</td>
        <td><span className="ax-flex"><Avatar role={roleOfInstance(t.instanceId)} size={18} animate={false} />{t.instanceId.split("@")[0]}</span></td><td><StatusPill s={t.status} small /></td><td style={{ width: 90 }}><Progress value={t.progress} thin label="progress" /></td>
        <td className="ax-xs">{t.deps.join(", ") || "–"}</td><td className="ax-xs"><Time iso={t.start} withDate /></td><td className="ax-xs"><Time iso={t.end} withDate /></td><td className="ax-num">{t.retries}</td></tr>)}</tbody></table>
  );
}

function Assignment({ missionId }: { missionId: string }) {
  const depts = useStore((s) => s.departments), agents = useStore((s) => s.agents), inst = useStore((s) => s.instances);
  return (
    <Panel i={2} title="Agent Assignment" icon={Users} help="Departments staffing this company and how many agents each has; the ring shows how many are on this mission.">
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${depts.length}, 1fr)`, gap: 4, height: "100%", alignItems: "center" }}>
        {depts.map((d, i) => { const n = agents.filter((a) => a.dept === d.id).length, here = inst.filter((x) => x.missionId === missionId && agents.find((a) => a.id === x.agentId)?.dept === d.id).length; return (
          <motion.a key={d.id} href={`#/control/${missionId}?tab=agents`} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, textDecoration: "none", color: "inherit" }} initial={{ y: 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: i * .05 }} whileHover={{ y: -4 }}
            data-tip={`${d.name}: ${here} of ${n} agents on this mission`}>
            <Avatar role={d.role} size={46} ring={here > 0} /><span className="ax-xs" style={{ fontWeight: 600, textAlign: "center", lineHeight: 1.1 }}>{d.name.replace(" / Verifier", "/QA")}</span><span className="ax-xs ax-muted">({n})</span></motion.a>); })}
      </div>
    </Panel>
  );
}
function CriticalPath({ tasks, onOpen }: { tasks: Task[]; onOpen: (t: Task) => void }) {
  const crit = tasks.filter((t) => t.critical).sort((a, b) => +new Date(a.start) - +new Date(b.start));
  return (
    <Panel i={3} title="Critical Path" icon={Route} help="The chain of tasks that sets the delivery date. A delay here delays the release.">
      <div className="ax-col" style={{ gap: 4, position: "relative" }}>
        {crit.map((t, i) => (
          <motion.button key={t.id} type="button" onClick={() => onOpen(t)} className="ax-flex ax-small" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }}
            style={{ border: 0, background: "transparent", color: "inherit", cursor: "pointer", padding: "2px 0", textAlign: "left" }} aria-label={`${t.id} ${t.title}`}>
            {t.meta?.milestone ? <Flag size={14} className="ax-gold" aria-hidden /> : <Circle size={12} style={{ color: "var(--ax-accent)", fill: t.status === "done" ? "var(--ax-accent)" : "transparent" }} aria-hidden />}
            <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.id} {t.title}</span>
            {t.status === "done" ? <span className="ax-ok ax-flex" style={{ gap: 2 }}><CheckCircle2 size={12} aria-hidden />Done</span> : t.meta?.milestone ? <Pill c="var(--ax-accent)"><Time iso={t.end} withDate /></Pill> : <><span style={{ width: 40 }}><Progress value={t.progress} thin label="progress" /></span><b className="ax-num ax-xs">{t.progress}%</b></>}
          </motion.button>))}
      </div>
    </Panel>
  );
}
function Blockers({ missionId, onOpen }: { missionId: string; onOpen: (taskId: string) => void }) {
  const tasks = useStore((s) => s.tasks.filter((t) => t.missionId === missionId));
  const list = missionId === "M-001" ? BLOCKERS : [];
  const issues = tasks.filter((t) => t.status === "failed" || t.status === "blocked").length;
  const atRisk = tasks.filter((t) => t.critical && t.status !== "done" && t.progress < 50 && !t.meta?.milestone).length;
  return (
    <Panel i={4} title="Blocker Summary" icon={TriangleAlert} help="What is stopping work and which tasks it blocks. Click to open the blocked task.">
      <div className="ax-col" style={{ gap: 5 }}>
        {list.map((b, i) => (
          <motion.button key={b.id} type="button" className="ax-tile click ax-flex" onClick={() => onOpen(b.blocks[0])} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .06 }} style={{ textAlign: "left", padding: "5px 7px" }}>
            <span className="ax-pill solid" style={{ "--c": "var(--ax-bad)" } as CSSProperties}>{b.id}</span>
            <span style={{ flex: 1, minWidth: 0 }}><b className="ax-small">{b.title}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Blocks: {b.blocks.join(", ")}</span></span><Pill c="var(--ax-bad)">{b.severity}</Pill>
          </motion.button>))}
        {!list.length && <span className="ax-small ax-muted">No blockers on this mission.</span>}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 5, marginTop: 2 }}>
          {[[list.length, "Blockers", "var(--ax-bad)"], [issues, "Issues", "var(--ax-warn)"], [atRisk, "At Risk", "var(--ax-warn)"]].map(([n, l, c]) => (
            <div key={l as string} className="ax-tile" style={{ textAlign: "center", padding: 4, borderColor: c as string }}><b style={{ color: c as string }} className="ax-flex"><AlertTriangle size={13} aria-hidden style={{ margin: "0 auto" }} />{n}</b><div className="ax-xs">{l}</div></div>))}
        </div>
      </div>
    </Panel>
  );
}
function NextRelease({ releaseAt, sample }: { releaseAt?: string; sample: boolean }) {
  if (!sample) return (
    <Panel i={5} title="Next Release" icon={Rocket} help="The release gate checklist of this mission's next version.">
      <Empty icon={Rocket} title="No release planned yet">The GM adds a release gate when the mission's first version is ready for review.</Empty>
    </Panel>
  );
  return (
    <Panel i={5} title="Next Release — v2.4.0" icon={Rocket} help="Release gate checklist. Deploying to production also needs your approval.">
      <div className="ax-col" style={{ gap: 4 }}>{RELEASE_CHECKLIST.map((c, i) => (
        <motion.div key={c.label} className="ax-flex ax-small" initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }}>
          {c.done ? <CheckCircle2 size={15} className="ax-ok" aria-label="done" /> : <Circle size={15} className="ax-faint" aria-label="open" />}<span style={{ flex: 1 }}>{c.label}</span>
          {c.done ? <CheckCircle2 size={13} className="ax-ok" aria-hidden /> : <b className="ax-num">{c.value || (releaseAt ? <Time iso={releaseAt} withDate /> : "—")}</b>}</motion.div>))}
        <div className="ax-flex ax-xs ax-muted"><Gauge size={12} aria-hidden />3 of 6 gates passed</div>
      </div>
    </Panel>
  );
}
