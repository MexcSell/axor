import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Circle, GitMerge, GitPullRequest, ShieldCheck, ThumbsUp, XCircle } from "lucide-react";
import { Btn, Modal, Panel, Pill, Progress, Time, useToast } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import type { MergeRequest } from "../../domain/types";

const CHECKS = ["Lint", "Type check", "Unit tests", "Integration tests", "E2E (Chromium)", "E2E (Safari)", "Security scan", "Dependency audit", "Build"];
const ST: Record<MergeRequest["status"], string> = { open: "var(--ax-info)", approved: "var(--ax-ok)", merged: "var(--ax-blocked)", blocked: "var(--ax-bad)" };

export function MergeRequestsTab({ prs }: { prs: MergeRequest[] }) {
  const toast = useToast();
  const [sel, setSel] = useState(prs[0]?.id ?? ""); const [approved, setApproved] = useState<Record<string, boolean>>({}); const [merged, setMerged] = useState<Record<string, boolean>>({}); const [ask, setAsk] = useState<string | null>(null); // the PR the confirmation is about (GPT review #2, #3)
  const pr = prs.find((p) => p.id === sel) ?? prs[0]; if (!pr) return null;
  const mergedOf = (p: typeof pr) => p.status === "merged" || !!merged[p.id];
  const gatesFor = (p: typeof pr) => [
    { l: "All CI checks pass", ok: p.checks.passed === p.checks.total, d: `${p.checks.passed}/${p.checks.total}` },
    { l: "QA verification passed", ok: p.qa === "passed", d: p.qa },
    { l: "No merge conflicts", ok: p.conflicts === 0, d: `${p.conflicts} conflict(s)` },
    { l: "Your approval given", ok: !!approved[p.id] || p.status === "approved" || mergedOf(p), d: approved[p.id] || p.status === "approved" ? "approved" : "waiting for you" },
  ];
  const canMerge = (p: typeof pr) => gatesFor(p).every((g) => g.ok) && !mergedOf(p);
  const isMerged = mergedOf(pr), gates = gatesFor(pr), can = canMerge(pr);
  const askPr = prs.find((p) => p.id === ask);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
      <Panel i={0} title="Merge Requests" icon={GitPullRequest} sub={`${prs.filter((p) => p.status !== "merged").length} open`}
        help="Pull requests from mission branches into main. A merge is blocked unless every check passes, QA has verified it, there is no conflict and you approved it. AXoR never merges automatically.">
        <table className="ax-table"><thead><tr><th>PR</th><th>Title</th><th>Branch → target</th><th>Checks</th><th>QA</th><th>Reviewers</th><th>Conflicts</th><th>Status</th></tr></thead>
          <tbody>{prs.map((p, i) => { const m = p.status === "merged" || merged[p.id]; return (
            <motion.tr key={p.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }} onClick={() => setSel(p.id)} tabIndex={0} aria-selected={sel === p.id} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(p.id); } }} style={{ cursor: "pointer", background: sel === p.id ? "color-mix(in srgb, var(--ax-accent) 10%, transparent)" : undefined }}>
              <td className="ax-mono"><b>#{p.number}</b></td><td>{p.title}<div className="ax-xs ax-muted"><Time iso={p.at} withDate /></div></td>
              <td className="ax-mono ax-small">{p.from} → {p.to}</td>
              <td style={{ minWidth: 90 }}><span className="ax-small ax-num">{p.checks.passed}/{p.checks.total}</span><Progress value={(p.checks.passed / p.checks.total) * 100} thin c1={p.checks.passed === p.checks.total ? "var(--ax-ok)" : "var(--ax-warn)"} c2={p.checks.passed === p.checks.total ? "var(--ax-ok)" : "var(--ax-warn)"} label="Checks" /></td>
              <td><Pill c={p.qa === "passed" ? "var(--ax-ok)" : p.qa === "failed" ? "var(--ax-bad)" : "var(--ax-warn)"} icon={p.qa === "passed" ? CheckCircle2 : p.qa === "failed" ? XCircle : ShieldCheck}>{p.qa}</Pill></td>
              <td><span className="ax-flex" style={{ gap: 2 }}>{p.reviewers.map((r) => <AgentTag key={r} id={r} size={20} />)}</span></td>
              <td>{p.conflicts ? <Pill c="var(--ax-bad)" icon={AlertTriangle}>{p.conflicts}</Pill> : <span className="ax-ok" aria-label="No conflicts">0</span>}</td>
              <td><Pill c={ST[m ? "merged" : p.status]} icon={m ? GitMerge : undefined}>{m ? "merged" : p.status}</Pill></td></motion.tr>); })}</tbody></table>
      </Panel>
      <Panel i={2} title={`CI checks · #${pr.number}`} icon={ShieldCheck} help="The checks behind the pass count (sample breakdown). A check that is not green blocks the merge.">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
          {CHECKS.map((n, i) => { const ok = i < Math.round((pr.checks.passed / pr.checks.total) * CHECKS.length) || pr.checks.passed === pr.checks.total; return (
            <motion.div key={n} className="ax-tile ax-flex ax-small" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .04 }}>{ok ? <CheckCircle2 size={14} className="ax-ok" aria-label="passed" /> : <XCircle size={14} className="ax-bad" aria-label="failing" />}{n}</motion.div>); })}
        </div>
        <div className="ax-small ax-muted" style={{ marginTop: 6 }}>Reviewers: {pr.reviewers.join(", ")} · QA {pr.qa}{pr.conflicts ? ` · ${pr.conflicts} conflict(s) must be resolved by the mission agent` : ""}</div>
      </Panel>
      </div>
      <Panel i={1} title={`Merge gate · #${pr.number}`} icon={ShieldCheck} hl help="The gate that must be green before Merge is enabled. Merging is always a deliberate action by you; in this prototype it only records the decision (sample data, no GitHub call).">
        <div className="ax-col" style={{ gap: 8 }}>
          <b>{pr.title}</b><span className="ax-mono ax-small">{pr.from} → {pr.to}</span>
          {gates.map((g, i) => <motion.div key={g.l} className="ax-tile ax-flex" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .07 }}>
            {g.ok ? <CheckCircle2 size={17} className="ax-ok" aria-label="passed" /> : <Circle size={17} className="ax-bad" aria-label="not met" />}<b className="ax-small" style={{ flex: 1 }}>{g.l}</b><span className="ax-small ax-muted">{g.d}</span></motion.div>)}
          {isMerged && <Pill c="var(--ax-blocked)" icon={GitMerge}>Already merged</Pill>}
          <div className="ax-flex">
            <Btn icon={ThumbsUp} disabled={isMerged || !!approved[pr.id] || pr.status === "approved" || pr.conflicts > 0} onClick={() => { setApproved({ ...approved, [pr.id]: true }); toast(`Approval recorded for #${pr.number} (sample)`, "ok"); }}>Approve</Btn>
            <Btn icon={GitMerge} tone="gold" disabled={!can} onClick={() => setAsk(pr.id)} title={can ? "Merge" : "Blocked until all gates are green"}>Merge</Btn>
          </div>
          {!can && !isMerged && <span className="ax-small ax-warn ax-flex"><AlertTriangle size={13} aria-hidden />Merge is blocked until every gate above is green. No automatic merge.</span>}
        </div>
      </Panel>
      <Modal open={!!askPr} onClose={() => setAsk(null)} title={askPr ? `Merge #${askPr.number} into ${askPr.to}?` : ""} icon={GitMerge} foot={<><Btn onClick={() => setAsk(null)}>Cancel</Btn><Btn tone="gold" icon={GitMerge} onClick={() => { if (!askPr) return; if (!canMerge(askPr)) { setAsk(null); toast(`#${askPr.number}: a gate changed, merge blocked. Check the gates again.`, "warn"); return; } setMerged({ ...merged, [askPr.id]: true }); setAsk(null); toast(`#${askPr.number} marked merged (sample data: no real merge happened). The GM stores the result in GitHub at the next stage commit.`, "ok"); }}>Confirm merge</Btn></>}>
        <p>This would merge <b className="ax-mono">{askPr?.from}</b> into <b className="ax-mono">{askPr?.to}</b> after all gates passed. This prototype only records it locally.</p>
      </Modal>
    </div>
  );
}
