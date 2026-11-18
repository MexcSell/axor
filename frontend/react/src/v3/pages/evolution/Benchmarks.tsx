import { motion } from "framer-motion";
import { ArrowRight, BarChart3, ShieldAlert, ShieldCheck, TrendingDown } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel, Pill } from "../../ui/kit";
import { useStore } from "../../data/store";
import { chartTip } from "../Overview";
import { CandPill, change, isSecurity, vetoOf } from "./shared";

export function BenchmarksTab({ sel, onSel }: { sel: string; onSel: (id: string) => void }) {
  const cands = useStore((s) => s.candidates); const c = cands.find((x) => x.id === sel) ?? cands[0];
  const veto = vetoOf(c); const regs = c.metrics.filter((m) => change(m).regression);
  const data = c.metrics.filter((m) => m.base > 0).map((m) => ({ name: m.name, Baseline: 100, Candidate: +((m.cand / m.base) * 100).toFixed(1), bad: change(m).regression }));
  const verdict = veto ? ["Vetoed: security regression", "var(--ax-bad)"] : regs.length ? [`Mixed: ${regs.length} regression(s)`, "var(--ax-warn)"] : c.delta > 0 ? ["Better than baseline", "var(--ax-ok)"] : ["Not better", "var(--ax-bad)"];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "52fr 48fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title={`Paired benchmark — ${c.from} (baseline) → ${c.to} (candidate)`} icon={BarChart3} help="Baseline and candidate are run on the same tasks. A metric that got worse (direction-aware: lower build time is better) is red. A security regression vetoes the candidate regardless of its other gains."
        actions={<select className="ax-select" style={{ width: 230 }} value={c.id} onChange={(e) => onSel(e.target.value)} aria-label="Candidate">{cands.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.title}</option>)}</select>}>
        <table className="ax-table"><thead><tr><th>Metric</th><th>Baseline</th><th /><th>Candidate</th><th>Change</th><th>Result</th></tr></thead>
          <tbody>{c.metrics.map((m, i) => { const ch = change(m); const col = ch.same ? "var(--ax-neutral)" : ch.better ? "var(--ax-ok)" : "var(--ax-bad)"; const sec = isSecurity(m.name);
            return (<motion.tr key={m.name} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .06 }} style={ch.regression ? { background: "color-mix(in srgb, var(--ax-bad) 10%, transparent)" } : undefined}>
              <td><b className="ax-small">{m.name}</b>{sec && <ShieldCheck size={12} className="ax-gold" style={{ marginLeft: 4 }} aria-label="security metric" />}<div className="ax-xs ax-muted">{m.higherBetter ? "higher is better" : "lower is better"}</div></td>
              <td className="ax-num">{m.unit === "$" ? "$" : ""}{m.base}{m.unit !== "$" ? m.unit : ""}</td><td><ArrowRight size={12} aria-hidden /></td>
              <td className="ax-num"><b style={{ color: col }}>{m.unit === "$" ? "$" : ""}{m.cand}{m.unit !== "$" ? m.unit : ""}</b></td>
              <td className="ax-num" style={{ color: col }}>{ch.same ? "±0" : `${ch.pct > 0 ? "+" : ""}${ch.pct.toFixed(1)}%`}</td>
              <td>{ch.same ? <Pill c="var(--ax-neutral)">no change</Pill> : ch.better ? <Pill c="var(--ax-ok)">better</Pill> : <Pill c="var(--ax-bad)" icon={TrendingDown} solid>regression</Pill>}</td></motion.tr>); })}</tbody></table>
        <div className="ax-grid2" style={{ marginTop: 10 }}>
          <div className="ax-tile ax-small"><b>Evaluation protocol</b><div className="ax-muted">Same 240 tasks, 3 runs each, baseline and candidate in fresh isolated instances; the verifier never saw the candidate's author notes (sample).</div></div>
          <div className="ax-tile ax-small"><b>Regressions</b><div className={regs.length ? "ax-bad" : "ax-ok"}>{regs.length ? regs.map((m) => m.name).join(", ") : "None: no metric got worse"}</div></div>
        </div>
        <div className="ax-flex" style={{ marginTop: 8, flexWrap: "wrap" }}><b className="ax-small">Verdict:</b><Pill c={verdict[1]} solid icon={veto ? ShieldAlert : undefined}>{verdict[0]}</Pill><CandPill s={c.status} /><span className="ax-small ax-muted">Verifier {c.evaluator} (independent of {c.agentId})</span></div>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr auto", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title="Baseline vs candidate (baseline = 100%)" icon={BarChart3} help="Each metric normalised to the baseline. Red bars are regressions; for 'lower is better' metrics a bar below 100 is an improvement.">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
            <CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" tick={{ fill: "var(--ax-muted)", fontSize: 10 }} /><YAxis tick={{ fill: "var(--ax-muted)", fontSize: 10 }} domain={[0, "dataMax + 10"]} />
            <Tooltip {...chartTip} /><Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="Baseline" fill="var(--ax-info)" radius={[4, 4, 0, 0]} isAnimationActive />
            <Bar dataKey="Candidate" fill="var(--ax-accent2)" radius={[4, 4, 0, 0]}>{data.map((d) => <Cell key={d.name} fill={d.bad ? "var(--ax-bad)" : "var(--ax-accent2)"} />)}</Bar></BarChart></ResponsiveContainer>
        </Panel>
        <Panel i={2} title="Security veto" icon={ShieldAlert} help="Security findings must not increase. Any new finding vetoes promotion, independent of benchmark gains." hl={veto}>
          {veto ? <div className="ax-bad ax-small"><b>Veto active:</b> security findings increased. Promotion is blocked until fixed.</div> : <div className="ax-small ax-ok ax-flex"><ShieldCheck size={15} aria-hidden /><b>No veto:</b> security findings did not increase ({c.metrics.find((m) => isSecurity(m.name))?.cand ?? 0} new).</div>}
        </Panel>
      </div>
    </div>
  );
}
