import { useState } from "react";
import { motion } from "framer-motion";
import { Bot, CheckCircle2, Copy, Download, FileJson, GitBranch, GitMerge, Layers, Package, Play, Plus, RotateCcw, Rocket, Settings, ShieldCheck, Tag, FlaskConical, GitCommit, Maximize2, Eye, Star, Network } from "lucide-react";
import { Avatar, type Role } from "../../ui/Avatar";
import { IconBtn, Panel, Pill, Seg, Time, useToast, Btn } from "../../ui/kit";
import type { Branch, MergeRequest, Release } from "../../domain/types";
import { COMMITS, benchOf } from "./data";
import { MockSite } from "./Preview";
import { REL_C, useDownload } from "./Releases";

// Default "Versions" tab: the 30-6 dashboard. All values are SAMPLE data (lanes mirror the reference mockup).
const PUR = "#c084fc", CY = "#22d3ee", GD = "#f2b53a";
interface Lane { name: string; sub?: string; y: number; c: string; from: 0 | 1 }
const LANES: Lane[] = [
  { name: "feature/ai-eval", sub: "(v1.4.0)", y: 22, c: PUR, from: 0 }, { name: "feature/ux-redesign", sub: "(v1.4.0)", y: 56, c: PUR, from: 0 }, { name: "feature/self-evolution", sub: "(v1.3.1)", y: 90, c: GD, from: 0 },
  { name: "agent/research", sub: "(RCH-01)", y: 212, c: CY, from: 0 }, { name: "agent/dev", sub: "(DEV-01)", y: 246, c: CY, from: 0 }, { name: "agent/qa", sub: "(QA-01)", y: 280, c: "#2fd27a", from: 0 },
  { name: "feature/knw-integration", y: 22, c: PUR, from: 1 }, { name: "agent/ops", sub: "(OPS-01)", y: 62, c: CY, from: 1 }, { name: "agent/fin", sub: "(FIN-01)", y: 102, c: CY, from: 1 },
  { name: "agent/deploy", sub: "(DEP-01)", y: 205, c: CY, from: 1 }, { name: "self-evolution/auto-opt", sub: "(v2.4.0)", y: 250, c: GD, from: 1 },
];
const MID = 152, X = [40, 450, 830];

function DashGraph({ cur }: { cur: string }) {
  return (
    <svg viewBox="0 0 900 322" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Branch graph: main, feature, agent and self-evolution lanes merging into releases" style={{ minHeight: 0 }}>
      <motion.path d={`M${X[0]} ${MID} L${X[1]} ${MID} L${X[2]} ${MID}`} stroke="var(--ax-ok)" strokeWidth="3.5" fill="none" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1 }} />
      {LANES.map((l, i) => {
        const sx = X[l.from], dx = X[l.from + 1], label = l.name + (l.sub ? " " + l.sub : ""), w = label.length * 5.9 + 12;
        const n = Math.max(2, Math.floor((dx - sx - 190 - w) / 52));
        return (
          <g key={l.name}>
            <motion.path d={`M${sx} ${MID} C${sx + 50} ${MID}, ${sx + 35} ${l.y}, ${sx + 90} ${l.y} L${dx - 90} ${l.y} C${dx - 35} ${l.y}, ${dx - 50} ${MID}, ${dx} ${MID}`} fill="none" stroke={l.c} strokeWidth="2.4" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: .9, delay: .05 * i }} />
            {Array.from({ length: n }).map((_, k) => <motion.circle key={k} cx={sx + 100 + w + 12 + k * ((dx - sx - 220 - w) / n)} cy={l.y} r="4" fill="var(--ax-panel2)" stroke={l.c} strokeWidth="2" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .5 + .06 * k + .04 * i }} />)}
            <rect x={sx + 96} y={l.y - 18} width={w} height="16" rx="8" fill={`color-mix(in srgb, ${l.c} 30%, var(--ax-panel2))`} stroke={l.c} />
            <text x={sx + 102} y={l.y - 6.5} fontSize="10.5" fill="var(--ax-text)">{l.name}{l.sub && <tspan fill="var(--ax-muted)"> {l.sub}</tspan>}</text>
          </g>);
      })}
      <circle cx={X[0]} cy={MID} r="13" fill="var(--ax-panel2)" stroke="var(--ax-info)" strokeWidth="3" /><circle cx={X[0]} cy={MID} r="5" fill="var(--ax-info)" />
      <rect x="10" y={MID + 22} width="62" height="48" rx="8" fill="var(--ax-panel2)" stroke="var(--ax-border)" /><text x="41" y={MID + 40} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--ax-text)">main</text>
      <text x="41" y={MID + 53} textAnchor="middle" fontSize="9" fill="var(--ax-muted)">(v1.5.0)</text><text x="41" y={MID + 64} textAnchor="middle" fontSize="8" fill="var(--ax-muted)">Base Stem (LTS)</text>
      {[[395, 30, "#312"], [745, 84, "#318"]].map(([x, y, n]) => (
        <g key={n as string}><rect x={(x as number) - 25} y={(y as number) - 12} width="50" height="26" rx="6" fill="var(--ax-panel2)" stroke="var(--ax-ok)" /><text x={x as number} y={(y as number) - 1} textAnchor="middle" fontSize="9" fill="var(--ax-text)" fontWeight="700">Merge</text><text x={x as number} y={(y as number) + 9} textAnchor="middle" fontSize="9" fill="var(--ax-text)">{n as string}</text>
          <circle cx={(x as number) + 24} cy={(y as number) + 14} r="8" fill="var(--ax-panel2)" stroke="var(--ax-ok)" strokeWidth="2" /><text x={(x as number) + 24} y={(y as number) + 18} textAnchor="middle" fontSize="10" fill="var(--ax-ok)" fontWeight="800">✓</text></g>))}
      {[[X[1], "v2.3.0", "Release"], [X[2], "v2.4.0", "Release (Current)"]].map(([x, v, s], i) => (
        <g key={v as string}><motion.circle cx={x as number} cy={MID} r="13" fill="var(--ax-panel2)" stroke={GD} strokeWidth="4" style={{ transformBox: "fill-box", transformOrigin: "center" }} animate={{ scale: [1, 1.154, 1] }} transition={{ repeat: Infinity, duration: 2.4, delay: i }} />
          <rect x={(x as number) - 36} y={MID - 52} width="72" height="34" rx="7" fill="var(--ax-panel2)" stroke={GD} /><text x={x as number} y={MID - 36} textAnchor="middle" fontSize="12" fontWeight="800" fill="var(--ax-text)">{v as string}</text><text x={x as number} y={MID - 24} textAnchor="middle" fontSize="8.5" fill="var(--ax-muted)">{(i === 1 ? "Release (" + cur + ")" : s) as string}</text></g>))}
      {[[X[1] + 30, "RP-003"], [X[2] + 20, "RP-004"]].map(([x, rp], i) => (
        <g key={rp as string}><motion.path d={`M${X[i + 1]} ${MID + 14} C${X[i + 1]} ${MID + 150}, ${(x as number) - 10} ${MID + 100}, ${(x as number) - 14} ${300}`} fill="none" stroke="var(--ax-bad)" strokeWidth="2" strokeDasharray="5 4" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 1, duration: .8 }} />
          <rect x={(x as number) - 14} y="290" width="76" height="28" rx="7" fill="var(--ax-panel2)" stroke="var(--ax-bad)" /><text x={(x as number) + 24} y="301" textAnchor="middle" fontSize="9" fill="var(--ax-text)">Rollback</text><text x={(x as number) + 24} y="312" textAnchor="middle" fontSize="9" fontWeight="700" fill="var(--ax-text)">{rp as string}</text></g>))}
    </svg>
  );
}

export function Legend2() {
  const it = (I: typeof GitCommit, c: string, t: string) => <span className="ax-flex ax-xs" style={{ gap: 4 }}><I size={12} style={{ color: c }} aria-hidden />{t}</span>;
  const ln = (c: string, t: string, dash?: boolean) => <span className="ax-flex ax-xs" style={{ gap: 4 }}><i style={{ width: 20, height: 0, borderTop: `3px ${dash ? "dashed" : "solid"} ${c}` }} aria-hidden />{t}</span>;
  return <div className="ax-flex" style={{ flexWrap: "wrap", gap: 9, padding: "3px 6px", border: "1px solid var(--ax-border)", borderRadius: 10 }} aria-label="Legend">
    {it(GitBranch, "var(--ax-info)", "Branch Base")}{it(GitCommit, "var(--ax-info)", "Commit")}{it(CheckCircle2, "var(--ax-ok)", "Merge")}{it(Tag, GD, "Release Tag")}{it(RotateCcw, "var(--ax-bad)", "Rollback Point")}
    {ln("var(--ax-ok)", "Main")}{ln(PUR, "Feature Branch")}{ln(CY, "Agent Branch")}{ln(GD, "Self-Evolution")}{ln("var(--ax-ok)", "Merge Flow")}{ln("var(--ax-bad)", "Rollback Flow", true)}</div>;
}

const AGENTS: [Role, string, number][] = [["research", "RCH", 12], ["developer", "DEV", 18], ["ops", "OPS", 8], ["qa", "QA", 14], ["knowledge", "KNW", 10], ["finance", "FIN", 6], ["deploy", "DEP", 8]];
const PIPE: [typeof Package, string, string][] = [[Package, "Build", "2m 14s"], [FlaskConical, "Test", "3m 01s"], [ShieldCheck, "QA", "1m 10s"], [Layers, "Package", "54s"], [Rocket, "Deploy", "1m 07s"]];

export function Dashboard({ releases, branches, prs, sel, onSelect, onRun, setTab }: { releases: Release[]; branches: Branch[]; prs: MergeRequest[]; sel: Release; onSelect: (v: string) => void; onRun: (r: Release) => void; setTab: (t: string) => void }) {
  const toast = useToast(); const dl = useDownload();
  const [view, setView] = useState<"graph" | "list" | "timeline">("graph");
  const [a, setA] = useState(() => (releases[releases.findIndex((r) => r.version === sel.version) + 1] ?? releases[1] ?? sel).version);
  const ra = releases.find((r) => r.version === a) ?? sel; const ba = benchOf(ra.version), bb = benchOf(sel.version);
  const outs = [...sel.artifacts.map((x) => ({ n: x.name, s: x.size, k: x.name })), { n: "Release Manifest (JSON)", s: "112 KB", k: "" }].slice(0, 4);
  const cmp = [...ba.slice(0, 4).map((m, i) => [m.name, m.value, bb[i].value, m.unit, m.higherBetter] as const), ["Total commits", ra.tests.total * 2, sel.tests.total * 2, "", true] as const];
  const pill = (r: Release) => <Pill c={REL_C[r.status]} solid={r.status === "current"}>{r.status === "candidate" ? "RC" : r.status}</Pill>;
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr) minmax(0, 0.62fr)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateColumns: "73fr 27fr", gap: "var(--ax-gap)" }}>
        <motion.section className="ax-panel ax-kpis" style={{ gridTemplateColumns: "1.15fr repeat(6, 1fr)", padding: 6 }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} aria-label="Key figures">
          <Kt i={0} icon={Layers} c="#a77bff" t={sel.version} l="Current" x={<small style={{ color: "var(--ax-ok)" }}>Stable Release</small>} onClick={() => setTab("releases")} />
          <Kt i={1} icon={GitBranch} c="#3b8cff" t={String(branches.length)} l="Total Branches" x={<small style={{ color: "var(--ax-ok)" }}>↑ +3 (vs. last week)</small>} onClick={() => setTab("branches")} />
          <Kt i={2} icon={GitMerge} c="#f2b53a" t={String(prs.filter((p) => p.status !== "merged").length)} l="Active PRs" x={<small className="ax-muted">{prs.filter((p) => p.status === "approved").length} Ready to Merge</small>} onClick={() => setTab("prs")} />
          <Kt i={3} icon={ShieldCheck} c="#2fd27a" t="98.7%" l="CI Success Rate" x={<small style={{ color: "var(--ax-ok)" }}>↑ +1.9 pp</small>} />
          <Kt i={4} icon={Rocket} c="#fb7185" t={releases.find((r) => r.status === "candidate")?.version ?? "v1.5.0"} l="Next Release (RC)" x={<small className="ax-muted">ETA: in 3 days</small>} onClick={() => setTab("releases")} />
          <Kt i={5} icon={Layers} c="#22d3ee" t={branches.reduce((n, b) => n + b.commits, 0).toLocaleString()} l="Total Commits" x={<small style={{ color: "var(--ax-ok)" }}>↑ +28 (24h)</small>} />
          <Kt i={6} icon={Bot} c="#a77bff" t="5" l="Active Agents" x={<small className="ax-muted">Code · Test · Review</small>} />
        </motion.section>
        <Panel i={0} title="Quick Actions" icon={Network} help="Shortcuts. Creating branches, tags or settings changes only explain what they would do: this is sample data." >
          <div className="ax-flex" style={{ justifyContent: "space-around" }}>
            <IconBtn icon={Plus} label="New branch (sample)" size="lg" onClick={() => toast("Would create a branch from main. Sample data: nothing is created in GitHub.", "info")} />
            <IconBtn icon={GitBranch} label="Branch graph" size="lg" onClick={() => setTab("branches")} />
            <IconBtn icon={GitMerge} label="Merge requests" size="lg" onClick={() => setTab("prs")} />
            <IconBtn icon={Play} label={`Run ${sel.version} preview`} size="lg" tone="ok" onClick={() => onRun(sel)} />
            <IconBtn icon={Tag} label="Releases" size="lg" onClick={() => setTab("releases")} />
            <IconBtn icon={Settings} label="Repository settings (sample)" size="lg" onClick={() => toast("Repository settings are not editable in this prototype", "info")} />
          </div>
        </Panel>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "60fr 20fr 19fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title="Branch Graph" icon={GitBranch} sub="Development, Agent Work, Self-Evolution & Release Flow" help="main (protected) fans out into feature, agent and self-evolution lanes that merge back at a PR and are tagged as a release. Red dashed arrows are rollback points. Sample data."
          actions={<Seg label="Graph view" value={view} onChange={setView} items={[{ id: "graph", label: "Graph" }, { id: "list", label: "List" }, { id: "timeline", label: "Timeline" }]} />}>
          {view === "graph" && <div style={{ height: "100%", display: "grid", gridTemplateRows: "minmax(0, 1fr) auto", gap: 4 }}><DashGraph cur="Current" /><Legend2 /></div>}
          {view === "list" && <table className="ax-table"><thead><tr><th>Lane</th><th>Kind</th><th>Flows into</th></tr></thead><tbody>{LANES.map((l) => <tr key={l.name}><td className="ax-mono">{l.name} <span className="ax-muted">{l.sub}</span></td><td><Pill c={l.c}>{l.name.startsWith("agent") ? "agent" : l.name.startsWith("self") || l.name.includes("self-evolution") ? "self-evolution" : "feature"}</Pill></td><td>{l.from ? "v2.4.0 via Merge #318" : "v2.3.0 via Merge #312"}</td></tr>)}</tbody></table>}
          {view === "timeline" && <div className="ax-col" style={{ gap: 5 }}>{[...releases].map((r, i) => <motion.div key={r.id} className="ax-tile ax-flex ax-small" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }}><Tag size={15} style={{ color: REL_C[r.status] }} aria-hidden /><b>{r.version}</b>{pill(r)}<span className="ax-muted" style={{ flex: 1 }}>{r.notes[0]} · merged {r.mergedFrom.length} branch(es)</span><Time iso={r.at} withDate /></motion.div>)}</div>}
        </Panel>
        <div style={{ display: "grid", gridTemplateRows: "minmax(0, 1fr) minmax(0, 0.9fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
          <Panel i={2} title="Selected Release" icon={Tag} sub={<>{sel.version}{pill(sel)}</>} help="The selected edition and its release notes. Change the selection in the Releases tab or the Version History table.">
            <div className="ax-flex ax-small" style={{ marginBottom: 4 }}><b style={{ fontSize: 15 }}>{sel.version}</b><span className="ax-muted"><Time iso={sel.at} withDate /></span></div>
            <div className="ax-col" style={{ gap: 3 }}>{[...sel.notes, ...sel.fixes].slice(0, 5).map((n, i) => <motion.span key={n} className="ax-flex ax-small" initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .1 + i * .05 }}><CheckCircle2 size={13} className="ax-ok" aria-hidden /><span style={{ minWidth: 0 }}>{n}</span></motion.span>)}</div>
          </Panel>
          <Panel i={3} title="Downloadable Outputs" icon={Download} help="Artifacts of the selected edition. Download saves a JSON manifest generated in your browser (sample data, not the binary).">
            <div className="ax-col" style={{ gap: 4 }}>{outs.map((o) => <div key={o.n} className="ax-tile ax-flex ax-small" style={{ padding: "3px 8px" }}>{o.k ? <FileArchiveI /> : <FileJson size={15} className="ax-info" aria-hidden />}<span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o.n}</span><span className="ax-muted">{o.s}</span><IconBtn icon={Download} size="sm" label={`Download ${o.n}`} onClick={() => dl(sel, o.k || undefined)} /></div>)}</div>
          </Panel>
        </div>
        <div style={{ display: "grid", gridTemplateRows: "minmax(0, 1fr) minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
          <Panel i={4} title={`Live Preview — ${sel.version}`} icon={Eye} help="A sandboxed sample page, not a real external site. Launch Preview opens the Preview tab." sub={<Pill c="var(--ax-ok)">Live</Pill>}>
            <div style={{ height: "100%", display: "grid", gridTemplateRows: "minmax(0, 1fr) auto", gap: 6 }}>
              <div style={{ position: "relative", overflow: "hidden", borderRadius: 8, border: "1px solid var(--ax-border)" }} aria-label="Preview thumbnail"><div style={{ width: 1280, height: 640, transform: "scale(.2)", transformOrigin: "0 0", pointerEvents: "none" }}><MockSite version={sel.version} commit={sel.commit} /></div>
                <IconBtn icon={Maximize2} label="Open full preview" size="sm" style={{ position: "absolute", right: 4, bottom: 4 }} onClick={() => onRun(sel)} /></div>
              <div className="ax-flex"><Btn icon={Play} tone="gold" style={{ flex: 1 }} disabled={!sel.runnable} onClick={() => onRun(sel)}>Launch Preview</Btn><IconBtn icon={Settings} label="Preview settings (sample)" onClick={() => toast("Preview runs in an isolated sandbox with a sample page", "info")} /></div>
            </div>
          </Panel>
          <Panel i={5} title="Compare Versions" icon={GitMerge} help="Quick comparison of two editions (sample benchmark values). Open the Compare tab for the full diff.">
            <div className="ax-flex" style={{ marginBottom: 4 }}><select className="ax-select" style={{ padding: "2px 6px" }} value={ra.version} onChange={(e) => setA(e.target.value)} aria-label="Base version">{releases.map((r) => <option key={r.id}>{r.version}</option>)}</select><span aria-hidden>⇄</span><select className="ax-select" style={{ padding: "2px 6px" }} value={sel.version} onChange={(e) => onSelect(e.target.value)} aria-label="Compared version">{releases.map((r) => <option key={r.id}>{r.version}</option>)}</select></div>
            {cmp.map(([n, x, y, u, hb]) => { const d = y - x, good = hb ? d >= 0 : d <= 0; return <div key={n} className="ax-flex ax-xs" style={{ gap: 4 }}><span style={{ flex: 1, minWidth: 0 }}>{n}</span><span className="ax-num ax-muted">{x}{u}</span>→<b className="ax-num">{y}{u}</b><b className="ax-num" style={{ color: d === 0 ? "var(--ax-muted)" : good ? "var(--ax-ok)" : "var(--ax-bad)", width: 52, textAlign: "right" }}>{d >= 0 ? "▲" : "▼"}{Math.abs(+d.toFixed(1))}</b></div>; })}
          </Panel>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "27fr 25fr 25fr 23fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={6} title="Recent Commits" icon={GitCommit} help="Latest commits across all branches (sample).">
          <div className="ax-col" style={{ gap: 3 }}>{COMMITS.slice(0, 5).map(([h, m, who, t], i) => <motion.div key={h} className="ax-flex ax-xs" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * .05 }}><Avatar role={roleFor(who)} size={18} /><span className="ax-mono ax-faint">{h}</span><span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m}</span><span className="ax-muted">{who} {t}</span><CheckCircle2 size={13} className="ax-ok" aria-label="checks passed" /></motion.div>)}</div>
        </Panel>
        <Panel i={7} title="CI/CD Pipeline" icon={Layers} help="Last build of the selected edition (sample timings)." >
          <div className="ax-flex ax-small"><b>{sel.version} Build #334</b><Pill c="var(--ax-ok)" solid>Success</Pill><span className="ax-muted">8m 26s</span></div>
          <div className="ax-flex" style={{ justifyContent: "space-between", paddingTop: 2 }}>{PIPE.map(([I, n, t], i) => <div key={n} style={{ display: "contents" }}><motion.div style={{ textAlign: "center", display: "grid", gap: 2, justifyItems: "center" }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .12 }}><motion.span style={{ width: 38, height: 38, borderRadius: 38, border: "2px solid var(--ax-info)", display: "grid", placeItems: "center", color: "var(--ax-info)" }} animate={{ boxShadow: ["0 0 0 transparent", "0 0 10px var(--ax-info)", "0 0 0 transparent"] }} transition={{ repeat: Infinity, duration: 2.4, delay: i * .3 }}><I size={18} aria-hidden /></motion.span><b className="ax-xs">{n}</b><span className="ax-xs ax-ok"><CheckCircle2 size={10} aria-hidden /> {t}</span></motion.div>{i < 4 && <span aria-hidden className="ax-muted">→</span>}</div>)}</div>
        </Panel>
        <Panel i={8} title="Version History" icon={Tag} help="All stored editions. Actions: copy commit, open in Releases, roll back (asks first; sample only).">
          <table className="ax-table"><thead><tr><th>Version</th><th>Release Date</th><th>Status</th><th>Actions</th></tr></thead><tbody>{releases.slice(0, 5).map((r) => <tr key={r.id}><td><b>{r.version}</b></td><td className="ax-small">{new Date(r.at).toLocaleDateString(undefined, { month: "short", day: "2-digit", year: "numeric" })}</td><td>{pill(r)}</td>
            <td><span className="ax-flex" style={{ gap: 2 }}><IconBtn icon={Copy} size="sm" label={`Copy ${r.version} commit`} onClick={() => { void navigator.clipboard?.writeText(r.commit); toast(`Copied ${r.commit}`, "ok"); }} /><IconBtn icon={Tag} size="sm" label={`Open ${r.version} in Releases`} onClick={() => { onSelect(r.version); setTab("releases"); }} /><IconBtn icon={RotateCcw} size="sm" label={`Roll back to ${r.version} (sample)`} onClick={() => { if (window.confirm(`Roll back to ${r.version}? (sample: nothing is changed)`)) toast(`Would roll back to ${r.version}: sample data, no change made`, "warn"); }} /></span></td></tr>)}</tbody></table>
        </Panel>
        <Panel i={9} title={`Agent Contributions (${sel.version})`} icon={Star} help="Commits per agent role for the selected edition (sample).">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, justifyItems: "center" }}>{AGENTS.map(([r, n, c], i) => <motion.div key={n} style={{ textAlign: "center" }} initial={{ opacity: 0, scale: .8 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * .06 }} whileHover={{ y: -3 }}><Avatar role={r} size={38} name={n} /><div className="ax-xs"><b>{n}</b></div><div className="ax-xs ax-muted">{c} commits</div></motion.div>)}</div>
        </Panel>
      </div>
    </div>
  );
}
const roleFor = (w: string): Role => (w.startsWith("QA") ? "qa" : w.startsWith("DEP") ? "deploy" : w === "GM" ? "gm" : w.startsWith("RCH") ? "research" : "developer");
function FileArchiveI() { return <Package size={15} className="ax-info" aria-hidden />; }
import type { LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
function Kt({ icon: I, c, t, l, x, onClick, i }: { icon: LucideIcon; c: string; t: string; l: string; x?: ReactNode; onClick?: () => void; i: number }) {
  return (
    <motion.button type="button" className="ax-kpi" onClick={onClick} style={{ "--c": c, padding: "6px 8px", gap: 8 } as CSSProperties} aria-label={`${l}: ${t}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 + i * .05 }} whileHover={{ y: -2 }} whileTap={{ scale: .97 }}>
      <motion.span className="ax-kpi-ic" style={{ width: 34, height: 34 }} animate={{ boxShadow: ["0 0 0 transparent", `0 0 14px ${c}`, "0 0 0 transparent"] }} transition={{ duration: 3.2, repeat: Infinity, delay: i * .3 }}><I size={18} aria-hidden /></motion.span>
      <span style={{ minWidth: 0 }}><b style={{ fontSize: 19 }}>{t}</b><span className="lbl">{l}</span>{x}</span>
    </motion.button>
  );
}
