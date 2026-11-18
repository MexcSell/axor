import { useState } from "react";
import { motion } from "framer-motion";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend as RLegend } from "recharts";
import {
  AlertTriangle, ArrowRight, Ban, Building2, CheckCircle2, ClipboardList, Coins, Crown, GitBranch, GitMerge, HeartPulse, Layers, Lightbulb, Lock, Maximize2, Network, Plus, RefreshCw, ScrollText,
  ShieldCheck, Target, ThumbsDown, ThumbsUp, TrendingUp, Users, Workflow, ChevronRight, Activity, LayoutGrid, Table2, Grid3x3, BarChart3, Shuffle,
} from "lucide-react";
import { Avatar, ROLES } from "../ui/Avatar";
import { Btn, Count, Donut, IconBtn, Kpi, Legend, Modal, Panel, Pill, PRIORITY, Progress, StatusPill, TabBody, Tabs, useToast } from "../ui/kit";
import { AgentTag, Dropdown } from "../ui/widgets";
import { go, useQueryParam } from "../app/router";
import { useStore } from "../data/store";
import { PERF_SERIES } from "../data/sample";
import { chartTip } from "./Overview";
import { CHARTER, EFFICIENCY, PROPOSALS, PROTECTED, SUBTITLE } from "./organization/data";
import { DeptCard, MiniOrg, money, unitsOf, useDeptStats } from "./organization/parts";

const TABS = [
  { id: "chart", label: "Org Chart", icon: Network }, { id: "departments", label: "Departments", icon: Layers }, { id: "agents", label: "Agents", icon: Users },
  { id: "assignments", label: "Assignments", icon: Grid3x3 }, { id: "performance", label: "Performance", icon: BarChart3 }, { id: "reorg", label: "Reorganization", icon: Shuffle },
];
const axis = { tick: { fontSize: 10, fill: "var(--ax-muted)" } };

export default function Organization() {
  const [tab, setTab] = useQueryParam("tab", "chart"); const [dept, setDept] = useQueryParam("dept", "development");
  const st = useDeptStats(); const approvals = useStore((s) => s.approvals);
  const { departments } = st; const d = departments.find((x) => x.id === dept) ?? departments[0];
  const totalSpent = departments.reduce((s, x) => s + x.spent, 0), totalBudget = departments.reduce((s, x) => s + x.budget, 0);
  const activeMissions = new Set(st.instances.filter((i) => i.status !== "done").map((i) => i.missionId)).size;
  const health = +(departments.reduce((s, x) => s + x.performance, 0) / departments.length).toFixed(1);
  const pendingAppr = approvals.filter((a) => a.status === "pending").length;
  const open = (id: string) => setDept(id);
  return (
    <div className="ax-page" style={{ gridTemplateColumns: "minmax(0,1fr) 330px", gridTemplateRows: "auto minmax(0,1fr)" }}>
      <Panel i={0} title="Organization" icon={Building2} help={{ body: "How the AI company is organized: the GM, seven departments and their agents, who works on which mission, how each department performs, and the GM's reorganization proposals.", source: "Departments, agents and instances (sample data)." }}
        actions={<Tabs label="Organization views" tabs={TABS} value={tab} onChange={setTab} />} style={{ gridColumn: 1 }}>      <div className="ax-kpis" style={{ gridColumn: 1, gridTemplateColumns: "repeat(6, 1fr)", height: 70 }}>
        <Kpi i={0} icon={Layers} c="#a77bff" value={departments.length} label="Departments" onClick={() => setTab("departments")} />
        <Kpi i={1} icon={Users} c="#3b8cff" value={st.agents.length} label="Total Agents" delta="+4 (vs. last week)" onClick={() => setTab("agents")} />
        <Kpi i={2} icon={HeartPulse} c="#2fd27a" value={health} decimals={1} suffix="%" label="Org Health" delta="+2.1 pp" onClick={() => setTab("performance")} />
        <Kpi i={3} icon={Coins} c="#c084fc" value={totalSpent} prefix="$" label="Month Spend" extra={<><small style={{ color: "var(--ax-muted)" }}>{Math.round((totalSpent / totalBudget) * 100)}% of Budget</small><Progress value={(totalSpent / totalBudget) * 100} thin label="Budget used" /></>} />
        <Kpi i={4} icon={Target} c="#f472b6" value={activeMissions} label="Active Missions" onClick={() => setTab("assignments")} />
        <Kpi i={5} icon={ClipboardList} c="#f2b53a" value={pendingAppr} label="Approvals" onClick={() => go("overview", null, { tab: "decisions" })} />
      </div>
      </Panel>
      <Panel i={1} title="Department Detail" icon={Building2} area="1 / 2 / 3 / 3" help={{ body: "Charter, running missions, staffing and budget of one department. Pick a department here or click it in a chart or table.", source: "Departments, instances (sample data)." }}
        actions={<Dropdown label="Department" value={d.id} onChange={open} options={departments.map((x) => ({ id: x.id, label: x.name }))} />}>
        <DeptDetail id={d.id} />
      </Panel>
      <div style={{ gridColumn: 1, minHeight: 0 }}>
        <TabBody k={tab}>
          {tab === "chart" && <ChartTab dept={d.id} open={open} setTab={setTab} />}
          {tab === "departments" && <DepartmentsTab dept={d.id} open={open} />}
          {tab === "agents" && <AgentsTab dept={d.id} />}
          {tab === "assignments" && <AssignmentsTab open={open} />}
          {tab === "performance" && <PerformanceTab open={open} />}
          {tab === "reorg" && <ReorgTab />}
        </TabBody>
      </div>
      <style>{".ax-compact td{padding:3px 8px}.ax-compact th{padding:4px 8px}"}</style>
    </div>
  );
}

/* ---------------- right column: department detail ---------------- */
function DeptDetail({ id }: { id: string }) {
  const st = useDeptStats(); const d = st.departments.find((x) => x.id === id)!; const s = st.stat(d);
  const mine = st.agents.filter((a) => a.dept === id); const head = st.agents.find((a) => a.id === d.head);
  const titles = new Map<string, number>(); mine.forEach((a) => titles.set(a.title, (titles.get(a.title) ?? 0) + 1));
  const forecast = Math.round(d.spent * 1.16);
  const sec = (t: string, ic: React.ReactNode, body: React.ReactNode, right?: React.ReactNode) => <div className="ax-tile" style={{ marginBottom: 6 }}><div className="ax-flex" style={{ gap: 6, marginBottom: 4, fontWeight: 650 }}>{ic}{t}<span className="ax-spacer" />{right}</div>{body}</div>;
  return (
    <div>
      <div className="ax-tile ax-flex" style={{ gap: 10, marginBottom: 6 }}><Avatar role={d.role} size={50} name={d.name} /><span style={{ minWidth: 0 }}><b style={{ fontSize: 15 }}>{d.name} Department</b><span className="ax-small ax-muted" style={{ display: "block" }}>{SUBTITLE[id]}</span>{head && <AgentTag id={head.id} size={18} sub="Head" />}</span><span className="ax-spacer" /><StatusPill s="running" label="Active" small /></div>
      {sec("Charter", <ScrollText size={14} className="ax-gold" aria-hidden />, <p className="ax-small" style={{ margin: 0 }}>{CHARTER[id]}</p>)}
      {sec(`Active Missions (${s.missions.size})`, <Target size={14} className="ax-gold" aria-hidden />, s.missions.size ? [...s.missions].map((mid) => { const m = st.missions.find((x) => x.id === mid); return m ? <div key={mid} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><CheckCircle2 size={13} className="ax-ok" aria-hidden /><span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.title}</span><span style={{ width: 54 }}><Progress value={m.progress} thin label={m.title} /></span><span className="ax-num ax-xs" style={{ width: 28, textAlign: "right" }}>{m.progress}%</span></div> : null; }) : <span className="ax-muted ax-small">No mission instance running.</span>)}
      {sec("Staffing", <Users size={14} className="ax-gold" aria-hidden />, [...titles].map(([t, c]) => <div key={t} className="ax-flex ax-small" style={{ padding: "1px 0" }}><span style={{ flex: 1 }}>{t}</span><b>{c}</b></div>), <span className="ax-small"><b>{mine.length}</b> agents</span>)}
      {sec("Budget", <Coins size={14} className="ax-gold" aria-hidden />, <>
        <div className="ax-flex ax-small"><span style={{ flex: 1 }}>This month spend</span><b>{money(d.spent)}</b></div><Progress value={s.pct} thin label="Budget used" />
        <div className="ax-flex ax-small" style={{ marginTop: 3 }}><span style={{ flex: 1 }}>Remaining</span><b>{money(d.budget - d.spent)}</b></div>
        <div className="ax-flex ax-small"><span style={{ flex: 1 }}>Forecast (end of month)</span><b className={forecast > d.budget ? "ax-bad" : ""}>{money(forecast)} ({Math.round((forecast / d.budget) * 100)}%)</b></div></>, <b className="ax-small">{money(d.budget)}</b>)}
      {sec("Performance", <Activity size={14} className="ax-gold" aria-hidden />, <div className="ax-flex ax-small"><span style={{ flex: 1 }}>Success rate</span><b className="ax-ok">{d.performance}%</b><span className="ax-muted">· backlog {d.backlog}</span></div>)}
    </div>
  );
}

/* ---------------- Org Chart tab (30-5) ---------------- */
function ChartTab({ dept, open, setTab }: { dept: string; open: (id: string) => void; setTab: (t: string) => void }) {
  const st = useDeptStats(); const { departments } = st; const n = departments.length;
  const approvals = useStore((s) => s.approvals); const threads = useStore((s) => s.threads);
  const [zoom, setZoom] = useState(100); const [full, setFull] = useState(false);
  const spent = departments.reduce((s, x) => s + x.spent, 0), budget = departments.reduce((s, x) => s + x.budget, 0);
  const hub = departments.map((d, i) => { const a = (i / n) * Math.PI * 2 - Math.PI / 2; return { d, x: 50 + 38 * Math.cos(a), y: 50 + 38 * Math.sin(a) }; });
  void approvals;
  return (
    <div style={{ display: "grid", gridTemplateRows: "minmax(0,1.6fr) minmax(0,1fr) minmax(0,.9fr)", gap: "var(--ax-gap)", height: "100%" }}>
      <Panel i={2} title="Organization Chart" icon={Network} help="GM at the top, seven departments below. Click a department to see its detail on the right. Solid gold lines are reporting lines; dashed cyan lines are collaboration between departments."
        actions={<><Legend items={[{ label: "Reporting", c: "var(--ax-accent)" }, { label: "Collaboration", c: "var(--ax-accent2)" }]} /><IconBtn icon={RefreshCw} size="sm" label="Reset zoom" onClick={() => setZoom(100)} /><IconBtn icon={Plus} size="sm" label="Zoom in" onClick={() => setZoom((z) => Math.min(140, z + 10))} /><span className="ax-xs ax-num">{zoom}%</span><IconBtn icon={Maximize2} size="sm" label={full ? "Normal size" : "Expand chart"} onClick={() => setFull((f) => !f)} /></>}>
        <div style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center", transition: "transform .25s" }}>
          <div className="ax-flex" style={{ justifyContent: "center", gap: 16, alignItems: "flex-start" }}>
            <motion.div className="ax-tile" style={{ display: "flex", gap: 12, alignItems: "center", borderColor: "var(--ax-accent)", boxShadow: "0 0 14px var(--ax-glow)", padding: "6px 22px" }} initial={{ y: -10, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
              <Avatar role="gm" size={52} name="GM" status="busy" /><span><b style={{ fontSize: 18 }}>General Manager (GM)</b><span className="ax-muted" style={{ display: "block" }}>Strategy · Planning · Control</span></span></motion.div>
            <div className="ax-tile" style={{ minWidth: 200 }}><b className="ax-small ax-flex" style={{ gap: 6 }}><Target size={14} className="ax-gold" aria-hidden />Company KPIs</b>
              {[["Mission Success", "96.4%"], ["Budget Usage", `${Math.round((spent / budget) * 100)}%`], ["Org Efficiency", "+18.6%"]].map(([k, v]) => <div key={k} className="ax-flex ax-xs" style={{ gap: 6 }}><CheckCircle2 size={11} className="ax-ok" aria-hidden /><span style={{ flex: 1 }}>{k}</span><b>{v}</b></div>)}</div>
          </div>
          <svg width="100%" height="26" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden><path d={`M50 0 V10 M${50 / n} 10 H${100 - 50 / n}`} stroke="var(--ax-accent)" strokeWidth="1" fill="none" vectorEffect="non-scaling-stroke" />
            {departments.map((_, i) => <motion.path key={i} d={`M${(100 / n) * i + 50 / n} 10 V26`} stroke="var(--ax-accent)" strokeWidth="1" vectorEffect="non-scaling-stroke" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .2 + i * .05 }} />)}</svg>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${n}, minmax(0,1fr))`, gap: 8 }}>
            {departments.map((d, i) => { const s = st.stat(d); return <DeptCard key={d.id} d={d} n={s.agents} m={s.missions.size} sel={dept === d.id} onClick={() => open(d.id)} i={i} />; })}</div>
        </div>
        <Modal open={full} onClose={() => setFull(false)} title="Organization Chart" icon={Network} width={900}><p className="ax-small">The full-size view lists every department with its head and head count.</p>
          {departments.map((d) => <div key={d.id} className="ax-flex ax-small" style={{ gap: 8, padding: "3px 0" }}><Avatar role={d.role} size={24} name={d.name} /><b style={{ width: 120 }}>{d.name}</b><AgentTag id={d.head} size={18} /><span className="ax-spacer" /><span>{st.stat(d).agents} agents</span></div>)}</Modal>
      </Panel>
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr .9fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={3} title="Department KPIs" icon={Table2} sub="This Month" help="Verified success and budget use per department, with efficiency change versus last month (sample).">
          <table className="ax-table ax-compact"><thead><tr><th>Department</th><th>Agents</th><th>Missions</th><th>Success</th><th>Budget</th><th>Effic.</th></tr></thead>
            <tbody>{departments.map((d) => { const s = st.stat(d); return <tr key={d.id} className="click" onClick={() => open(d.id)}><td><span className="ax-flex" style={{ gap: 6 }}><Avatar role={d.role} size={18} name={d.name} />{d.name.replace(" / Verifier", "/QA")}</span></td><td className="ax-num">{s.agents}</td><td className="ax-num">{s.missions.size}</td><td className="ax-num">{d.performance}%</td><td className="ax-num">{money(d.spent)} ({s.pct}%)</td><td className="ax-ok ax-num">+{EFFICIENCY[d.id]}%</td></tr>; })}</tbody></table>
        </Panel>
        <Panel i={4} title="Organization Insights" icon={Lightbulb} help="Four headline numbers about the whole organization.">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {[[Users, "#3b8cff", st.agents.length, "Total Agents", ""], [Target, "#a77bff", new Set(st.instances.filter((i) => i.status !== "done").map((i) => i.missionId)).size, "Active Missions", ""], [Coins, "#c084fc", spent, "Monthly Spend", "$"], [TrendingUp, "#2fd27a", 18.6, "Org Efficiency", "+"]].map(([I, c, v, l, p], k) => { const Ic = I as typeof Users; return (
              <motion.div key={l as string} className="ax-tile ax-flex" style={{ gap: 8 }} initial={{ opacity: 0, scale: .9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: .1 * k }}><Ic size={22} style={{ color: c as string }} aria-hidden /><span><b style={{ fontSize: 17 }}><Count value={v as number} prefix={p as string} decimals={k === 3 ? 1 : 0} suffix={k === 3 ? "%" : ""} /></b><span className="ax-xs ax-muted" style={{ display: "block" }}>{l as string}</span></span></motion.div>); })}</div>
        </Panel>
        <Panel i={5} title="Relations & Flows" icon={Workflow} help="Who connects to whom: reporting lines (to the GM), collaboration (peer conversations), resource flow (budget) and mission relations (instances).">
          <div className="ax-flex" style={{ gap: 8, height: "100%" }}>
            <svg viewBox="0 0 100 100" style={{ flex: 1, minWidth: 0, height: "100%" }} role="img" aria-label="Hub diagram of departments around the GM">
              {hub.map(({ d, x, y }) => <line key={d.id} x1="50" y1="50" x2={x} y2={y} stroke="var(--ax-accent)" strokeWidth=".8" strokeDasharray={d.id === "operations" ? "2 2" : undefined} />)}
              <circle cx="50" cy="50" r="9" fill="var(--ax-panel2)" stroke="var(--ax-accent)" /><text x="50" y="53" textAnchor="middle" fontSize="8" fill="var(--ax-text)" fontWeight="700">GM</text>
              {hub.map(({ d, x, y }) => <g key={d.id}><circle cx={x} cy={y} r="7" fill="var(--ax-panel2)" stroke={ROLES[d.role].c} /><text x={x} y={y + 2.5} textAnchor="middle" fontSize="6.5" fill={ROLES[d.role].c} fontWeight="700">{d.name[0]}</text></g>)}
            </svg>
            <div className="ax-xs" style={{ display: "grid", gap: 3, alignContent: "center" }}>
              {[["Reporting", st.agents.filter((a) => a.reportsTo === "GM").length, "var(--ax-accent)"], ["Collaboration", threads.filter((t) => t.kind === "peer").length, "var(--ax-accent2)"], ["Resource Flow", n, "var(--ax-ok)"], ["Mission Relation", st.instances.length, "var(--ax-blocked)"]].map(([k, v, c]) => <span key={k as string} className="ax-flex" style={{ gap: 4 }}><i style={{ width: 14, height: 2, background: c as string, display: "inline-block" }} aria-hidden />{k as string} <b>({v as number})</b></span>)}</div>
          </div>
        </Panel>
      </div>
      <Panel i={6} title="Organization Evolution" icon={GitBranch} help="How the structure itself evolves: proposals from the GM, the branch-and-merge control for org changes, and company-level suggestions. Nothing changes without approval.">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.1fr 1fr", gap: "var(--ax-gap)", height: "100%" }}>
          <div className="ax-tile"><b className="ax-small ax-flex" style={{ gap: 6 }}><Shuffle size={14} className="ax-gold" aria-hidden />Restructuring Proposals ({PROPOSALS.length})</b>
            {PROPOSALS.map((p) => <div key={p.id} className="ax-row click" role="button" tabIndex={0} onClick={() => setTab("reorg")} onKeyDown={(e) => e.key === "Enter" && setTab("reorg")}><span className="grow ax-small">{p.title}</span><Pill c={PRIORITY[p.priority]}>{p.priority}</Pill><ChevronRight size={14} aria-hidden /></div>)}</div>
          <div className="ax-tile"><b className="ax-small ax-flex" style={{ gap: 6 }}><GitBranch size={14} className="ax-gold" aria-hidden />Branch-and-Merge (Org Change Control)</b>
            <div className="ax-flex ax-xs" style={{ gap: 6, marginTop: 8, flexWrap: "wrap" }}><Pill c="var(--ax-neutral)" icon={GitBranch}>main · v1.5.0 (current org)</Pill><ArrowRight size={12} aria-hidden /><span style={{ display: "grid", gap: 3 }}><Pill c="var(--ax-accent2)">feature/org-restructure</Pill><Pill c="var(--ax-accent2)">feature/ai-safety-dept</Pill></span><ArrowRight size={12} aria-hidden /><Pill c="var(--ax-ok)" icon={GitMerge}>merge → v1.6.0 (proposed)</Pill></div>
            <div className="ax-xs ax-muted" style={{ marginTop: 6 }}>Structure diff (7 changes) · budget rebalance +2.4% · impact: low</div></div>
          <div className="ax-tile"><b className="ax-small ax-flex" style={{ gap: 6 }}><Lightbulb size={14} className="ax-gold" aria-hidden />Company Evolution Suggestions</b>
            {[["Evolve to a Product-Line Organization", 22.7], ["Add a Customer Success department", 16.4], ["Establish an AI Governance & Compliance unit", 14.9]].map(([t, g]) => <div key={t as string} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><span style={{ flex: 1 }}>{t as string}</span><b className="ax-ok">+{g as number}%</b></div>)}</div>
        </div>
      </Panel>
    </div>
  );
}

/* ---------------- Departments tab ---------------- */
function DepartmentsTab({ dept, open }: { dept: string; open: (id: string) => void }) {
  const st = useDeptStats(); const { departments } = st;
  const bars = departments.map((d) => ({ name: d.name.split(" ")[0], Budget: d.budget, Spent: d.spent }));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)", gridTemplateRows: "minmax(0,1fr) minmax(0,1fr)", gap: "var(--ax-gap)", height: "100%" }}>
      <Panel i={2} title="Departments" icon={Layers} area="1 / 1 / 3 / 2" help="Each department with its head, size, active missions, budget use and verified performance. Click a row to load it in the detail panel.">
        <table className="ax-table ax-compact"><thead><tr><th>Department</th><th>Head</th><th>Agents</th><th>Missions</th><th>Backlog</th><th>Budget</th><th>Spent</th><th>Used</th><th>Success</th></tr></thead>
          <tbody>{departments.map((d, k) => { const s = st.stat(d); return (
            <motion.tr key={d.id} className={`click ${dept === d.id ? "sel" : ""}`} onClick={() => open(d.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && open(d.id)} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
              <td><span className="ax-flex" style={{ gap: 8 }}><Avatar role={d.role} size={30} name={d.name} /><span><b>{d.name}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{SUBTITLE[d.id]}</span></span></span></td>
              <td><AgentTag id={d.head} size={20} /></td><td className="ax-num">{s.agents}</td><td className="ax-num">{s.missions.size}</td><td className="ax-num">{d.backlog}</td><td className="ax-num">{money(d.budget)}</td><td className="ax-num">{money(d.spent)}</td>
              <td style={{ minWidth: 90 }}><span className="ax-xs ax-num">{s.pct}%</span><Progress value={s.pct} thin c1={s.pct > 85 ? "var(--ax-warn)" : undefined} label="Budget used" /></td><td className="ax-num ax-ok"><b>{d.performance}%</b></td></motion.tr>); })}</tbody></table>
      </Panel>
      <Panel i={3} title="Budget vs spend ($)" icon={Coins} help="Monthly budget and what each department has spent so far.">
        <ResponsiveContainer width="100%" height="100%"><BarChart data={bars} margin={{ left: -14, right: 4, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="name" {...axis} interval={0} /><YAxis {...axis} /><Tooltip {...chartTip} /><RLegend wrapperStyle={{ fontSize: 11 }} /><Bar dataKey="Budget" fill="var(--ax-neutral)" radius={[3, 3, 0, 0]} /><Bar dataKey="Spent" fill="var(--ax-accent2)" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>
      </Panel>
      <Panel i={4} title="Head count by department" icon={Users} help="Share of the company's agents in each department.">
        <div className="ax-flex" style={{ gap: 14, height: "100%", justifyContent: "center" }}>
          <Donut label="Agents by department" size={130} center={<b>{st.agents.length}</b>} parts={departments.map((d) => ({ label: d.name, value: st.stat(d).agents, c: ROLES[d.role].c }))} />
          <Legend items={departments.map((d) => ({ label: d.name.replace(" / Verifier", "/QA"), value: st.stat(d).agents, c: ROLES[d.role].c }))} />
        </div>
      </Panel>
    </div>
  );
}

/* ---------------- Agents tab: roster per department ---------------- */
function AgentsTab({ dept }: { dept: string }) {
  const st = useDeptStats(); const cols = [{ id: "executive", name: "Executive", role: "gm" as const }, ...st.departments];
  return (
    <Panel i={2} title={`Agent roster (${st.agents.length})`} icon={Users} help="All agents grouped by department, with who they report to. Click an agent to open its profile. The ring on the avatar shows its live status.">
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols.length}, minmax(0,1fr))`, gap: 8, height: "100%" }}>
        {cols.map((c, ci) => (
          <div key={c.id} className="ax-tile" style={{ minHeight: 0, overflow: "auto", borderColor: dept === c.id ? "var(--ax-accent)" : undefined }}>
            <div className="ax-flex" style={{ gap: 6, marginBottom: 4 }}><Avatar role={c.role} size={22} name={c.name} /><b className="ax-small" style={{ flex: 1 }}>{c.name.replace(" / Verifier", "/QA")}</b></div>
            {st.agents.filter((a) => a.dept === c.id).map((a, k) => (
              <motion.button key={a.id} type="button" onClick={() => go("agents", a.id, { tab: "profile" })} className="ax-row click" style={{ width: "100%", background: "transparent", color: "inherit", font: "inherit", textAlign: "left" }} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: ci * .03 + k * .02 }} whileHover={{ x: 2 }} aria-label={`${a.id}, ${a.title}, ${a.status}`}>
                <Avatar role={a.role} size={24} name={a.id} status={a.status} /><span className="grow"><b className="t ax-small">{a.id}</b><span className="s">{a.status}{a.reportsTo ? ` · → ${a.reportsTo}` : ""}</span></span></motion.button>))}
          </div>))}
      </div>
    </Panel>
  );
}

/* ---------------- Assignments tab: mission x department matrix ---------------- */
function AssignmentsTab({ open }: { open: (id: string) => void }) {
  const st = useDeptStats(); const ms = st.missions.filter((m) => !m.archived);
  const cell = (mid: string, did: string) => st.instances.filter((i) => i.missionId === mid && st.dept.get(i.agentId) === did && i.status !== "done").length;
  const load = st.departments.map((d) => ({ d, n: st.instances.filter((i) => st.dept.get(i.agentId) === d.id && i.status !== "done").length }));
  const maxLoad = Math.max(1, ...load.map((l) => l.n));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.8fr) minmax(0,1fr)", gap: "var(--ax-gap)", height: "100%" }}>
      <Panel i={2} title="Mission × department assignments" icon={Grid3x3} help="Each cell counts isolated agent instances of that department working on the mission. Empty cells mean the department is not involved. The GM staffs missions after planning.">
        <table className="ax-table ax-compact"><thead><tr><th>Mission</th><th>Status</th>{st.departments.map((d) => <th key={d.id} style={{ textAlign: "center" }}><button type="button" className="ax-xs" style={{ all: "unset", cursor: "pointer" }} onClick={() => open(d.id)}>{d.name.replace(" / Verifier", "/QA")}</button></th>)}<th>Total</th></tr></thead>
          <tbody>{ms.map((m, k) => { const row = st.departments.map((d) => cell(m.id, d.id)); const tot = row.reduce((a, b) => a + b, 0); return (
            <motion.tr key={m.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
              <td style={{ whiteSpace: "nowrap", maxWidth: 230, overflow: "hidden", textOverflow: "ellipsis" }}><b>{m.id}</b> <span className="ax-xs ax-muted">{m.title}</span></td><td><StatusPill s={m.status} small /></td>
              {row.map((n, i) => <td key={i} style={{ textAlign: "center" }}>{n ? <span className="ax-num" style={{ display: "inline-block", minWidth: 24, padding: "1px 6px", borderRadius: 6, fontWeight: 700, background: `color-mix(in srgb, ${ROLES[st.departments[i].role].c} ${20 + Math.min(n, 4) * 14}%, transparent)` }}>{n}</span> : <span className="ax-faint" aria-label="none">·</span>}</td>)}
              <td className="ax-num"><b>{tot}</b>{tot === 0 && <span className="ax-xs ax-warn"> unstaffed</span>}</td></motion.tr>); })}</tbody></table>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={3} title="Load by department" icon={Activity} help="Running instances per department. A department far above the others is a candidate for splitting (see Reorganization).">
          {load.map(({ d, n }) => <div key={d.id} className="ax-flex ax-small" style={{ gap: 8, padding: "3px 0" }}><Avatar role={d.role} size={20} name={d.name} /><span style={{ width: 90 }}>{d.name.replace(" / Verifier", "/QA")}</span><span style={{ flex: 1 }}><Progress value={(n / maxLoad) * 100} thin label={`${d.name} instances`} /></span><b className="ax-num" style={{ width: 24, textAlign: "right" }}>{n}</b></div>)}
        </Panel>
        <Panel i={4} title="Needs attention" icon={AlertTriangle} help="Missions without any staffed department, and departments with a backlog above 8 items.">
          {ms.filter((m) => st.departments.every((d) => !cell(m.id, d.id))).map((m) => <div key={m.id} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><AlertTriangle size={13} className="ax-warn" aria-hidden />{m.id} has no agents assigned yet</div>)}
          {st.departments.filter((d) => d.backlog > 8).map((d) => <div key={d.id} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><AlertTriangle size={13} className="ax-warn" aria-hidden />{d.name}: backlog {d.backlog}</div>)}
          <div className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><CheckCircle2 size={13} className="ax-ok" aria-hidden />Every instance is pinned to one version and isolated to one mission</div>
        </Panel>
      </div>
    </div>
  );
}

/* ---------------- Performance tab ---------------- */
function PerformanceTab({ open }: { open: (id: string) => void }) {
  const st = useDeptStats(); const { departments } = st;
  const data = departments.map((d) => ({ name: d.name.split(" ")[0], id: d.id, Success: d.performance, Budget: Math.round((d.spent / d.budget) * 100), Efficiency: EFFICIENCY[d.id] * 3 + 40 }));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gridTemplateRows: "minmax(0,1fr) minmax(0,1fr)", gap: "var(--ax-gap)", height: "100%" }}>
      <Panel i={2} title="Success rate by department (%)" icon={BarChart3} help="Verified mission success per department. Click a bar to load the department.">
        <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ left: -14, right: 4, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="name" {...axis} interval={0} /><YAxis domain={[85, 100]} {...axis} /><Tooltip {...chartTip} />
          <Bar dataKey="Success" radius={[3, 3, 0, 0]} onClick={(e) => open((e as unknown as { id: string }).id)}>{data.map((d) => <Cell key={d.id} fill={ROLES[departments.find((x) => x.id === d.id)!.role].c} />)}</Bar></BarChart></ResponsiveContainer>
      </Panel>
      <Panel i={3} title="Department profile" icon={Target} help="Radar of success, budget use and relative efficiency for every department.">
        <ResponsiveContainer width="100%" height="100%"><RadarChart data={data} outerRadius="68%"><PolarGrid stroke="var(--ax-border)" /><PolarAngleAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--ax-muted)" }} /><Radar name="Success" dataKey="Success" stroke="var(--ax-ok)" fill="var(--ax-ok)" fillOpacity={.2} /><Radar name="Budget used" dataKey="Budget" stroke="var(--ax-accent)" fill="var(--ax-accent)" fillOpacity={.15} /><RLegend wrapperStyle={{ fontSize: 11 }} /><Tooltip {...chartTip} /></RadarChart></ResponsiveContainer>
      </Panel>
      <Panel i={4} title="Company success, 30 days (%)" icon={TrendingUp} help="Verified success and autonomy of the whole company over the last 30 days (sample series).">
        <ResponsiveContainer width="100%" height="100%"><LineChart data={PERF_SERIES} margin={{ left: -14, right: 6, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="day" {...axis} interval={6} /><YAxis {...axis} domain={["auto", "auto"]} /><Tooltip {...chartTip} /><RLegend wrapperStyle={{ fontSize: 11 }} /><Line dataKey="success" stroke="var(--ax-ok)" dot={false} strokeWidth={2} /><Line dataKey="autonomy" stroke="var(--ax-accent2)" dot={false} strokeWidth={2} /></LineChart></ResponsiveContainer>
      </Panel>
      <Panel i={5} title="Leaderboard" icon={ShieldCheck} area="2 / 1 / 3 / 3" help="Departments ranked by verified success, with backlog, budget use and efficiency change.">
        <table className="ax-table ax-compact"><thead><tr><th>#</th><th>Department</th><th>Success</th><th>Backlog</th><th>Budget used</th><th>Efficiency vs prev.</th></tr></thead>
          <tbody>{[...departments].sort((a, b) => b.performance - a.performance).map((d, k) => <motion.tr key={d.id} className="click" onClick={() => open(d.id)} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .04 }}><td className="ax-num">{k + 1}</td><td><span className="ax-flex" style={{ gap: 6 }}><Avatar role={d.role} size={20} name={d.name} />{d.name}</span></td><td className="ax-num"><b>{d.performance}%</b></td><td className="ax-num">{d.backlog}</td><td style={{ minWidth: 100 }}><Progress value={(d.spent / d.budget) * 100} thin label="Budget used" /></td><td className="ax-ok ax-num">+{EFFICIENCY[d.id]}%</td></motion.tr>)}</tbody></table>
      </Panel>
      <Panel i={6} title="Verified, not claimed" icon={ShieldCheck} help="Performance numbers come from independent QA verification of mission outputs. Efficiency deltas are sample values in this build.">
        <p className="ax-small" style={{ marginTop: 0 }}>Success is the share of missions and tasks a QA agent confirmed. A department never grades itself.</p>
        <div className="ax-flex ax-small" style={{ gap: 6 }}><CheckCircle2 size={14} className="ax-ok" aria-hidden />Verifier independence kept</div>
        <div className="ax-flex ax-small" style={{ gap: 6, marginTop: 3 }}><CheckCircle2 size={14} className="ax-ok" aria-hidden />Sample data, not live telemetry</div>
      </Panel>
    </div>
  );
}

/* ---------------- Reorganization tab (ADMIN-02) ---------------- */
function ReorgTab() {
  const st = useDeptStats(); const toast = useToast();
  const [sel, setSel] = useState(PROPOSALS[0].id); const [status, setStatus] = useState<Record<string, "approved" | "rejected">>({}); const [ask, setAsk] = useState<null | "approve" | "reject">(null); const [why, setWhy] = useState("");
  const p = PROPOSALS.find((x) => x.id === sel)!; const before = unitsOf(st.departments, (id) => st.agents.filter((a) => a.dept === id).length); const after = p.after(before);
  const stt = status[p.id]; const blocked = !!p.protectedHit;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "250px minmax(0,1fr)", gap: "var(--ax-gap)", height: "100%" }}>
      <div style={{ display: "grid", gridTemplateRows: "minmax(0,1fr) auto", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={2} title={`GM proposals (${PROPOSALS.length})`} icon={Crown} help="The General Manager proposes organization changes. You approve or reject each one; nothing is applied automatically.">
          {PROPOSALS.map((x) => <div key={x.id} className={`ax-row click ${sel === x.id ? "sel" : ""}`} role="button" tabIndex={0} aria-pressed={sel === x.id} onClick={() => setSel(x.id)} onKeyDown={(e) => e.key === "Enter" && setSel(x.id)} style={{ marginBottom: 4, alignItems: "flex-start" }}>
            <span className="grow"><b className="t" style={{ whiteSpace: "normal" }}>{x.title}</b><span className="s" style={{ marginTop: 2 }}><Pill c={PRIORITY[x.priority]}>{x.priority}</Pill> {status[x.id] ? <Pill c={status[x.id] === "approved" ? "var(--ax-ok)" : "var(--ax-neutral)"}>{status[x.id]}</Pill> : <span>pending</span>}</span></span></div>)}
        </Panel>
        <Panel i={3} title="Protected roles" icon={Lock} help="Governance roles that no reorganization may remove, merge or reassign without Governance approval.">
          {PROTECTED.map((r) => <div key={r.id} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }} data-tip={r.why}><Lock size={12} className="ax-gold" aria-hidden /><b>{r.id}</b><span className="ax-muted">{r.label}</span></div>)}
        </Panel>
      </div>
      <div style={{ display: "grid", gridTemplateRows: "minmax(0,1.15fr) minmax(0,1fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={4} title={`Before / after: ${p.title}`} icon={Shuffle} help="Left is the current organization, right is the organization after this proposal. Green is new, amber changed, blue merged."
          actions={<>{stt ? <StatusPill s={stt === "approved" ? "passed" : "cancelled"} label={stt === "approved" ? "Approved (sample)" : "Rejected"} /> : <>
            <IconBtn icon={ThumbsUp} tone="ok" label={blocked ? `Blocked: touches protected role ${p.protectedHit}` : "Approve this reorganization"} disabled={blocked} onClick={() => setAsk("approve")} />
            <IconBtn icon={ThumbsDown} tone="bad" label="Reject this reorganization" onClick={() => setAsk("reject")} /></>}</>}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 6, alignItems: "center", height: "100%" }}>
            <MiniOrg units={before} title="Before (v1.5.0)" /><ArrowRight size={22} className="ax-gold" aria-hidden /><MiniOrg units={after} title="After (v1.6.0 proposed)" accent />
          </div>
        </Panel>
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
          <Panel i={5} title="Role changes" icon={Users} help="Which agents change role or team. A lock marks a protected governance role.">
            <table className="ax-table ax-compact"><thead><tr><th>Role</th><th>From</th><th>To</th><th>Agents</th></tr></thead><tbody>{p.changes.map((c) => <tr key={c.role}><td><b>{c.role}</b> {c.protectedRole && <Lock size={11} className="ax-bad" aria-label="protected role" />}</td><td className="ax-small">{c.from}</td><td className="ax-small">{c.to}</td><td className="ax-num">{c.agents}</td></tr>)}</tbody></table>
            <p className="ax-xs ax-muted" style={{ marginBottom: 0 }}>{p.summary}</p>
          </Panel>
          <Panel i={6} title="Expected benefit" icon={TrendingUp} help="The GM's estimate. It is verified after rollout against the same metrics, not trusted as is.">
            <div className="ax-flex" style={{ gap: 8 }}><b style={{ fontSize: 26, color: "var(--ax-ok)" }}>+{p.gain}%</b><span className="ax-small">{p.benefit}</span></div>
            <p className="ax-xs ax-muted">Change control: lands on a feature branch of the org (branch-and-merge), reviewed, then merged. Rollback keeps the previous org version.</p>
          </Panel>
          <Panel i={7} title="Risks" icon={AlertTriangle} help="What could go wrong. Governance risks block approval until Governance signs off.">
            {p.risks.map((r) => <div key={r} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0", alignItems: "flex-start" }}><AlertTriangle size={13} className="ax-warn" style={{ flex: "none", marginTop: 2 }} aria-hidden />{r}</div>)}
            {blocked && <div className="ax-flex ax-small ax-bad" style={{ gap: 6, marginTop: 6 }}><Ban size={13} aria-hidden /><b>Cannot be approved here: {p.protectedHit} is a protected governance role.</b></div>}
          </Panel>
        </div>
      </div>
      <Modal open={!!ask} onClose={() => setAsk(null)} title={ask === "approve" ? `Approve "${p.title}"?` : `Reject "${p.title}"?`} icon={ask === "approve" ? ThumbsUp : ThumbsDown} width={460}
        foot={<><Btn onClick={() => setAsk(null)}>Cancel</Btn><Btn tone="gold" icon={ask === "approve" ? CheckCircle2 : ThumbsDown} onClick={() => { setStatus((s) => ({ ...s, [p.id]: ask! === "approve" ? "approved" : "rejected" })); toast(ask === "approve" ? `Sample: ${p.id} approved. A real build would open an org feature branch and notify the affected agents` : `${p.id} rejected${why ? `: ${why}` : ""}`, ask === "approve" ? "ok" : "warn"); setAsk(null); setWhy(""); }}>{ask === "approve" ? "Confirm approval" : "Confirm rejection"}</Btn></>}>
        <p className="ax-small" style={{ marginTop: 0 }}>{ask === "approve" ? `${p.changes.reduce((s, c) => s + c.agents, 0)} agents change team or role. Protected governance roles are untouched. Nothing is applied in production from this sample page.` : "The GM is told why, and may propose a revised version."}</p>
        {ask === "reject" && <textarea className="ax-textarea" rows={3} placeholder="Reason (optional)" aria-label="Rejection reason" value={why} onChange={(e) => setWhy(e.target.value)} />}
      </Modal>
    </div>
  );
}
void LayoutGrid;
