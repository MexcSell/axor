import { useMemo } from "react";
import { motion } from "framer-motion";
import { Box, ExternalLink, FileArchive, GitBranch, GitCompare, GitPullRequest, Lock, Play, Rocket, Star, Eye, Github } from "lucide-react";
import { Pill, TabBody, Tabs, useToast, Help } from "../ui/kit";
import { useStore } from "../data/store";
import { go, useQueryParam, useRoute } from "../app/router";
import { REPO } from "./versions/data";
import { ReleasesTab } from "./versions/Releases";
import { BranchGraphTab } from "./versions/BranchGraph";
import { CompareTab } from "./versions/Compare";
import { MergeRequestsTab } from "./versions/MergeRequests";
import { PreviewTab } from "./versions/Preview";
import { Dashboard } from "./versions/Dashboard";
import { DownloadsTab } from "./versions/Downloads";

// Versions & GitHub (readme §4–5; Detailed UI v3 §4.8; VER-001..006, PREV-01..04; canonical reference 30-6).
// `#/preview/<version>` renders this page too and opens the Preview tab. Tab and selected version live in the URL (?tab=, ?v=).
export default function Versions() {
  const route = useRoute(); const toast = useToast();
  const rawReleases = useStore((s) => s.releases), rawBranches = useStore((s) => s.branches), prs = useStore((s) => s.mergeRequests);
  const releases = rawReleases, branches = rawBranches;
  const [tabQ, setTabQ] = useQueryParam("tab", "versions");
  const alias: Record<string, string> = { graph: "branches", mrs: "prs" };
  const tab = route.page === "preview" ? "preview" : alias[tabQ] ?? tabQ;
  const current = releases.find((r) => r.status === "current") ?? releases[0];
  const v = route.q.get("v") ?? (route.page === "preview" ? route.param : null) ?? current.version;
  const sel = releases.find((r) => r.version === v) ?? current;
  const setTab = (t: string) => { if (route.page === "preview") go("versions", null, { tab: t === "versions" ? undefined : t, v: sel.version }); else setTabQ(t); };
  const setV = (x: string) => { const q = new URLSearchParams(route.q); q.set("v", x); window.history.replaceState(null, "", `#/${route.page}${route.param ? "/" + encodeURIComponent(route.param) : ""}?${q}`); window.dispatchEvent(new HashChangeEvent("hashchange")); };
  const run = (r: { version: string }) => { go("versions", null, { tab: "preview", v: r.version }); toast(`Starting ${r.version} in the sandboxed preview (sample page)`, "info"); };
  const openPr = prs.filter((p) => p.status !== "merged");
  const TABS = useMemo(() => [
    { id: "versions", label: "Versions", icon: Box }, { id: "branches", label: "Branches", icon: GitBranch }, { id: "prs", label: "Pull Requests", icon: GitPullRequest, count: openPr.length },
    { id: "releases", label: "Releases", icon: Rocket, count: releases.length }, { id: "preview", label: "Preview", icon: Play }, { id: "compare", label: "Compare", icon: GitCompare }, { id: "downloads", label: "Downloads", icon: FileArchive },
  ], [releases.length, openPr.length]);
  return (
    <div className="ax-page" style={{ gridTemplateRows: "auto auto minmax(0, 1fr)" }}>
      <motion.section className="ax-panel" style={{ padding: "8px 12px", gap: 8 }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} aria-label="Versions header">
        <div className="ax-flex" style={{ gap: 12 }}>
          <motion.span animate={{ rotate: [0, -8, 0] }} transition={{ duration: 4, repeat: Infinity }}><GitBranch size={38} className="ax-gold" aria-hidden /></motion.span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="ax-flex"><h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Versions &amp; GitHub</h1><Help title="Versions & GitHub" body="The edition management system stores editions automatically. Select an edition to see its updates, download its output or Run it in the isolated Preview. Mission work happens on feature branches that are merged into main only after checks and your approval." /></div>
            <div className="ax-small ax-muted">AI-Native Version Control · Branching · Merging · Releases · Agent Collaboration</div>
          </div>
          <span className="ax-chip" style={{ padding: "5px 10px" }}><Github size={14} aria-hidden />{REPO}<ExternalLink size={12} aria-hidden /></span><Pill c="var(--ax-neutral)" icon={Lock}>Private</Pill>
          <select className="ax-select" style={{ width: 165 }} aria-label="Workspace" defaultValue="main"><option value="main">Main Workspace</option><option value="lab">Lab Workspace</option></select><Pill c="var(--ax-warn)">Sample data</Pill>
          <span className="ax-chip"><Star size={13} aria-hidden />1,248</span><span className="ax-chip"><GitBranch size={13} aria-hidden />386</span><span className="ax-chip"><Eye size={13} aria-hidden />87</span>
        </div>
      </motion.section>
      <Tabs label="Versions tabs" value={tab} onChange={setTab} tabs={TABS} />
      <div style={{ minHeight: 0 }}>
        <TabBody k={tab}>
          {tab === "versions" && <Dashboard releases={releases} branches={branches} prs={prs} sel={sel} onSelect={setV} onRun={run} setTab={setTab} />}
          {tab === "releases" && <ReleasesTab releases={releases} sel={sel.version} onSelect={setV} onRun={run} />}
          {tab === "branches" && <BranchGraphTab branches={branches} releases={releases} />}
          {tab === "compare" && <CompareTab releases={releases} initial={sel.version} />}
          {tab === "prs" && <MergeRequestsTab prs={prs} />}
          {tab === "preview" && <PreviewTab release={sel} releases={releases} onPick={setV} />}
          {tab === "downloads" && <DownloadsTab releases={releases} sel={sel.version} />}
        </TabBody>
      </div>
    </div>
  );
}
