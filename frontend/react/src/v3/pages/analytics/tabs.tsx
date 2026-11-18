import { motion } from "framer-motion";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from "recharts";
import { AlertTriangle, ArrowRight, Bot, Coins, Flame, Lightbulb, Rocket, ShieldAlert, Target, Timer, TrendingUp, Trophy, Users, Wallet } from "lucide-react";
import { Count, Donut, Empty, IconBtn, Legend, Panel, Pill, Progress, StatusPill, useToast } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";
import { useStore } from "../../data/store";
import { FINANCE, PERF_SERIES, SPEND_BREAKDOWN, SPEND_SERIES } from "../../data/sample";
import { href } from "../../app/router";
import { chartTip } from "../Overview";
import { SamplePill, Trends, usePredictions, useRoi, ValueRoi } from "./overview";
import { fmt$, project, missionBuckets, roleStats, tail, type Range } from "./data";

const axis = { tick: { fill: "var(--ax-muted)", fontSize: 10 }, stroke: "var(--ax-border)", tickLine: false } as const;
const grid = (cols: string, rows?: string) => ({ display: "grid", gridTemplateColumns: cols, gridTemplateRows: rows, gap: "var(--ax-gap)", minHeight: 0, height: "100%" }) as const;
const th = { textAlign: "left", fontWeight: 600, fontSize: 11, color: "var(--ax-muted)", padding: "4px 6px", position: "sticky", top: 0, background: "var(--ax-panel)" } as const;
const td = { padding: "4px 6px", fontSize: 12, borderTop: "1px solid var(--ax-border)" } as const;

/* ============ Agents ============ */
export function AgentsTab({ range }: { range: Range }) {
  const agents = useStore((s) => s.agents);
  const roles = roleStats(agents);
  const ranked = [...agents].sort((a, b) => b.successRate - a.successRate);
  return (
    <div style={grid("1.6fr 1fr", "1fr")}>
      <Panel i={1} title="Agent Leaderboard" icon={Trophy} help="Every agent ranked by verified success rate, with tasks done, cost per task and latency. Open an agent for its full profile." sub={`${agents.length} agents`}>
        {!ranked.length ? <Empty icon={Bot} title="No agents yet" /> : <table style={{ width: "100%", borderCollapse: "collapse" }}><thead><tr><th style={th}>#</th><th style={th}>Agent</th><th style={th}>Role</th><th style={{ ...th, width: 150 }}>Success</th><th style={th}>Tasks</th><th style={th}>$ / task</th><th style={th}>Latency</th><th style={th}>Status</th></tr></thead>
          <tbody>{ranked.map((a, k) => <motion.tr key={a.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(k, 12) * .02 }} whileHover={{ backgroundColor: "var(--ax-hover)" }}>
            <td style={td} className="ax-faint">{k + 1}</td>
            <td style={td}><a href={href("agents", a.id)} className="ax-flex" style={{ gap: 6, color: "inherit" }}><Avatar role={a.role} size={22} /><b>{a.id}</b></a></td>
            <td style={td} className="ax-muted">{a.title}</td>
            <td style={td}><div className="ax-flex"><Progress value={a.successRate} thin label={`${a.id} success`} /><b className="ax-num" style={{ width: 44 }}>{a.successRate.toFixed(1)}%</b></div></td>
            <td style={td} className="ax-num">{a.tasksDone}</td><td style={td} className="ax-num">${a.costPerTask.toFixed(2)}</td><td style={td} className="ax-num">{a.latencyS.toFixed(1)}s</td>
            <td style={td}><Pill c={a.status === "error" ? "var(--ax-bad)" : a.status === "offline" ? "var(--ax-neutral)" : a.status === "busy" ? "var(--ax-info)" : "var(--ax-ok)"}>{a.status}</Pill></td></motion.tr>)}</tbody></table>}
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={2} title="Success by Role" icon={Users} help="Average success rate for each role (derived from the agents)." style={{ flex: 1 }}>
          {!roles.length ? <Empty icon={Users} title="No roles yet" /> : <ResponsiveContainer width="100%" height="100%"><BarChart data={roles} layout="vertical" margin={{ left: 4, right: 14, top: 2, bottom: 0 }}>
            <XAxis type="number" domain={[80, 100]} {...axis} /><YAxis type="category" dataKey="label" width={92} {...axis} /><Tooltip {...chartTip} cursor={{ fill: "var(--ax-hover)" }} />
            <Bar dataKey="success" name="Success %" radius={[0, 3, 3, 0]}>{roles.map((r) => <Cell key={r.role} fill={r.c} />)}</Bar></BarChart></ResponsiveContainer>}
        </Panel>
        <Trends range={range} i={3} full />
      </div>
    </div>
  );
}

/* ============ Missions ============ */
export function MissionsTab() {
  const missions = useStore((s) => s.missions), tasks = useStore((s) => s.tasks);
  const b = missionBuckets(missions);
  const ts = (k: string[]) => tasks.filter((t) => k.includes(t.status)).length;
  const tb = [{ label: "Done", value: ts(["done", "passed"]), c: "var(--ax-ok)" }, { label: "Running", value: ts(["running", "verifying", "review"]), c: "var(--ax-info)" }, { label: "Queued", value: ts(["queued", "ready", "waiting_agent", "waiting_user", "draft", "paused"]), c: "var(--ax-neutral)" }, { label: "Blocked / failed", value: ts(["blocked", "failed"]), c: "var(--ax-bad)" }];
  const attention = missions.filter((m) => !m.archived && (m.status === "blocked" || m.status === "failed" || m.risk === "high")).slice(0, 6);
  const rows = [...missions].filter((m) => !m.archived).sort((a, b) => b.budget.spent - a.budget.spent);
  return (
    <div style={grid("1.7fr 1fr", "1fr")}>
      <Panel i={1} title="Mission Performance" icon={Target} help="Every mission with its progress, budget burn and risk. Click a mission to open it in Mission Control." sub={`${rows.length} missions`}>
        {!rows.length ? <Empty icon={Target} title="No missions yet">Create a mission to see its performance.</Empty> : <table style={{ width: "100%", borderCollapse: "collapse" }}><thead><tr><th style={th}>Mission</th><th style={th}>Status</th><th style={{ ...th, width: 130 }}>Progress</th><th style={{ ...th, width: 150 }}>Budget used</th><th style={th}>Tasks</th><th style={th}>Risk</th></tr></thead>
          <tbody>{rows.map((m, k) => { const used = m.budget.limit ? (m.budget.spent / m.budget.limit) * 100 : 0; return <motion.tr key={m.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(k, 12) * .02 }} whileHover={{ backgroundColor: "var(--ax-hover)" }}>
            <td style={td}><a href={href("control", m.id)} style={{ color: "inherit" }}><b>{m.id}</b> <span className="ax-muted">{m.title}</span></a></td><td style={td}><StatusPill s={m.status} small /></td>
            <td style={td}><div className="ax-flex"><Progress value={m.progress} thin label={`${m.id} progress`} /><span className="ax-num" style={{ width: 34 }}>{Math.round(m.progress)}%</span></div></td>
            <td style={td}><div className="ax-flex"><Progress value={used} thin c1={used > 90 ? "var(--ax-bad)" : "var(--ax-ok)"} c2={used > 90 ? "var(--ax-bad)" : "var(--ax-ok)"} label={`${m.id} budget`} /><span className="ax-num" style={{ width: 64 }}>{fmt$(m.budget.spent)}</span></div></td>
            <td style={td} className="ax-num">{tasks.filter((t) => t.missionId === m.id).length}</td>
            <td style={td}><Pill c={m.risk === "high" ? "var(--ax-bad)" : m.risk === "medium" ? "var(--ax-warn)" : "var(--ax-ok)"} icon={m.risk === "low" ? undefined : AlertTriangle}>{m.risk}</Pill></td></motion.tr>; })}</tbody></table>}
      </Panel>
      <div className="ax-col" style={{ gap: "var(--ax-gap)" }}>
        <Panel i={2} title="Mission Outcomes" icon={Rocket} help="Missions by outcome.">
          <div className="ax-flex" style={{ gap: 14 }}><Donut label="Missions by outcome" size={96} stroke={12} center={<b className="ax-num">{missions.length}</b>} parts={b} /><Legend items={b.map((x) => ({ label: x.label, value: x.value, c: x.c }))} /></div>
        </Panel>
        <Panel i={3} title="Task Pipeline" icon={Timer} help="All tasks by state across every mission.">
          {!tasks.length ? <Empty icon={Timer} title="No tasks yet" /> : <div className="ax-flex" style={{ gap: 14 }}><Donut label="Tasks by state" size={96} stroke={12} center={<b className="ax-num">{tasks.length}</b>} parts={tb} /><Legend items={tb.map((x) => ({ label: x.label, value: x.value, c: x.c }))} /></div>}
        </Panel>
        <Panel i={4} title="Needs Attention" icon={AlertTriangle} help="Missions that are blocked, failed or high risk." style={{ flex: 1 }}>
          {!attention.length ? <Empty icon={Target} title="Nothing needs attention" /> : <div className="ax-col" style={{ gap: 4 }}>{attention.map((m) => <motion.a key={m.id} href={href("control", m.id)} whileHover={{ x: 2 }} className="ax-flex" style={{ fontSize: 12, color: "inherit" }}><b style={{ width: 46 }}>{m.id}</b><span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.title}</span><StatusPill s={m.status} small /></motion.a>)}</div>}
        </Panel>
      </div>
    </div>
  );
}

/* ============ Cost & ROI ============ */
export function CostTab({ range }: { range: Range }) {
  const missions = useStore((s) => s.missions), agents = useStore((s) => s.agents);
  const { value, cost, roi } = useRoi();
  const s = tail(SPEND_SERIES, range);
  const byMission = [...missions].filter((m) => m.budget.spent > 0).sort((a, b) => b.budget.spent - a.budget.spent).slice(0, 8).map((m) => ({ id: m.id, spent: m.budget.spent, limit: m.budget.limit }));
  const roles = roleStats(agents).filter((r) => r.cost > 0);
  const tiles = [{ I: Coins, l: "Spend this month", v: FINANCE.month, p: "$", c: "var(--ax-warn)" }, { I: Wallet, l: "Budget", v: FINANCE.budget, p: "$", c: "var(--ax-info)" }, { I: Flame, l: "Burn / day", v: FINANCE.burnPerDay, p: "$", d: 1, c: "var(--ax-bad)" }, { I: TrendingUp, l: "Cost / success", v: FINANCE.costPerSuccess, p: "$", d: 1, c: "var(--ax-ok)" }];
  return (
    <div style={grid("1.4fr 1fr 1fr", "auto 1fr 1fr")}>
      <div style={{ gridColumn: "1 / -1", display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--ax-gap)", position: "relative", zIndex: 1 }}>{tiles.map((t, k) => <motion.div key={t.l} className="ax-tile" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .05 }} whileHover={{ y: -2 }} style={{ display: "flex", gap: 10, alignItems: "center", borderColor: t.c }}>
        <t.I size={24} style={{ color: t.c }} aria-hidden /><span><b className="ax-num" style={{ fontSize: 20 }}><Count value={t.v} prefix={t.p} decimals={t.d ?? 0} /></b><small className="ax-muted" style={{ display: "block" }}>{t.l} <SamplePill /></small></span></motion.div>)}</div>
      <Panel i={1} title="Spend vs Budget" icon={Wallet} help="Daily spend against the daily budget line." actions={<SamplePill />} style={{ gridRow: "2 / 4" }}>
        <ResponsiveContainer width="100%" height="100%"><ComposedChart data={s} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}><CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="day" {...axis} minTickGap={26} /><YAxis {...axis} width={40} /><Tooltip {...chartTip} />
          <Area type="monotone" dataKey="spend" name="Spend" stroke="#f2b53a" fill="#f2b53a" fillOpacity={.25} /><Line type="monotone" dataKey="budget" name="Budget" stroke="#94a3b8" strokeDasharray="5 4" dot={false} /></ComposedChart></ResponsiveContainer>
      </Panel>
      <Panel i={2} title="Where the Money Goes" icon={Coins} help="Spend split by category." actions={<SamplePill />}>
        <div className="ax-flex" style={{ gap: 14 }}><Donut label="Spend by category" size={104} stroke={13} center={<b className="ax-num">{fmt$(cost)}</b>} parts={SPEND_BREAKDOWN} /><Legend items={SPEND_BREAKDOWN.map((x) => ({ label: x.label, value: `${x.value}%`, c: x.c }))} /></div>
      </Panel>
      <ValueRoi range={range} i={3} />
      <Panel i={4} title="Spend by Mission" icon={Target} help="Budget spent against each mission's limit (derived from the missions).">
        {!byMission.length ? <Empty icon={Target} title="No spend recorded yet" /> : <ResponsiveContainer width="100%" height="100%"><BarChart data={byMission} margin={{ top: 4, right: 6, left: -12, bottom: 0 }}><XAxis dataKey="id" {...axis} /><YAxis {...axis} width={42} /><Tooltip {...chartTip} cursor={{ fill: "var(--ax-hover)" }} /><Bar dataKey="limit" name="Limit" fill="var(--ax-border)" radius={[3, 3, 0, 0]} /><Bar dataKey="spent" name="Spent" fill="#f2b53a" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>}
      </Panel>
      <Panel i={5} title="Cost per Task by Role" icon={Bot} help="Average cost of one task for each agent role (derived from the agents). ROI overall is shown on the right.">
        <div className="ax-flex" style={{ gap: 10, height: "100%" }}><div style={{ flex: 1, height: "100%" }}>{!roles.length ? <Empty icon={Bot} title="No cost data" /> : <ResponsiveContainer width="100%" height="100%"><BarChart data={roles} layout="vertical" margin={{ left: 4, right: 12 }}><XAxis type="number" {...axis} /><YAxis type="category" dataKey="label" width={86} {...axis} /><Tooltip {...chartTip} cursor={{ fill: "var(--ax-hover)" }} /><Bar dataKey="cost" name="$ / task" radius={[0, 3, 3, 0]}>{roles.map((r) => <Cell key={r.role} fill={r.c} />)}</Bar></BarChart></ResponsiveContainer>}</div>
          <div className="ax-tile" style={{ textAlign: "center" }}><small className="ax-muted">ROI</small><b className="ax-num" style={{ display: "block", fontSize: 24 }}>{roi.toFixed(1)}x</b><small className="ax-muted">{fmt$(value)} / {fmt$(cost)}</small></div></div>
      </Panel>
    </div>
  );
}

/* ============ Predictions ============ */
export function PredictionsTab() {
  const toast = useToast();
  const missions = useStore((s) => s.missions);
  const p = usePredictions();
  const ok = PERF_SERIES.map((x) => x.success), f = project(ok, 7, 7);
  const data = [...PERF_SERIES.slice(-14).map((x) => ({ day: x.day, actual: x.success, fc: null as number | null })), ...f.next.map((v, k) => ({ day: `+${k + 1}d`, actual: null as number | null, fc: +Math.min(99.5, v).toFixed(1) }))];
  data[13].fc = data[13].actual;
  const spend = SPEND_SERIES.map((x) => x.spend), sf = project(spend, 14, 10);
  const spendData = [...SPEND_SERIES.slice(-14).map((x) => ({ day: x.day, spend: x.spend as number | null, fc: null as number | null })), ...sf.next.map((v, k) => ({ day: `+${k + 1}d`, spend: null as number | null, fc: Math.round(v) }))];
  spendData[13].fc = spendData[13].spend;
  const projMonth = FINANCE.month + sf.next.reduce((a, b) => a + b, 0);
  const risky = missions.filter((m) => !m.archived && m.status !== "done" && (m.risk === "high" || (m.budget.limit && m.budget.spent / m.budget.limit > .8)));
  const recs = [
    { I: Lightbulb, t: "Shift routine QA to the cheaper model", d: `Cost per success is ${fmt$(FINANCE.costPerSuccess)}; routing low-risk checks could cut it by about 12%.`, c: "var(--ax-ok)" },
    { I: ShieldAlert, t: "Review high-risk missions before the next release", d: `${risky.length} mission${risky.length === 1 ? "" : "s"} are high risk or above 80% of budget.`, c: "var(--ax-warn)" },
    { I: Wallet, t: "Raise the monthly budget or slow the burn", d: `At the current trend, month spend lands near ${fmt$(projMonth)} against a ${fmt$(FINANCE.budget)} budget.`, c: projMonth > FINANCE.budget ? "var(--ax-bad)" : "var(--ax-info)" },
  ];
  return (
    <div style={grid("1.5fr 1fr", "1fr 1fr")}>
      <Panel i={1} title="Success Rate Forecast (Next 7 Days)" icon={TrendingUp} help="Solid line: verified success. Dashed line: a straight-line projection of the recent trend. It is an estimate, not a guarantee." actions={<SamplePill what="Sample forecast" />} style={{ gridRow: "1 / 3" }}>
        <div className="ax-col" style={{ height: "100%", gap: 6 }}>
          <div className="ax-flex" style={{ gap: 18, fontSize: 12 }}><span>Expected: <b className="ax-num">{p.exp.toFixed(1)}%</b></span><span className={f.slope >= 0 ? "ax-ok" : "ax-bad"}>trend {f.slope >= 0 ? "+" : ""}{(f.slope).toFixed(2)} pp / day</span></div>
          <div style={{ flex: 1, minHeight: 0 }}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}><CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="day" {...axis} /><YAxis {...axis} domain={[88, 100]} width={38} /><Tooltip {...chartTip} />
            <Line dataKey="actual" name="Verified" stroke="#22d3ee" strokeWidth={2} dot={false} connectNulls={false} /><Line dataKey="fc" name="Forecast" stroke="#a77bff" strokeWidth={2} strokeDasharray="6 4" dot={{ r: 2 }} connectNulls={false} /></ComposedChart></ResponsiveContainer></div>
        </div>
      </Panel>
      <Panel i={2} title="Spend & Value Outlook" icon={Coins} help="A straight-line projection of spend for the next 14 days and the value it is expected to return." actions={<SamplePill what="Sample forecast" />}>
        <div className="ax-col" style={{ gap: 8 }}>
          {[{ l: "Projected month-end spend", v: fmt$(projMonth), s: `budget ${fmt$(FINANCE.budget)}`, p: (projMonth / FINANCE.budget) * 100 }, { l: "Projected value (30d)", v: fmt$(p.projected), s: `+${p.valueDelta.toFixed(0)}% vs now`, p: 100 }, { l: "Compute demand", v: `+${p.demand}%`, s: "next 7 days", p: Math.min(100, 50 + p.demand) }].map((x) => <div key={x.l}><div className="ax-flex" style={{ justifyContent: "space-between", fontSize: 12 }}><span>{x.l}</span><b className="ax-num">{x.v}</b></div><Progress value={x.p} thin label={x.l} /><small className="ax-muted">{x.s}</small></div>)}
          <div style={{ height: 150 }}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={spendData} margin={{ top: 4, right: 6, left: 0, bottom: 0 }}><CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="day" {...axis} minTickGap={24} /><YAxis {...axis} width={36} /><Tooltip {...chartTip} />
            <Line dataKey="spend" name="Spend" stroke="#f2b53a" strokeWidth={2} dot={false} /><Line dataKey="fc" name="Projected" stroke="#a77bff" strokeWidth={2} strokeDasharray="6 4" dot={false} /></ComposedChart></ResponsiveContainer></div>
        </div>
      </Panel>
      <Panel i={3} title="Recommended Actions" icon={Lightbulb} help="Suggestions drawn from the forecasts. Applying one only records your intent here; nothing is changed in production.">
        <div className="ax-col" style={{ gap: 6 }}>{recs.map((r, k) => <motion.div key={r.t} className="ax-tile" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 + k * .06 }} whileHover={{ x: 2 }} style={{ display: "flex", gap: 8, alignItems: "center", borderLeft: `3px solid ${r.c}` }}>
          <r.I size={18} style={{ color: r.c }} aria-hidden /><span style={{ flex: 1, minWidth: 0 }}><b style={{ fontSize: 12.5 }}>{r.t}</b><small className="ax-muted" style={{ display: "block" }}>{r.d}</small></span>
          <IconBtn icon={ArrowRight} label={`Note recommendation: ${r.t}`} size="sm" onClick={() => toast("Recommendation noted (sample forecast, nothing was changed)", "info")} /></motion.div>)}</div>
      </Panel>
    </div>
  );
}
