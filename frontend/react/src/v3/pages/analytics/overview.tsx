import { useState } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowRight, BarChart3, BrainCircuit, CheckCircle2, Cpu, HeartPulse, Layers, LineChart as LineIcon, Network, Zap, Gem, Boxes } from "lucide-react";
import { Count, Donut, Gauge, Panel, Pill, Progress, Seg, Empty } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";
import { useStore } from "../../data/store";
import { FINANCE, PERF_SERIES } from "../../data/sample";
import { chartTip } from "../Overview";
import { RESOURCES, avg, project, fmt$, missionBuckets, resourceSeries, roleStats, tail, throughput, trendSeries, type Metric, type Range } from "./data";

const axis = { tick: { fill: "var(--ax-muted)", fontSize: 10 }, stroke: "var(--ax-border)", tickLine: false } as const;
export const SamplePill = ({ what = "Sample" }: { what?: string }) => <Pill c="var(--ax-info)">{what}</Pill>;

/* ---- Agent Fleet Performance ---- */
export function Fleet({ i = 2 }: { i?: number }) {
  const agents = useStore((s) => s.agents);
  const [filter, setFilter] = useState("all");
  const stats = roleStats(agents);
  const shown = stats.filter((r) => filter === "all" || r.role === filter).slice(0, 10);
  return (
    <Panel i={i} title="Agent Fleet Performance" icon={Network} sub="success rate by role" help={{ body: "One tile per agent role: the average success rate of the agents holding that role and how many agents there are. Use the filter to focus on one role.", source: "Agent registry (derived from the agents in the store)." }}
      actions={<select className="ax-select" aria-label="Filter fleet by role" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "auto", fontSize: 12, padding: "3px 8px" }}><option value="all">All Agents</option>{stats.map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}</select>}>
      {!shown.length ? <Empty icon={Network} title="No agents registered yet">Agents appear here once the company has a fleet.</Empty> : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gridAutoRows: "1fr", gap: 8, height: "100%" }}>
          {shown.map((r, k) => (
            <motion.div key={r.role} className="ax-tile" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 + k * .04 }} whileHover={{ y: -3, scale: 1.02 }}
              style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", borderColor: `color-mix(in srgb, ${r.c} 45%, var(--ax-border))`, padding: "6px 8px" }}>
              <div className="ax-flex" style={{ justifyContent: "space-between" }}><span style={{ color: r.c, fontWeight: 700, fontSize: 12.5, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</span><Avatar role={r.role} size={34} /></div>
              <div className="ax-flex" style={{ justifyContent: "space-between", fontSize: 11 }}><span className="ax-muted">{r.n} agent{r.n === 1 ? "" : "s"}</span><b className="ax-num">{r.success.toFixed(1)}%</b></div>
              <Progress value={r.success} thin label={`${r.label} success rate`} />
            </motion.div>))}
        </div>)}
    </Panel>
  );
}

/* ---- Performance Trends ---- */
export function Trends({ range, i = 3, full }: { range: Range; i?: number; full?: boolean }) {
  const [metric, setMetric] = useState<Metric>("success");
  const t = trendSeries(metric, range);
  const last = t.rows[t.rows.length - 1] as unknown as Record<string, number> | undefined;
  return (
    <Panel i={i} title="Performance Trends" icon={LineIcon} help={{ body: "How the chosen metric moved over the selected period. Success Rate follows the verified success series; Throughput, Cost and Value are shown on the same time axis.", source: "Success and spend series from the sample dataset; throughput and value are illustrative." }}
      actions={<><SamplePill /><Seg label="Metric" value={metric} onChange={setMetric} items={[{ id: "success", label: "Success Rate" }, { id: "throughput", label: "Throughput" }, { id: "cost", label: "Cost" }, { id: "value", label: "Value" }]} /></>}>
      <div style={{ display: "grid", gridTemplateColumns: full ? "1fr" : "1fr 150px", gap: 8, height: "100%", minHeight: 0 }}>
        <div style={{ minHeight: 0 }}><ResponsiveContainer width="100%" height="100%"><LineChart data={t.rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" {...axis} interval="preserveStartEnd" minTickGap={28} /><YAxis {...axis} domain={t.dom} width={46} tickFormatter={(v) => `${t.unit === "$" ? "$" : ""}${v}${t.unit === "%" ? "%" : ""}`} />
          <Tooltip {...chartTip} />
          {t.lines.map((l) => <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.c} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive />)}
        </LineChart></ResponsiveContainer></div>
        {!full && <div className="ax-col" style={{ justifyContent: "center", gap: 14 }}>
          {t.lines.map((l) => <div key={l.key} className="ax-flex" style={{ justifyContent: "space-between", fontSize: 12 }}><span className="ax-flex"><i style={{ width: 9, height: 9, borderRadius: 9, background: l.c, flex: "none" }} aria-hidden />{l.name}</span><b className="ax-num">{last ? `${t.unit === "$" ? "$" : ""}${last[l.key]}${t.unit === "%" ? "%" : ""}` : "-"}</b></div>)}
        </div>}
      </div>
    </Panel>
  );
}

/* ---- Mission Execution Analysis ---- */
export function Execution({ range, i = 4 }: { range: Range; i?: number }) {
  const missions = useStore((s) => s.missions);
  const b = missionBuckets(missions), total = missions.length;
  const bars = throughput(range, total / 8);
  return (
    <Panel i={i} title="Mission Execution Analysis" icon={Activity} help={{ body: "Where your missions stand now (left) and how many were completed per day (right).", source: "Mission list (derived). Daily throughput bars are illustrative sample data." }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.05fr) minmax(0,1.3fr)", gap: 12, height: "100%", minHeight: 0 }}>
        {!total ? <Empty icon={Activity} title="No missions yet">Start a mission to see its execution analysis.</Empty> : (
          <div className="ax-flex" style={{ gap: 14 }}>
            <Donut label="Missions by status" size={116} stroke={13} center={<span style={{ textAlign: "center", lineHeight: 1.1 }}><b className="ax-num" style={{ fontSize: 22 }}>{total}</b><br /><small className="ax-muted">Missions</small></span>} parts={b} />
            <div className="ax-col" style={{ flex: 1, gap: 5 }}>{b.map((x) => <div key={x.label} className="ax-flex" style={{ fontSize: 12 }}><i style={{ width: 9, height: 9, borderRadius: 9, background: x.c, flex: "none" }} aria-hidden /><span style={{ flex: 1 }}>{x.label}</span><b className="ax-num" style={{ width: 24, textAlign: "right" }}>{x.value}</b><span className="ax-muted ax-num" style={{ width: 42, textAlign: "right" }}>{(total ? (x.value / total) * 100 : 0).toFixed(1)}%</span></div>)}</div>
          </div>)}
        <div className="ax-col" style={{ minHeight: 0, gap: 2 }}><span className="ax-small" style={{ fontWeight: 600 }}>Mission Throughput (Daily) <SamplePill /></span>
          <div style={{ flex: 1, minHeight: 0 }}><ResponsiveContainer width="100%" height="100%"><BarChart data={bars} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <XAxis dataKey="day" {...axis} interval="preserveStartEnd" minTickGap={30} /><YAxis {...axis} width={30} /><Tooltip {...chartTip} cursor={{ fill: "var(--ax-hover)" }} />
            <Bar dataKey="v" name="Missions completed" radius={[2, 2, 0, 0]}>{bars.map((_, k) => <Cell key={k} fill={`color-mix(in srgb, #3b8cff ${100 - Math.round((k / bars.length) * 60)}%, #a77bff)`} />)}</Bar>
          </BarChart></ResponsiveContainer></div></div>
      </div>
    </Panel>
  );
}

/* ---- Predictive Intelligence ---- */
export function usePredictions() {
  const missions = useStore((s) => s.missions);
  const ok = PERF_SERIES.map((p) => p.success), f = project(ok, 7), exp = Math.min(99.4, avg(f.next));
  const pp = exp - ok[ok.length - 1];
  const spend = FINANCE.month, projected = FINANCE.revenue * 1.35;
  const active = missions.filter((m) => !m.archived && m.status !== "cancelled" && m.status !== "done").length;
  return { exp, pp, projected, valueDelta: ((projected / FINANCE.revenue) - 1) * 100, demand: Math.round(Math.min(40, 6 + active * 1.5)), spend };
}
export function Predictive({ onRecs, i = 5 }: { onRecs: () => void; i?: number }) {
  const p = usePredictions();
  const rows = [
    { I: CheckCircle2, l: "Expected Mission Success (Next 7D)", v: `${p.exp.toFixed(1)}%`, d: `${p.pp >= 0 ? "+" : ""}${p.pp.toFixed(1)} pp`, up: p.pp >= 0 },
    { I: BarChart3, l: "Projected Value Generation", v: fmt$(p.projected), d: `+${p.valueDelta.toFixed(0)}%`, up: true },
    { I: Zap, l: "Resource Demand (Compute)", v: `+${p.demand}%`, d: "", up: true },
  ];
  return (
    <Panel i={i} title="Predictive Intelligence" icon={BrainCircuit} help={{ body: "A simple forecast for the next 7 days: expected mission success is a linear projection of the verified success series. Value and resource demand are indicative estimates, not commitments.", source: "Linear projection over the sample performance series (derived)." }} actions={<SamplePill what="Sample forecast" />}>
      <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 8, height: "100%", minHeight: 0, alignItems: "center" }}>
        <motion.div animate={{ y: [0, -4, 0], filter: ["drop-shadow(0 0 6px var(--ax-glow))", "drop-shadow(0 0 16px var(--ax-glow))", "drop-shadow(0 0 6px var(--ax-glow))"] }} transition={{ duration: 3.4, repeat: Infinity }} style={{ display: "grid", placeItems: "center", color: "var(--ax-accent)" }}><BrainCircuit size={84} strokeWidth={1.2} aria-label="Prediction engine" /></motion.div>
        <div className="ax-col" style={{ gap: 4 }}>
          {rows.map((r, k) => <motion.div key={r.l} className="ax-tile" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .15 + k * .06 }} whileHover={{ x: -2 }} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 9px", fontSize: 12 }}>
            <r.I size={16} className="ax-accent" aria-hidden /><span style={{ flex: 1 }}>{r.l}</span><b className="ax-num">{r.v}</b><span className={`${r.up ? "ax-ok" : "ax-bad"} ax-num`} style={{ width: 62, textAlign: "right", fontSize: 11 }}>{r.d && <>{r.up ? "▲" : "▼"} {r.d}</>}</span></motion.div>)}
          <div className="ax-tile" style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 9px", fontSize: 12 }}><Layers size={16} className="ax-accent" aria-hidden /><span style={{ flex: 1 }}>Recommended Actions</span>
            <motion.button type="button" className="ax-btn gold" onClick={onRecs} whileHover={{ scale: 1.04 }} whileTap={{ scale: .95 }}>View 3 Recommendations <ArrowRight size={14} aria-hidden /></motion.button></div>
        </div>
      </div>
    </Panel>
  );
}

/* ---- Agent Resource Utilization ---- */
export function Resources({ range, i = 6 }: { range: Range; i?: number }) {
  const rows = resourceSeries(range);
  return (
    <Panel i={i} title="Agent Resource Utilization" icon={Cpu} help={{ body: "How the agent fleet's resource use splits between compute, memory, storage, tools and other over time (100% stacked).", source: "Illustrative sample series." }} actions={<SamplePill />}>
      <div className="ax-col" style={{ height: "100%", gap: 2 }}>
        <div className="ax-flex" style={{ gap: 10, fontSize: 10.5, flexWrap: "wrap" }}>{RESOURCES.map((r) => <span key={r.k} className="ax-flex" style={{ gap: 4 }}><i style={{ width: 8, height: 8, borderRadius: 8, background: r.c }} aria-hidden />{r.n} {r.w}%</span>)}</div>
        <div style={{ flex: 1, minHeight: 0 }}><ResponsiveContainer width="100%" height="100%"><AreaChart data={rows} stackOffset="expand" margin={{ top: 4, right: 6, left: 0, bottom: 0 }}>
          <XAxis dataKey="day" {...axis} interval="preserveStartEnd" minTickGap={30} /><YAxis {...axis} width={40} tickFormatter={(v) => `${Math.round(v * 100)}%`} /><Tooltip {...chartTip} />
          {RESOURCES.map((r) => <Area key={r.k} type="monotone" dataKey={r.k} name={r.n} stackId="1" stroke={r.c} fill={r.c} fillOpacity={.55} />)}
        </AreaChart></ResponsiveContainer></div>
      </div>
    </Panel>
  );
}

/* ---- Value & ROI ---- */
export function useRoi() { const value = FINANCE.revenue, cost = FINANCE.month; return { value, cost, roi: cost ? value / cost : 0 }; }
export function ValueRoi({ range, i = 7 }: { range: Range; i?: number }) {
  const { value, cost, roi } = useRoi();
  const bars = tail(trendSeries("value", range).rows, range).map((r) => ({ day: r.day, v: (r as { a: number }).a }));
  return (
    <Panel i={i} title="Value & ROI" icon={Gem} help={{ body: "Value generated against what it cost to run the company. ROI is value divided by cost.", source: "Finance totals from the sample dataset; daily bars are illustrative." }} actions={<SamplePill />}>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 10, height: "100%", minHeight: 0 }}>
        <div className="ax-col" style={{ gap: 6, justifyContent: "center" }}>
          <div><small className="ax-muted">Value Generated</small><b className="ax-num" style={{ display: "block", fontSize: 20 }}><Count value={value} prefix="$" /></b><small className="ax-ok">▲ +{(((value / Math.max(1, cost)) - 1) * 10).toFixed(0)}%</small></div>
          <div><small className="ax-muted">Cost</small><b className="ax-num" style={{ display: "block", fontSize: 20 }}><Count value={cost} prefix="$" /></b><small className="ax-warn">spend this month</small></div>
        </div>
        <div style={{ minHeight: 0 }}><ResponsiveContainer width="100%" height="100%"><BarChart data={bars} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}><XAxis dataKey="day" hide /><Tooltip {...chartTip} cursor={{ fill: "var(--ax-hover)" }} /><Bar dataKey="v" name="Value" radius={[2, 2, 0, 0]}>{bars.map((_, k) => <Cell key={k} fill={`color-mix(in srgb, #3b8cff ${100 - Math.round((k / bars.length) * 70)}%, #a77bff)`} />)}</Bar></BarChart></ResponsiveContainer></div>
        <motion.div className="ax-tile" whileHover={{ scale: 1.05 }} style={{ alignSelf: "center", textAlign: "center", padding: "8px 14px", borderColor: "var(--ax-accent)" }}><small className="ax-muted">ROI</small><b className="ax-num" style={{ display: "block", fontSize: 26 }}><Count value={roi} decimals={1} suffix="x" /></b></motion.div>
      </div>
    </Panel>
  );
}

/* ---- System Health & Evolution ---- */
export function useHealth() {
  const agents = useStore((s) => s.agents), missions = useStore((s) => s.missions);
  const pct = (ok: number, n: number) => (n ? Math.round((ok / n) * 100) : 100);
  const items = [
    { l: "Agent Service", v: pct(agents.filter((a) => a.status !== "error" && a.status !== "offline").length, agents.length), d: true },
    { l: "Mission Engine", v: pct(missions.filter((m) => m.status !== "failed").length, missions.length), d: true },
    { l: "Knowledge Sync", v: 99, d: false }, { l: "Evolution Engine", v: 97, d: false }, { l: "Infrastructure", v: 98, d: false },
  ];
  return { items, overall: Math.round(avg(items.map((x) => x.v))) };
}
export function HealthEvo({ i = 8 }: { i?: number }) {
  const { items, overall } = useHealth();
  const version = useStore((s) => s.agentVersions.filter((v) => v.status === "baseline").sort((a, b) => b.at.localeCompare(a.at))[0]?.version);
  return (
    <Panel i={i} title="System Health & Evolution" icon={HeartPulse} help={{ body: "Overall health is the average of the five subsystem scores. Agent Service and Mission Engine are computed from your agents and missions; the other three are sample values.", source: "Agents and missions (derived) plus sample subsystem scores." }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 74px", gap: 10, height: "100%", alignItems: "center" }}>
        <Gauge value={overall} size={96} stroke={10} label="health" />
        <div className="ax-col" style={{ gap: 3 }}>{items.map((x) => <div key={x.l} className="ax-flex" style={{ fontSize: 11.5 }}><CheckCircle2 size={14} className={x.v >= 95 ? "ax-ok" : "ax-warn"} aria-label={x.v >= 95 ? "healthy" : "degraded"} /><span style={{ flex: 1 }}>{x.l}{!x.d && <sup className="ax-faint"> sample</sup>}</span><b className="ax-num">{x.v}%</b></div>)}</div>
        <motion.div animate={{ y: [0, -3, 0] }} transition={{ duration: 3, repeat: Infinity }} className="ax-col" style={{ alignItems: "center", gap: 2, color: "var(--ax-accent)" }}><Boxes size={36} aria-hidden /><b style={{ fontSize: 13, color: "var(--ax-text)" }}>{version ?? "v-"}</b><small className="ax-muted">Evolving...</small></motion.div>
      </div>
    </Panel>
  );
}
