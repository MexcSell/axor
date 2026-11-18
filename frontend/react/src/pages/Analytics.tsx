import { useState } from "react";
import { getJSON } from "../http";
import { useLoad } from "../useLoad";
import { Head, Loaded, Panel, tok } from "../ui";

// Moved from the classic front end (analytics.js, AXoR 5.0) unchanged in content: GET /api/analytics?days=N
type Period = { per_validated: number | null; validated: number; tokens: number; usd: number; usd_per_validated: number | null;
  ledger: { runs: number; done: number; failed: number; validated: number }; missions: { verified: number } };
type Score = { name: string; want: string; value: string | number | null; detail: string; state: "ok" | "weak" | "none" };
type Sys = { label: string; runs: number; success: number | null; avg_score: number | null; validated: number; tokens: number; per_validated: number | null; secs: number | null };
type Agent = { name: string; system: string; runs: number; success: number | null; avg_score: number | null; validated: number; tokens: number; per_validated: number | null };
type Day = { day: string; tokens: number; validated: number };
type A = { days: number; valid: number; current: Period; previous: Period; trend: number | null; scorecard: Score[]; series: Day[];
  systems: Sys[]; agents: Agent[]; errors: string[] };

const STATE = { ok: ["on", "On track"], weak: ["warn", "Needs work"], none: ["off", "No data"] } as const;
const SYSTEMS: Record<string, string> = { hub: "Your agents", builtin: "Built-in", workforce: "Workforce", company: "Company", teams: "Competition teams",
  workflow: "Workflow", hq: "Agent HQ", missions: "Mission Control", longtask: "Long tasks", team: "Project team" };

function readDays() { try { return Number(localStorage.getItem("g5.days")) || 30; } catch { return 30; } }

export default function Analytics() {
  const [days, setDays] = useState(readDays);
  const { load, reload } = useLoad((s) => getJSON<A>(`/api/analytics?days=${days}`, s), 0, [days]);
  const pick = (n: number) => { setDays(n); try { localStorage.setItem("g5.days", String(n)); } catch { /* private window */ } };
  return (
    <>
      <Head kicker="Analytics · moved to React" title="Analytics"
        lede="Performance, cost and intelligence across every agent system. The number that matters: what one successfully validated deliverable costs. It should fall as AXoR learns, not rise with more tokens or more agents."
        actions={<div className="chips" role="group" aria-label="Period">{[7, 30, 90].map((n) => (
          <button key={n} type="button" className="chip" aria-pressed={days === n} onClick={() => pick(n)}>{n} days</button>))}</div>} />
      <Loaded load={load} retry={() => reload()}>{(d) => <Body d={d} />}</Loaded>
    </>
  );
}

function Kpi({ label, value, note, tone = "" }: { label: string; value: string | number; note: string; tone?: string }) {
  return <div className={`kpi ${tone}`}><span className="kpi-label">{label}</span><strong className="num">{value}</strong><span className="muted small">{note}</span></div>;
}

function Columns({ series, k, label, fmt }: { series: Day[]; k: "tokens" | "validated"; label: string; fmt: (n: number) => string }) {
  const max = Math.max(0, ...series.map((s) => s[k]));
  if (!max) return <p className="muted">No {label.toLowerCase()} in this period.</p>;
  const step = Math.max(1, Math.ceil(series.length / 6));
  return (
    <>
      <div className="cols" role="img" aria-label={`${label} per day`}>
        {series.map((s, i) => (
          <span key={s.day} className="col" title={`${s.day}: ${fmt(s[k])} ${label.toLowerCase()}`}>
            <i style={{ height: s[k] ? `${Math.max(2, (s[k] / max) * 100).toFixed(1)}%` : 0 }} />
            {i % step === 0 && <small>{s.day.slice(5)}</small>}
          </span>
        ))}
      </div>
      <p className="muted small">Peak {fmt(max)} · {series.length} days</p>
    </>
  );
}

function Body({ d }: { d: A }) {
  const c = d.current, p = d.previous;
  const trend = d.trend == null ? "no earlier period to compare" : `${d.trend > 0 ? "+" : ""}${d.trend}% vs the previous ${d.days} days`;
  const okPct = c.ledger.runs ? Math.round((100 * c.ledger.done) / c.ledger.runs) : null;
  return (
    <>
      <section className="kpis">
        <Kpi label="Cost per validated deliverable" value={c.per_validated ? `${tok(c.per_validated)} tok` : "–"}
          note={c.per_validated ? trend : "nothing validated in this period"} tone={d.trend && d.trend > 0 ? "warn" : d.trend && d.trend < 0 ? "good" : ""} />
        <Kpi label="Validated deliverables" value={c.validated} note={`${c.ledger.validated} scored ${d.valid}+ · ${c.missions.verified} verified missions`} />
        <Kpi label="Tokens" value={tok(c.tokens)} note={`previous period ${tok(p.tokens)}`} />
        <Kpi label="Runs finished" value={c.ledger.runs} note={okPct == null ? "–" : `${okPct}% done · ${c.ledger.failed} failed`} tone={c.ledger.failed > c.ledger.done ? "warn" : ""} />
        {c.usd ? <Kpi label="Reported spend" value={`$${c.usd.toFixed(2)}`} note={c.usd_per_validated ? `$${c.usd_per_validated.toFixed(3)} per validated deliverable` : "where systems report dollars"} /> : null}
      </section>
      <Panel title="Generation 5 scorecard" note="measured, never assumed">
        <div className="tablewrap"><table>
          <thead><tr><th>Measurement</th><th className="hide-narrow">Desired capability</th><th className="r">Value</th><th className="hide-narrow">Evidence</th><th>State</th></tr></thead>
          <tbody>{d.scorecard.map((r) => (
            <tr key={r.name}><td><b>{r.name}</b></td><td className="muted hide-narrow">{r.want}</td><td className="r num">{r.value ?? "–"}</td>
              <td className="muted hide-narrow">{r.detail}</td><td><span className={`badge ${STATE[r.state][0]}`}>{STATE[r.state][1]}</span></td></tr>))}</tbody>
        </table></div>
      </Panel>
      <div className="two">
        <Panel title="Tokens per day"><Columns series={d.series} k="tokens" label="Tokens" fmt={tok} /></Panel>
        <Panel title="Validated deliverables per day"><Columns series={d.series} k="validated" label="Validated" fmt={String} /></Panel>
      </div>
      <Panel title="By system" note={`the run ledger, ${d.days} days`}>
        {!d.systems.length ? <p className="muted">No run recorded in this period.</p> : (
          <div className="tablewrap"><table>
            <thead><tr><th>System</th><th className="r">Runs</th><th className="r">Done</th><th className="r">Avg score</th><th className="r">Validated</th><th className="r">Tokens</th><th className="r hide-narrow">Tokens / validated</th><th className="r hide-narrow">Avg time</th></tr></thead>
            <tbody>{d.systems.map((s) => (
              <tr key={s.label}><td>{s.label}</td><td className="r num">{s.runs}</td><td className="r num">{s.success ?? "–"}%</td><td className="r num">{s.avg_score ?? "–"}</td>
                <td className="r num">{s.validated}</td><td className="r num">{tok(s.tokens)}</td><td className="r num hide-narrow">{s.per_validated ? tok(s.per_validated) : "–"}</td>
                <td className="r num hide-narrow">{s.secs ? `${s.secs}s` : "–"}</td></tr>))}</tbody>
          </table></div>)}
      </Panel>
      <Panel title="Agents" note="the 40 that used the most tokens">
        {!d.agents.length ? <p className="muted">No agent run recorded in this period.</p> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Agent</th><th className="hide-narrow">System</th><th className="r">Runs</th><th className="r">Done</th><th className="r hide-narrow">Avg score</th><th className="r">Validated</th><th className="r">Tokens</th><th className="r hide-narrow">Tokens / validated</th></tr></thead>
            <tbody>{d.agents.map((a, i) => (
              <tr key={`${a.name}-${i}`}><td>{a.name}</td><td className="muted hide-narrow">{SYSTEMS[a.system] ?? a.system}</td><td className="r num">{a.runs}</td>
                <td className="r num">{a.success ?? "–"}%</td><td className="r num hide-narrow">{a.avg_score ?? "–"}</td><td className="r num">{a.validated}</td>
                <td className="r num">{tok(a.tokens)}</td><td className="r num hide-narrow">{a.per_validated ? tok(a.per_validated) : "–"}</td></tr>))}</tbody>
          </table></div>)}
      </Panel>
      <p className="muted small">A deliverable counts as validated only when something other than its author checked it: a run an evaluator or verifier scored {d.valid} or more, or a mission whose independent reviewer found every criterion met. Tokens count every run in the period, so wasted work raises the cost.</p>
      {d.errors.length > 0 && <p className="muted small">{d.errors.join(" · ")}</p>}
    </>
  );
}
