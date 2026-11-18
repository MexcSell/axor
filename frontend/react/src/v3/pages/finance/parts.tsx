import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, BarChart3, Building2, Check, Gauge as GaugeIcon, Info, Landmark, LineChart as LineIcon, PiggyBank, Scale, Target, Users, Wallet, Zap, Layers, Database } from "lucide-react";
import { Donut, Gauge, Kpi, Legend, Panel, Pill, Progress, Seg, Switch } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";
import { useStore } from "../../data/store";
import { FINANCE } from "../../data/sample";
import { chartTip } from "../Overview";
import { CATEGORIES, LAST30, SAVINGS_YTD, projection, sustainability, usd } from "./calc";
import { OPTIMISATIONS, THRESHOLDS } from "./data";

export const usageColor = (p: number) => (p >= 95 ? "var(--ax-bad)" : p >= 80 ? "var(--ax-warn)" : "var(--ax-ok)");
export function UsageBar({ pct, label }: { pct: number; label: string }) {
  const c = usageColor(pct);
  return <span className="ax-flex" style={{ gap: 5 }}><span style={{ width: 56, flex: "none" }}><Progress value={Math.min(100, pct)} c1={c} c2={c} thin label={label} /></span><span className="ax-num ax-small" style={{ color: c }}>{pct.toFixed(0)}%</span></span>;
}
export const Delta = ({ v }: { v: number }) => <span className="ax-num ax-small" style={{ color: v > 0 ? "var(--ax-bad)" : "var(--ax-ok)" }}>{v > 0 ? "▲" : "▼"} {Math.abs(v).toFixed(1)}%</span>;

export function useFin() {
  const departments = useStore((s) => s.departments), missions = useStore((s) => s.missions);
  const proj = useMemo(() => projection(30, "base"), []);
  const spendPct = FINANCE.month / FINANCE.budget * 100;
  return { departments, missions, proj, spendPct, remaining: FINANCE.budget - FINANCE.month, ratio: sustainability() };
}

export function FinKpis() {
  const { proj, spendPct, remaining, ratio } = useFin();
  const fcDelta = (proj.total / LAST30 - 1) * 100;
  return (
    <div className="ax-kpis" style={{ gridTemplateColumns: "repeat(6, 1fr)" }}>
      <Kpi i={0} icon={Wallet} c="#f2b53a" value={FINANCE.budget} prefix="$" label="Total Budget" delta={`↑ +${FINANCE.deltaPct}% (vs. last month)`} />
      <Kpi i={1} icon={Layers} c="#a77bff" value={FINANCE.month} prefix="$" label="Total Spend" delta={`${spendPct.toFixed(1)}% of Budget`} />
      <Kpi i={2} icon={Landmark} c="#2fd27a" value={remaining} prefix="$" label="Remaining" delta={`${(100 - spendPct).toFixed(1)}%`} />
      <Kpi i={3} icon={Target} c="#a77bff" value={proj.total} prefix="$" label="Forecast (Next 30 d)" delta={`↑ ${fcDelta > 0 ? "+" : ""}${fcDelta.toFixed(1)}% vs last 30 d`} help="Linear trend of the last 14 days. See the Forecast tab for assumptions and the uncertainty band." />
      <Kpi i={4} icon={PiggyBank} c="#f2b53a" value={SAVINGS_YTD} prefix="$" label="Cost Savings (YTD)" delta="↑ +18.4%" />
      <Kpi i={5} icon={Scale} c="#2fd27a" value={ratio} decimals={2} suffix="x" label="Sustainability Ratio" delta={ratio >= 1 ? "Self-sustaining (target >= 1.0x)" : "Below 1.0x: not self-sustaining"} help="Operating Sustainability Ratio = Recurring Revenue / Recurring Operating Costs." />
    </div>
  );
}

export function BudgetPanel({ i = 0 }: { i?: number }) {
  const { spendPct } = useFin();
  return (
    <Panel i={i} title="Budget & Usage Overview" icon={Wallet} help="How much of this month's budget is spent, and where the money goes by category.">
      <div className="ax-flex" style={{ gap: 14, height: "100%" }}>
        <Donut label="Budget used" parts={CATEGORIES.map((c) => ({ label: c.label, value: c.value, c: c.c }))} size={118} stroke={16} center={<><b style={{ fontSize: 20 }}>{Math.round(spendPct)}%</b><small className="ax-xs ax-muted">Budget Used</small></>} />
        <Legend items={CATEGORIES.map((c) => ({ label: c.label, c: c.c, value: <span className="ax-num">{c.value}% &nbsp; {usd(c.spend)}</span> }))} />
      </div>
    </Panel>
  );
}

export function CategoryPanel({ i = 0 }: { i?: number }) {
  return (
    <Panel i={i} className="fin-compact" title="Category Breakdown" icon={BarChart3} help="Spend against budget for each cost category. Usage turns amber from 80% and red from 95%. Budgets per category are sample allocations.">
      <table className="ax-table"><thead><tr><th>Category</th><th>Budget</th><th>Spend</th><th>Usage</th><th>MoM</th></tr></thead>
        <tbody>{CATEGORIES.map((c, k) => (
          <motion.tr key={c.label} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
            <td><span className="ax-flex"><i style={{ width: 9, height: 9, borderRadius: 3, background: c.c, display: "inline-block" }} aria-hidden />{c.label}</span></td>
            <td className="ax-num">{usd(c.budget)}</td><td className="ax-num">{usd(c.spend)}</td><td><UsageBar pct={c.usage} label={`${c.label} usage`} /></td><td><Delta v={c.mom} /></td>
          </motion.tr>))}</tbody></table>
    </Panel>
  );
}

export function TrendChart({ points, height = "100%" }: { points: ReturnType<typeof projection>["points"]; height?: number | string }) {
  const todayIdx = points.findIndex((p) => p.actual != null && p.fc != null);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={points} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 4" vertical={false} />
        <XAxis dataKey="day" tick={{ fill: "var(--ax-muted)", fontSize: 10 }} interval={6} stroke="var(--ax-border)" />
        <YAxis tick={{ fill: "var(--ax-muted)", fontSize: 10 }} stroke="var(--ax-border)" tickFormatter={(v) => "$" + v} />
        <Tooltip {...chartTip} formatter={(v: number, n: string) => [usd(v), n]} />
        <Area dataKey="lo" name="Lower bound (90%)" stackId="b" stroke="none" fill="none" />
        <Area dataKey="band" name="Band width" stackId="b" stroke="none" fill="var(--ax-accent2)" fillOpacity={.18} />
        <Line dataKey="actual" name="Spend (actual, per day)" stroke="var(--ax-info)" strokeWidth={2} dot={false} />
        <Line dataKey="fc" name="Forecast (per day)" stroke="var(--ax-warn)" strokeWidth={2} strokeDasharray="5 4" dot={false} />
        <Line dataKey="budget" name="Daily budget" stroke="var(--ax-faint)" strokeWidth={1} dot={false} />
        {todayIdx >= 0 && <ReferenceLine x={points[todayIdx].day} stroke="var(--ax-accent)" label={{ value: "Today", fill: "var(--ax-accent)", fontSize: 10, position: "top" }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
export function TrendPanel({ i = 0 }: { i?: number }) {
  const [range, setRange] = useState<"30" | "14">("30");
  const { proj } = useFin();
  const pts = range === "30" ? proj.points : proj.points.filter((_, k) => k >= 16);
  return (
    <Panel i={i} title="Spending Trend & Forecast" icon={LineIcon} help="Daily spend (blue) and the trend-based forecast (dashed amber) with its uncertainty band. Daily figures, not cumulative."
      actions={<Seg label="Chart range" value={range} onChange={setRange} items={[{ id: "30", label: "30 d" }, { id: "14", label: "14 d" }]} />}>
      <TrendChart points={pts} />
    </Panel>
  );
}

const STATUS_FILTERS = [["all", "All"], ["running", "In Progress"], ["review", "Review"], ["done", "Completed"]] as const;
export function MissionSpendPanel({ i = 0, full }: { i?: number; full?: boolean }) {
  const { missions } = useFin();
  const [f, setF] = useState<(typeof STATUS_FILTERS)[number][0]>("all");
  const rows = missions.filter((m) => !m.archived && (f === "all" || m.status === f));
  return (
    <Panel i={i} title="Mission Spending" icon={Target} help="Spend against each mission's own budget (lifetime, not monthly). Open Cost by Mission for cost per point of progress."
      tabs={<Seg label="Mission status" value={f} onChange={setF} items={STATUS_FILTERS.map(([id, label]) => ({ id, label: `${label} (${missions.filter((m) => !m.archived && (id === "all" || m.status === id)).length})` }))} />}>
      <table className="ax-table"><thead><tr><th>Mission</th><th>Spend</th><th>Budget</th><th>Usage</th></tr></thead>
        <tbody>{rows.slice(0, full ? 99 : 12).map((m, k) => { const u = m.budget.spent / m.budget.limit * 100; return (
          <motion.tr key={m.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
            <td><span className="ax-small">{m.title}</span></td><td className="ax-num">{usd(m.budget.spent)}</td><td className="ax-num">{usd(m.budget.limit)}</td><td><UsageBar pct={u} label={`${m.title} usage`} /></td></motion.tr>); })}</tbody></table>
      {!rows.length && <p className="ax-small ax-muted">No missions with this status.</p>}
    </Panel>
  );
}

export function DeptPanel({ i = 0 }: { i?: number }) {
  const { departments } = useFin();
  return (
    <Panel i={i} title="Department Spending" icon={Building2} help="Monthly spend against each department's allocated budget. The remainder of the company's spend is shared infrastructure that is not attributed to a department.">
      <table className="ax-table"><thead><tr><th>Department</th><th>Spend</th><th>Budget</th><th>Usage</th></tr></thead>
        <tbody>{departments.map((d, k) => (
          <motion.tr key={d.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
            <td><span className="ax-flex"><Avatar role={d.role} size={18} />{d.name}</span></td><td className="ax-num">{usd(d.spent)}</td><td className="ax-num">{usd(d.budget)}</td><td><UsageBar pct={d.spent / d.budget * 100} label={`${d.name} usage`} /></td></motion.tr>))}</tbody></table>
    </Panel>
  );
}

export interface FinAlert { id: string; text: string; sev: "High" | "Medium" | "Info"; why: string }
export function deriveAlerts(rules: { scope: string; pct: number; on: boolean }[], depts: { name: string; spent: number; budget: number }[]): FinAlert[] {
  const out: FinAlert[] = [], on = (s: string) => rules.find((r) => r.scope === s && r.on);
  const co = on("Company monthly budget"); if (co && FINANCE.month / FINANCE.budget * 100 >= co.pct) out.push({ id: "co", text: `Company spend at ${(FINANCE.month / FINANCE.budget * 100).toFixed(1)}% of budget`, sev: "Medium", why: `Threshold ${co.pct}%` });
  const llm = CATEGORIES[0], rl = on("LLM / API category"); if (rl && llm.usage >= rl.pct) out.push({ id: "llm", text: `LLM / API spend at ${llm.usage.toFixed(1)}% of its budget`, sev: "High", why: `Threshold ${rl.pct}%` });
  const rd = on("Any department"); if (rd) depts.filter((d) => d.spent / d.budget * 100 >= rd.pct).forEach((d) => out.push({ id: d.name, text: `${d.name} at ${(d.spent / d.budget * 100).toFixed(0)}% of department budget`, sev: "Medium", why: `Threshold ${rd.pct}%` }));
  const fc = projection(30, "base").total; if (fc > FINANCE.budget) out.push({ id: "fc", text: `Forecast ${usd(fc)} for the next 30 days exceeds the ${usd(FINANCE.budget)} monthly budget`, sev: "High", why: "Trend forecast, see Forecast tab" });
  out.push({ id: "evo", text: "Self-Evolution Engine spend +6.7% MoM", sev: "Medium", why: "Month-on-month, sample" }, { id: "idle", text: "Idle compute detected (about $14)", sev: "Medium", why: "Ops monitor, sample" }, { id: "opt", text: `${OPTIMISATIONS.length} cost optimization opportunities`, sev: "Info", why: "Right-sizing, routing, caching" }, { id: "dept", text: `${depts.filter((d) => d.spent / d.budget < .85).length} of ${depts.length} departments within budget`, sev: "Info", why: "Below the department threshold" });
  return out;
}
const SEV: Record<string, string> = { High: "var(--ax-bad)", Medium: "var(--ax-warn)", Info: "var(--ax-info)" };
export function AlertsPanel({ i = 0 }: { i?: number }) {
  const { departments } = useFin();
  const alerts = deriveAlerts(THRESHOLDS, departments);
  return (
    <Panel i={i} title="Alerts & Recommendations" icon={AlertTriangle} help="Alerts raised by the thresholds in the Alerts tab, plus recommendations from the Finance agent.">
      <div className="ax-rows">{alerts.map((a, k) => (
        <motion.div key={a.id} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
          {a.sev === "Info" ? <Check size={14} style={{ color: "var(--ax-ok)" }} aria-hidden /> : <AlertTriangle size={14} style={{ color: SEV[a.sev] }} aria-hidden />}
          <span className="grow"><span className="t ax-small" style={{ whiteSpace: "normal" }}>{a.text}</span></span><Pill c={SEV[a.sev]}>{a.sev}</Pill></motion.div>))}</div>
    </Panel>
  );
}

export function OptimPanel({ i = 0 }: { i?: number }) {
  const [on, setOn] = useState<Record<string, boolean>>(Object.fromEntries(OPTIMISATIONS.map((o) => [o.id, true])));
  const total = OPTIMISATIONS.filter((o) => on[o.id]).reduce((a, o) => a + o.saving, 0);
  return (
    <Panel i={i} title="Cost Optimization" icon={Zap} help="Automatic savings the Finance agent may apply inside its approved limits. Estimates are sample values; toggles here are not yet saved to a server.">
      <div className="ax-rows">{OPTIMISATIONS.map((o) => (
        <div key={o.id} className="ax-row"><Check size={14} style={{ color: on[o.id] ? "var(--ax-ok)" : "var(--ax-faint)" }} aria-hidden /><span className="grow t ax-small">{o.label}</span><span className="ax-xs ax-muted ax-num">{usd(o.saving)}/mo</span>
          <Switch label={`${o.label}`} on={on[o.id]} onChange={(v) => setOn({ ...on, [o.id]: v })} /></div>))}</div>
      <div className="ax-xs ax-muted" style={{ marginTop: 4 }}>Estimated saving if all on: <b className="ax-num">{usd(total)}</b> per month</div>
    </Panel>
  );
}

export function AgentAllocPanel({ i = 0 }: { i?: number }) {
  const { departments } = useFin();
  const tot = departments.reduce((a, d) => a + d.spent, 0), n = departments.length + 1;
  return (
    <Panel i={i} title="Agent Organization & Cost Allocation" icon={Users} help="Monthly spend attributed to each department's agents. Shared infrastructure is not attributed.">
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", height: "100%" }}>
        <motion.div className="ax-tile" style={{ display: "flex", gap: 8, alignItems: "center", borderColor: "var(--ax-accent)" }} initial={{ y: -8, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
          <Avatar role="gm" size={30} name="GM" /><span><b className="ax-small">General Manager (GM)</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Strategy · Planning · Control</span></span></motion.div>
        <svg width="100%" height="14" viewBox="0 0 100 14" preserveAspectRatio="none" aria-hidden style={{ flex: "none" }}>
          <path d="M50 0 V6" stroke="var(--ax-accent)" strokeWidth=".6" /><path d={`M${50 / n} 6 H${100 - 50 / n}`} stroke="var(--ax-accent)" strokeWidth=".6" />
          {Array.from({ length: n }, (_, k) => <motion.path key={k} d={`M${(100 / n) * k + 50 / n} 6 V14`} stroke="var(--ax-accent)" strokeWidth=".6" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .2 + k * .05 }} />)}
        </svg>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${n}, 1fr)`, width: "100%", flex: 1, alignItems: "start" }}>
          {departments.map((d, k) => (
            <motion.div key={d.id} style={{ textAlign: "center" }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .05 }}>
              <Avatar role={d.role} size={34} name={d.name} /><div className="ax-small"><b>{d.name.replace(" / Verifier", "")}</b></div>
              <div className="ax-num ax-small">{usd(d.spent)}</div><div className="ax-xs ax-muted">{(d.spent / tot * 100).toFixed(1)}%</div></motion.div>))}
          <motion.div style={{ textAlign: "center" }} initial={{ opacity: 0 }} animate={{ opacity: 1 }}><span className="ax-pi" style={{ display: "inline-grid", width: 40, height: 40, placeItems: "center" }}><Database size={20} aria-hidden /></span>
            <div className="ax-small"><b>Shared infra</b></div><div className="ax-num ax-small">{usd(FINANCE.month - tot)}</div><div className="ax-xs ax-muted">not attributed</div></motion.div>
        </div>
      </div>
    </Panel>
  );
}

export function SustainPanel({ i = 0 }: { i?: number }) {
  const r = sustainability();
  return (
    <Panel i={i} title="Operating Sustainability" icon={GaugeIcon} help={{ body: "Operating Sustainability Ratio = Recurring Revenue / Recurring Operating Costs. At 1.0x or more the company pays for itself from recurring revenue.", example: `${usd(FINANCE.revenue)} / ${usd(FINANCE.opCost)} = ${r.toFixed(2)}x`, source: "Finance sample data" }}>
      <div className="ax-flex" style={{ gap: 12 }}>
        <Gauge value={Math.min(100, r / 2 * 100)} size={96} stroke={10} label="Sustainability ratio" center={<div><b style={{ fontSize: 22, fontWeight: 750 }}>{r.toFixed(2)}x</b><div className="ax-xs ax-muted">{r >= 1 ? "self-sustaining" : "below break-even"}</div></div>} />
        <dl className="ax-small" style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 10px" }}>
          <dt className="ax-muted">Recurring revenue</dt><dd className="ax-num" style={{ margin: 0 }}>{usd(FINANCE.revenue)}</dd>
          <dt className="ax-muted">Recurring op. costs</dt><dd className="ax-num" style={{ margin: 0 }}>{usd(FINANCE.opCost)}</dd>
          <dt className="ax-muted">Margin</dt><dd className="ax-num" style={{ margin: 0 }}>{usd(FINANCE.revenue - FINANCE.opCost)}</dd>
          <dt className="ax-muted">Cost / success</dt><dd className="ax-num" style={{ margin: 0 }}>{usd(FINANCE.costPerSuccess, 2)}</dd>
        </dl>
      </div>
      <p className="ax-xs ax-faint" style={{ margin: "4px 0 0" }}><Info size={10} aria-hidden /> Gauge scale 0 to 2.0x; 1.0x is break-even.</p>
    </Panel>
  );
}

