import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { motion } from "framer-motion";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart, Cell } from "recharts";
import {
  Activity, Bot, Building2, CheckCircle2, ClipboardList, Coins, Database, Dna, FlaskConical, GitBranch, GitPullRequest, BookOpen, Layers, Play, Plus,
  RefreshCw, Rss, Shield, ShieldCheck, Sparkles, Star, Target, Trophy, Users, Workflow, Zap, MessagesSquare, Inbox, HeartPulse, Server, Lightbulb, Newspaper, Globe,
  AlertTriangle,
} from "lucide-react";
import { Count, Donut, Gauge, IconBtn, Kpi, Legend, Panel, Pill, Progress, Row, StatusPill, Switch, TabBody, Tabs, Time, useToast, Empty, Seg, SampleMark } from "../ui/kit";
import { Avatar } from "../ui/Avatar";
import {
  ActivityList, AgentTag, Composer, DecisionRows, Dropdown, Gantt, GitGraph, MissionRows, OrgTree, ReleaseCard, StageStepper, ThreadList, Transcript, threadTitle,
} from "../ui/widgets";
import { byMission, setSettings, useStore, candidateAction, toastIfErr } from "../data/store";
import { FINANCE, KNOWLEDGE_TILES, PERF_SERIES, SPEND_BREAKDOWN } from "../data/sample";
import { go, href, useQueryParam } from "../app/router";
import { AddMissionModal } from "./AddMission";

export const chartTip = { contentStyle: { background: "var(--ax-raised)", border: "1px solid var(--ax-border)", borderRadius: 8, color: "var(--ax-text)", fontSize: 12 }, labelStyle: { color: "var(--ax-muted)" } };
const rowGrid = (cols: string): CSSProperties => ({ display: "grid", gridTemplateColumns: cols, gap: "var(--ax-gap)", minHeight: 0 });

export default function Overview() {
  const [tab, setTab] = useQueryParam("tab", "summary");
  const [adding, setAdding] = useState(false);
  const missions = useStore((s) => s.missions), agents = useStore((s) => s.agents), approvals = useStore((s) => s.approvals);
  const pending = approvals.filter((a) => a.status === "pending");
  const active = missions.filter((m) => !m.archived && m.status !== "cancelled");
  const finished = missions.filter((m) => m.status === "done").length;
  // Page-level views (spec: Summary · Missions · Decisions · Performance · System Health) as an icon segment, so the
  // Summary dashboard keeps the 30-1 layout; each icon has a tooltip and accessible name.
  const pageTabs = (
    <Seg label="Overview views" value={tab} onChange={setTab} items={[
      { id: "summary", label: "Summary dashboard", icon: Building2 }, { id: "missions", label: `Mission portfolio (${missions.length})`, icon: Target },
      { id: "decisions", label: `Decisions (${pending.length} pending)`, icon: Inbox }, { id: "performance", label: "Performance over time", icon: Activity }, { id: "health", label: "System health", icon: HeartPulse }]} />
  );
  return (
    <div className="ax-page" style={{ gridTemplateRows: tab === "summary" ? "15fr 29fr 20fr 22fr" : "auto 1fr" }}>
      <div style={rowGrid(tab === "summary" ? "52fr 20fr 13fr" : "1fr")}>
        <Panel i={0} title="Company Overview" icon={Building2} help={{ body: "A 10-second summary of what AXoR is doing, what it costs and what needs you. Click a tile to open its detail.", source: "Missions, agents, approvals and finance stores; mission success = verified completed / finished missions (30 days)." }}
          sub={tab === "summary" ? "Run, build, verify, evolve, and grow your AI company." : undefined} actions={pageTabs}>
          {tab === "summary" ? (
            <div className="ax-kpis" style={{ gridTemplateColumns: "repeat(5, 1fr)", height: "100%" }}>
              <Kpi i={0} icon={Target} c="#a77bff" value={active.length} label="Active Missions" delta="↑ +2 (vs. last week)" onClick={() => go("missions")} />
              <Kpi i={1} icon={Users} c="#3b8cff" value={agents.filter((a) => a.status !== "offline").length} label="Active Agents" delta="↑ +4 (vs. last week)" onClick={() => go("agents")} />
              <Kpi i={2} icon={ClipboardList} c="#f2b53a" value={pending.length} label="Pending Approvals" onClick={() => setTab("decisions")} />
              <Kpi i={3} icon={Trophy} c="#2fd27a" value={96.4} decimals={1} suffix="%" sample label="Mission Success" delta="↑ +2.1 pp" onClick={() => setTab("performance")} help={`Verified: ${finished} completed this period`} />
              <Kpi i={4} icon={Coins} c="#c084fc" value={FINANCE.month} prefix="$" sample label="This Month Spend" onClick={() => go("finance")}
                extra={<><small style={{ color: "var(--ax-muted)" }}>{Math.round((FINANCE.month / FINANCE.budget) * 100)}% of Budget</small><Progress value={(FINANCE.month / FINANCE.budget) * 100} thin c1="var(--ax-ok)" c2="var(--ax-ok)" label="Budget used" /></>} />
            </div>
          ) : null}
        </Panel>
        {tab === "summary" && <HealthPanel />}
        {tab === "summary" && <QuickActions onAdd={() => setAdding(true)} />}
      </div>
      {tab === "summary" ? <Summary onAdd={() => setAdding(true)} /> : (
        <TabBody k={tab}>
          {tab === "missions" && <MissionsFull onAdd={() => setAdding(true)} />}
          {tab === "decisions" && <Panel i={1} title="Decision Inbox" icon={Inbox} help="Only actionable pending decisions, grouped by urgency. Resolved ones stay in History."><DecisionRows approvals={[...pending].sort((a, b) => ["High", "Medium", "Low"].indexOf(a.priority) - ["High", "Medium", "Low"].indexOf(b.priority))} /></Panel>}
          {tab === "performance" && <Performance />}
          {tab === "health" && <HealthFull />}
        </TabBody>
      )}
      <AddMissionModal open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}

function HealthPanel() {
  const agents = useStore((s) => s.agents), models = useStore((s) => s.models);
  const up = agents.filter((a) => a.status !== "offline").length;
  const rows: [string, ReactNode, boolean][] = [["Agents", `${up} / ${agents.length - 1}`, true], ["Execution Jobs", "12 / 12", true], ["Infrastructure", "99.9%", true], ["Knowledge Sync", "Up to date", true],
    ["Model providers", `${models.filter((m) => m.enabled && m.health === "ok").length} / ${models.filter((m) => m.enabled).length}`, models.filter((m) => m.enabled).every((m) => m.health === "ok")]];
  return (
    <Panel i={1} title="Company Health" icon={HeartPulse} headExtra={<SampleMark />} help={{ body: "Weighted health of agents, execution jobs, infrastructure, knowledge sync and model providers.", source: "Heartbeats + provider checks (sample)." }}>
      <div className="ax-flex" style={{ gap: 14, height: "100%" }}>
        <Gauge value={98} size={96} label="healthy" />
        <div className="ax-col" style={{ gap: 3, flex: 1, minWidth: 0 }}>
          {rows.slice(0, 4).map(([k, v, ok], i) => (
            <motion.div key={k} className="ax-flex ax-small" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .2 + i * .06 }}>
              {ok ? <CheckCircle2 size={14} className="ax-ok" aria-label="ok" /> : <AlertTriangle size={14} className="ax-warn" aria-label="degraded" />}<span style={{ flex: 1 }}>{k}</span><b className="ax-num">{v}</b>
            </motion.div>))}
        </div>
      </div>
    </Panel>
  );
}

function QuickActions({ onAdd }: { onAdd: () => void }) {
  const toast = useToast();
  const items = [
    { icon: Plus, label: "Add mission", run: onAdd, tone: undefined },
    { icon: Play, label: "Resume all paused missions", run: () => toast("No paused missions to resume", "info"), tone: "gold" as const },
    { icon: RefreshCw, label: "Sync data now", run: () => toast("Data refreshed") },
    { icon: GitBranch, label: "Open versions & branches", run: () => go("versions") },
    { icon: FlaskConical, label: "Open Evolution Lab experiments", run: () => go("evolution", null, { tab: "experiments" }) },
    { icon: Sparkles, label: "Ask the General Manager", run: () => go("control", "M-001", { tab: "conversations", with: "GM" }) },
  ];
  return (
    <Panel i={2} title="Quick Actions" icon={Zap} help="One-click shortcuts. Hover an icon to see what it does.">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, height: "100%", alignContent: "center", justifyItems: "center" }}>
        {items.map((it) => <IconBtn key={it.label} icon={it.icon} label={it.label} size="lg" iconSize={22} tone={it.tone} onClick={it.run} />)}
      </div>
    </Panel>
  );
}

function Summary({ onAdd }: { onAdd: () => void }) {
  const [mTab, setMTab] = useState("all"), [oTab, setOTab] = useState("org"), [cTab, setCTab] = useState("flow"), [dTab, setDTab] = useState("pending");
  const missions = useStore((s) => s.missions), approvals = useStore((s) => s.approvals), events = useStore((s) => s.events);
  const fil = { all: missions, running: missions.filter((m) => m.status === "running"), review: missions.filter((m) => m.status === "review"), done: missions.filter((m) => m.status === "done") } as Record<string, typeof missions>;
  const lead = missions[0];
  if (!lead) return (
    <div style={{ gridRow: "2 / 5", display: "grid", placeItems: "center" }} className="ax-panel">
      <Empty icon={Target} title="No missions yet">Start your first mission: describe the goal, attach documents, images or a GitHub address, and the General Manager plans the rest.
        <span style={{ display: "block", marginTop: 10 }}><button type="button" className="ax-btn gold" onClick={onAdd}>Create your first mission</button></span></Empty>
    </div>
  );
  return (
    <>
      <div style={rowGrid("26.5fr 26fr 33fr")}>
        <Panel i={3} title="Missions" icon={Target} help={{ body: "Every mission you can see: progress by verified milestones, current version and open issues (amber) / decisions waiting for you (purple).", source: "Mission store" }}
          actions={<IconBtn icon={Plus} label="Add mission" tone="gold" size="sm" onClick={onAdd} />}
          tabs={<Tabs label="Mission filter" value={mTab} onChange={setMTab} tabs={[{ id: "all", label: "All", count: fil.all.length }, { id: "running", label: "In Progress", count: fil.running.length }, { id: "review", label: "Review", count: fil.review.length }, { id: "done", label: "Completed", count: fil.done.length }]} />}>
          <TabBody k={mTab}>{fil[mTab].length ? <MissionRows missions={fil[mTab].slice(0, 8)} onOpen={(m) => go("control", m.id)} /> : <Empty title="No missions here" />}</TabBody>
        </Panel>
        <Panel i={4} title="Organization Snapshot" icon={Users} help="The company structure. The GM directs department heads who direct specialist agents."
          tabs={<Tabs label="Organization views" value={oTab} onChange={setOTab} tabs={[{ id: "org", label: "Org Chart" }, { id: "graph", label: "Agent Graph" }, { id: "depts", label: "Departments" }, { id: "perf", label: "Performance" }]} />}>
          <TabBody k={oTab}><OrgMini tab={oTab} /></TabBody>
        </Panel>
        <Panel i={5} title={<>Mission Control — {lead.title}</>} icon={Workflow} help="The lead mission at a glance. Open Mission Control for the full view."
          headExtra={<><StatusPill s={lead.status} /><b className="ax-num ax-small">{lead.progress}%</b></>}
          tabs={<Tabs label="Mission control views" value={cTab} onChange={setCTab} tabs={[{ id: "overview", label: "Overview" }, { id: "flow", label: "Task Flow" }, { id: "agents", label: "Agents" }, { id: "conv", label: "Conversations" }, { id: "appr", label: "Approvals", alert: byMission(approvals, lead.id).filter((a) => a.status === "pending").length }, { id: "act", label: "Activity" }]} />}>
          <TabBody k={cTab}><ControlMini tab={cTab} missionId={lead.id} /></TabBody>
        </Panel>
      </div>
      <div style={rowGrid("30fr 34fr 22.5fr")}>
        <Panel i={6} title="Decision Inbox" icon={Inbox} help="Decisions only you can make. Approve (✓) or reject (✗); high-impact items ask for confirmation. Answered items leave this list and stay in History."
          tabs={<Tabs label="Decision filter" value={dTab} onChange={setDTab} tabs={[{ id: "pending", label: "Pending", count: approvals.filter((a) => a.status === "pending").length }, { id: "approved", label: "Approved", count: approvals.filter((a) => a.status === "approved").length }, { id: "rejected", label: "Rejected", count: approvals.filter((a) => a.status === "rejected").length }]} />}>
          <TabBody k={dTab}><DecisionRows compact approvals={approvals.filter((a) => a.status === dTab)} /></TabBody>
        </Panel>
        <ConversationMini />
        <Panel i={8} title="Recent Activity" icon={Activity} help="Verified events from the event log, newest first. Not agent 'thoughts'."><ActivityList events={events} compact limit={8} /></Panel>
      </div>
      <div style={rowGrid("19fr 17.5fr 16.5fr 16.5fr 15fr")}>
        <VersionsMini /><EvolutionMini /><KnowledgeMini /><FinanceMini /><GovernanceMini />
      </div>
    </>
  );
}

function OrgMini({ tab }: { tab: string }) {
  const depts = useStore((s) => s.departments), agents = useStore((s) => s.agents);
  if (tab === "org") return <OrgTree compact onSelect={(d) => go("organization", null, { dept: d })} />;
  if (tab === "graph") {
    const n = depts.length; const R = 38;
    return (
      <svg viewBox="0 0 200 110" width="100%" height="100%" role="img" aria-label="Agent graph: GM linked to department heads">
        {depts.map((d, i) => { const a = (Math.PI * 2 * i) / n - Math.PI / 2, x = 100 + Math.cos(a) * R * 2, y = 55 + Math.sin(a) * R; return (
          <g key={d.id}><line x1="100" y1="55" x2={x} y2={y} stroke="var(--ax-accent2)" strokeWidth=".8" className="ax-flow-dash" />
            <motion.circle cx={x} cy={y} r="9" fill="var(--ax-panel2)" stroke="var(--ax-accent2)" style={{ transformBox: "fill-box", transformOrigin: "center" }} initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: i * .06 }} />
            <text x={x} y={y + 3} textAnchor="middle" fontSize="6" fill="var(--ax-text)">{d.head.split("-")[0]}</text></g>); })}
        <circle cx="100" cy="55" r="13" fill="var(--ax-accent)" /><text x="100" y="58" textAnchor="middle" fontSize="8" fontWeight="700" fill="var(--ax-on-accent)">GM</text>
      </svg>
    );
  }
  if (tab === "depts") return (
    <table className="ax-table"><thead><tr><th>Department</th><th>Agents</th><th>Budget</th><th>Backlog</th></tr></thead>
      <tbody>{depts.map((d) => <tr key={d.id} className="click" onClick={() => go("organization", null, { tab: "departments", dept: d.id })}><td><span className="ax-flex"><Avatar role={d.role} size={18} animate={false} />{d.name}</span></td><td className="ax-num">{agents.filter((a) => a.dept === d.id).length}</td><td className="ax-num">${d.spent}/{d.budget}</td><td className="ax-num">{d.backlog}</td></tr>)}</tbody></table>
  );
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={depts.map((d) => ({ name: d.name.split(" ")[0], v: d.performance }))} margin={{ top: 6, right: 4, left: -22, bottom: 0 }}>
        <XAxis dataKey="name" tick={{ fill: "var(--ax-muted)", fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis domain={[85, 100]} tick={{ fill: "var(--ax-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
        <Tooltip {...chartTip} formatter={(v: number) => [`${v}%`, "Verified success"]} />
        <Bar dataKey="v" radius={[5, 5, 0, 0]}>{depts.map((d, i) => <Cell key={d.id} fill={["#22d3ee", "#3b8cff", "#94a3b8", "#2fd27a", "#a77bff", "#fbbf24", "#fb7185"][i]} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function ControlMini({ tab, missionId }: { tab: string; missionId: string }) {
  const m = useStore((s) => s.missions.find((x) => x.id === missionId));
  const tasks = useStore((s) => s.tasks), instances = useStore((s) => s.instances), threads = useStore((s) => s.threads), approvals = useStore((s) => s.approvals), events = useStore((s) => s.events);
  if (!m) return null; // mission list swapped (sample <-> live): the parent re-renders with a valid id next
  const mt = byMission(tasks, missionId);
  if (tab === "overview") return (
    <div className="ax-col" style={{ gap: 10 }}><StageStepper stage={m.stage} compact />
      <dl className="ax-kv"><dt>Version</dt><dd>{m.version}</dd><dt>Started</dt><dd><Time iso={m.startedAt} withDate /></dd><dt>Due ({m.dueKind})</dt><dd><Time iso={m.dueAt} withDate /></dd>
        <dt>Issues</dt><dd className="ax-bad">{m.issuesOpen} ({m.decisionsPending} need you)</dd><dt>Next edition</dt><dd>{m.nextEditionAt ? <Time iso={m.nextEditionAt} withDate /> : "Not scheduled"}</dd></dl></div>
  );
  if (tab === "flow") {
    const pick = ["T-002", "T-007", "T-005", "T-010"].map((id) => mt.find((t) => t.id === id)).filter(Boolean) as typeof mt;
    const rows = pick.length ? pick : mt.slice(0, 4);
    return <div className="ax-col" style={{ gap: 8 }}><StageStepper stage={m.stage} compact /><Gantt tasks={rows} days={11} rowH={22} labelW={118} onSelect={(t) => go("control", missionId, { tab: "flow", task: t.id })} /></div>;
  }
  if (tab === "agents") return <div className="ax-rows">{byMission(instances, missionId).slice(0, 8).map((x, i) => <Row key={x.id} i={i} onClick={() => go("control", missionId, { tab: "conversations", with: x.agentId })}><AgentTag id={x.agentId} sub={x.pinnedVersion} /><span className="grow" /><Progress value={x.progress} thin label={`${x.agentId} progress`} /><StatusPill s={x.status} small /></Row>)}</div>;
  if (tab === "conv") return <ThreadList compact threads={byMission(threads, missionId).slice(0, 6)} value={null} onChange={(id) => go("control", missionId, { tab: "conversations", thread: id })} />;
  if (tab === "appr") return <DecisionRows compact approvals={byMission(approvals, missionId).filter((a) => a.status === "pending")} />;
  return <ActivityList compact events={byMission(events, missionId)} limit={6} />;
}

function ConversationMini() {
  const threads = useStore((s) => s.threads), messages = useStore((s) => s.messages);
  const [filter, setFilter] = useState("all"); const [tid, setTid] = useState("TH-1");
  const list = threads.filter((t) => filter === "all" || t.kind === filter);
  const t = threads.find((x) => x.id === tid) ?? threads[0];
  const msgs = messages.filter((m) => m.threadId === t.id && m.condensed);
  return (
    <Panel i={7} title="Agent Conversation" icon={MessagesSquare} headExtra={<SampleMark />} help="Pick a conversation to read it. Type to instruct the selected agent; the status under your message shows queued → running → done."
      actions={<IconBtn icon={Plus} label="New conversation" size="sm" onClick={() => go("control", t.missionId, { tab: "conversations" })} />}>
      <div style={{ display: "grid", gridTemplateColumns: "42% 58%", gap: 8, height: "100%", minHeight: 0 }}>
        <div className="ax-col" style={{ minHeight: 0 }}>
          <Dropdown label="Conversation filter" value={filter} onChange={setFilter} options={[{ id: "all", label: "All Chats" }, { id: "user", label: "With users" }, { id: "subordinate", label: "To juniors" }, { id: "superior", label: "To seniors" }, { id: "peer", label: "Peers" }]} />
          <div style={{ overflow: "auto", minHeight: 0 }}><ThreadList compact threads={list} value={t.id} onChange={setTid} /></div>
          <a className="ax-small ax-gold" href={href("control", t.missionId, { tab: "conversations" })}>All Conversations →</a>
        </div>
        <div className="ax-col" style={{ minHeight: 0, border: "1px solid var(--ax-border)", borderRadius: 10, padding: 8 }}>
          <b className="ax-small">{threadTitle(t)}</b>
          <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}><Transcript messages={msgs.slice(-2)} me={t.a === "user" ? "user" : t.b} showMeta={false} /></div>
          <Composer compact missionId={t.missionId} to={t.a === "user" ? t.b : t.b === "user" ? t.a : t.b} threadId={t.a === "user" || t.b === "user" ? t.id : null} onSent={setTid} />
        </div>
      </div>
    </Panel>
  );
}

function VersionsMini() {
  const [tab, setTab] = useState("versions"); const branches = useStore((s) => s.branches), releases = useStore((s) => s.releases), prs = useStore((s) => s.mergeRequests);
  return (
    <Panel i={9} title="Versions & GitHub" icon={GitBranch} headExtra={<SampleMark />} help="Mission deliverable versions: main ↔ feature branches ↔ merges. Agent versions are tracked separately in Evolution Lab."
      tabs={<Tabs label="Version views" value={tab} onChange={setTab} tabs={[{ id: "versions", label: "Versions" }, { id: "branches", label: "Branches" }, { id: "prs", label: "Pull Requests" }, { id: "releases", label: "Releases" }]} />}>
      <TabBody k={tab}>
        {tab === "versions" && <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 8, height: "100%" }}><GitGraph rowH={24} branches={branches.filter((b) => ["main", "feature/ai-eval", "feature/ux-redesign", "feature/self-evolution"].includes(b.name))} onSelect={() => go("versions", null, { tab: "graph" })} /><ReleaseCard compact r={releases[0]} /></div>}
        {tab === "branches" && <div className="ax-rows">{branches.map((b, i) => <Row key={b.name} i={i} onClick={() => go("versions", null, { tab: "graph" })}><GitBranch size={13} aria-hidden /><span className="grow t ax-small">{b.name}</span><Pill c={b.status === "conflict" ? "var(--ax-bad)" : b.status === "open" ? "var(--ax-info)" : "var(--ax-ok)"}>{b.status}</Pill></Row>)}</div>}
        {tab === "prs" && <div className="ax-rows">{prs.map((p, i) => <Row key={p.id} i={i} onClick={() => go("versions", null, { tab: "merge" })}><GitPullRequest size={13} aria-hidden /><span className="grow t ax-small">#{p.number} {p.title}</span><span className="ax-xs ax-num">{p.checks.passed}/{p.checks.total}</span><StatusPill small s={p.status === "merged" ? "done" : p.status === "blocked" ? "blocked" : p.status === "approved" ? "passed" : "review"} label={p.status} /></Row>)}</div>}
        {tab === "releases" && <div className="ax-rows">{releases.map((r, i) => <Row key={r.id} i={i} onClick={() => go("versions", null, { v: r.version })}><b className="ax-small ax-num">{r.version}</b><span className="grow s"><Time iso={r.at} withDate /></span><StatusPill small s={r.status === "failed" ? "failed" : r.status === "candidate" ? "review" : "passed"} label={r.status} /></Row>)}</div>}
      </TabBody>
    </Panel>
  );
}

function EvolutionMini() {
  const [tab, setTab] = useState("proposals"); const cands = useStore((s) => s.candidates); const toast = useToast();
  const lists: Record<string, typeof cands> = { proposals: cands.filter((c) => ["passed", "evaluating", "experiment", "proposed"].includes(c.status)), experiments: cands.filter((c) => c.status === "experiment" || c.status === "evaluating"),
    evaluation: cands.filter((c) => ["passed", "failed", "evaluating"].includes(c.status)), history: cands.filter((c) => ["promoted", "rejected", "rolled_back", "failed"].includes(c.status)) };
  return (
    <Panel i={10} title="Evolution Lab" icon={Dna} headExtra={<SampleMark />} help="Agents propose improvements from mission experience; an independent verifier benchmarks them; only verified improvements are promoted."
      tabs={<Tabs label="Evolution views" value={tab} onChange={setTab} tabs={[{ id: "proposals", label: "Proposals" }, { id: "experiments", label: "Experiments" }, { id: "evaluation", label: "Evaluation" }, { id: "history", label: "History" }]} />}>
      <TabBody k={tab}><div className="ax-rows">{lists[tab].map((c, i) => (
        <Row key={c.id} i={i} onClick={() => go("evolution", null, { c: c.id })}>
          <Avatar role={c.agentId.startsWith("QA") ? "qa" : c.agentId.startsWith("RCH") ? "research" : c.agentId.startsWith("KNW") ? "knowledge" : c.agentId.startsWith("OPS") ? "ops" : "developer"} size={24} animate={false} />
          <span className="grow t ax-small">{c.title}</span><b className={`ax-small ax-num ${c.delta >= 0 ? "ax-ok" : "ax-bad"}`}>{c.delta >= 0 ? "+" : ""}{c.delta}%</b>
          {tab === "proposals" ? <IconBtn icon={Play} label={c.status === "passed" ? `Promote ${c.to}` : `Run evaluation for ${c.title}`} size="sm" tone={c.status === "passed" ? "gold" : undefined} onClick={(e) => { e.stopPropagation(); if (!toastIfErr(candidateAction(c.id, c.status === "passed" ? "promote" : "evaluate"), toast)) toast(c.status === "passed" ? `${c.agentId} ${c.to} promoted (sample)` : `Evaluating ${c.title}…`); }} /> : <StatusPill small s={c.status === "promoted" ? "done" : c.status === "failed" || c.status === "rejected" ? "failed" : c.status === "rolled_back" ? "rolled_back" : c.status === "passed" ? "passed" : "running"} label={c.status} />}
        </Row>))}{!lists[tab].length && <Empty title="Nothing here" />}</div></TabBody>
    </Panel>
  );
}

function KnowledgeMini() {
  const [tab, setTab] = useState("library"); const news = useStore((s) => s.news), sources = useStore((s) => s.newsSources), knowledge = useStore((s) => s.knowledge);
  const tiles: [string, number, typeof Layers][] = [[KNOWLEDGE_TILES[0][0], KNOWLEDGE_TILES[0][1], Layers], [KNOWLEDGE_TILES[1][0], KNOWLEDGE_TILES[1][1], FlaskConical], [KNOWLEDGE_TILES[2][0], KNOWLEDGE_TILES[2][1], Star], [KNOWLEDGE_TILES[3][0], KNOWLEDGE_TILES[3][1], Globe], [KNOWLEDGE_TILES[4][0], KNOWLEDGE_TILES[4][1], Newspaper], [KNOWLEDGE_TILES[5][0], KNOWLEDGE_TILES[5][1], Lightbulb]];
  return (
    <Panel i={11} title="Knowledge & News" icon={BookOpen} headExtra={<SampleMark />} help="The company brain: verified knowledge, research, news and the sources it comes from."
      tabs={<Tabs label="Knowledge views" value={tab} onChange={setTab} tabs={[{ id: "library", label: "Library" }, { id: "research", label: "Research" }, { id: "news", label: "News Feed" }, { id: "sources", label: "Sources" }]} />}>
      <TabBody k={tab}>
        {tab === "library" && <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 5 }}>{tiles.map(([l, v, I], i) => (
          <motion.button key={l} type="button" className="ax-tile click" onClick={() => go("knowledge")} style={{ textAlign: "center", padding: "5px 2px" }} initial={{ opacity: 0, scale: .9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * .04 }} whileHover={{ y: -2 }} aria-label={`${l}: ${v}`}>
            <I size={16} className="ax-gold" aria-hidden /><div className="ax-xs" style={{ lineHeight: 1.1 }}>{l}</div><b className="ax-small"><Count value={v} /></b></motion.button>))}</div>}
        {tab === "research" && <div className="ax-rows">{knowledge.filter((k) => k.kind === "research").map((k, i) => <Row key={k.id} i={i} onClick={() => go("knowledge", null, { tab: "research" })}><FlaskConical size={13} aria-hidden /><span className="grow t ax-small">{k.title}</span><Pill c={k.status === "verified" ? "var(--ax-ok)" : k.status === "conflict" ? "var(--ax-bad)" : "var(--ax-warn)"}>{k.status}</Pill></Row>)}</div>}
        {tab === "news" && <div className="ax-rows">{news.slice(0, 6).map((n, i) => <Row key={n.id} i={i} onClick={() => go("knowledge", null, { tab: "news" })}><Newspaper size={13} aria-hidden /><span className="grow t ax-small">{n.title}</span></Row>)}</div>}
        {tab === "sources" && <div className="ax-rows">{sources.map((s, i) => <Row key={s.id} i={i} onClick={() => go("knowledge", null, { tab: "sources" })}><Rss size={13} aria-hidden /><span className="grow t ax-small">{s.name}</span><Pill c={s.status === "ok" ? "var(--ax-ok)" : "var(--ax-bad)"}>{s.status}</Pill></Row>)}</div>}
      </TabBody>
    </Panel>
  );
}

function FinanceMini() {
  const [tab, setTab] = useState("overview"); const depts = useStore((s) => s.departments); const models = useStore((s) => s.models);
  return (
    <Panel i={12} title="Finance" icon={Coins} headExtra={<SampleMark />} help={{ body: "Spend this month against budget, by category.", source: "Cost events (tokens, compute, tools, storage). Sample values." }}
      tabs={<Tabs label="Finance views" value={tab} onChange={setTab} tabs={[{ id: "overview", label: "Overview" }, { id: "budget", label: "Budget" }, { id: "usage", label: "Usage" }, { id: "alerts", label: "Alerts" }]} />}>
      <TabBody k={tab}>
        {tab === "overview" && <div className="ax-flex" style={{ gap: 8, alignItems: "center", height: "100%" }}>
          <div><b style={{ fontSize: 20 }}><Count value={FINANCE.month} prefix="$" /></b><div className="ax-xs ax-muted">This Month</div><div className="ax-xs ax-ok">↑ +{FINANCE.deltaPct}%</div></div>
          <Donut label="Spend by category" size={78} stroke={10} parts={SPEND_BREAKDOWN} center={<div><b style={{ fontSize: 14 }}>{Math.round((FINANCE.month / FINANCE.budget) * 100)}%</b><div style={{ fontSize: 8 }} className="ax-muted">Budget Used</div></div>} />
          <div style={{ flex: 1, minWidth: 0, fontSize: 10 }}><Legend items={SPEND_BREAKDOWN.map((p) => ({ label: p.label, value: `${p.value}%`, c: p.c }))} /></div>
        </div>}
        {tab === "budget" && <div className="ax-col" style={{ gap: 5 }}>{depts.map((d) => <div key={d.id}><div className="ax-flex ax-xs"><span style={{ flex: 1 }}>{d.name}</span><span className="ax-num">${d.spent}/{d.budget}</span></div><Progress value={(d.spent / d.budget) * 100} thin c1={d.spent / d.budget > .8 ? "var(--ax-warn)" : "var(--ax-info)"} label={`${d.name} budget`} /></div>)}</div>}
        {tab === "usage" && <div className="ax-rows">{models.filter((m) => m.enabled).map((m, i) => <Row key={m.id} i={i}><Database size={13} aria-hidden /><span className="grow t ax-small">{m.model}</span><span className="ax-xs ax-num">${(m.costIn * 9 + m.costOut * 3).toFixed(0)}</span></Row>)}</div>}
        {tab === "alerts" && <div className="ax-rows">{[["Compute at 76% of budget with 9 days left", "warn"], ["gpt-6.1 degraded: fallback used 41×", "warn"], ["Research spend +22% week over week", "info"]].map(([t, k], i) => <Row key={t} i={i}><AlertTriangle size={13} className={k === "warn" ? "ax-warn" : "ax-gold"} aria-hidden /><span className="grow ax-small">{t}</span></Row>)}</div>}
      </TabBody>
    </Panel>
  );
}

function GovernanceMini() {
  const [tab, setTab] = useState("policies"); const settings = useStore((s) => s.settings); const models = useStore((s) => s.models);
  const levels: [string, string][] = [["L3", "L3 – Manage Workflows"], ["L4", "L4 – Propose Evolution"], ["L5", "L5 – Company Optimization"]];
  return (
    <Panel i={13} title="Governance" icon={Shield} headExtra={<SampleMark />} help="What agents may do on their own. Effective permission is the intersection of company, mission, agent and tool limits."
      tabs={<Tabs label="Governance views" value={tab} onChange={setTab} tabs={[{ id: "policies", label: "Policies" }, { id: "perm", label: "Permissions" }, { id: "models", label: "Models" }, { id: "renew", label: "Self-Renewal" }]} />}>
      <TabBody k={tab}>
        {tab === "policies" && <div className="ax-col" style={{ gap: 6 }}>{levels.map(([k, l]) => <div key={k} className="ax-flex ax-small"><CheckCircle2 size={14} className={settings.autonomy[k] ? "ax-ok" : "ax-faint"} aria-hidden /><span style={{ flex: 1 }}>{l}</span><Switch on={!!settings.autonomy[k]} label={l} onChange={(v) => setSettings({ autonomy: { ...settings.autonomy, [k]: v } })} /></div>)}
          <div className="ax-flex ax-small"><RefreshCw size={14} className="ax-gold" aria-hidden /><span style={{ flex: 1 }}><b>Self-Renewal</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Auto evolutionary update</span></span><Switch on={settings.selfRenewal} label="Self-renewal" onChange={(v) => setSettings({ selfRenewal: v })} /></div></div>}
        {tab === "perm" && <div className="ax-rows">{[["Deploy to production", "Owner approval"], ["Spend above budget", "Owner approval"], ["Create repository", "Owner approval"], ["Change org structure", "Owner + review"], ["Run tests / previews", "Automatic"]].map(([a, b], i) => <Row key={a} i={i}><ShieldCheck size={13} className="ax-gold" aria-hidden /><span className="grow ax-small">{a}</span><span className="ax-xs ax-muted">{b}</span></Row>)}</div>}
        {tab === "models" && <div className="ax-rows">{models.map((m, i) => <Row key={m.id} i={i} onClick={() => go("governance", null, { tab: "models" })}><Bot size={13} aria-hidden /><span className="grow t ax-small">{m.model}</span><Pill c={m.health === "ok" ? "var(--ax-ok)" : m.health === "degraded" ? "var(--ax-warn)" : "var(--ax-bad)"}>{m.health}</Pill></Row>)}</div>}
        {tab === "renew" && <div className="ax-col ax-small"><div className="ax-flex"><span style={{ flex: 1 }}>Self-Renewal</span><Switch on={settings.selfRenewal} label="Self-renewal" onChange={(v) => setSettings({ selfRenewal: v })} /></div>
          <span className="ax-muted">{settings.selfRenewal ? "On: the GM continuously proposes and evaluates upgrades within budget and safety gates." : "Off: improvements are only proposed during mission work."}</span><a className="ax-gold" href={href("governance", null, { tab: "renewal" })}>Configure →</a></div>}
      </TabBody>
    </Panel>
  );
}

function MissionsFull({ onAdd }: { onAdd: () => void }) {
  const missions = useStore((s) => s.missions);
  return <Panel i={1} title="Mission Portfolio" icon={Target} actions={<IconBtn icon={Plus} label="Add mission" tone="gold" onClick={onAdd} />} help="All missions, sortable in the Missions page.">
    <MissionRows missions={missions} onOpen={(m) => go("control", m.id)} /></Panel>;
}

function Performance() {
  const [range, setRange] = useState("30");
  const data = useMemo(() => PERF_SERIES.slice(-Number(range)), [range]);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "var(--ax-gap)", height: "100%" }}>
      <Panel i={1} title="Company Performance" icon={Activity} help={{ body: "Verified mission success and autonomy rate (share of tasks finished without human help).", source: "Task events; sample series." }}
        actions={<Tabs label="Range" value={range} onChange={setRange} tabs={[{ id: "7", label: "7 days" }, { id: "14", label: "14 days" }, { id: "30", label: "30 days" }]} />}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 16, left: -10, bottom: 0 }}>
            <CartesianGrid stroke="var(--ax-border)" strokeDasharray="3 3" opacity={.4} />
            <XAxis dataKey="day" tick={{ fill: "var(--ax-muted)", fontSize: 11 }} /><YAxis domain={[60, 100]} tick={{ fill: "var(--ax-muted)", fontSize: 11 }} />
            <Tooltip {...chartTip} />
            <Line type="monotone" dataKey="success" name="Success rate %" stroke="#a77bff" strokeWidth={2.5} dot={false} />
            <Line type="monotone" dataKey="autonomy" name="Autonomy rate %" stroke="#22d3ee" strokeWidth={2.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Panel>
      <Panel i={2} title="Baseline comparison" icon={Trophy} help="This period vs the previous period of equal length.">
        <div className="ax-col">{[["Mission success", "96.4%", "+2.1 pp"], ["Autonomous completion", "84.0%", "+5.3 pp"], ["Human interventions / mission", "1.8", "−0.6"], ["Cost per verified success", "$11.80", "−8.2%"], ["Mean time to recover", "14 min", "−4 min"]].map(([k, v, d], i) =>
          <Row key={k} i={i}><span className="grow ax-small">{k}</span><b className="ax-num">{v}</b><span className="ax-xs ax-ok">{d}</span></Row>)}</div>
      </Panel>
    </div>
  );
}

function HealthFull() {
  const models = useStore((s) => s.models);
  const svc: [string, "ok" | "degraded" | "down", string][] = [["API gateway", "ok", "p95 210 ms"], ["Mission orchestrator", "ok", "12 / 12 jobs"], ["Agent runtime", "ok", "38 agents"], ["Event bus", "ok", "lag 0.4 s"], ["Knowledge index", "ok", "synced 3 min ago"], ["Preview service", "ok", "2 previews"],
    ...models.map((m) => [`Model: ${m.model}`, m.enabled ? m.health : "down", m.enabled ? `${m.latencyMs} ms` : "disabled"] as [string, "ok" | "degraded" | "down", string])];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "var(--ax-gap)", height: "100%" }}>
      <Panel i={1} title="Overall health" icon={HeartPulse}><div style={{ display: "grid", placeItems: "center", height: "100%" }}><Gauge value={98} size={170} stroke={16} label="healthy" /></div></Panel>
      <Panel i={2} title="Services & providers" icon={Server} help="Heartbeat of each subsystem. Degraded providers fall back to the next model in the route.">
        <table className="ax-table"><thead><tr><th>Service</th><th>Status</th><th>Detail</th></tr></thead><tbody>
          {svc.map(([n, s, d]) => <tr key={n}><td>{n}</td><td><StatusPill s={s === "ok" ? "passed" : s === "degraded" ? "review" : "failed"} label={s === "ok" ? "Healthy" : s === "degraded" ? "Degraded" : "Down"} small /></td><td className="ax-muted">{d}</td></tr>)}
        </tbody></table>
      </Panel>
    </div>
  );
}
