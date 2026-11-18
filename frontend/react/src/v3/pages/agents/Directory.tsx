import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  ArrowRight, Bot, ChevronsUp, ExternalLink, FileText, Layers, Search, ShieldCheck, TrendingUp, UserPlus, Users, Workflow, Brain, GraduationCap, Cpu, Trophy, Zap,
} from "lucide-react";
import { Avatar, ROLES } from "../../ui/Avatar";
import { Btn, Count, IconBtn, Panel, Pill, Progress, Seg, StatusPill, Tabs, useToast } from "../../ui/kit";
import { AgentTag, Dropdown } from "../../ui/widgets";
import { candidateAction, toastIfErr, useStore } from "../../data/store";
import { useQueryParam } from "../../app/router";
import { chartTip } from "../Overview";
import { HEALTH_C, HEALTH_LABEL, activeInstances, deptName, experiencesFor, healthOf, loadOf, mentorOf, sampleXp, skillScore, verifierOf, perfSeries } from "./data";
import { useSelected } from "./util";
import type { AgentIdentity } from "../../domain/types";

const cellHealth = (a: AgentIdentity) => { const h = healthOf(a); return <span style={{ color: HEALTH_C[h] }} className="ax-num" data-tip={HEALTH_LABEL[h]}><b>{Math.round(a.successRate)}%</b> <span className="ax-xs">{HEALTH_LABEL[h]}</span></span>; };

/* ---------- Agent Management table (30-4 left) ---------- */
export function AgentTable({ i = 1, onOpen, big }: { i?: number; onOpen: (id: string) => void; big?: boolean }) {
  const agents = useStore((s) => s.agents), departments = useStore((s) => s.departments), s = useStore((x) => x);
  const { id: sel, select } = useSelected(); const toast = useToast();
  const [status, setStatus] = useQueryParam("status", "all"); const [dept, setDept] = useQueryParam("dept", "all"); const [q, setQ] = useState("");
  const count = (f: (a: AgentIdentity) => boolean) => agents.filter(f).length;
  const rows = useMemo(() => agents.filter((a) =>
    (status === "all" || (status === "active" ? a.status === "active" || a.status === "busy" : healthOf(a) === status)) &&
    (dept === "all" || a.dept === dept) && (!q || `${a.id} ${a.name} ${a.title}`.toLowerCase().includes(q.toLowerCase()))), [agents, status, dept, q]);
  return (
    <Panel i={i} title="Agent Management" icon={Bot} help={{ body: "Every agent is a stable identity with a version, health and capacity. Click a row to inspect it; use the open icon for the full profile.", source: "Agent registry (sample data).", example: "Filter Degraded to see agents below 90% verified success." }}
      sub={`${rows.length} of ${agents.length}`}
      actions={<IconBtn icon={UserPlus} label="Request a new agent (the GM proposes it in Organization)" size="sm" onClick={() => toast("Sample: a new-agent request would go to the GM for an org proposal", "info")} />}>
      <div className="ax-flex" style={{ gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
        <Tabs label="Agent status filter" value={status} onChange={setStatus} tabs={[
          { id: "all", label: `All Agents (${agents.length})` }, { id: "active", label: `Active (${count((a) => a.status === "active" || a.status === "busy")})` },
          { id: "degraded", label: `Degraded (${count((a) => healthOf(a) === "degraded")})` }, { id: "at_risk", label: `At Risk (${count((a) => healthOf(a) === "at_risk")})` }]} />
        <span className="ax-search" style={{ flex: "1 1 110px", minWidth: 100 }}><Search size={14} aria-hidden /><input className="ax-input" style={{ padding: "4px 8px 4px 30px", fontSize: 12 }} placeholder="Search agents" aria-label="Search agents" value={q} onChange={(e) => setQ(e.target.value)} /></span>
        <Dropdown label="Department filter" value={dept} onChange={setDept} options={[{ id: "all", label: "All departments" }, { id: "executive", label: "Executive" }, ...departments.map((d) => ({ id: d.id, label: d.name }))]} />
      </div>
      <table className="ax-table ax-compact">
        <thead><tr><th>Agent (Role)</th><th>Department</th><th>Version</th><th>Health</th><th>Skill</th><th>Missions</th><th>Load</th><th>Evolution</th></tr></thead>
        <tbody>
          {rows.map((a, k) => {
            const load = loadOf(a);
            return (
              <motion.tr key={a.id} className={`click ${sel === a.id ? "sel" : ""}`} onClick={() => select(a.id)} onDoubleClick={() => onOpen(a.id)} tabIndex={0} aria-selected={sel === a.id}
                onKeyDown={(e) => { if (e.key === "Enter") select(a.id); }} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(k, 14) * .02 }} whileHover={{ x: 2 }}>
                <td><span className="ax-flex" style={{ gap: 6 }}><Avatar role={a.role} size={big ? 30 : 26} name={a.id} status={a.status} /><span><b>{a.id}</b><span className="ax-xs ax-muted" style={{ display: "block", whiteSpace: "nowrap" }}>{a.name}</span></span></span></td>
                <td className="ax-small">{deptName(s, a.dept)}</td>
                <td className="ax-num ax-small">{a.baseline}</td>
                <td>{cellHealth(a)}</td>
                <td className="ax-num">{skillScore(a)}</td>
                <td className="ax-num">{activeInstances(s, a.id).length}</td>
                <td style={{ minWidth: 70 }}><span className="ax-xs ax-num">{load}%</span><Progress value={load} thin label={`${a.id} load`} /></td>
                <td className="ax-small ax-num" style={{ whiteSpace: "nowrap" }}>{a.baseline}{a.candidate ? <> <ArrowRight size={10} aria-hidden /> <b style={{ color: "var(--ax-accent)" }}>{a.candidate}</b></> : <span className="ax-faint"> stable</span>}</td>
              </motion.tr>);
          })}
        </tbody>
      </table>
      {!rows.length && <p className="ax-muted ax-small">No agents match these filters.</p>}
    </Panel>
  );
}

/* ---------- Agent Detail (30-4 centre) ---------- */
export function AgentDetail({ id, i = 2, onOpen }: { id: string; i?: number; onOpen: (id: string, ptab?: string) => void }) {
  const s = useStore((x) => x); const a = s.agents.find((x) => x.id === id) ?? s.agents[0];
  const [t, setT] = useState("overview"); const toast = useToast();
  const inst = activeInstances(s, a.id); const xp = experiencesFor(s, a); const ment = s.mentoring.filter((m) => m.mentor === a.id || m.trainee === a.id);
  const dl = (k: string, icon: React.ReactNode, v: React.ReactNode) => <div className="ax-flex" style={{ gap: 8, padding: "3px 0", borderBottom: "1px solid color-mix(in srgb, var(--ax-border) 40%, transparent)", fontSize: 12 }}><span className="ax-muted ax-flex" style={{ gap: 6, width: 112, flex: "none" }}>{icon}{k}</span><span style={{ minWidth: 0 }}>{v}</span></div>;
  const h = healthOf(a);
  return (
    <Panel i={i} title={`Agent Detail — ${a.id}`} icon={Bot} help={{ body: "A stable agent identity: it keeps one baseline version and many isolated mission instances. Switch the mini-tabs to see its missions, lessons, mentor, verifier and model.", source: "Agent registry, instances, experiences, mentoring (sample data)." }}
      actions={<IconBtn icon={ExternalLink} label={`Open full profile of ${a.id}`} size="sm" onClick={() => onOpen(a.id)} />}>
      <div className="ax-flex" style={{ gap: 10, alignItems: "flex-start", marginBottom: 6 }}>
        <Avatar role={a.role} size={56} name={a.id} status={a.status} />
        <div style={{ minWidth: 0 }}>
          <div className="ax-flex" style={{ gap: 6, flexWrap: "wrap" }}><b style={{ fontSize: 18 }}>{a.id}</b><span className="ax-muted">{a.name}</span></div>
          <div className="ax-flex" style={{ gap: 4, flexWrap: "wrap", marginTop: 3 }}>
            <Pill c="var(--ax-accent2)">{a.baseline}</Pill>
            <StatusPill s={a.status === "offline" ? "failed" : a.status === "idle" ? "paused" : "running"} label={a.status[0].toUpperCase() + a.status.slice(1)} small />
            {inst.length > 1 && <Pill c="#a77bff" icon={Layers}>Multi-Mission</Pill>}
          </div>
          <p className="ax-xs ax-muted" style={{ margin: "4px 0 0" }}>{a.title}. {ROLES[a.role].label} role; verified success {a.successRate.toFixed(1)}%.</p>
        </div>
      </div>
      <Tabs wrap label="Agent detail sections" value={t} onChange={setT} tabs={[{ id: "overview", label: "Overview" }, { id: "missions", label: "Missions" }, { id: "experience", label: "Experience" }, { id: "mentoring", label: "Mentoring" }, { id: "verifier", label: "Verifier" }, { id: "model", label: "Model" }]} />
      <div style={{ marginTop: 6 }}>
        {t === "overview" && <>
          {dl("Role", <Bot size={13} aria-hidden />, `${ROLES[a.role].label} (${deptName(s, a.dept)})`)}
          {dl("Agent ID", <Cpu size={13} aria-hidden />, a.id)}
          {dl("Status", <ShieldCheck size={13} aria-hidden />, <><b style={{ color: HEALTH_C[h] }}>{a.status}</b> ({HEALTH_LABEL[h]})</>)}
          {dl("Current Version", <Layers size={13} aria-hidden />, <b style={{ color: "var(--ax-accent)" }}>{a.baseline}</b>)}
          {dl("Upgrade Candidate", <TrendingUp size={13} aria-hidden />, a.candidate ? <Pill c="#a77bff">{a.candidate}</Pill> : <span className="ax-muted">none pending</span>)}
          {dl("Model Used", <Brain size={13} aria-hidden />, a.models.join(" · "))}
          {dl("Verifier", <ShieldCheck size={13} aria-hidden />, <AgentTag id={verifierOf(a)} size={16} />)}
          {dl("Mentor", <GraduationCap size={13} aria-hidden />, <AgentTag id={mentorOf(a)} size={16} />)}
          {dl("Experience", <Trophy size={13} aria-hidden />, <><b>{sampleXp(a).toLocaleString()} XP</b> <span className="ax-xs ax-ok">(+2.7% this week, sample)</span></>)}
        </>}
        {t === "missions" && (inst.length ? inst.map((x) => <div key={x.id} className="ax-flex" style={{ gap: 8, padding: "4px 0" }}><b>{x.missionId}</b><span className="ax-xs ax-muted ax-num">{x.pinnedVersion}</span><span style={{ flex: 1 }}><Progress value={x.progress} thin label={x.id} /></span><span className="ax-xs ax-num">{x.progress}%</span></div>) : <p className="ax-muted ax-small">Not mobilized for any mission right now.</p>)}
        {t === "experience" && xp.list.slice(0, 4).map((e) => <div key={e.id} className="ax-small" style={{ padding: "3px 0", opacity: e.eligible ? 1 : .6 }}><b className={e.eligible ? "ax-ok" : "ax-faint"}>{e.eligible ? "Eligible" : "Excluded"}</b> · {e.lesson}</div>)}
        {t === "mentoring" && (ment.length ? ment.map((m) => <div key={m.id} className="ax-small" style={{ padding: "3px 0" }}><b>{m.mentor}</b> <ArrowRight size={10} aria-hidden /> <b>{m.trainee}</b> · {m.module} · {m.progress}%</div>) : <p className="ax-muted ax-small">No active mentoring. Default mentor: {mentorOf(a)}.</p>)}
        {t === "verifier" && <><AgentTag id={verifierOf(a)} size={26} sub="Independent verifier: never the author of the candidate" /><p className="ax-small ax-muted">Verifies benchmarks and the privacy filter before any lesson becomes part of {a.id}'s baseline.</p></>}
        {t === "model" && a.models.map((m) => <div key={m} className="ax-small ax-flex" style={{ gap: 6, padding: "3px 0" }}><Cpu size={13} aria-hidden />{m}</div>)}
      </div>
      <div className="ax-flex" style={{ gap: 6, marginTop: 6 }}><Btn icon={FileText} onClick={() => onOpen(a.id, "audit")}>Audit</Btn><Btn icon={Zap} onClick={() => toast(`Sample: ${a.id} would be asked to report status`, "info")}>Ask status</Btn></div>
    </Panel>
  );
}

/* ---------- bottom panels ---------- */
export function SkillRadar({ a, i = 4, size = 150 }: { a: AgentIdentity; i?: number; size?: number }) {
  const data = a.skills.map((k) => ({ skill: k.name, v: k.level }));
  return (
    <Panel i={i} title="Agent Skills & Competency" icon={Workflow} help={{ body: "Skill levels are verified scores (0 to 100) from benchmarks, not self-reported claims. The number in the middle is the average.", source: "Benchmark results (sample data)." }}>
      <div style={{ position: "relative", height: "100%", minHeight: size }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} outerRadius="68%"><PolarGrid stroke="var(--ax-border)" /><PolarAngleAxis dataKey="skill" tick={{ fill: "var(--ax-muted)", fontSize: 10 }} />
            <Radar dataKey="v" stroke="var(--ax-accent2)" fill="var(--ax-accent2)" fillOpacity={.35} isAnimationActive /><Tooltip {...chartTip} /></RadarChart>
        </ResponsiveContainer>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none" }}><span style={{ textAlign: "center", lineHeight: 1 }}><b style={{ fontSize: 20 }}><Count value={skillScore(a)} decimals={1} /></b><small className="ax-muted" style={{ display: "block", fontSize: 9 }}>Skill Score</small></span></div>
      </div>
    </Panel>
  );
}
export function InstancesPanel({ a, i = 5, onOpen }: { a: AgentIdentity; i?: number; onOpen: (ptab: string) => void }) {
  const s = useStore((x) => x); const [f, setF] = useState<"active" | "completed" | "all">("active");
  const all = s.instances.filter((x) => x.agentId === a.id); const act = all.filter((x) => x.status !== "done"); const done = all.filter((x) => x.status === "done");
  const list = f === "active" ? act : f === "completed" ? done : all;
  return (
    <Panel i={i} title={`Mission Instances (${a.id})`} icon={Layers} help="Each instance is an isolated copy of this agent pinned to one version for one mission. Nothing crosses missions until the experience is verified and merged."
      actions={<IconBtn icon={ExternalLink} label="Open instances with branch and merge" size="sm" onClick={() => onOpen("instances")} />}>
      <Seg label="Instance filter" value={f} onChange={setF} items={[{ id: "active", label: `Active (${act.length})` }, { id: "completed", label: `Completed (${done.length})` }, { id: "all", label: `All (${all.length})` }]} />
      <div style={{ marginTop: 5 }}>
        {list.slice(0, 5).map((x, k) => { const m = s.missions.find((y) => y.id === x.missionId); return (
          <motion.div key={x.id} className="ax-flex" style={{ gap: 8, padding: "4px 2px", borderBottom: "1px solid color-mix(in srgb, var(--ax-border) 40%, transparent)" }} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
            <span style={{ flex: 1, minWidth: 0 }}><b className="ax-small">{x.missionId}</b><span className="ax-xs ax-muted" style={{ display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m?.title}</span></span>
            <StatusPill s={x.status} small /><span className="ax-xs ax-num" style={{ width: 30, textAlign: "right" }}>{x.progress}%</span></motion.div>); })}
        {!list.length && <p className="ax-muted ax-small">No {f} instances.</p>}
      </div>
    </Panel>
  );
}
export function EvolutionPanel({ a, i = 6, onOpen }: { a: AgentIdentity; i?: number; onOpen: (ptab: string) => void }) {
  const cands = useStore((x) => x.candidates); const c = cands.find((x) => x.agentId === a.id && x.status !== "rolled_back" && x.status !== "rejected");
  const toast = useToast(); const [confirm, setConfirm] = useState(false);
  return (
    <Panel i={i} title="Evolution & Upgrade" icon={ChevronsUp} help={{ body: "A candidate version is only promoted when an independent verifier confirms it beats the baseline. The Promote icon stays disabled until then.", policy: "Promotion only if verified better (EVAL-002)." }}
      actions={<IconBtn icon={ExternalLink} label="Open evolution detail" size="sm" onClick={() => onOpen("evolution")} />}>
      {c ? <>
        <div className="ax-flex" style={{ gap: 6, justifyContent: "center" }}>
          <div className="ax-tile" style={{ textAlign: "center", flex: 1 }}><span className="ax-xs ax-muted">Current</span><b style={{ display: "block", fontSize: 16 }}>{c.from}</b></div><ArrowRight size={16} aria-hidden />
          <div className="ax-tile" style={{ textAlign: "center", flex: 1, borderColor: "#a77bff" }}><span className="ax-xs ax-muted">Candidate</span><b style={{ display: "block", fontSize: 16 }}>{c.to}</b></div></div>
        <div style={{ marginTop: 5 }}>{c.metrics.slice(0, 4).map((m) => { const d = m.higherBetter ? m.cand - m.base : m.base - m.cand; return (
          <div key={m.name} className="ax-flex ax-small" style={{ gap: 6, padding: "1px 0" }}><span style={{ flex: 1 }}>{m.name}</span><b className={d >= 0 ? "ax-ok" : "ax-bad"}>{d >= 0 ? "+" : ""}{(+d.toFixed(2))}{m.unit}</b></div>); })}</div>
        <div className="ax-flex" style={{ gap: 6, marginTop: 6 }}>
          <Btn tone="gold" icon={ChevronsUp} disabled={c.status !== "passed"} data-tip={c.status === "passed" ? undefined : `Not verified yet (${c.status})`} onClick={() => setConfirm(true)} style={{ flex: 1, justifyContent: "center" }}>Promote to {c.to}</Btn>
          {c.status !== "passed" && <span className="ax-xs ax-warn">needs verification</span>}</div>
        {confirm && <PromoteConfirm id={c.id} agent={a.id} to={c.to} onClose={() => setConfirm(false)} onDone={() => { if (!toastIfErr(candidateAction(c.id, "promote"), toast)) toast(`${a.id} baseline is now ${c.to} (sample data; nothing deployed)`, "ok"); setConfirm(false); }} />}
      </> : <p className="ax-muted ax-small">No candidate is pending for {a.id}. Eligible lessons accumulate until the GM proposes one.</p>}
    </Panel>
  );
}
import { Modal } from "../../ui/kit";
export function PromoteConfirm({ agent, to, onClose, onDone }: { id: string; agent: string; to: string; onClose: () => void; onDone: () => void }) {
  return <Modal open onClose={onClose} title={`Promote ${agent} to ${to}?`} icon={ChevronsUp} width={440} foot={<><Btn onClick={onClose}>Cancel</Btn><Btn tone="gold" icon={ChevronsUp} onClick={onDone}>Promote</Btn></>}>
    <p className="ax-small">The verified candidate becomes the new baseline of {agent}; the old baseline is kept and can be rolled back from the Audit tab. Running mission instances keep their pinned version. This changes sample data only.</p></Modal>;
}
export function VerifierPanel({ a, i = 7 }: { a: AgentIdentity; i?: number }) {
  const ver = verifierOf(a); const toast = useToast();
  const checks: [string, string][] = [["Output verification", "100%"], ["Evidence check", "99.6%"], ["Quality gate", "97.8%"], ["Approval latency", "2.4 min"]];
  return (
    <Panel i={i} title="Verifier Relationship" icon={ShieldCheck} help="Every agent is verified by a different, independent agent. The verifier checks outputs, evidence and quality gates, and cannot be the author of the work (sample values).">
      <div className="ax-flex" style={{ gap: 10, justifyContent: "center", marginBottom: 6 }}><AgentTag id={a.id} size={34} sub={ROLES[a.role].label} /><motion.span animate={{ x: [-3, 3, -3] }} transition={{ repeat: Infinity, duration: 2 }}><Workflow size={18} aria-hidden /></motion.span><AgentTag id={ver} size={34} sub="Verifier" /></div>
      {checks.map(([k, v]) => <div key={k} className="ax-flex ax-small" style={{ gap: 6, padding: "1px 0" }}><ShieldCheck size={13} className="ax-ok" aria-hidden /><span style={{ flex: 1 }}>{k}</span><b>{v}</b></div>)}
      <div style={{ marginTop: 5 }}><Btn icon={FileText} onClick={() => toast("Sample: verification logs would open here", "info")}>View Verification Logs</Btn></div>
    </Panel>
  );
}
export function MentoringPanel({ a, i = 8 }: { a: AgentIdentity; i?: number }) {
  const ment = useStore((x) => x.mentoring); const mine = ment.filter((m) => m.mentor === a.id || m.trainee === a.id);
  const ser = useMemo(() => perfSeries(a).filter((_, k) => k % 3 === 0).map((p, k) => ({ d: p.day, xp: sampleXp(a) - 900 + k * 120 })), [a]);
  const trainees = ment.filter((m) => m.mentor === a.id).map((m) => m.trainee);
  return (
    <Panel i={i} title="Mentoring & Experience" icon={GraduationCap} help="Who trains this agent, whom it trains, and how verified experience accumulates over time (XP values are sample data).">
      <div className="ax-flex ax-small" style={{ gap: 6 }}><GraduationCap size={14} aria-hidden /><b>Mentor:</b><AgentTag id={mentorOf(a)} size={16} /></div>
      <div className="ax-flex ax-small" style={{ gap: 6, margin: "3px 0" }}><Users size={14} aria-hidden /><b>Mentees ({trainees.length}):</b> {trainees.length ? trainees.join(", ") : <span className="ax-muted">none</span>}{mine.length > trainees.length && <span className="ax-muted">; in training: {mine.filter((m) => m.trainee === a.id).map((m) => m.module).join(", ")}</span>}</div>
      <div className="ax-flex ax-small" style={{ gap: 6 }}><b>Experience Growth</b><span className="ax-spacer" /><b>{sampleXp(a).toLocaleString()} XP</b></div>
      <div style={{ height: 70 }}><ResponsiveContainer width="100%" height="100%"><AreaChart data={ser} margin={{ left: -24, right: 4, top: 4, bottom: 0 }}><XAxis dataKey="d" tick={{ fontSize: 9, fill: "var(--ax-muted)" }} /><YAxis tick={{ fontSize: 9, fill: "var(--ax-muted)" }} domain={["dataMin", "dataMax"]} /><Tooltip {...chartTip} /><Area dataKey="xp" stroke="var(--ax-accent2)" fill="var(--ax-accent2)" fillOpacity={.25} /></AreaChart></ResponsiveContainer></div>
    </Panel>
  );
}
