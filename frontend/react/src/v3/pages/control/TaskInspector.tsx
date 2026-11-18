import { motion } from "framer-motion";
import { Ban, CheckCircle2, Circle, ExternalLink, FileText, ListChecks, Pause, Play, RotateCcw, X } from "lucide-react";
import { IconBtn, Modal, Progress, StatusPill, Time, progressColors, useToast, Pill } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import { liveMode, reassignTask, taskAction, useStore } from "../../data/store";
import { go } from "../../app/router";
import type { Task } from "../../domain/types";

// Selected task detail (MC-FLOW-003): scope, acceptance criteria, evidence, blockers, dependencies, history and role-limited actions.
export function TaskInspector({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const tasks = useStore((s) => s.tasks), instances = useStore((s) => s.instances);
  const toast = useToast();
  const t = task ? tasks.find((x) => x.id === task.id) ?? task : null;
  const [c1, c2] = t ? progressColors(t.progress, t.status) : ["", ""];
  return (
    <Modal open={!!t} onClose={onClose} title={t ? `${t.id} · ${t.title}` : ""} icon={ListChecks} width={760}
      foot={t && <>
        <IconBtn icon={t.status === "paused" ? Play : Pause} label={t.status === "paused" ? "Resume task" : "Pause task"} onClick={() => { const e = taskAction(t.id, t.status === "paused" ? "resume" : "pause"); if (e) toast(e, "warn"); else if (!liveMode()) toast(`${t.id} ${t.status === "paused" ? "resumed" : "paused"}`); }} />
        <IconBtn icon={RotateCcw} label="Retry (idempotent; previous trace kept)" onClick={() => { const e = taskAction(t.id, "retry"); if (e) toast(e, "warn"); else if (!liveMode()) toast(`${t.id} retry #${t.retries + 1} queued`); }} disabled={t.status === "done"} />
        <IconBtn icon={X} label="Cancel task" tone="bad" onClick={() => { if (window.confirm(`Cancel ${t.id}? This is recorded in the audit log.`)) { const e = taskAction(t.id, "cancel"); if (e) toast(e, "warn"); else if (!liveMode()) toast(`${t.id} cancelled`, "warn"); } }} disabled={t.status === "done"} />
        <span className="ax-spacer" />
        <label className="ax-small ax-flex">Reassign
          <select className="ax-select" style={{ width: 170 }} value={t.instanceId} onChange={(e) => { reassignTask(t.id, e.target.value); toast(`${t.id} → ${e.target.value}`); }} aria-label="Reassign to agent instance">
            {instances.filter((i) => i.missionId === t.missionId).map((i) => <option key={i.id} value={i.id}>{i.id}</option>)}</select></label>
        <IconBtn icon={ExternalLink} label="Open the agent's conversation" onClick={() => { onClose(); go("control", t.missionId, { tab: "agents", agent: t.instanceId.split("@")[0] }); }} />
      </>}>
      {t && <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
        <div className="ax-col" style={{ gap: 10 }}>
          <div className="ax-flex"><StatusPill s={t.status} />{t.meta && <Pill c={{ P0: "var(--ax-bad)", P1: "var(--ax-warn)", P2: "var(--ax-blocked)", P3: "var(--ax-neutral)" }[t.meta.p]}>{t.meta.p}</Pill>}{t.critical && <Pill c="var(--ax-accent)">critical path</Pill>}</div>
          <p style={{ margin: 0 }}>{t.desc ?? t.phase}</p>
          <div><div className="ax-flex ax-small"><span>Progress (verified)</span><span className="ax-spacer" /><b className="ax-num">{t.progress}%</b></div><Progress value={t.progress} c1={c1} c2={c2} label="Task progress" /></div>
          {t.blocker && <motion.div className="ax-tile" style={{ borderColor: "var(--ax-blocked)" }} initial={{ x: -6 }} animate={{ x: 0 }}>
            <div className="ax-flex ax-small"><Ban size={14} style={{ color: "var(--ax-blocked)" }} aria-hidden /><b>Blocked:</b> {t.blocker.text}</div>
            {t.blocker.approvalId && <button type="button" className="ax-btn" style={{ marginTop: 6 }} onClick={() => { onClose(); go("control", t.missionId, { tab: "approvals", a: t.blocker!.approvalId }); }}>Open decision {t.blocker.approvalId}</button>}
          </motion.div>}
          <div><b className="ax-small">Acceptance criteria</b><ul className="ax-small" style={{ margin: "4px 0 0", paddingLeft: 0, listStyle: "none" }}>
            {t.acceptance.map((a, i) => <li key={a} className="ax-flex">{t.status === "done" || (i === 0 && t.progress > 80) ? <CheckCircle2 size={13} className="ax-ok" aria-label="met" /> : <Circle size={13} className="ax-faint" aria-label="open" />}{a}</li>)}</ul></div>
          <div><b className="ax-small">Evidence & artifacts</b><div className="ax-flex" style={{ flexWrap: "wrap", marginTop: 4 }}>{t.evidence.length ? t.evidence.map((e) => <span key={e} className="ax-chip"><FileText size={11} aria-hidden />{e}</span>) : <span className="ax-small ax-muted">None yet. Needed before the task can be marked done.</span>}</div></div>
        </div>
        <div className="ax-col" style={{ gap: 10 }}>
          <dl className="ax-kv"><dt>Assignee</dt><dd><AgentTag id={t.instanceId} sub={t.instanceId} /></dd><dt>Start</dt><dd><Time iso={t.start} withDate /></dd><dt>Due</dt><dd>{t.dueUnknown ? "Not scheduled" : <Time iso={t.end} withDate />}</dd>
            <dt>Output version</dt><dd>{t.outputVersion ?? "—"}</dd><dt>Retries</dt><dd>{t.retries}</dd><dt>Hours left</dt><dd>{t.meta?.hours ?? "—"}</dd></dl>
          <div><b className="ax-small">Depends on</b><div className="ax-col" style={{ gap: 3, marginTop: 4 }}>{t.deps.length ? t.deps.map((d) => { const dt = tasks.find((x) => x.id === d); return <span key={d} className="ax-flex ax-small">{dt && <StatusPill s={dt.status} small />}<b>{d}</b> {dt?.title}</span>; }) : <span className="ax-small ax-muted">No dependencies</span>}</div></div>
          <div><b className="ax-small">History</b><div className="ax-col" style={{ gap: 2, marginTop: 4, maxHeight: 150, overflow: "auto" }}>{[...t.history].reverse().map((h, i) => <span key={i} className="ax-xs"><span className="ax-muted"><Time iso={h.at} withDate /></span> · {h.text}</span>)}</div></div>
        </div>
      </div>}
    </Modal>
  );
}
