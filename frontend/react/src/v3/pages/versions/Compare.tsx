import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, ArrowLeftRight, FlaskConical, Gauge as GaugeI, Minus, Plus, ScrollText } from "lucide-react";
import { IconBtn, Panel, Pill } from "../../ui/kit";
import type { Release } from "../../domain/types";
import { benchOf } from "./data";

const delta = (a: number, b: number, hb: boolean) => { const d = b - a; const good = hb ? d >= 0 : d <= 0; return { d, good, same: d === 0 }; };

export function CompareTab({ releases, initial }: { releases: Release[]; initial: string }) {
  const [b, setB] = useState(initial || releases[0].version); const [a, setA] = useState(() => { const i = releases.findIndex((r) => r.version === (initial || releases[0].version)); return (releases[i + 1] ?? releases[i - 1] ?? releases[0]).version; });
  const ra = releases.find((r) => r.version === a)!, rb = releases.find((r) => r.version === b)!;
  const added = rb.notes.filter((n) => !ra.notes.includes(n)), removed = ra.notes.filter((n) => !rb.notes.includes(n));
  const ba = useMemo(() => benchOf(a), [a]), bb = useMemo(() => benchOf(b), [b]);
  const sel = (v: string, on: (x: string) => void, l: string) => <select className="ax-select" style={{ width: 140 }} value={v} onChange={(e) => on(e.target.value)} aria-label={l}>{releases.map((r) => <option key={r.id} value={r.version}>{r.version}</option>)}</select>;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Compare" icon={ArrowLeftRight} help="Pick two editions: the differences in their release notes, test results and benchmarks. Green = improved, red = regressed."
        actions={<><span className="ax-flex">{sel(a, setA, "Base version")}<ArrowRight size={14} aria-hidden />{sel(b, setB, "Compared version")}</span><IconBtn icon={ArrowLeftRight} label="Swap versions" size="sm" onClick={() => { setA(b); setB(a); }} /></>}>
        <div className="ax-col" style={{ gap: 8 }}>
          <div className="ax-flex ax-small"><b>{a}</b><span className="ax-muted">{ra.status}</span><ArrowRight size={13} aria-hidden /><b>{b}</b><span className="ax-muted">{rb.status}</span></div>
          <div className="ax-kv"><span className="ax-muted">Branch</span><span className="ax-mono">{ra.branch} → {rb.branch}</span><span className="ax-muted">Commit</span><span className="ax-mono">{ra.commit} → {rb.commit}</span>
            <span className="ax-muted">Merged branches</span><span>{ra.mergedFrom.length} → {rb.mergedFrom.length}</span><span className="ax-muted">Author</span><span>{ra.author} → {rb.author}</span><span className="ax-muted">Security</span><span>{ra.security} → {rb.security}</span><span className="ax-muted">Artifacts</span><span>{ra.artifacts.length} → {rb.artifacts.length}</span><span className="ax-muted">Known issues</span><span>{ra.known.length} → {rb.known.length}</span></div>
          <div className="ax-small ax-muted">Sample data: the commit-level diff is not computed in this prototype.</div>
        </div>
      </Panel>
      <Panel i={1} title="Release notes diff" icon={ScrollText} help="Lines only in the newer edition are added (+); lines only in the older one are removed (−).">
        <div className="ax-col" style={{ gap: 5 }}>
          {added.map((n, i) => <motion.div key={n} className="ax-flex ax-small" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }} style={{ background: "color-mix(in srgb, var(--ax-ok) 12%, transparent)", padding: "4px 8px", borderRadius: 6 }}><Plus size={13} className="ax-ok" aria-label="added" />{n}</motion.div>)}
          {removed.map((n, i) => <motion.div key={n} className="ax-flex ax-small" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }} style={{ background: "color-mix(in srgb, var(--ax-bad) 12%, transparent)", padding: "4px 8px", borderRadius: 6 }}><Minus size={13} className="ax-bad" aria-label="removed" />{n}</motion.div>)}
          {!added.length && !removed.length && <span className="ax-muted ax-small">Identical release notes.</span>}
          {rb.fixes.filter((n) => !ra.fixes.includes(n)).map((n) => <div key={n} className="ax-flex ax-small" style={{ background: "color-mix(in srgb, var(--ax-ok) 12%, transparent)", padding: "4px 8px", borderRadius: 6 }}><Plus size={13} className="ax-ok" aria-label="added fix" />Fix: {n}</div>)}
          {rb.mergedFrom.filter((n) => !ra.mergedFrom.includes(n)).map((n) => <div key={n} className="ax-flex ax-small" style={{ background: "color-mix(in srgb, var(--ax-info) 12%, transparent)", padding: "4px 8px", borderRadius: 6 }}><Plus size={13} className="ax-info" aria-label="newly merged" />Merged branch {n}</div>)}
          <div className="ax-flex ax-small" style={{ marginTop: 6 }}><FlaskConical size={14} aria-hidden /><b>Tests</b><span className="ax-num">{ra.tests.passed}/{ra.tests.total}</span><ArrowRight size={12} aria-hidden /><span className="ax-num">{rb.tests.passed}/{rb.tests.total}</span>
            <Pill c={rb.tests.total - rb.tests.passed <= ra.tests.total - ra.tests.passed ? "var(--ax-ok)" : "var(--ax-bad)"}>{rb.tests.total - ra.tests.total >= 0 ? "+" : ""}{rb.tests.total - ra.tests.total} tests</Pill></div>
        </div>
      </Panel>
      <Panel i={2} title="Benchmarks" icon={GaugeI} help="Paired benchmark values of the two editions (sample values derived from the version string, for illustration).">
        <div className="ax-col" style={{ gap: 8 }}>
          {ba.map((m, i) => { const t = bb[i]; const d = delta(m.value, t.value, m.higherBetter); const c = d.same ? "var(--ax-neutral)" : d.good ? "var(--ax-ok)" : "var(--ax-bad)"; const max = Math.max(m.value, t.value) * 1.05;
            return (<div key={m.name}><div className="ax-flex ax-small"><b style={{ flex: 1 }}>{m.name}</b><span className="ax-num">{m.value}{m.unit}</span><ArrowRight size={11} aria-hidden /><b className="ax-num" style={{ color: c }}>{t.value}{m.unit}</b>
              <Pill c={c}>{d.same ? "no change" : `${d.d > 0 ? "+" : ""}${+d.d.toFixed(1)}${m.unit} ${d.good ? "better" : "worse"}`}</Pill></div>
              {[["a", m.value, "var(--ax-info)"], ["b", t.value, c]].map(([k, v, col]) => <div key={k as string} className="ax-bar thin" style={{ marginTop: 2 }}><motion.i initial={{ width: 0 }} animate={{ width: `${((v as number) / max) * 100}%` }} transition={{ duration: .7, delay: i * .06 }} style={{ background: col as string }} /></div>)}</div>); })}
        </div>
      </Panel>
    </div>
  );
}
