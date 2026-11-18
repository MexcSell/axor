import { useMemo, useState, type CSSProperties } from "react";
import { motion } from "framer-motion";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Check, Info, Pencil, X } from "lucide-react";
import { Btn, IconBtn, Modal, Panel, Pill, Progress, Seg, Switch, useToast } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";
import { AgentTag } from "../../ui/widgets";
import { useStore } from "../../data/store";
import { FINANCE, SPEND_SERIES } from "../../data/sample";
import { chartTip } from "../Overview";
import { LAST30, SCENARIO, projection, sustainability, usd, type Scenario } from "./calc";
import { FORECAST_ASSUMPTIONS, MODEL_USAGE, THRESHOLDS } from "./data";
import { AlertsPanel, CategoryPanel, OptimPanel, TrendChart, UsageBar, deriveAlerts, usageColor } from "./parts";

const cols = (c: string): CSSProperties => ({ display: "grid", gridTemplateColumns: c, gap: "var(--ax-gap)", height: "100%", minHeight: 0 });

/* ---------- Budgets ---------- */
export function BudgetsTab() {
  const depts = useStore((s) => s.departments), toast = useToast();
  const [caps, setCaps] = useState<Record<string, number>>({});
  const [edit, setEdit] = useState<{ id: string; name: string; cur: number; next: string } | null>(null);
  const cap = (id: string, b: number) => caps[id] ?? b;
  const allocated = depts.reduce((a, d) => a + cap(d.id, d.budget), 0);
  const n = edit ? Number(edit.next) : 0, valid = !!edit && Number.isFinite(n) && n > 0;
  const spent = edit ? depts.find((d) => d.id === edit.id)!.spent : 0;
  return (
    <div style={cols("1.5fr 1fr")}>
      <Panel i={0} title="Department budgets" icon={Check} help="Monthly cap per department. A cap change needs confirmation and is recorded in the audit log. Caps shown here are local to this session (sample mode)."
        sub={`Allocated ${usd(allocated)} of ${usd(FINANCE.budget)}; reserve ${usd(FINANCE.budget - allocated)}`}>
        <table className="ax-table"><thead><tr><th>Department</th><th>Cap</th><th>Spent</th><th>Remaining</th><th>Usage</th><th /></tr></thead>
          <tbody>{depts.map((d, k) => { const c = cap(d.id, d.budget); return (
            <motion.tr key={d.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
              <td><span className="ax-flex"><Avatar role={d.role} size={18} />{d.name}</span></td><td className="ax-num">{usd(c)}{caps[d.id] != null && <Pill c="var(--ax-info)">changed</Pill>}</td><td className="ax-num">{usd(d.spent)}</td>
              <td className="ax-num">{usd(c - d.spent)}</td><td><UsageBar pct={d.spent / c * 100} label={`${d.name} usage`} /></td>
              <td><IconBtn icon={Pencil} label={`Adjust ${d.name} cap`} size="sm" tone="ghost" onClick={() => setEdit({ id: d.id, name: d.name, cur: c, next: String(c) })} /></td></motion.tr>); })}</tbody></table>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title="Budget rules" icon={Info} help="How budgets are enforced. These rules are policy, shown read-only here.">
          <div className="ax-rows ax-small">{["Hard cap: spending stops at 100% of a department cap until the owner raises it.", "Soft alert at the thresholds set in the Alerts tab.", "A cap increase above 10% needs owner approval (class A2).", "Agents cannot raise their own cap.", "Unallocated reserve is released only by the owner."].map((t) => <div key={t} className="ax-row"><Check size={13} style={{ color: "var(--ax-ok)" }} aria-hidden /><span className="grow" style={{ whiteSpace: "normal" }}>{t}</span></div>)}</div>
        </Panel>
        <CategoryPanel i={2} />
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={`Adjust ${edit?.name} monthly cap`} width={420}
        foot={<><Btn icon={X} onClick={() => setEdit(null)}>Cancel</Btn><Btn tone="gold" icon={Check} disabled={!valid || n < spent} onClick={() => { if (!edit) return; setCaps({ ...caps, [edit.id]: n }); toast(`Cap for ${edit.name}: ${usd(edit.cur)} to ${usd(n)}${n > edit.cur * 1.1 ? " (increase above 10%: would need owner approval)" : ""}. Sample mode: not saved to a server.`); setEdit(null); }}>Confirm change</Btn></>}>
        <label className="ax-small" htmlFor="cap-in">New monthly cap (USD)</label>
        <input id="cap-in" className="ax-input" type="number" min={1} value={edit?.next ?? ""} onChange={(e) => edit && setEdit({ ...edit, next: e.target.value })} aria-invalid={!!edit && (!valid || n < spent)} />
        <p className="ax-xs" style={{ color: edit && valid && n < spent ? "var(--ax-bad)" : "var(--ax-muted)" }}>{edit && valid && n < spent ? `A cap below current spend (${usd(spent)}) would freeze the department; choose a higher value.` : `Current cap ${edit ? usd(edit.cur) : ""}. Change is recorded in the audit log when a server is connected.`}</p>
      </Modal>
    </div>
  );
}

/* ---------- Usage ---------- */
export function UsageTab() {
  const models = useStore((s) => s.models), agents = useStore((s) => s.agents);
  const llm = Math.round(FINANCE.month * .42);
  const top = useMemo(() => [...agents].map((a) => ({ a, cost: a.costPerTask * a.tasksDone })).sort((x, y) => y.cost - x.cost).slice(0, 8), [agents]);
  return (
    <div style={cols("1.2fr 1fr")}>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1.2fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="Daily spend vs budget" icon={Info} help="Daily total cost over the last 30 days against the daily budget line.">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={SPEND_SERIES} margin={{ top: 4, right: 6, left: -16, bottom: 0 }}>
            <CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 4" vertical={false} /><XAxis dataKey="day" interval={4} tick={{ fill: "var(--ax-muted)", fontSize: 10 }} stroke="var(--ax-border)" /><YAxis tick={{ fill: "var(--ax-muted)", fontSize: 10 }} stroke="var(--ax-border)" />
            <Tooltip {...chartTip} formatter={(v: number) => [usd(v), "Spend"]} /><Bar dataKey="spend" radius={[3, 3, 0, 0]}>{SPEND_SERIES.map((p) => <Cell key={p.day} fill={p.spend > p.budget ? "var(--ax-bad)" : "var(--ax-info)"} />)}</Bar></BarChart></ResponsiveContainer>
        </Panel>
        <Panel i={1} title="Usage by model" icon={Info} help="LLM / API spend split across registered models. Shares, calls and tokens are sample values; real values come from the provider usage API.">
          <table className="ax-table"><thead><tr><th>Model</th><th>Provider</th><th>Calls</th><th>Tokens (M)</th><th>Cost</th><th>Share</th></tr></thead>
            <tbody>{models.map((m, k) => { const u = MODEL_USAGE[m.model] ?? { share: 0, calls: 0, tokensM: 0 }; return (
              <motion.tr key={m.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: m.enabled ? 1 : .5, x: 0 }} transition={{ delay: k * .03 }}>
                <td><b>{m.model}</b>{!m.enabled && <Pill c="var(--ax-neutral)">disabled</Pill>}</td><td className="ax-small">{m.provider}</td><td className="ax-num">{u.calls.toLocaleString()}</td><td className="ax-num">{u.tokensM}</td>
                <td className="ax-num">{usd(llm * u.share)}</td><td style={{ width: 90 }}><Progress value={u.share * 100} thin label={`${m.model} share`} /></td></motion.tr>); })}</tbody></table>
        </Panel>
      </div>
      <Panel i={2} title="Usage by agent" icon={Info} help="The eight agents with the highest estimated spend (cost per task x tasks done, sample estimate).">
        <table className="ax-table"><thead><tr><th>Agent</th><th>Tasks</th><th>$/task</th><th>Estimated spend</th></tr></thead>
          <tbody>{top.map(({ a, cost }, k) => (
            <motion.tr key={a.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
              <td><AgentTag id={a.id} size={20} sub={a.title} /></td><td className="ax-num">{a.tasksDone}</td><td className="ax-num">{usd(a.costPerTask, 2)}</td><td className="ax-num">{usd(cost)}</td></motion.tr>))}</tbody></table>
      </Panel>
    </div>
  );
}

/* ---------- Cost by mission ---------- */
export function MissionCostTab() {
  const missions = useStore((s) => s.missions).filter((m) => !m.archived);
  const rows = missions.map((m) => ({ m, u: m.budget.spent / m.budget.limit * 100, perPt: m.progress ? m.budget.spent / m.progress : 0, proj: m.progress ? m.budget.spent / m.progress * 100 : m.budget.limit })).sort((a, b) => b.m.budget.spent - a.m.budget.spent);
  const data = rows.map((r) => ({ name: r.m.id, spent: r.m.budget.spent, limit: r.m.budget.limit }));
  return (
    <div style={cols("1.7fr 1fr")}>
      <Panel i={0} title="Cost by Mission" icon={Info} help="Spend, budget and the projected total at completion if cost per point of progress stays the same. Projection is a straight-line estimate.">
        <table className="ax-table"><thead><tr><th>Mission</th><th>Progress</th><th>Spend</th><th>Budget</th><th>Usage</th><th>$ / progress pt</th><th>Projected at 100%</th></tr></thead>
          <tbody>{rows.map(({ m, u, perPt, proj }, k) => (
            <motion.tr key={m.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
              <td><b className="ax-small">{m.id}</b> <span className="ax-small">{m.title}</span></td><td className="ax-num">{m.progress}%</td><td className="ax-num">{usd(m.budget.spent)}</td><td className="ax-num">{usd(m.budget.limit)}</td>
              <td><UsageBar pct={u} label={`${m.title} usage`} /></td><td className="ax-num">{perPt ? usd(perPt, 2) : "n/a"}</td>
              <td className="ax-num" style={{ color: proj > m.budget.limit ? "var(--ax-bad)" : undefined }}>{usd(proj)} {proj > m.budget.limit && <Pill c="var(--ax-bad)" icon={AlertTriangle}>over budget</Pill>}</td></motion.tr>))}</tbody></table>
      </Panel>
      <Panel i={1} title="Spend vs budget" icon={Info} help="Per mission: spend so far (filled) against the mission budget.">
        <ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 4" horizontal={false} /><XAxis type="number" tick={{ fill: "var(--ax-muted)", fontSize: 10 }} stroke="var(--ax-border)" /><YAxis type="category" dataKey="name" width={44} tick={{ fill: "var(--ax-muted)", fontSize: 10 }} stroke="var(--ax-border)" />
          <Tooltip {...chartTip} formatter={(v: number, n: string) => [usd(v), n === "spent" ? "Spend" : "Budget"]} /><Bar dataKey="limit" fill="var(--ax-border)" radius={3} /><Bar dataKey="spent" fill="var(--ax-accent)" radius={3} /></BarChart></ResponsiveContainer>
      </Panel>
    </div>
  );
}

/* ---------- Alerts ---------- */
export function AlertsTab() {
  const depts = useStore((s) => s.departments), toast = useToast();
  const [rules, setRules] = useState(THRESHOLDS);
  const set = (id: string, p: Partial<(typeof THRESHOLDS)[number]>) => setRules((r) => r.map((x) => (x.id === id ? { ...x, ...p } : x)));
  const live = deriveAlerts(rules, depts).filter((a) => a.sev !== "Info").length;
  return (
    <div style={cols("1.2fr 1fr")}>
      <Panel i={0} title="Alert thresholds" icon={AlertTriangle} sub={`${live} active alerts with these thresholds`} help="When usage reaches the threshold, an alert is raised and the Finance agent proposes a fix. Changes apply to this session only (sample mode).">
        <table className="ax-table"><thead><tr><th>Scope</th><th>Alert at usage of</th><th>Enabled</th></tr></thead>
          <tbody>{rules.map((r) => (
            <tr key={r.id}><td>{r.scope}</td>
              <td><div className="ax-flex"><input type="range" min={50} max={150} step={5} value={r.pct} aria-label={`Threshold for ${r.scope}`} style={{ accentColor: usageColor(r.pct) }} onChange={(e) => set(r.id, { pct: +e.target.value })} /><span className="ax-num" style={{ width: 40 }}>{r.pct}%</span></div></td>
              <td><Switch label={`${r.on ? "Disable" : "Enable"} alert for ${r.scope}`} on={r.on} onChange={(v) => set(r.id, { on: v })} /></td></tr>))}</tbody></table>
        <div className="ax-flex" style={{ marginTop: 8 }}><Btn icon={Check} onClick={() => toast("Sample mode: thresholds are kept in this session only.")}>Save thresholds</Btn></div>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <AlertsPanel i={1} />
        <OptimPanel i={2} />
      </div>
    </div>
  );
}

/* ---------- Forecast ---------- */
export function ForecastTab() {
  const [sc, setSc] = useState<Scenario>("base");
  const p = useMemo(() => projection(30, sc), [sc]);
  const growth = 0.02, ratio = FINANCE.revenue * (1 + growth) / Math.max(1, FINANCE.opCost + (p.total - LAST30));
  const over = p.hi > FINANCE.budget;
  return (
    <div style={cols("1.5fr 1fr")}>
      <div style={{ display: "grid", gridTemplateRows: "1fr auto", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="30-day spend forecast" icon={Info} help="Projection of daily spend. The shaded band is a 90% uncertainty range under the model's assumptions; it is not a guarantee. Switch scenario to see sensitivity."
          actions={<Seg label="Scenario" value={sc} onChange={setSc} items={(Object.keys(SCENARIO) as Scenario[]).map((k) => ({ id: k, label: SCENARIO[k].label }))} />}>
          <TrendChart points={p.points} />
        </Panel>
        <Panel i={1} title="Result" icon={Info} help="Totals over the next 30 days under the selected scenario.">
          <div className="ax-kpis" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            {[["Expected", usd(p.total)], ["90% range", `${usd(p.lo)} to ${usd(p.hi)}`], ["vs last 30 days", `${((p.total / LAST30 - 1) * 100).toFixed(1)}% (${usd(LAST30)})`], ["Sustainability (fc)", `${ratio.toFixed(2)}x (now ${sustainability().toFixed(2)}x)`]].map(([l, v]) => (
              <div key={l} className="ax-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 0 }}><span className="ax-xs ax-muted">{l}</span><b className="ax-num">{v}</b></div>))}
          </div>
          <div className="ax-small" style={{ marginTop: 4, color: over ? "var(--ax-warn)" : "var(--ax-ok)" }}>{over ? <AlertTriangle size={12} aria-hidden /> : <Check size={12} aria-hidden />} {over ? `The upper end of the range (${usd(p.hi)}) exceeds the monthly budget (${usd(FINANCE.budget)}).` : `Even the upper end of the range stays within the monthly budget (${usd(FINANCE.budget)}).`}</div>
        </Panel>
      </div>
      <Panel i={2} title="Assumptions & uncertainty" icon={Info} help="Everything the forecast depends on. If any of these is wrong, treat the result with more caution.">
        <p className="ax-small" style={{ marginTop: 0 }}><b>{SCENARIO[sc].label}:</b> {SCENARIO[sc].why}</p>
        <div className="ax-small" style={{ display: "flex", flexDirection: "column", gap: 6 }}>{FORECAST_ASSUMPTIONS.map(([k, v]) => <div key={k}><b className="ax-muted">{k}</b><div>{v}</div></div>)}</div>
        <p className="ax-xs ax-faint">Level {usd(p.level)}/day; trend slope {p.slope >= 0 ? "+" : ""}{p.slope} $/day per day; residual spread ±{p.sigma} $/day. Forecast of a short, noisy series: expect it to be wrong in the details.</p>
      </Panel>
    </div>
  );
}

