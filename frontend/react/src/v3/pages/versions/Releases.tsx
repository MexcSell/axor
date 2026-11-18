import { motion } from "framer-motion";
import { AlertTriangle, Bug, Download, FileArchive, FlaskConical, GitBranch, GitCommit, GitMerge, Github, Play, ShieldCheck, Sparkles, Tag, Wrench } from "lucide-react";
import { CopyBtn, IconBtn, Panel, Pill, Progress, Row, useToast, Empty } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import type { Release } from "../../domain/types";
import { COMMITS, REPO, manifestOf, provenance, saveJson } from "./data";

export const REL_C: Record<Release["status"], string> = { current: "var(--ax-ok)", stable: "var(--ax-ok)", candidate: "var(--ax-info)", superseded: "var(--ax-neutral)", failed: "var(--ax-bad)" };
const SEC = { pass: ["Security pass", ShieldCheck, "var(--ax-ok)"], warn: ["Security warnings", AlertTriangle, "var(--ax-warn)"], fail: ["Security failed", AlertTriangle, "var(--ax-bad)"] } as const;

export function useDownload() {
  const toast = useToast();
  return (r: Release, art?: string) => {
    saveJson(art ? `${art}.manifest.json` : `release-manifest-${r.version}.json`, manifestOf(r, art));
    toast(`Downloaded ${art ? art + ".manifest.json" : `release-manifest-${r.version}.json`}: a manifest generated in your browser from sample data, not the binary artifact`, "ok");
  };
}

function Section({ icon: I, title, c, items, empty }: { icon: typeof Bug; title: string; c: string; items: string[]; empty: string }) {
  return (
    <div className="ax-tile" style={{ padding: "6px 9px" }}>
      <div className="ax-flex ax-small" style={{ gap: 6, marginBottom: 3 }}><I size={14} style={{ color: c }} aria-hidden /><b>{title}</b><span className="ax-muted">({items.length})</span></div>
      {items.length ? items.map((n, i) => <motion.div key={n} className="ax-small" initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }} style={{ display: "flex", gap: 6, padding: "1px 0" }}><span style={{ color: c }} aria-hidden>•</span>{n}</motion.div>) : <span className="ax-small ax-muted">{empty}</span>}
    </div>
  );
}

export function ReleasesTab({ releases, sel, onSelect, onRun }: { releases: Release[]; sel: string; onSelect: (v: string) => void; onRun: (r: Release) => void }) {
  const toast = useToast(); const dl = useDownload();
  const r = releases.find((x) => x.version === sel) ?? releases[0];
  if (!r) return <Empty title="No releases yet" />;
  const [secL, SecI, secC] = SEC[r.security]; const pv = provenance(r);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 34fr) 66fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Editions" icon={Tag} sub={`${releases.length} stored automatically`}
        help={{ body: "The edition management system stores every edition automatically. Pick one to see its information, including its updates, on the right. Download gives its release manifest; Run starts the homepage of that edition in the Preview tab.", source: "Releases store (sample data)." }}>
        <div className="ax-rows" style={{ display: "grid", gap: 5 }}>
          {releases.map((x, i) => (
            <Row key={x.id} i={i} sel={x.version === r.version} onClick={() => onSelect(x.version)} label={`${x.version}, ${x.status}`}>
              <motion.span animate={x.status === "current" ? { scale: [1, 1.12, 1] } : {}} transition={{ repeat: Infinity, duration: 2.4 }} style={{ display: "grid" }}><Tag size={18} style={{ color: REL_C[x.status] }} aria-hidden /></motion.span>
              <span className="grow"><b className="t">{x.version}</b><span className="s">{new Date(x.at).toLocaleDateString()} · {x.notes[0]}</span></span>
              <Pill c={REL_C[x.status]} solid={x.status === "current"}>{x.status}</Pill>
              <IconBtn icon={Download} label={`Download ${x.version} manifest`} size="sm" onClick={(e) => { e.stopPropagation(); dl(x); }} />
              <IconBtn icon={Play} label={x.runnable ? `Run ${x.version} in Preview` : `${x.version} is not runnable (failed build)`} size="sm" disabled={!x.runnable} onClick={(e) => { e.stopPropagation(); onRun(x); }} />
            </Row>))}
        </div>
      </Panel>
      <Panel i={1} title={<>Edition {r.version}</>} icon={Sparkles} hl
        sub={<Pill c={REL_C[r.status]} solid>{r.status}</Pill>}
        help="Everything about the selected edition: changelog, fixes, known issues, test and security results, and artifacts with their sha256 checksums."
        actions={<><IconBtn icon={Download} label="Download release manifest (JSON)" tone="gold" onClick={() => dl(r)} />
          <IconBtn icon={Play} label={r.runnable ? "Run this edition in the sandboxed Preview" : "Not runnable: this edition failed its build"} tone="ok" disabled={!r.runnable} onClick={() => onRun(r)} />
          <IconBtn icon={Github} label="Open on GitHub (sample repo)" onClick={() => toast(`Would open github.com/${REPO}/releases/tag/${r.version}. This is sample data, no external link is opened.`, "info")} /></>}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--ax-gap)", alignContent: "start" }}>
          <div className="ax-col" style={{ gap: 6 }}>
            <Section icon={Sparkles} title="Changelog (updates)" c="var(--ax-ok)" items={r.notes} empty="No notes" />
            <Section icon={Wrench} title="Fixes" c="var(--ax-info)" items={r.fixes} empty="No fixes" />
            <Section icon={Bug} title="Known issues" c="var(--ax-warn)" items={r.known} empty="None known" />
            <div className="ax-tile" style={{ padding: "6px 9px" }}>
              <div className="ax-flex ax-small" style={{ marginBottom: 3 }}><GitCommit size={14} className="ax-info" aria-hidden /><b>Recent commits</b><span className="ax-muted">(sample)</span></div>
              {COMMITS.slice(0, 5).map(([h, m, who, t], i) => <motion.div key={h} className="ax-flex ax-small" style={{ padding: "1px 0" }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * .05 }}><span className="ax-mono ax-faint">{h}</span><span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m}</span><span className="ax-muted">{who} {t}</span></motion.div>)}
            </div>
          </div>
          <div className="ax-col" style={{ gap: 6 }}>
            <div className="ax-tile" style={{ padding: "6px 9px" }}>
              <div className="ax-flex ax-small"><FlaskConical size={14} className="ax-ok" aria-hidden /><b>Tests</b><span className="ax-spacer" /><b className="ax-num">{r.tests.passed}/{r.tests.total}</b></div>
              <Progress value={(r.tests.passed / r.tests.total) * 100} thin c1={r.tests.passed === r.tests.total ? "var(--ax-ok)" : "var(--ax-warn)"} c2={r.tests.passed === r.tests.total ? "var(--ax-ok)" : "var(--ax-warn)"} label="Tests passed" />
              <div className="ax-flex ax-small" style={{ marginTop: 5 }}><SecI size={14} style={{ color: secC }} aria-hidden /><b style={{ color: secC }}>{secL}</b><span className="ax-muted">(secret scan, dependency audit)</span></div>
            </div>
            <div className="ax-tile ax-kv" style={{ padding: "6px 9px" }}>
              <span className="ax-muted">Branch</span><span className="ax-flex"><GitBranch size={13} aria-hidden /><span className="ax-mono">{r.branch}</span></span>
              <span className="ax-muted">Commit</span><span className="ax-flex"><span className="ax-mono">{r.commit}</span><CopyBtn text={r.commit} label="Copy commit" /></span>
              <span className="ax-muted">Author</span><AgentTag id={r.author} size={18} />
              <span className="ax-muted">Merged from</span><span className="ax-flex" style={{ flexWrap: "wrap", gap: 4 }}>{r.mergedFrom.map((b) => <Pill key={b} c="var(--ax-blocked)" icon={GitMerge}>{b}</Pill>)}</span>
              <span className="ax-muted">Provenance</span><span className="ax-small">{pv.workflow} · {pv.run} · unsigned (sample)</span>
            </div>
            <div className="ax-tile" style={{ padding: "6px 9px" }}>
              <div className="ax-flex ax-small" style={{ marginBottom: 3 }}><FileArchive size={14} className="ax-gold" aria-hidden /><b>Artifacts</b></div>
              {r.artifacts.map((a) => (
                <div key={a.name} className="ax-flex ax-small" style={{ padding: "2px 0" }}>
                  <span style={{ flex: 1, minWidth: 0 }}><b style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</b><span className="ax-mono ax-faint" title={a.sha256}>sha256 {a.sha256.slice(0, 20)}…</span></span>
                  <span className="ax-muted">{a.size}</span><CopyBtn text={a.sha256} label={`Copy sha256 of ${a.name}`} />
                  <IconBtn icon={Download} label={`Download ${a.name} manifest`} size="sm" onClick={() => dl(r, a.name)} />
                </div>))}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}
