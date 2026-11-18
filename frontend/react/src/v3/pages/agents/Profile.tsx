import { useState, type ReactNode } from "react";
import { motion } from "framer-motion";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  Activity, ArrowRight, Ban, Brain, CheckCircle2, ChevronsUp, Clock3, Coins, Cpu, FlaskConical, GitBranch, GitCommitHorizontal, GraduationCap, History, KeyRound, Layers, Lock, RotateCcw, ScrollText,
  ShieldCheck, Sparkles, Target, Timer, Trophy, Wrench, XCircle, Lightbulb, Network, Copy,
} from "lucide-react";
import { Avatar, ROLES } from "../../ui/Avatar";
import { Btn, CopyBtn, IconBtn, Kpi, Modal, Panel, Pill, Progress, Seg, StatusPill, TabBody, Tabs, Time, useToast, Empty, Count } from "../../ui/kit";
import { AgentTag, Dropdown } from "../../ui/widgets";
import { candidateAction, rollbackAgentVersion, toastIfErr, useStore } from "../../data/store";
import { chartTip } from "../Overview";
import { BranchMerge } from "./BranchMerge";
import { PromoteConfirm } from "./Directory";
import { activeInstances, deptName, experiencesFor, healthOf, HEALTH_C, HEALTH_LABEL, mentorOf, perfSeries, skillScore, verifierOf, versionsFor } from "./data";
import { missionColor, useSelected } from "./util";
import { useQueryParam } from "../../app/router";
import type { AgentIdentity, Candidate } from "../../domain/types";

const PTABS = [
  { id: "capabilities", label: "Capabilities", icon: Sparkles }, { id: "instances", label: "Mission Instances", icon: Layers }, { id: "experience", label: "Experience", icon: Lightbulb },
  { id: "evolution", label: "Evolution", icon: ChevronsUp }, { id: "mentoring", label: "Mentoring", icon: GraduationCap }, { id: "performance", label: "Performance", icon: Activity }, { id: "audit", label: "Audit", icon: History },
];
const tile = (title: string, icon: ReactNode, body: ReactNode, extra?: React.CSSProperties) => <div className="ax-tile" style={{ display: "flex", flexDirection: "column", minHeight: 0, ...extra }}><div className="ax-flex" style={{ gap: 6, marginBottom: 5, fontWeight: 650 }}>{icon}{title}</div><div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{body}</div></div>;
const TOOL_ICON: Record<string, typeof Wrench> = {};

export function ProfileView({ a }: { a: AgentIdentity }) {
  const [pt, setPt] = useQueryParam("ptab", "capabilities"); const { select } = useSelected();
  const s = useStore((x) => x); const agents = s.agents; const h = healthOf(a); const inst = activeInstances(s, a.id);
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto minmax(0,1fr)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={1} title={`Agent Profile — ${a.id}`} icon={Cpu} help={{ body: "The stable identity of one agent: who it is, what it can do and where it has worked. Missions only ever see isolated instances of it (spec 4.10).", source: "Agent registry (sample data)." }}
        actions={<><Dropdown label="Select agent" value={a.id} onChange={select} options={agents.map((x) => ({ id: x.id, label: `${x.id} · ${x.name}` }))} /><CopyBtn text={a.id} label="Copy agent id" /></>}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(250px,1.1fr) repeat(5, minmax(0,1fr))", gap: "var(--ax-gap)", alignItems: "center" }}>
          <div className="ax-flex" style={{ gap: 10 }}><Avatar role={a.role} size={52} name={a.id} status={a.status} />
            <div style={{ minWidth: 0 }}><b style={{ fontSize: 18 }}>{a.id}</b> <span className="ax-muted">{a.name}</span>
              <div className="ax-flex" style={{ gap: 4, flexWrap: "wrap", marginTop: 3 }}><Pill c="var(--ax-accent2)">{a.baseline}</Pill>{a.candidate && <Pill c="#a77bff" icon={FlaskConical}>{a.candidate}</Pill>}<Pill c={HEALTH_C[h]}>{HEALTH_LABEL[h]}</Pill><Pill c={ROLES[a.role].c}>{deptName(s, a.dept)}</Pill></div></div></div>
          <Kpi i={0} icon={Trophy} c="#2fd27a" value={a.successRate} decimals={1} suffix="%" label="Verified success" />
          <Kpi i={1} icon={Target} c="#3b8cff" value={a.tasksDone} label="Tasks done" />
          <Kpi i={2} icon={Layers} c="#a77bff" value={inst.length} label="Active missions" />
          <Kpi i={3} icon={Coins} c="#f2b53a" value={a.costPerTask} decimals={2} prefix="$" label="Cost / task" />
          <Kpi i={4} icon={Timer} c="#22d3ee" value={a.latencyS} suffix=" s" label="Latency" />
        </div>
      </Panel>
      <Panel i={2} title="Profile" icon={ScrollText} help="Seven views of one agent: what it can do, where it works, what it learned, how it evolves, who mentors it, how it performs and its version audit trail."
        tabs={<Tabs label="Profile sections" tabs={PTABS} value={pt} onChange={setPt} />}>
        <TabBody k={pt}>
          {pt === "capabilities" && <Capabilities a={a} />}
          {pt === "instances" && <Instances a={a} />}
          {pt === "experience" && <Experience a={a} />}
          {pt === "evolution" && <EvolutionTab a={a} />}
          {pt === "mentoring" && <MentoringTab a={a} />}
          {pt === "performance" && <PerformanceTab a={a} />}
          {pt === "audit" && <AuditTab a={a} />}
        </TabBody>
      </Panel>
    </div>
  );
}

/* ---- Capabilities ---- */
function Capabilities({ a }: { a: AgentIdentity }) {
  const data = a.skills.map((k) => ({ skill: k.name, v: k.level }));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 1fr", gap: "var(--ax-gap)", height: "100%" }}>
      {tile("Skills radar", <Sparkles size={15} className="ax-gold" aria-hidden />, <div style={{ position: "relative", height: "100%", minHeight: 200 }}>
        <ResponsiveContainer width="100%" height="100%"><RadarChart data={data} outerRadius="70%"><PolarGrid stroke="var(--ax-border)" /><PolarAngleAxis dataKey="skill" tick={{ fill: "var(--ax-text)", fontSize: 11 }} />
          <Radar dataKey="v" stroke="var(--ax-accent2)" fill="var(--ax-accent2)" fillOpacity={.35} /><Tooltip {...chartTip} /></RadarChart></ResponsiveContainer>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none" }}><b style={{ fontSize: 22 }}><Count value={skillScore(a)} decimals={1} /></b></div></div>)}
      {tile("Skills (verified level)", <Target size={15} className="ax-gold" aria-hidden />, <>{a.skills.map((k) => <div key={k.name} style={{ marginBottom: 7 }}><div className="ax-flex ax-small"><span style={{ flex: 1 }}>{k.name}</span><b className="ax-num">{k.level}</b></div><Progress value={k.level} thin label={k.name} /></div>)}
        <div className="ax-xs ax-muted" style={{ marginTop: 6 }}>Qualified to lead: {a.qualified.join(", ")}</div></>)}
      {tile("Tools & models", <Wrench size={15} className="ax-gold" aria-hidden />, <>
        <div className="ax-xs ax-muted">Tools</div><div className="ax-flex" style={{ gap: 4, flexWrap: "wrap", margin: "3px 0 8px" }}>{a.tools.map((t) => <Pill key={t} c="var(--ax-info)" icon={TOOL_ICON[t] ?? Wrench}>{t}</Pill>)}</div>
        <div className="ax-xs ax-muted">Models (via the model registry)</div><div style={{ marginTop: 3 }}>{a.models.map((m) => <div key={m} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><Brain size={13} aria-hidden />{m}</div>)}</div></>)}
      {tile("Permissions", <KeyRound size={15} className="ax-gold" aria-hidden />, <>{a.permissions.map((p) => <div key={p} className="ax-flex ax-small" style={{ gap: 6, padding: "3px 0" }}><CheckCircle2 size={13} className="ax-ok" aria-hidden />{p}</div>)}
        <div className="ax-xs ax-muted" style={{ margin: "8px 0 3px" }}>Never granted to any agent</div>
        {["merge to protected branches", "change own permissions", "approve own candidate"].map((p) => <div key={p} className="ax-flex ax-small ax-muted" style={{ gap: 6, padding: "2px 0" }}><Ban size={13} className="ax-bad" aria-hidden />{p}</div>)}
        <div className="ax-flex ax-xs ax-muted" style={{ gap: 4, marginTop: 8 }}><Lock size={11} aria-hidden />Mission instances inherit these permissions, scoped to their mission.</div></>)}
    </div>
  );
}

/* ---- Mission instances ---- */
function Instances({ a }: { a: AgentIdentity }) {
  const s = useStore((x) => x); const mine = s.instances.filter((i) => i.agentId === a.id);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(380px,.95fr) 1.25fr", gap: "var(--ax-gap)", height: "100%" }}>
      {tile("Branch & merge: stem, mission branches, merge back", <GitBranch size={15} className="ax-gold" aria-hidden />, <>
        <BranchMerge agentId={a.id} max={4} />
        <p className="ax-xs ax-muted" style={{ marginTop: 8 }}>One agent can be mobilized for several missions that run separately. When a mission completes, its verified experience is combined back into the original agent, like branching from the stem and merging back.</p></>)}
      {tile(`Instances (${mine.length})`, <Layers size={15} className="ax-gold" aria-hidden />, mine.length ? <table className="ax-table ax-compact"><thead><tr><th>Instance</th><th>Mission</th><th>Pinned</th><th>Branch</th><th>Status</th><th>Progress</th><th>Tasks</th><th>Errors</th><th>Spend</th></tr></thead>
        <tbody>{mine.map((i, k) => { const m = s.missions.find((x) => x.id === i.missionId); return (
          <motion.tr key={i.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
            <td><b style={{ color: missionColor(i.missionId) }}>{i.id}</b></td><td className="ax-small">{m?.title ?? i.missionId}</td><td className="ax-num">{i.pinnedVersion}</td>
            <td><code className="ax-xs" style={{ whiteSpace: "nowrap" }}>{i.branch}</code></td><td><StatusPill s={i.status} small /></td><td style={{ minWidth: 80 }}><Progress value={i.progress} thin label={i.id} /></td>
            <td className="ax-num">{i.tasks}</td><td className={`ax-num ${i.errors ? "ax-bad" : ""}`}>{i.errors}</td><td className="ax-num">${i.spend}</td></motion.tr>); })}</tbody></table>
        : <Empty icon={GitBranch} title="No mission instances">{a.id} has not been mobilized yet.</Empty>)}
    </div>
  );
}

/* ---- Experience ---- */
const KIND_C: Record<string, string> = { verified: "var(--ax-ok)", tentative: "var(--ax-warn)", code: "var(--ax-info)", security: "var(--ax-bad)", private: "var(--ax-neutral)" };
function Experience({ a }: { a: AgentIdentity }) {
  const s = useStore((x) => x); const { list, sample } = experiencesFor(s, a); const [f, setF] = useState<"all" | "eligible" | "excluded">("all");
  const rows = list.filter((e) => f === "all" || (f === "eligible") === e.eligible);
  const el = list.filter((e) => e.eligible).length;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 290px", gap: "var(--ax-gap)", height: "100%" }}>
      {tile(`Lessons from missions (${list.length})`, <Lightbulb size={15} className="ax-gold" aria-hidden />, <>
        <div className="ax-flex" style={{ gap: 8, marginBottom: 6 }}><Seg label="Lesson filter" value={f} onChange={setF} items={[{ id: "all", label: `All (${list.length})` }, { id: "eligible", label: `Eligible (${el})` }, { id: "excluded", label: `Excluded (${list.length - el})` }]} />{sample && <Pill c="var(--ax-warn)">Sample lessons</Pill>}</div>
        <table className="ax-table ax-compact"><thead><tr><th>Lesson</th><th>Kind</th><th>Mission</th><th>Confidence</th><th>Generalizes</th><th>Merge</th><th>Evidence</th></tr></thead>
          <tbody>{rows.map((e, k) => <motion.tr key={e.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .04 }} style={{ opacity: e.eligible ? 1 : .7 }}>
            <td style={{ maxWidth: 300 }}>{e.lesson}</td><td><Pill c={KIND_C[e.kind]}>{e.kind}</Pill></td><td className="ax-num">{e.missionId}</td>
            <td style={{ minWidth: 80 }}><span className="ax-xs ax-num">{Math.round(e.confidence * 100)}%</span><Progress value={e.confidence * 100} thin label="confidence" /></td>
            <td className="ax-num">{Math.round(e.generalization * 100)}%</td>
            <td>{e.eligible ? <span className="ax-ok ax-flex" style={{ gap: 3 }}><CheckCircle2 size={13} aria-hidden />Eligible</span> : <span className="ax-faint ax-flex" style={{ gap: 3 }}><Ban size={13} aria-hidden />Excluded</span>}</td>
            <td className="ax-xs ax-muted">{e.evidence}</td></motion.tr>)}</tbody></table></>)}
      {tile("Privacy filter (AG-004)", <ShieldCheck size={15} className="ax-gold" aria-hidden />, <>
        <p className="ax-small" style={{ marginTop: 0 }}>Only lessons that are <b>verified</b>, <b>generalizable</b> and free of mission-private data flow back into the stem agent.</p>
        {[["Verified evidence", "needs a log, run or scan reference"], ["Confidence ≥ 80%", "tentative ones wait for more observations"], ["No private data", "customer content, secrets and tokens stay in the mission"], ["Independent check", `${verifierOf(a)} reviews every merge`]].map(([t, d]) => <div key={t} className="ax-flex" style={{ gap: 6, padding: "4px 0", alignItems: "flex-start" }}><CheckCircle2 size={14} className="ax-ok" style={{ flex: "none", marginTop: 2 }} aria-hidden /><span className="ax-small"><b>{t}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{d}</span></span></div>)}
        <div className="ax-tile" style={{ marginTop: 8 }}><div className="ax-flex ax-small"><span style={{ flex: 1 }}>Eligible for the next candidate</span><b className="ax-ok">{el}</b></div><div className="ax-flex ax-small"><span style={{ flex: 1 }}>Excluded by the filter</span><b className="ax-faint">{list.length - el}</b></div></div></>)}
    </div>
  );
}

/* ---- Evolution ---- */
const LIFE = ["proposed", "experiment", "evaluating", "passed", "promoted"] as const;
function EvolutionTab({ a }: { a: AgentIdentity }) {
  const s = useStore((x) => x); const toast = useToast(); const [confirm, setConfirm] = useState(false);
  const mine = s.candidates.filter((c) => c.agentId === a.id).sort((x, y) => +new Date(y.at) - +new Date(x.at));
  const [sel, setSel] = useState<string | null>(null);
  const c: Candidate | undefined = mine.find((x) => x.id === sel) ?? mine.find((x) => x.status !== "rolled_back" && x.status !== "rejected") ?? mine[0];
  const vers = versionsFor(s, a); const base = vers.find((v) => v.version === c?.from), cv = vers.find((v) => v.version === c?.to);
  if (!c) return <Empty icon={FlaskConical} title="No candidate versions">No evolution candidate exists for {a.id}. The GM proposes one once enough eligible experience has accumulated.</Empty>;
  const idx = LIFE.indexOf(c.status as typeof LIFE[number]);
  const bars = c.metrics.map((m) => ({ name: m.name, gain: m.base === 0 ? 0 : +(((m.higherBetter ? m.cand - m.base : m.base - m.cand) / m.base) * 100).toFixed(1) }));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "230px 1.15fr 1fr", gap: "var(--ax-gap)", height: "100%" }}>
      {tile("Candidates", <FlaskConical size={15} className="ax-gold" aria-hidden />, mine.map((x) => <div key={x.id} className={`ax-row click ${x.id === c.id ? "sel" : ""}`} role="button" tabIndex={0} onClick={() => setSel(x.id)} onKeyDown={(e) => e.key === "Enter" && setSel(x.id)} style={{ marginBottom: 4 }}>
        <span className="grow"><b className="t">{x.from} → {x.to}</b><span className="s">{x.title}</span></span><StatusPill s={x.status === "passed" ? "passed" : x.status === "failed" ? "failed" : x.status === "promoted" ? "done" : x.status === "rolled_back" ? "rolled_back" : x.status === "rejected" ? "cancelled" : "verifying"} label={x.status.replace("_", " ")} small /></div>))}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--ax-gap)", minHeight: 0 }}>
        {tile(`Baseline ${c.from} vs candidate ${c.to}`, <GitCommitHorizontal size={15} className="ax-gold" aria-hidden />, <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div><Pill c="var(--ax-neutral)">Baseline {c.from}</Pill><div className="ax-xs ax-muted" style={{ marginTop: 4 }}>score {base?.score ?? "-"}</div>{(base?.changes ?? ["Current production behaviour"]).map((x) => <div key={x} className="ax-small" style={{ padding: "2px 0" }}>{x}</div>)}</div>
            <div><Pill c="#a77bff" icon={FlaskConical}>Candidate {c.to}</Pill><div className="ax-xs ax-muted" style={{ marginTop: 4 }}>score {cv?.score ?? "-"} · {c.kind} change · risk {c.risk}</div>{(cv?.changes ?? [c.summary]).map((x) => <div key={x} className="ax-small ax-ok" style={{ padding: "2px 0" }}>+ {x}</div>)}</div></div>
          <p className="ax-xs ax-muted" style={{ marginBottom: 0 }}>Built from verified lessons of {c.sourceInstances.join(", ")}. Evaluator: {c.evaluator} (independent).</p></>, { flex: "none" })}
        {tile("Lifecycle", <Network size={15} className="ax-gold" aria-hidden />, <div className="ax-flex" style={{ gap: 4, flexWrap: "wrap" }}>{LIFE.map((st, k) => <span key={st} className="ax-flex" style={{ gap: 4 }}><Pill c={k <= idx ? "var(--ax-ok)" : "var(--ax-neutral)"} icon={k <= idx ? CheckCircle2 : Clock3}>{st}</Pill>{k < LIFE.length - 1 && <ArrowRight size={11} aria-hidden />}</span>)}
          {["failed", "rejected", "rolled_back"].includes(c.status) && <Pill c="var(--ax-bad)" icon={XCircle}>{c.status.replace("_", " ")}</Pill>}</div>, { flex: "none" })}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--ax-gap)", minHeight: 0 }}>
        {tile(`Benchmarks (${c.delta >= 0 ? "+" : ""}${c.delta}% overall)`, <Activity size={15} className="ax-gold" aria-hidden />, <>
          {c.metrics.map((m) => { const d = m.higherBetter ? m.cand - m.base : m.base - m.cand; return <div key={m.name} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><span style={{ flex: 1 }}>{m.name}</span><span className="ax-num ax-muted">{m.base}{m.unit} → {m.cand}{m.unit}</span><b className={d > 0 ? "ax-ok" : d < 0 ? "ax-bad" : "ax-muted"} style={{ width: 54, textAlign: "right" }}>{d > 0 ? "better" : d < 0 ? "worse" : "same"}</b></div>; })}
          <div style={{ height: 90 }}><ResponsiveContainer width="100%" height="100%"><BarChart data={bars} margin={{ left: -20, right: 4, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 9, fill: "var(--ax-muted)" }} /><YAxis tick={{ fontSize: 9, fill: "var(--ax-muted)" }} /><Tooltip {...chartTip} /><Bar dataKey="gain" name="Improvement %" radius={[3, 3, 0, 0]}>{bars.map((d) => <Cell key={d.name} fill={d.gain >= 0 ? "var(--ax-ok)" : "var(--ax-bad)"} />)}</Bar></BarChart></ResponsiveContainer></div></>, { flex: 1 })}
        {tile("Decision", <ShieldCheck size={15} className="ax-gold" aria-hidden />, <>
          <div className="ax-small" style={{ marginBottom: 6 }}>{c.status === "passed" ? <span className="ax-ok">Independently verified better than baseline. Promotion is allowed.</span> : c.status === "promoted" ? <span className="ax-ok">Promoted; canary {c.canary ?? 0}%.</span> : <span className="ax-warn">Not verified better yet ({c.status.replace("_", " ")}); promotion is locked.</span>}</div>
          <div className="ax-flex" style={{ gap: 6 }}>
            <Btn tone="gold" icon={ChevronsUp} disabled={c.status !== "passed"} onClick={() => setConfirm(true)}>Promote to {c.to}</Btn>
            <IconBtn icon={FlaskConical} label="Run independent evaluation" disabled={c.status === "evaluating" || c.status === "promoted"} onClick={() => { if (!toastIfErr(candidateAction(c.id, "evaluate"), toast)) toast(`Evaluation of ${c.to} started by ${c.evaluator} (simulated)`, "info"); }} />
            <IconBtn icon={XCircle} tone="bad" label="Reject candidate" disabled={c.status === "promoted" || c.status === "rejected"} onClick={() => { if (!toastIfErr(candidateAction(c.id, "reject"), toast)) toast(`${c.to} rejected`, "warn"); }} /></div></>, { flex: "none" })}
      </div>
      {confirm && <PromoteConfirm id={c.id} agent={a.id} to={c.to} onClose={() => setConfirm(false)} onDone={() => { if (!toastIfErr(candidateAction(c.id, "promote"), toast)) toast(`${a.id} baseline is now ${c.to} (sample data; nothing deployed)`); setConfirm(false); }} />}
    </div>
  );
}

/* ---- Mentoring ---- */
function MentoringTab({ a }: { a: AgentIdentity }) {
  const ment = useStore((x) => x.mentoring); const toast = useToast();
  const mine = ment.filter((m) => m.mentor === a.id || m.trainee === a.id);
  const mt = (m: typeof ment[number], k: number, hl: boolean) => (
    <motion.div key={m.id} className="ax-tile" style={{ borderColor: hl ? "var(--ax-accent)" : undefined }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .05 }}>
      <div className="ax-flex" style={{ gap: 8 }}><AgentTag id={m.mentor} size={26} sub="Mentor" /><ArrowRight size={14} aria-hidden /><AgentTag id={m.trainee} size={26} sub="Trainee" /><span className="ax-spacer" /><StatusPill s={m.status} small /></div>
      <div className="ax-small" style={{ margin: "5px 0 3px" }}><b>{m.module}</b> <span className="ax-muted">· {m.transfers} knowledge transfers</span></div>
      <Progress value={m.progress} thin label={m.module} />
      <div className="ax-flex ax-xs" style={{ gap: 8, marginTop: 4 }}><span>{m.progress}% complete</span><span className="ax-spacer" /><ShieldCheck size={12} aria-hidden /><span>Verifier {m.verifier}</span><span>·</span><span>{m.assessment == null ? "assessment pending" : `assessment ${m.assessment}% ${m.assessment >= 80 ? "(pass)" : "(fail: below 80%)"}`}</span></div>
    </motion.div>);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 300px", gap: "var(--ax-gap)", height: "100%" }}>
      {tile(`${a.id} mentoring (${mine.length})`, <GraduationCap size={15} className="ax-gold" aria-hidden />, <div style={{ display: "grid", gap: 6 }}>{mine.map((m, k) => mt(m, k, true))}
        {!mine.length && <Empty icon={GraduationCap} title="No mentoring relationship">Default mentor: {mentorOf(a)}. A trainee only learns what the mentor has verified.</Empty>}</div>)}
      {tile(`All programs (${ment.length})`, <Network size={15} className="ax-gold" aria-hidden />, <div style={{ display: "grid", gap: 6 }}>{ment.map((m, k) => mt(m, k, false))}</div>)}
      {tile("How mentoring works", <Lightbulb size={15} className="ax-gold" aria-hidden />, <>
        {["Mentor shares a verified procedure or skill (not raw mission data).", "The trainee practises it in an isolated exercise.", "An independent verifier assesses the trainee; below 80% the module fails.", "Only a passed module becomes part of the trainee's next candidate."].map((t, k) => <div key={t} className="ax-flex ax-small" style={{ gap: 8, padding: "5px 0", alignItems: "flex-start" }}><b className="ax-gold" style={{ width: 16 }}>{k + 1}</b>{t}</div>)}
        <div style={{ marginTop: 8 }}><Btn icon={GraduationCap} onClick={() => toast(`Sample: a mentoring module for ${a.id} would be proposed to ${mentorOf(a)}`, "info")}>Propose a module</Btn></div></>)}
    </div>
  );
}

/* ---- Performance ---- */
function PerformanceTab({ a }: { a: AgentIdentity }) {
  const ser = perfSeries(a); const axis = { tick: { fontSize: 10, fill: "var(--ax-muted)" } };
  const card = (title: string, node: ReactNode) => tile(title, <Activity size={15} className="ax-gold" aria-hidden />, <div style={{ height: "100%", minHeight: 150 }}>{node}</div>);
  const mk = (key: string, c: string, dom?: [number | string, number | string]) => <ResponsiveContainer width="100%" height="100%"><LineChart data={ser} margin={{ left: -18, right: 6, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="day" {...axis} interval={6} /><YAxis {...axis} domain={dom ?? ["auto", "auto"]} /><Tooltip {...chartTip} /><Line dataKey={key} stroke={c} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", height: "100%" }}>
      {card("Verified success rate (%, 30 d)", mk("success", "var(--ax-ok)"))}
      {card("Cost per task ($)", mk("cost", "var(--ax-accent)"))}
      {card("Latency (s)", mk("latency", "var(--ax-info)"))}
      {card("Tasks per day", <ResponsiveContainer width="100%" height="100%"><BarChart data={ser} margin={{ left: -18, right: 6, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="day" {...axis} interval={6} /><YAxis {...axis} /><Tooltip {...chartTip} /><Bar dataKey="tasks" fill="var(--ax-accent2)" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>)}
      {tile("Verified metrics", <ShieldCheck size={15} className="ax-gold" aria-hidden />, <>
        {[["Verified success", `${a.successRate.toFixed(1)}%`], ["Tasks completed", a.tasksDone], ["Cost / task", `$${a.costPerTask}`], ["Latency", `${a.latencyS} s`], ["Skill score", skillScore(a)]].map(([k, v]) => <div key={k as string} className="ax-flex ax-small" style={{ padding: "2px 0" }}><span style={{ flex: 1 }}>{k}</span><b className="ax-num">{v}</b></div>)}
        <p className="ax-xs ax-muted" style={{ marginBottom: 0 }}>Only metrics confirmed by an independent verifier are shown (sample data).</p></>, { gridColumn: "span 1" })}
      {tile("Versus department", <Target size={15} className="ax-gold" aria-hidden />, <VsDept a={a} />, { gridColumn: "span 2" })}
      {tile("Mission contribution", <Layers size={15} className="ax-gold" aria-hidden />, <MissionContribution a={a} />)}
    </div>
  );
}
function VsDept({ a }: { a: AgentIdentity }) {
  const agents = useStore((x) => x.agents).filter((x) => x.dept === a.dept);
  const data = agents.map((x) => ({ id: x.id, success: +x.successRate.toFixed(1), me: x.id === a.id }));
  return <div style={{ height: 130 }}><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ left: -18, right: 6, top: 6 }}><CartesianGrid stroke="var(--ax-border)" vertical={false} /><XAxis dataKey="id" tick={{ fontSize: 9, fill: "var(--ax-muted)" }} /><YAxis domain={[80, 100]} tick={{ fontSize: 9, fill: "var(--ax-muted)" }} /><Tooltip {...chartTip} />
    <Bar dataKey="success" radius={[3, 3, 0, 0]}>{data.map((d) => <Cell key={d.id} fill={d.me ? "var(--ax-accent)" : "var(--ax-neutral)"} />)}</Bar></BarChart></ResponsiveContainer></div>;
}
function MissionContribution({ a }: { a: AgentIdentity }) {
  const s = useStore((x) => x); const mine = s.instances.filter((i) => i.agentId === a.id);
  return <>{mine.length ? mine.map((i) => <div key={i.id} className="ax-flex ax-small" style={{ gap: 6, padding: "2px 0" }}><b style={{ color: missionColor(i.missionId), width: 48 }}>{i.missionId}</b><span style={{ flex: 1 }}><Progress value={i.progress} thin label={i.id} /></span><span className="ax-num">{i.tasks} tasks</span></div>) : <p className="ax-muted ax-small">No mission work yet.</p>}</>;
}

/* ---- Audit ---- */
function AuditTab({ a }: { a: AgentIdentity }) {
  const s = useStore((x) => x); const toast = useToast();
  const vers = versionsFor(s, a).slice().reverse(); const [ask, setAsk] = useState<string | null>(null);
  const events = s.events.filter((e) => e.target.includes(a.id) || e.actor === a.id).slice(0, 8);
  const st = (v: typeof vers[number]) => v.status;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "var(--ax-gap)", height: "100%" }}>
      {tile(`Version history (${vers.length})`, <History size={15} className="ax-gold" aria-hidden />, <div style={{ position: "relative", paddingLeft: 18 }}>
        <span style={{ position: "absolute", left: 6, top: 6, bottom: 6, width: 2, background: "var(--ax-border)" }} aria-hidden />
        {vers.map((v, k) => { const stt = st(v); const col = stt === "baseline" ? "var(--ax-ok)" : stt === "candidate" ? "#a77bff" : stt === "rolled_back" || stt === "rejected" ? "var(--ax-bad)" : "var(--ax-neutral)"; return (
          <motion.div key={v.version} className="ax-tile" style={{ marginBottom: 6, position: "relative" }} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .05 }}>
            <span style={{ position: "absolute", left: -17, top: 14, width: 10, height: 10, borderRadius: 99, background: col }} aria-hidden />
            <div className="ax-flex" style={{ gap: 8 }}><b>{v.version}</b><Pill c={col}>{stt.replace("_", " ")}</Pill><span className="ax-xs ax-muted">from {v.parent ?? "none"} · <Time iso={v.at} withDate /></span><span className="ax-spacer" />
              <span className="ax-xs">score <b>{v.score}</b></span>
              {v.status !== "baseline" && v.status !== "candidate" && <IconBtn icon={RotateCcw} size="sm" label={`Roll back to ${v.version}`} onClick={() => setAsk(v.version)} />}</div>
            <div className="ax-small" style={{ marginTop: 3 }}>{v.changes.join(" · ")}</div>
            <div className="ax-flex" style={{ gap: 4, marginTop: 3 }}>{v.kind.map((x) => <Pill key={x} c="var(--ax-info)">{x}</Pill>)}</div></motion.div>); })}</div>)}
      {tile("Audit trail", <ScrollText size={15} className="ax-gold" aria-hidden />, <>
        {events.length ? events.map((e) => <div key={e.id} className="ax-flex ax-small" style={{ gap: 6, padding: "3px 0", borderBottom: "1px solid color-mix(in srgb, var(--ax-border) 40%, transparent)" }}><Time iso={e.at} /><span style={{ flex: 1 }}>{e.actor}: {e.action} <span className="ax-muted">{e.target}</span></span><Pill c={e.result === "failure" ? "var(--ax-bad)" : "var(--ax-ok)"}>{e.result}</Pill></div>)
          : <p className="ax-muted ax-small">No events recorded for {a.id} in this session. Version changes, promotions and rollbacks appear here with who approved them.</p>}
        <div className="ax-flex ax-small" style={{ gap: 6, marginTop: 8 }}><Copy size={13} aria-hidden />Created <Time iso={a.created} withDate /> · identity <code>{a.id}</code> never changes across versions.</div></>)}
      <Modal open={!!ask} onClose={() => setAsk(null)} title={`Roll back ${a.id} to ${ask}?`} icon={RotateCcw} width={440} foot={<><Btn onClick={() => setAsk(null)}>Cancel</Btn><Btn tone="gold" icon={RotateCcw} onClick={() => { if (!toastIfErr(rollbackAgentVersion(a.id, ask!), toast)) toast(`${a.id} baseline is now ${ask} (sample data); running instances keep their pinned version`, "warn"); setAsk(null); }}>Roll back</Btn></>}>
        <p className="ax-small">Rolling back makes {ask} the baseline again. Existing mission instances stay pinned to their version. This is recorded in the audit trail (shown here as a local sample action).</p></Modal>
    </div>
  );
}
