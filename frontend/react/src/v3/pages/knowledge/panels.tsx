import { useState } from "react";
import { motion } from "framer-motion";
import {
  Activity, BookOpen, Check, Code2, Database, ExternalLink, FileText, Fingerprint, GitBranch, Globe, Layers, Library, Network, Play, Plus, RefreshCw, Settings2, Target, Workflow, Quote,
} from "lucide-react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Btn, CopyBtn, IconBtn, Panel, Pill, Progress, Tabs, Time, useToast } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";
import { AgentTag, OrgTree } from "../../ui/widgets";
import { useStore } from "../../data/store";
import { sha } from "../../data/sample";
import { chartTip } from "../Overview";
import { go } from "../../app/router";
import { CITATIONS, EXTERNAL_SOURCES, ORG_MEMORY } from "./data";
import { KIND_C, KStatus } from "./shared";

const MEM_ICON = [Layers, Target, Workflow, Code2, Settings2, BookOpen];
export function OrgMemoryPanel({ i = 0 }: { i?: number }) {
  return (
    <Panel i={i} className="kn-mem" title="Organizational Memory" icon={Database} help="How much of each knowledge domain is indexed and verified. The whole company learns from this memory.">
      <div className="ax-rows">{ORG_MEMORY.map((r, k) => { const I = MEM_ICON[k]; return (
        <motion.div key={r.name} className="ax-row" style={{ padding: "1px 4px" }} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .05 }}>
          <span style={{ color: r.c, display: "inline-grid", width: 24, placeItems: "center" }}><I size={18} aria-hidden /></span>
          <span className="grow"><span className="t ax-small">{r.name}</span><span className="s">{r.sub}</span></span>
          <span className="ax-num ax-small" style={{ width: 46, textAlign: "right" }}>{r.n.toLocaleString()}</span>
          <span style={{ width: 96 }}><Progress value={r.pct} c1={r.c} c2={r.c} thin label={`${r.name} ${r.pct}%`} /></span><span className="ax-num ax-small" style={{ width: 36, textAlign: "right" }}>{r.pct}%</span>
        </motion.div>); })}</div>
    </Panel>
  );
}

export function AgentOrgPanel({ i = 0 }: { i?: number }) {
  const [t, setT] = useState("org");
  const depts = useStore((s) => s.departments), agents = useStore((s) => s.agents);
  const n = depts.length, R = 40;
  return (
    <Panel i={i} title="Agent Organization" icon={Network} help="The agents that learn from and contribute to company knowledge, by department."
      tabs={<Tabs label="Agent organization views" value={t} onChange={setT} tabs={[{ id: "org", label: "Org Chart" }, { id: "graph", label: "Agent Graph" }, { id: "depts", label: "Departments" }, { id: "perf", label: "Performance" }]} />}>
      {t === "org" && <OrgTree compact onSelect={(d) => go("organization", null, { dept: d })} />}
      {t === "graph" && (
        <svg viewBox="0 0 220 110" width="100%" height="100%" role="img" aria-label="Agent graph: GM linked to department heads">
          {depts.map((d, k) => { const a = (Math.PI * 2 * k) / n - Math.PI / 2, x = 110 + Math.cos(a) * R * 2, y = 55 + Math.sin(a) * R; return (
            <g key={d.id}><line x1="110" y1="55" x2={x} y2={y} stroke="var(--ax-accent2)" strokeWidth=".8" className="ax-flow-dash" />
              <motion.circle cx={x} cy={y} r="9" fill="var(--ax-panel2)" stroke="var(--ax-accent2)" style={{ transformBox: "fill-box", transformOrigin: "center" }} initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: k * .06 }} />
              <text x={x} y={y + 3} textAnchor="middle" fontSize="6" fill="var(--ax-text)">{d.head.split("-")[0]}</text></g>); })}
          <circle cx="110" cy="55" r="13" fill="var(--ax-accent)" /><text x="110" y="58" textAnchor="middle" fontSize="8" fontWeight="700" fill="var(--ax-on-accent)">GM</text>
        </svg>)}
      {t === "depts" && <table className="ax-table"><thead><tr><th>Department</th><th>Agents</th><th>Knowledge contributions</th></tr></thead>
        <tbody>{depts.map((d, k) => <tr key={d.id}><td><span className="ax-flex"><Avatar role={d.role} size={18} animate={false} />{d.name}</span></td><td className="ax-num">{agents.filter((a) => a.dept === d.id).length}</td><td className="ax-num">{120 + k * 37} items</td></tr>)}</tbody></table>}
      {t === "perf" && <ResponsiveContainer width="100%" height="100%"><BarChart data={depts.map((d) => ({ name: d.name.split(" ")[0], v: d.performance }))} margin={{ top: 6, right: 4, left: -22, bottom: 0 }}>
        <XAxis dataKey="name" tick={{ fill: "var(--ax-muted)", fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis domain={[85, 100]} tick={{ fill: "var(--ax-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
        <Tooltip {...chartTip} formatter={(v: number) => [`${v}%`, "Verified success"]} /><Bar dataKey="v" radius={[5, 5, 0, 0]}>{depts.map((d, k) => <Cell key={d.id} fill={["#22d3ee", "#3b8cff", "#94a3b8", "#2fd27a", "#a77bff", "#fbbf24", "#fb7185"][k]} />)}</Bar></BarChart></ResponsiveContainer>}
    </Panel>
  );
}

export function ExternalPanel({ i = 0, onAdd }: { i?: number; onAdd: () => void }) {
  const toast = useToast();
  return (
    <Panel i={i} className="kn-ext" title="External Research & Sources" icon={Globe} help="Pages and papers agents used while researching. External content is untrusted until verified; cite counts show how often it was used."
      actions={<><IconBtn icon={Plus} label="Add a source" size="sm" onClick={onAdd} /><IconBtn icon={RefreshCw} label="Refresh (sample: simulated)" size="sm" onClick={() => toast("Sample mode: nothing was fetched.")} /></>}>
      <div className="ax-rows">{EXTERNAL_SOURCES.map((s, k) => (
        <motion.div key={s.url} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .05 }}>
          <span style={{ width: 24, height: 24, borderRadius: 6, display: "inline-grid", placeItems: "center", background: s.c, color: "#fff", fontWeight: 800, fontSize: 12, flex: "none" }} aria-hidden>{s.mark}</span>
          <span className="grow"><span className="t ax-small">{s.name}</span><span className="s">{s.url}</span></span>
          <Pill c="var(--ax-accent2)" icon={Quote}>{s.cites}</Pill>
          <IconBtn icon={Play} label={`Open ${s.name} (sample, not a live link)`} size="sm" onClick={() => toast("Sample source: the link is illustrative.")} />
        </motion.div>))}</div>
    </Panel>
  );
}

const TOPICS = [["Agent Architecture", "#a77bff"], ["Evaluation", "#2fd27a"], ["Operations", "#22d3ee"], ["Product & R&D", "#3b8cff"], ["Cost Optimization", "#f2b53a"], ["Governance", "#fb7185"], ["Multi-Agent", "#3b8cff"], ["Self-Evolution", "#22d3ee"]] as const;
export function GraphPanel({ i = 0, onTopic }: { i?: number; onTopic: (t: string) => void }) {
  return (
    <Panel i={i} title="Knowledge Graph & Related Topics" icon={Network} help="How knowledge areas connect around the company memory. Click a topic to filter the library.">
      <svg viewBox="0 0 320 190" width="100%" height="100%" role="group" aria-label="Knowledge graph">
        {TOPICS.map(([t, c], k) => { const a = (Math.PI * 2 * k) / TOPICS.length - Math.PI / 2 + Math.PI / 8, x = 160 + Math.cos(a) * 120, y = 95 + Math.sin(a) * 68; return (
          <g key={t} role="button" tabIndex={0} aria-label={`Filter library by ${t}`} style={{ cursor: "pointer" }} onClick={() => onTopic(t)} onKeyDown={(e) => e.key === "Enter" && onTopic(t)}>
            <line x1="160" y1="95" x2={x} y2={y} stroke={c} strokeWidth="1.2" strokeDasharray="4 3" className="ax-flow-dash" />
            <motion.rect x={x - 38} y={y - 9} width="76" height="18" rx="9" fill="var(--ax-panel2)" stroke={c} initial={{ opacity: 0, scale: .6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: .1 + k * .07, type: "spring" }} whileHover={{ scale: 1.08 }} style={{ transformOrigin: `${x}px ${y}px` }} />
            <text x={x} y={y + 3} textAnchor="middle" fontSize="8.5" fill="var(--ax-text)" pointerEvents="none">{t}</text></g>); })}
        <motion.circle cx="160" cy="95" r="30" fill="var(--ax-panel2)" stroke="var(--ax-accent)" strokeWidth="2" style={{ transformBox: "fill-box", transformOrigin: "center" }} animate={{ scale: [1, 1.100, 1] }} transition={{ duration: 3, repeat: Infinity }} />
        <text x="160" y="92" textAnchor="middle" fontSize="9" fontWeight="700" fill="var(--ax-text)">AXoR</text><text x="160" y="103" textAnchor="middle" fontSize="8" fill="var(--ax-text)">Knowledge</text>
      </svg>
    </Panel>
  );
}

export function DetailPanel({ id, setSel, i = 0 }: { id: string; setSel: (id: string) => void; i?: number }) {
  const items = useStore((s) => s.knowledge), missions = useStore((s) => s.missions), toast = useToast();
  const k = items.find((x) => x.id === id) ?? items[0];
  if (!k) return null;
  const ix = items.indexOf(k), cit = CITATIONS[ix % CITATIONS.length];
  const used = missions.slice(ix % 3, (ix % 3) + 4);
  const related = [...items.filter((x) => x.id !== k.id && x.tags.some((t) => k.tags.includes(t))), ...items.filter((x) => x.id !== k.id)].slice(0, 3);
  const hash = sha(k.id + k.title, 8) + "..." + sha(k.title, 4);
  const ver = `v${1 + (ix % 3)}.${ix % 5}.0`;
  const Sec = ({ t, n, children }: { t: string; n?: number; children: React.ReactNode }) => <section aria-label={t}><h3 className="ax-small" style={{ margin: "0 0 4px", display: "flex", gap: 6 }}><b>{t}{n != null && ` (${n})`}</b></h3>{children}</section>;
  return (
    <Panel i={i} area="detail" title="Knowledge Detail" icon={BookOpen} help="Provenance and use of the selected item: where it came from, which missions rely on it, and related knowledge.">
      <motion.div key={k.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <div className="ax-flex" style={{ alignItems: "flex-start" }}><FileTile kind={k.kind} /><div style={{ minWidth: 0 }}><b>{k.title} ({ver})</b>
          <div className="ax-flex" style={{ flexWrap: "wrap", gap: 5, marginTop: 3 }}><Pill c={KIND_C[k.kind]}>{k.kind}</Pill><span className="ax-xs ax-muted">ID: {k.id}</span><KStatus s={k.status} /></div></div></div>
        <p className="ax-xs ax-muted" style={{ margin: 0 }}>A {k.kind} about {k.tags.join(", ")}: {k.citations} citations, {Math.round(k.confidence * 100)}% confidence, owned by {k.owner}. Sample description.</p>
        <Sec t="Provenance">
          <dl className="ax-small" style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr auto", gap: "3px 10px", alignItems: "center" }}>
            <dt className="ax-muted"><Globe size={12} aria-hidden /> Source</dt><dd style={{ margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cit.source} ({cit.url.replace(/^https?:\/\//, "").slice(0, 26)})</dd><dd style={{ margin: 0 }}><IconBtn icon={ExternalLink} label="Open source (sample link)" size="sm" tone="ghost" onClick={() => toast("Sample provenance: not a live link.")} /></dd>
            <dt className="ax-muted"><FileText size={12} aria-hidden /> Imported</dt><dd style={{ margin: 0 }}><Time iso={k.updated} withDate /> (by {k.owner})</dd><dd />
            <dt className="ax-muted"><GitBranch size={12} aria-hidden /> Version</dt><dd style={{ margin: 0 }}>{ver} (derived from v{1 + (ix % 3)}.{Math.max(0, ix % 5 - 1)}.0)</dd><dd />
            <dt className="ax-muted"><Fingerprint size={12} aria-hidden /> Content Hash</dt><dd className="ax-num" style={{ margin: 0 }}>{hash}</dd><dd style={{ margin: 0 }}><CopyBtn text={hash} label="Copy content hash" /></dd>
          </dl>
        </Sec>
        <Sec t="Used By Missions" n={used.length}>
          <div className="ax-rows">{used.map((m) => <div key={m.id} className="ax-row" style={{ padding: "1px 4px" }}><Target size={13} style={{ color: "var(--ax-accent)" }} aria-hidden /><span className="grow ax-small t">{m.title}</span><span className="ax-xs ax-muted">{m.version}</span><Check size={14} style={{ color: "var(--ax-ok)" }} aria-label="In use" /></div>)}</div>
        </Sec>
        <Sec t="Related Knowledge">
          <div className="ax-rows">{related.map((r) => <button key={r.id} type="button" className="ax-row click" style={{ width: "100%", background: "none", font: "inherit", color: "inherit", textAlign: "left", padding: "1px 4px" }} onClick={() => setSel(r.id)}>
            <Library size={13} style={{ color: "var(--ax-accent2)" }} aria-hidden /><span className="grow ax-small t">{r.title}</span><span className="ax-xs ax-faint">[{r.id}]</span></button>)}</div>
        </Sec>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginTop: "auto", position: "sticky", bottom: 0, background: "var(--ax-panel)", paddingTop: 4 }}>
          <Btn tone="gold" icon={Play} style={{ padding: "7px 4px", fontSize: 12 }} onClick={() => toast("Sample mode: the full item viewer is not connected.")}>Open</Btn>
          <Btn icon={GitBranch} style={{ padding: "7px 4px", fontSize: 12 }} onClick={() => go("missions")}>Use in Mission</Btn>
          <Btn icon={Library} style={{ padding: "7px 4px", fontSize: 12 }} disabled={k.status !== "verified"} onClick={() => toast("Already part of the library.")}>Add to Library</Btn>
        </div>
      </motion.div>
    </Panel>
  );
}
function FileTile({ kind }: { kind: string }) { return <span style={{ width: 28, height: 32, borderRadius: 6, display: "inline-grid", placeItems: "center", background: "color-mix(in srgb, " + (KIND_C[kind] ?? "#888") + " 25%, transparent)", color: KIND_C[kind], flex: "none" }}><FileText size={16} aria-hidden /></span>; }

/* ---------- Lessons Learned tab ---------- */
export function LessonsTab() {
  const xp = useStore((s) => s.experiences), items = useStore((s) => s.knowledge);
  const lessons = items.filter((k) => k.kind === "lesson");
  const KC: Record<string, string> = { verified: "var(--ax-ok)", tentative: "var(--ax-warn)", code: "var(--ax-info)", security: "var(--ax-bad)", private: "var(--ax-neutral)" };
  return (
    <div style={{ overflow: "auto", height: "100%", display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
      <div><h3 className="ax-small ax-muted" style={{ margin: "0 0 4px" }}>Lessons from mission work (retros, failures, optimizations)</h3>
        <table className="ax-table"><thead><tr><th>Lesson</th><th>Agent</th><th>Mission</th><th>Kind</th><th>Confidence</th><th>Shared with company</th></tr></thead>
          <tbody>{xp.map((x, k) => (
            <motion.tr key={x.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
              <td><b className="ax-small">{x.lesson}</b><span className="ax-xs ax-faint" style={{ display: "block" }}>Evidence: {x.evidence}</span></td><td><AgentTag id={x.agentId} size={18} /></td><td className="ax-small">{x.missionId}</td>
              <td><Pill c={KC[x.kind]}>{x.kind}</Pill></td><td style={{ width: 90 }}><Progress value={x.confidence * 100} thin label={`${Math.round(x.confidence * 100)}%`} /></td>
              <td>{x.eligible ? <Pill c="var(--ax-ok)" icon={Check}>Eligible</Pill> : <Pill c="var(--ax-neutral)">Held back</Pill>}</td></motion.tr>))}</tbody></table></div>
      <div><h3 className="ax-small ax-muted" style={{ margin: "0 0 4px" }}>Lessons already in the library</h3>
        <div className="ax-rows">{lessons.map((l) => <div key={l.id} className="ax-row"><Activity size={13} style={{ color: "var(--ax-warn)" }} aria-hidden /><span className="grow t ax-small">{l.title}</span><KStatus s={l.status} label={l.status} /></div>)}</div>
        <p className="ax-xs ax-faint">Private mission material and unverified lessons are never shared company-wide (AG-004).</p></div>
    </div>
  );
}

