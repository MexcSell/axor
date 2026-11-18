import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, GitBranch, GitCommit, GitMerge, RotateCcw, Tag } from "lucide-react";
import { CopyBtn, Panel, Pill, Seg, useToast } from "../../ui/kit";
import type { Branch, Release } from "../../domain/types";
import { AgentTag } from "../../ui/widgets";

const COL = { main: "var(--ax-ok)", feature: "#c084fc", release: "var(--ax-warn)", agent: "#22d3ee" } as const;
const SC: Record<Branch["status"], string> = { protected: "var(--ax-ok)", open: "var(--ax-info)", merged: "var(--ax-blocked)", staged: "var(--ax-warn)", conflict: "var(--ax-bad)" };

// Main lane on top, one lane per branch below. x grows with time: fork at the left, merge back into main towards the right.
export function BranchGraphTab({ branches, releases }: { branches: Branch[]; releases: Release[] }) {
  const [view, setView] = useState<"graph" | "list">("graph"); const [sel, setSel] = useState<string>(branches.find((b) => b.status === "conflict")?.name ?? branches[1]?.name ?? "main");
  const toast = useToast();
  const main = branches.find((b) => b.kind === "main"); const lanes = branches.filter((b) => b.kind !== "main");
  const W = 1100, X0 = 250, rowH = 46, MY = 100, H = MY + lanes.length * rowH + 30;
  const y = (i: number) => i < 0 ? MY : MY + (i + 1) * rowH - 10;
  const b = branches.find((x) => x.name === sel) ?? main!;
  const relPts = [...releases].filter((r) => r.status !== "failed").reverse();
  const rx = (i: number) => X0 + 140 + i * ((W - X0 - 220) / Math.max(1, relPts.length - 1));
  const merged = lanes.filter((l) => l.status === "merged");
  const forkX = (i: number) => X0 + 14 + (i % 4) * 30; const mergeX = (i: number) => rx(Math.min(relPts.length - 1, 1 + (i % Math.max(1, relPts.length - 1)))) - 48;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr minmax(260px, 24%)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Branch Graph" icon={GitBranch} sub="main ↔ mission feature branches ↔ merges · conflicts · rollback points"
        help="main (protected) at the top. Each mission works on its own feature branch; merged branches curve back into main at the PR number. Release tags sit on main; red dashed arrows are rollback points to the previous stable version. A red node is a merge conflict."
        actions={<Seg label="Graph view" value={view} onChange={setView} items={[{ id: "graph", label: "Graph" }, { id: "list", label: "List" }]} />}>
        {view === "graph" ? (
          <div style={{ height: "100%", display: "grid", gridTemplateRows: "1fr auto", minHeight: 0 }}>
            <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Branch graph" style={{ minHeight: 0 }}>
              <motion.line x1={30} x2={W - 30} y1={y(-1) + 0} y2={y(-1) + 0} stroke={COL.main} strokeWidth="4" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1 }} />
              <circle cx={30} cy={y(-1)} r="9" fill="var(--ax-panel2)" stroke={COL.main} strokeWidth="3" />
              <text x={46} y={y(-1) - 14} fontSize="12" fill="var(--ax-text)" fontWeight="700">main ({main?.version})</text>
              {lanes.map((l, i) => {
                const ly = y(i), fx = forkX(i), c = COL[l.kind] ; const isM = l.status === "merged"; const mi = merged.indexOf(l); const mx = isM ? mergeX(mi) : W - 90 - (i % 3) * 20;
                const dots = Math.min(5, Math.max(2, Math.round(l.commits / 8)));
                return (
                  <g key={l.name} onClick={() => setSel(l.name)} style={{ cursor: "pointer" }} tabIndex={0} role="button" aria-label={`${l.name}, ${l.status}`} onKeyDown={(e) => e.key === "Enter" && setSel(l.name)} opacity={sel === l.name ? 1 : .85}>
                    <motion.path d={`M${fx} ${y(-1)} C${fx} ${ly}, ${fx + 10} ${ly}, ${fx + 40} ${ly} L${mx - (isM ? 40 : 0)} ${ly}${isM ? ` C${mx} ${ly}, ${mx} ${y(-1)}, ${mx} ${y(-1)}` : ""}`}
                      fill="none" stroke={l.status === "conflict" ? "var(--ax-bad)" : c} strokeWidth={sel === l.name ? 4 : 2.6} strokeDasharray={l.status === "open" || l.status === "conflict" ? "0" : "0"} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: .8, delay: .1 * i }} />
                    {Array.from({ length: dots }).map((_, k) => <motion.circle key={k} cx={fx + 56 + k * ((mx - fx - 100) / dots)} cy={ly} r="4.5" fill="var(--ax-panel2)" stroke={c} strokeWidth="2" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .3 + .08 * k + .1 * i }} />)}
                    {isM && <g><motion.circle cx={mx} cy={y(-1)} r="12" fill="var(--ax-panel2)" stroke="var(--ax-ok)" strokeWidth="3" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .8 + .1 * i, type: "spring" }} />
                      <text x={mx} y={y(-1) + 4} textAnchor="middle" fontSize="10" fill="var(--ax-ok)" fontWeight="800">✓</text>
                      <text x={mx} y={y(-1) - 18} textAnchor="middle" fontSize="10" fill="var(--ax-muted)">Merge #{l.pr}</text></g>}
                    {l.status === "conflict" && <motion.g animate={{ scale: [1, 1.25, 1] }} transition={{ repeat: Infinity, duration: 1.4 }} style={{ transformOrigin: `${mx}px ${ly}px` }}><circle cx={mx} cy={ly} r="10" fill="var(--ax-bad)" /><text x={mx} y={ly + 4} textAnchor="middle" fontSize="12" fill="#fff" fontWeight="800">!</text></motion.g>}
                    {l.status === "open" && <motion.circle cx={mx} cy={ly} r="7" fill={c} animate={{ opacity: [1, .35, 1] }} transition={{ repeat: Infinity, duration: 1.6 }} />}
                    {l.status === "staged" && <rect x={mx - 7} y={ly - 7} width="14" height="14" rx="3" fill="var(--ax-warn)" />}
                    <text x={8} y={ly + 4} fontSize="11.5" fill="var(--ax-text)" fontWeight={sel === l.name ? 800 : 600}>{l.name} <tspan fill="var(--ax-muted)" fontWeight="400">({l.version}){l.pr ? ` · #${l.pr}` : ""}</tspan></text>
                  </g>);
              })}
              {relPts.map((r, i) => (
                <g key={r.id}>
                  <motion.rect x={rx(i) - 7} y={y(-1) - 7} width="14" height="14" rx="3" transform={`rotate(45 ${rx(i)} ${y(-1)})`} fill="var(--ax-panel2)" stroke={r.status === "candidate" ? "var(--ax-info)" : "var(--ax-warn)"} strokeWidth="2.5" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .5 + i * .1 }} />
                  <text x={rx(i)} y={y(-1) + 26} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--ax-text)">{r.version}</text>
                  {i > 0 && <g><motion.path d={`M${rx(i)} ${y(-1) - 12} C${rx(i)} ${y(-1) - 70}, ${rx(i - 1)} ${y(-1) - 70}, ${rx(i - 1)} ${y(-1) - 12}`} fill="none" stroke="var(--ax-bad)" strokeWidth="1.8" strokeDasharray="5 4" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 1 + i * .12, duration: .8 }} />
                    <text x={(rx(i) + rx(i - 1)) / 2} y={y(-1) - 62} textAnchor="middle" fontSize="10" fill="var(--ax-bad)">Rollback RP-{String(i).padStart(3, "0")} → {relPts[i - 1].version}</text></g>}
                </g>))}
            </svg>
            <div className="ax-flex ax-xs" style={{ flexWrap: "wrap", gap: 10, padding: "4px 2px" }} aria-label="Legend">
              <span className="ax-flex"><GitCommit size={12} aria-hidden />Commit</span><span className="ax-flex"><GitMerge size={12} className="ax-ok" aria-hidden />Merge</span>
              <span className="ax-flex"><Tag size={12} className="ax-warn" aria-hidden />Release tag</span><span className="ax-flex"><RotateCcw size={12} className="ax-bad" aria-hidden />Rollback point</span>
              <span className="ax-flex"><AlertTriangle size={12} className="ax-bad" aria-hidden />Conflict</span>
              {(["main", "feature", "agent", "release"] as const).map((k) => <span key={k} className="ax-flex"><i style={{ width: 16, height: 3, background: COL[k], borderRadius: 2 }} aria-hidden />{k}</span>)}
            </div>
          </div>
        ) : (
          <table className="ax-table"><thead><tr><th>Branch</th><th>Mission</th><th>Status</th><th>Version</th><th>PR</th><th>Commits</th><th>Ahead/behind</th></tr></thead>
            <tbody>{branches.map((x) => <tr key={x.name} onClick={() => setSel(x.name)} style={{ cursor: "pointer", background: sel === x.name ? "color-mix(in srgb, var(--ax-accent) 10%, transparent)" : undefined }}>
              <td className="ax-mono">{x.name}</td><td>{x.missionId ?? "–"}</td><td><Pill c={SC[x.status]}>{x.status}</Pill></td><td>{x.version}</td><td>{x.pr ? `#${x.pr}` : "–"}</td><td className="ax-num">{x.commits}</td><td className="ax-num">{x.ahead}/{x.behind}</td></tr>)}</tbody></table>
        )}
      </Panel>
      <Panel i={1} title="Branch details" icon={GitBranch} help="Details of the selected branch. A mission works in its own isolated branch; only the verified result is merged into main, after checks and approval.">
        <div className="ax-col" style={{ gap: 8 }}>
          <div className="ax-flex"><b className="ax-mono" style={{ overflowWrap: "anywhere" }}>{b.name}</b><Pill c={SC[b.status]} solid>{b.status}</Pill></div>
          <div className="ax-kv">
            <span className="ax-muted">Kind</span><span>{b.kind}</span><span className="ax-muted">Mission</span><span>{b.missionId ?? "company-wide"}</span>
            <span className="ax-muted">Version</span><span>{b.version}</span><span className="ax-muted">Commits</span><span className="ax-num">{b.commits}</span>
            <span className="ax-muted">Ahead / behind</span><span className="ax-num">{b.ahead} / {b.behind}</span>
            <span className="ax-muted">Head</span><span className="ax-flex"><span className="ax-mono">{b.head}</span><CopyBtn text={b.head} label="Copy head commit" /></span>
            <span className="ax-muted">Pull request</span><span>{b.pr ? `#${b.pr}` : "none"}</span>
          </div>
          {b.status === "conflict" && <div className="ax-tile" style={{ borderColor: "var(--ax-bad)" }}><b className="ax-bad ax-flex ax-small"><AlertTriangle size={14} aria-hidden />Merge conflict</b><span className="ax-small">{b.behind} commits behind main touch the same theme tokens. The mission agent must rebase and re-run checks; the merge stays blocked meanwhile.</span></div>}
          {b.kind === "agent" && <div className="ax-small ax-muted">Agent candidate branch: evaluated in the Evolution Lab before it can be promoted.</div>}
          {b.missionId && <AgentTag id="DEV-01" sub="author (sample)" />}
          <button className="ax-btn" type="button" onClick={() => toast(`Would create rollback point RP for ${b.name} (sample: nothing is changed in GitHub)`, "info")}><RotateCcw size={14} aria-hidden />Mark rollback point</button>
        </div>
      </Panel>
    </div>
  );
}
