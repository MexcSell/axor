import { Fragment, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain, Check, CheckCircle2, ClipboardCheck, Download, Eye, EyeOff, FileJson, FileText, Filter, History, Image as ImageIcon, Inbox, ListTree, MessageSquareText, MessagesSquare,
  Network, PencilLine, ScrollText, Search, ShieldCheck, X, Bot, Wrench, Layers, ArrowDownRight, ArrowUpLeft,
} from "lucide-react";
import { Btn, CopyBtn, Empty, IconBtn, Modal, Panel, Pill, PRIORITY, Progress, Row, Seg, StatusPill, Tabs, Time, useToast, TabBody } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";
import { AgentTag, Composer, StageStepper, ThreadList, Transcript, threadTitle, roleOf } from "../../ui/widgets";
import { liveMode, decide, readThread, toastIfErr, useStore } from "../../data/store";
import type { Approval, Event, Message, Thread } from "../../domain/types";
import { go, useQueryParam } from "../../app/router";
import { AgentGraph, GraphLegend } from "./AgentGraph";

const KIND_FILTERS = [{ id: "all", label: "All" }, { id: "user", label: "Users" }, { id: "superior", label: "Seniors" }, { id: "subordinate", label: "Juniors" }, { id: "peer", label: "Peers" }];
// Thread kind is stored from the first participant's view; recompute relative to the selected agent.
function relation(t: Thread, me: string, agents: { id: string; reportsTo: string | null }[]): Thread["kind"] {
  const other = t.a === me ? t.b : t.a;
  if (other === "user") return "user";
  const mine = agents.find((a) => a.id === me), them = agents.find((a) => a.id === other);
  if (mine?.reportsTo === other || (me !== "GM" && other === "GM")) return "superior";
  if (them?.reportsTo === me || me === "GM") return "subordinate";
  return "peer";
}

/* ======================= OVERVIEW (readme §3 layout: hierarchy left, plan centre, decisions right) ======================= */
export function OverviewTab({ missionId }: { missionId: string }) {
  const m = useStore((s) => s.missions.find((x) => x.id === missionId));
  const tasks = useStore((s) => s.tasks.filter((t) => t.missionId === missionId));
  const [agent, setAgent] = useState<string | null>(null);
  if (!m) return null; // the mission list was just swapped (sample <-> live): the parent re-renders with a valid id next
  return (
    <div style={{ display: "grid", gridTemplateColumns: "30fr 38fr 32fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Agent hierarchy" icon={Network} help="Who commands whom on this mission, and live report traffic. Click an agent to talk to it." flush headExtra={<GraphLegend />}>
        <AgentGraph missionId={missionId} selected={agent} compact onSelect={(a) => { setAgent(a); go("control", missionId, { tab: "agents", agent: a }); }} />
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "auto 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title="Plan & progress" icon={ListTree} help={{ body: "Stages and milestones of the GM's plan. Progress = verified, weighted milestones.", source: `${tasks.length} tasks` }}>
          <StageStepper stage={m.stage} />
          <dl className="ax-kv" style={{ marginTop: 10, gridTemplateColumns: "auto 1fr auto 1fr" }}>
            <dt>Version</dt><dd>{m.version}</dd><dt>Started</dt><dd><Time iso={m.startedAt} withDate /></dd>
            <dt>Due ({m.dueKind})</dt><dd><Time iso={m.dueAt} withDate /></dd><dt>Next edition</dt><dd>{m.nextEditionAt ? <><Time iso={m.nextEditionAt} withDate /> <span className="ax-xs ax-muted">({m.nextEditionKind})</span></> : "Not scheduled"}</dd>
            <dt>Issues</dt><dd className="ax-warn">{m.issuesOpen}</dd><dt>Needs you</dt><dd style={{ color: "var(--ax-blocked)" }}>{m.decisionsPending}</dd>
            <dt>Budget</dt><dd>{m.tokenBudget ? `${m.tokenBudget.usedToday.toLocaleString()} / ${m.tokenBudget.perDay.toLocaleString()} tokens today` : `$${m.budget.spent} / $${m.budget.limit}`}</dd><dt>Repository</dt><dd style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.repo ? m.repo.url.replace("https://github.com/", "") : "none"}</dd>
          </dl>
        </Panel>
        <GmWindow missionId={missionId} i={2} />
      </div>
      <DecisionBox missionId={missionId} i={3} />
    </div>
  );
}

/* GM "thoughts" (auditable plan notes, not chain-of-thought) and reports received from subordinates (CTRL-007). */
export function GmWindow({ missionId, i = 0 }: { missionId: string; i?: number }) {
  const thoughts = useStore((s) => s.gmThoughts); const messages = useStore((s) => s.messages);
  const [tab, setTab] = useState("notes");
  const reports = messages.filter((m) => m.missionId === missionId && m.to === "GM" && (m.kind === "report" || m.kind === "result")).sort((a, b) => +new Date(b.at) - +new Date(a.at));
  return (
    <Panel i={i} title="General Manager — notes & reports" icon={Brain} help={{ body: "The GM's recorded plan notes and decisions, and the reports it received from deputies and agents. These are auditable notes, not hidden model reasoning.", policy: "CTRL-007" }}
      tabs={<Tabs label="GM window" value={tab} onChange={setTab} tabs={[{ id: "notes", label: "GM notes", icon: Brain }, { id: "reports", label: "Reports received", icon: ArrowUpLeft, count: reports.length }]} />}>
      <TabBody k={tab}>{tab === "notes" ? (
        <div className="ax-col" style={{ gap: 6 }}>{[...thoughts].reverse().map((t, k) => (
          <motion.div key={t.at} className="ax-tile ax-small" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .05 }}>
            <div className="ax-flex ax-xs ax-muted"><Avatar role="gm" size={16} animate={false} />GM · <Time iso={t.at} /><span className="ax-spacer" /><CopyBtn text={t.text} label="Copy note" /></div>{t.text}</motion.div>))}</div>
      ) : (
        <div className="ax-col" style={{ gap: 6 }}>{reports.map((r, k) => (
          <motion.div key={r.id} className="ax-tile ax-small" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .05 }}>
            <div className="ax-flex ax-xs ax-muted"><Avatar role={roleOf(r.from)} size={16} animate={false} /><b style={{ color: "var(--ax-text)" }}>{r.from}</b>{r.from === "DGM" && <Pill c="var(--ax-accent)">Deputy (associate governor)</Pill>} → GM · <Time iso={r.at} />{r.state && <StatusPill s={r.state} small />}<span className="ax-spacer" /><CopyBtn text={r.text} label="Copy report" /></div>{r.text}</motion.div>))}
          {!reports.length && <Empty title="No reports yet" />}</div>
      )}</TabBody>
    </Panel>
  );
}

/* Decisions waiting for the user, with candidates, text + image input, Confirm; answered items move to history (readme §3, CTRL-009/010). */
export function DecisionBox({ missionId, i = 0 }: { missionId: string; i?: number }) {
  const approvals = useStore((s) => s.approvals.filter((a) => a.missionId === missionId));
  const pending = approvals.filter((a) => a.status === "pending"); const done = approvals.filter((a) => a.status !== "pending");
  const [open, setOpen] = useState<string | null>(pending[0]?.id ?? null);
  const cur = pending.find((a) => a.id === open) ?? pending[0];
  return (
    <div style={{ display: "grid", gridTemplateRows: "1fr auto", gap: "var(--ax-gap)", minHeight: 0 }}>
      <Panel i={i} title="Needs your decision" icon={Inbox} help="Only unanswered questions appear here. Pick a candidate or write your own answer, attach images if useful, then Confirm. Answered items move to the history below." hl={pending.length > 0}
        headExtra={pending.length ? <Pill c="var(--ax-blocked)" solid>{pending.length}</Pill> : undefined}>
        {cur ? <>
          {pending.length > 1 && <div className="ax-flex" style={{ flexWrap: "wrap", gap: 4, marginBottom: 6 }}>{pending.map((a) => <button key={a.id} type="button" className="ax-tab" aria-selected={a.id === cur.id} onClick={() => setOpen(a.id)} style={a.id === cur.id ? { borderColor: "var(--ax-accent)" } : undefined}><span>{a.ref}</span></button>)}</div>}
          <DecisionForm key={cur.id} a={cur} compact />
        </> : <Empty icon={CheckCircle2} title="Nothing waiting for you" />}
      </Panel>
      <Panel i={i + 1} title="Decision history" icon={History} help="Everything you already answered, with your response and time." style={{ maxHeight: 210 }}>
        <div className="ax-rows">{done.map((a, k) => <Row key={a.id} i={k}><StatusPill s={a.status === "approved" ? "passed" : a.status === "rejected" ? "failed" : "review"} label={a.status} small /><span className="grow"><span className="t ax-small">{a.title}</span><span className="s">“{a.response?.text}”</span></span><span className="ax-xs ax-muted">{a.response && <Time iso={a.response.at} withDate />}</span></Row>)}
          {!done.length && <span className="ax-small ax-muted">No answered decisions yet.</span>}</div>
      </Panel>
    </div>
  );
}

export function DecisionForm({ a, compact }: { a: Approval; compact?: boolean }) {
  const [opt, setOpt] = useState<string>(a.options.find((o) => o.recommended)?.id ?? a.options[0]?.id ?? "");
  const [text, setText] = useState(""); const [imgs, setImgs] = useState<{ name: string; url: string }[]>([]);
  const [confirm, setConfirm] = useState<null | "approve" | "reject" | "changes">(null);
  const ref = useRef<HTMLInputElement>(null); const toast = useToast();
  const submit = (kind: "approve" | "reject" | "changes") => {
    if (!a.options.some((o) => o.id === opt) && kind === "approve") { toast("Choose one of the candidates", "warn"); return; }
    if ((kind === "reject" || kind === "changes") && !text.trim()) { toast("Add a short explanation for the agent", "warn"); return; }
    if (a.risk === "high" && !confirm) { setConfirm(kind); return; }
    if (toastIfErr(decide(a.id, kind === "approve" ? opt : kind, text.trim() || a.options.find((o) => o.id === opt)?.label || "", imgs.map((x) => x.name)), toast)) { setConfirm(null); return; }
    if (!liveMode()) toast(kind === "approve" ? `Confirmed: ${a.options.find((o) => o.id === opt)?.label}` : kind === "reject" ? "Rejected" : "Changes requested", kind === "approve" ? "ok" : "warn");
    setConfirm(null); setText("");
  };
  return (
    <motion.div key={a.id} className="ax-col" style={{ gap: 8 }} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }}>
      <div className="ax-flex"><Pill c={PRIORITY[a.priority]}>{a.priority}</Pill><span className="ax-xs ax-muted">{a.area} · {a.ref} · from {a.requestedBy} · due <Time iso={a.dueAt} withDate /></span></div>
      <b>{a.question}</b>
      {!compact && <p className="ax-small ax-muted" style={{ margin: 0 }}>{a.context}</p>}
      <div className="ax-small"><span className="ax-muted">Impact:</span> {a.impact}</div>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="ax-col">
        <legend className="ax-label">Candidates</legend>
        {a.options.map((o) => (
          <label key={o.id} className={`ax-tile click ax-flex ${opt === o.id ? "sel" : ""}`} style={{ cursor: "pointer", padding: "5px 8px" }}>
            <input type="radio" name={`opt-${a.id}`} checked={opt === o.id} onChange={() => setOpt(o.id)} />
            <span style={{ flex: 1 }}><b className="ax-small">{o.label}</b>{o.detail && <span className="ax-xs ax-muted" style={{ display: "block" }}>{o.detail}</span>}</span>
            {o.recommended && <Pill c="var(--ax-accent)">GM recommends</Pill>}
          </label>))}
      </fieldset>
      {a.evidence.length > 0 && <div className="ax-flex" style={{ flexWrap: "wrap", gap: 4 }}>{a.evidence.map((e) => <span key={e} className="ax-chip"><ShieldCheck size={10} aria-hidden />{e}</span>)}</div>}
      <textarea className="ax-textarea" rows={2} placeholder="Your answer or instructions (optional for Confirm, required to reject)…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Your response" />
      <input ref={ref} type="file" accept="image/*" multiple hidden onChange={(e) => { // data: URLs: AXoR's CSP allows data: images, not blob:
        for (const fl of [...(e.target.files ?? [])]) { if (fl.size > 8 * 1048576) { toast(`${fl.name} is over 8 MB`, "warn"); continue; } const rd = new FileReader(); rd.onload = () => setImgs((x) => [...x, { name: fl.name, url: String(rd.result) }]); rd.readAsDataURL(fl); }
        e.target.value = ""; }} />
      {imgs.length > 0 && <div className="ax-flex" style={{ flexWrap: "wrap" }}>{imgs.map((im) => <span key={im.url} style={{ position: "relative" }}><img src={im.url} alt={im.name} style={{ width: 54, height: 40, objectFit: "cover", borderRadius: 6, border: "1px solid var(--ax-border)" }} />
        <button type="button" aria-label={`Remove ${im.name}`} onClick={() => setImgs(imgs.filter((x) => x.url !== im.url))} style={{ position: "absolute", top: -6, right: -6, border: 0, borderRadius: 9, background: "var(--ax-bad)", color: "#fff", width: 16, height: 16, cursor: "pointer", padding: 0, fontSize: 10 }}>×</button></span>)}</div>}
      <div className="ax-flex">
        <IconBtn icon={ImageIcon} label="Attach image" onClick={() => ref.current?.click()} />
        <IconBtn icon={PencilLine} label="Request changes" onClick={() => submit("changes")} />
        <IconBtn icon={X} label="Reject" tone="bad" onClick={() => submit("reject")} />
        <span className="ax-spacer" />
        <Btn tone="gold" icon={Check} onClick={() => submit("approve")}>Confirm</Btn>
      </div>
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title="High-impact decision" icon={ShieldCheck} width={480}
        foot={<><span className="ax-spacer" /><Btn onClick={() => setConfirm(null)}>Back</Btn><Btn tone="gold" onClick={() => confirm && submit(confirm)}>Yes, {confirm === "approve" ? "confirm" : confirm === "reject" ? "reject" : "request changes"}</Btn></>}>
        <p style={{ marginTop: 0 }}>{a.title}</p><p className="ax-small ax-muted">{a.impact}</p><p className="ax-small">This is recorded with your name and time and cannot be auto-approved.</p>
      </Modal>
    </motion.div>
  );
}

/* ======================= AGENTS: hierarchy left, chat with the selected agent right (readme §3) ======================= */
export function AgentsTab({ missionId }: { missionId: string }) {
  const [agentParam, setAgent] = useQueryParam("agent", "GM");
  const first = useStore((s) => s.instances.find((i) => i.missionId === missionId)?.agentId);
  const onMission = useStore((s) => s.instances.some((i) => i.missionId === missionId && i.agentId === agentParam));
  const agent = onMission ? agentParam : first ?? agentParam;
  const inst = useStore((s) => s.instances.find((i) => i.missionId === missionId && i.agentId === agent));
  const ag = useStore((s) => s.agents.find((a) => a.id === agent));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "48fr 52fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateRows: "1fr auto", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="Agents on this mission" icon={Network} help="Hierarchy with live command (gold) and report (cyan) arrows. Click an agent to open its conversations on the right." flush headExtra={<GraphLegend />}>
          <AgentGraph missionId={missionId} selected={agent} onSelect={setAgent} />
        </Panel>
        {inst && ag && <Panel i={1} title={<>{ag.id} · {ag.name}</>} icon={Bot} help="This is a mission-scoped instance of a stable agent. It is pinned to one agent version and isolated from the same agent's work on other missions."
          actions={<IconBtn icon={Layers} label="Open agent profile" size="sm" onClick={() => go("agents", ag.id)} />}>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr 1fr", gap: 10, alignItems: "center" }}>
            <Avatar role={ag.role} size={46} status={ag.status} />
            <dl className="ax-kv" style={{ gridTemplateColumns: "auto 1fr" }}><dt>Instance</dt><dd className="ax-mono" style={{ fontSize: 11 }}>{inst.derived ? <span tabIndex={0} data-tip="AXoR has no per-mission GM: the company's lead answers for every live mission">company lead (all missions)</span> : inst.id}</dd><dt>Pinned</dt><dd>{inst.pinnedVersion}</dd></dl>
            <dl className="ax-kv" style={{ gridTemplateColumns: "auto 1fr" }}><dt>Model</dt><dd style={{ fontSize: 11 }}>{ag.models[0]}</dd><dt>Tasks</dt><dd>{inst.tasks}</dd></dl>
            <div><StatusPill s={inst.status} /><Progress value={inst.progress} thin label="Instance progress" /><span className="ax-xs ax-muted">Tools: {ag.tools.join(", ")}</span></div>
          </div>
        </Panel>}
      </div>
      <AgentChat missionId={missionId} agent={agent} />
    </div>
  );
}

export function AgentChat({ missionId, agent }: { missionId: string; agent: string }) {
  const threads = useStore((s) => s.threads), messages = useStore((s) => s.messages), agents = useStore((s) => s.agents);
  const [kind, setKind] = useState("all"), [mode, setMode] = useState<"full" | "summary">("full");
  const mine = useMemo(() => threads.filter((t) => t.missionId === missionId && (t.a === agent || t.b === agent)), [threads, missionId, agent]);
  const userThread = mine.find((t) => t.a === "user" || t.b === "user");
  const [tid, setTid] = useState<string | null>(null);
  const shown = mine.filter((t) => kind === "all" || relation(t, agent, agents) === kind);
  const cur = tid === "__new" ? null : mine.find((t) => t.id === tid) ?? userThread ?? mine[0] ?? null; // "__new": first conversation with this agent
  const msgs = cur ? messages.filter((m) => m.threadId === cur.id && (mode === "full" || m.condensed)) : [];
  const isUserThread = !cur || cur.a === "user" || cur.b === "user";
  return (
    <Panel i={2} title={<>Conversation with {agent === "user" ? "you" : agent}</>} icon={MessagesSquare}
      help={liveMode() ? "Left: conversations on this mission. Typing here sends a real message to this agent through AXoR's company chat, with the mission named at the top; it uses model credits. Earlier agent-to-agent threads are sample data."
        : "Left: everyone this agent talked to on this mission (you, seniors, juniors, peers). Pick one to read it. Typing here instructs the selected agent in this mission only."}
      actions={<Seg label="Conversation view" value={mode} onChange={setMode} items={[{ id: "full", label: "Full trace: missions, process, tool calls, reports", icon: ScrollText }, { id: "summary", label: "Summary: assignments, reports, results", icon: ClipboardCheck }]} />}>
      <div style={{ display: "grid", gridTemplateColumns: "36% 64%", gap: 8, height: "100%", minHeight: 0 }}>
        <div className="ax-col" style={{ minHeight: 0 }}>
          <div className="ax-flex" style={{ flexWrap: "wrap", gap: 3 }}>{KIND_FILTERS.map((k) => <button key={k.id} type="button" className="ax-tab" aria-pressed={kind === k.id} onClick={() => setKind(k.id)} style={kind === k.id ? { borderColor: "var(--ax-accent)", background: "color-mix(in srgb, var(--ax-accent) 20%, transparent)" } : { fontSize: 11 }}><span>{k.label}</span></button>)}</div>
          <div style={{ overflow: "auto", minHeight: 0 }}>
            {shown.map((t, k) => <Row key={t.id} i={k} sel={cur?.id === t.id} onClick={() => { setTid(t.id); readThread(t.id); }} label={threadTitle(t)}>
              <Avatar role={roleOf(t.a === agent ? t.b : t.a)} size={24} animate={false} /><span className="grow"><span className="t ax-small">{t.a === agent ? (t.b === "user" ? "You" : t.b) : (t.a === "user" ? "You" : t.a)}</span><span className="s">{relation(t, agent, agents)}</span></span>
              {t.unread > 0 && <Pill c="var(--ax-bad)" solid>{t.unread}</Pill>}<span className="ax-xs ax-muted"><Time iso={t.lastAt} /></span></Row>)}
            {!shown.length && <span className="ax-small ax-muted">No conversations of this kind yet.</span>}
          </div>
        </div>
        <div className="ax-col" style={{ minHeight: 0, border: "1px solid var(--ax-border)", borderRadius: 10, padding: 8 }}>
          <div className="ax-flex"><b className="ax-small">{cur ? threadTitle(cur) : `You ↔ ${agent}`}</b><span className="ax-spacer" />{cur && <CopyBtn text={msgs.map((m) => `[${m.at}] ${m.from} → ${m.to} (${m.kind}): ${m.text}`).join("\n")} label="Copy whole conversation" />}</div>
          <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>{msgs.length ? <Transcript messages={msgs} me={cur && (cur.a === "user" || cur.b === "user") ? "user" : agent} /> : <Empty icon={MessageSquareText} title="No messages yet" >Say hello: your instruction goes to {agent}.</Empty>}</div>
          {isUserThread ? <Composer missionId={missionId} to={agent} threadId={cur && (cur.a === "user" || cur.b === "user") ? cur.id : null} onSent={setTid} />
            : <div className="ax-flex ax-xs ax-muted"><Eye size={12} aria-hidden />Read-only agent-to-agent thread. <button type="button" className="ax-btn" style={{ padding: "2px 8px" }} onClick={() => setTid(userThread?.id ?? "__new")}>Message {agent}</button></div>}
        </div>
      </div>
    </Panel>
  );
}

/* ======================= CONVERSATIONS (CTRL-004/005, UI-AT-04) ======================= */
export function ConversationsTab({ missionId }: { missionId: string }) {
  const threads = useStore((s) => s.threads.filter((t) => t.missionId === missionId)); const messages = useStore((s) => s.messages);
  const [tid, setTid] = useQueryParam("thread", threads[0]?.id ?? ""); const [q, setQ] = useState(""), [kind, setKind] = useState("all"), [mode, setMode] = useState<"full" | "summary">("full");
  const [types, setTypes] = useState<Message["kind"][]>([]);
  const list = threads.filter((t) => (kind === "all" || t.kind === kind) && (!q || threadTitle(t).toLowerCase().includes(q.toLowerCase()) || messages.some((m) => m.threadId === t.id && m.text.toLowerCase().includes(q.toLowerCase()))));
  const cur = threads.find((t) => t.id === tid) ?? threads[0];
  const msgs = cur ? messages.filter((m) => m.threadId === cur.id && m.missionId === missionId && (mode === "full" || m.condensed) && (!types.length || types.includes(m.kind))) : [];
  const allTypes: Message["kind"][] = ["instruction", "plan", "tool", "report", "result", "message", "thought"];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "24fr 46fr 30fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Conversations" icon={MessagesSquare} help="Every conversation on this mission: with you, between seniors and juniors, and between peers. Search searches inside messages too."
        tabs={<div className="ax-col" style={{ gap: 5 }}><div className="ax-search"><Search size={13} aria-hidden /><input className="ax-input" style={{ padding: "4px 8px 4px 28px" }} placeholder="Search conversations" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search conversations" /></div>
          <div className="ax-flex" style={{ flexWrap: "wrap", gap: 3 }}>{KIND_FILTERS.map((k) => <button key={k.id} type="button" className="ax-tab" aria-pressed={kind === k.id} onClick={() => setKind(k.id)} style={kind === k.id ? { borderColor: "var(--ax-accent)", background: "color-mix(in srgb, var(--ax-accent) 20%, transparent)" } : { fontSize: 11 }}><span>{k.label}</span></button>)}</div></div>}>
        <ThreadList threads={list} value={cur?.id ?? null} onChange={setTid} />
      </Panel>
      <Panel i={1} title={cur ? threadTitle(cur) : "Conversation"} icon={MessageSquareText} help={{ body: "Full trace shows assigned and received missions, plans, tool calls, reports and results. Summary shows only assignments, reports and results. Every message has a time and a copy button.", policy: "Messages never cross missions (UI-AT-04)." }}
        headExtra={cur && <StatusPill s={cur.status} small />}
        actions={<><Seg label="View" value={mode} onChange={setMode} items={[{ id: "full", label: "Full trace", icon: ScrollText }, { id: "summary", label: "Summary only", icon: ClipboardCheck }]} />
          <IconBtn icon={Filter} label={types.length ? `Filtered: ${types.join(", ")}` : "Filter by message type"} size="sm" onClick={() => setTypes(types.length ? [] : ["instruction", "report", "result"])} />
          {cur && <CopyBtn text={msgs.map((m) => `[${m.at}] ${m.from} → ${m.to} (${m.kind}): ${m.text}`).join("\n")} label="Copy conversation" size="md" />}</>}>
        <div className="ax-col" style={{ height: "100%", minHeight: 0 }}>
          {types.length > 0 && <div className="ax-flex" style={{ flexWrap: "wrap", gap: 4 }}>{allTypes.map((t) => <label key={t} className="ax-flex ax-xs"><input type="checkbox" checked={types.includes(t)} onChange={() => setTypes(types.includes(t) ? types.filter((x) => x !== t) : [...types, t])} />{t}</label>)}</div>}
          <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>{msgs.length ? <Transcript messages={msgs} me={cur && (cur.a === "user" || cur.b === "user") ? "user" : cur!.a} /> : <Empty title="No messages in this view" />}</div>
          {cur && (cur.a === "user" || cur.b === "user") ? <Composer missionId={missionId} to={cur.a === "user" ? cur.b : cur.a} threadId={cur.id} /> : cur && <div className="ax-xs ax-muted ax-flex"><Eye size={12} aria-hidden />Agent-to-agent conversation (read-only). Open the Agents tab to message {cur.a} or {cur.b}.</div>}
        </div>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <GmWindow missionId={missionId} i={2} />
        <Panel i={3} title="Execution status" icon={ListTree} help="Every command in this conversation and whether it ran: queued, running, succeeded, failed, blocked or waiting for you (icon + text + colour).">
          <div className="ax-rows">{messages.filter((m) => m.missionId === missionId && m.state && (m.kind === "instruction" || m.kind === "tool")).slice(-10).reverse().map((m, k) => (
            <Row key={m.id} i={k}><StatusPill s={m.state!} small /><span className="grow"><span className="t ax-small">{m.text.slice(0, 70)}</span><span className="s">{m.from} → {m.to}</span></span><span className="ax-xs ax-muted"><Time iso={m.at} /></span></Row>))}</div>
        </Panel>
      </div>
    </div>
  );
}

/* ======================= APPROVALS (UI-AT-05) ======================= */
export function ApprovalsTab({ missionId }: { missionId: string }) {
  const approvals = useStore((s) => s.approvals.filter((a) => a.missionId === missionId));
  const [showResolved, setShowResolved] = useState(false); const [sel, setSel] = useQueryParam("a", "");
  const list = approvals.filter((a) => showResolved || a.status === "pending").sort((a, b) => (a.status === "pending" ? 0 : 1) - (b.status === "pending" ? 0 : 1) || ["High", "Medium", "Low"].indexOf(a.priority) - ["High", "Medium", "Low"].indexOf(b.priority));
  const cur = approvals.find((a) => a.id === sel) ?? list[0];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "32fr 40fr 28fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Pending decisions" icon={Inbox} help="Unanswered decisions only, most urgent first. Turn on “Show resolved” to see answered ones."
        actions={<label className="ax-flex ax-xs">{showResolved ? <Eye size={13} aria-hidden /> : <EyeOff size={13} aria-hidden />}Show resolved<input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /></label>}>
        <div className="ax-rows"><AnimatePresence initial={false}>{list.map((a, k) => (
          <motion.div key={a.id} layout exit={{ opacity: 0, x: -30 }}><Row i={k} sel={cur?.id === a.id} onClick={() => setSel(a.id)}>
            <Pill c={PRIORITY[a.priority]}>{a.priority}</Pill><span className="grow"><span className="t ax-small">{a.title}</span><span className="s">{a.area} · {a.ref} · due <Time iso={a.dueAt} withDate /></span></span>
            {a.status === "pending" ? <StatusPill s="waiting_user" label="Pending" small /> : <StatusPill s={a.status === "approved" ? "passed" : a.status === "rejected" ? "failed" : "review"} label={a.status} small />}
          </Row></motion.div>))}</AnimatePresence>
          {!list.length && <Empty icon={CheckCircle2} title="All decisions answered" />}</div>
      </Panel>
      <Panel i={1} title="Decision dossier" icon={FileText} help="The proposed action, why, alternatives, evidence, impact, author and risk.">
        {cur ? cur.status === "pending" ? <DecisionForm key={cur.id} a={cur} /> : (
          <div className="ax-col"><b>{cur.question}</b><p className="ax-small ax-muted">{cur.context}</p>
            <div className="ax-tile"><div className="ax-flex"><StatusPill s={cur.status === "approved" ? "passed" : "failed"} label={cur.status} /><span className="ax-xs ax-muted">by {cur.response?.by} · {cur.response && <Time iso={cur.response.at} withDate />}</span></div>
              <p style={{ margin: "6px 0 0" }}>“{cur.response?.text}”</p>{cur.response?.images.length ? <span className="ax-xs">{cur.response.images.length} image(s) attached</span> : null}</div></div>
        ) : <Empty title="Select a decision" />}
      </Panel>
      <Panel i={2} title="Context & audit" icon={History} help="Who asked, the risk tier, who may approve, and the audit trail for this decision.">
        {cur && <div className="ax-col">
          <dl className="ax-kv"><dt>Requested by</dt><dd><AgentTag id={cur.requestedBy} /></dd><dt>Risk tier</dt><dd>{cur.risk}</dd><dt>Approver</dt><dd>Owner / admin</dd><dt>Auto-approve</dt><dd>{cur.risk === "high" ? "Never" : "No"}</dd><dt>Created</dt><dd><Time iso={cur.at} withDate /></dd></dl>
          <div className="ax-divider" /><b className="ax-small">Context</b><p className="ax-small" style={{ margin: 0 }}>{cur.context}</p>
          <b className="ax-small">Evidence</b>{cur.evidence.map((e) => <span key={e} className="ax-chip"><FileText size={10} aria-hidden />{e}</span>)}
        </div>}
      </Panel>
    </div>
  );
}

/* ======================= ACTIVITY LOG ======================= */
export function ActivityTab({ missionId }: { missionId: string }) {
  const events = useStore((s) => s.events.filter((e) => e.missionId === missionId || e.missionId === null));
  const [actor, setActor] = useState("all"), [result, setResult] = useState("all"), [sev, setSev] = useState("all"), [q, setQ] = useState(""), [sel, setSel] = useState<Event | null>(null);
  const actors = [...new Set(events.map((e) => e.actor))];
  const list = events.filter((e) => (actor === "all" || e.actor === actor) && (result === "all" || e.result === result) && (sev === "all" || e.severity === sev) && (!q || (e.action + e.target + e.trace).toLowerCase().includes(q.toLowerCase())));
  const dl = (fmt: "json" | "csv") => {
    const data = fmt === "json" ? JSON.stringify(list, null, 2) : ["at,actor,action,target,result,severity,trace", ...list.map((e) => [e.at, e.actor, e.action, e.target, e.result, e.severity, e.trace].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([data], { type: fmt === "json" ? "application/json" : "text/csv" })); const a = document.createElement("a"); a.href = url; a.download = `axor-${missionId}-activity.${fmt}`; a.click(); URL.revokeObjectURL(url);
  };
  const color = { success: "passed", failure: "failed", running: "running", info: "ready", warning: "review" } as const;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "68fr 32fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Activity Log" icon={ScrollText} help={{ body: "Every command and state change on this mission, newest first, with trace IDs. Secrets are redacted.", policy: "Export is permission-scoped." }}
        actions={<><div className="ax-search" style={{ width: 170 }}><Search size={13} aria-hidden /><input className="ax-input" style={{ padding: "4px 8px 4px 28px" }} placeholder="Search events" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search events" /></div>
          <select className="ax-select" style={{ width: "auto", padding: "4px 8px" }} value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Actor"><option value="all">All agents</option>{actors.map((a) => <option key={a}>{a}</option>)}</select>
          <select className="ax-select" style={{ width: "auto", padding: "4px 8px" }} value={result} onChange={(e) => setResult(e.target.value)} aria-label="Result"><option value="all">All results</option><option value="success">Success</option><option value="failure">Failure</option><option value="running">Running</option><option value="warning">Warning</option><option value="info">Info</option></select>
          <select className="ax-select" style={{ width: "auto", padding: "4px 8px" }} value={sev} onChange={(e) => setSev(e.target.value)} aria-label="Severity"><option value="all">Any severity</option><option>high</option><option>medium</option><option>low</option><option>info</option></select>
          <IconBtn icon={FileJson} label="Export JSON" onClick={() => dl("json")} /><IconBtn icon={Download} label="Export CSV" onClick={() => dl("csv")} /></>} flush>
        <div style={{ overflow: "auto", height: "100%" }}><table className="ax-table"><thead><tr><th>Time</th><th>Initiator</th><th>Command / event</th><th>Target</th><th>Result</th><th>Severity</th><th>Trace</th><th aria-label="Copy" /></tr></thead>
          <tbody>{list.map((e) => <tr key={e.id} className={`click ${sel?.id === e.id ? "sel" : ""}`} onClick={() => setSel(e)} tabIndex={0} aria-selected={sel?.id === e.id} onKeyDown={(k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); setSel(e); } }}><td className="ax-num" style={{ whiteSpace: "nowrap" }}><Time iso={e.at} withDate /></td><td><AgentTag id={e.actor === "system" ? "OPS-01" : e.actor} size={18} /></td><td>{e.action}</td><td className="ax-muted">{e.target}</td>
            <td><StatusPill s={color[e.result]} label={e.result} small /></td><td><Pill c={e.severity === "high" ? "var(--ax-bad)" : e.severity === "medium" ? "var(--ax-warn)" : "var(--ax-neutral)"}>{e.severity}</Pill></td><td className="ax-mono ax-xs">{e.trace}</td>
            <td onClick={(ev) => ev.stopPropagation()}><CopyBtn text={JSON.stringify(e)} label="Copy event" /></td></tr>)}</tbody></table></div>
      </Panel>
      <Panel i={1} title="Trace inspector" icon={ListTree} help="Parent/child operations for the selected event (inputs are summarised, outputs digested).">
        {sel ? <div className="ax-col">
          <div className="ax-flex"><StatusPill s={color[sel.result]} label={sel.result} /><span className="ax-mono ax-xs">{sel.trace}</span><CopyBtn text={sel.trace} label="Copy trace id" /></div>
          <dl className="ax-kv"><dt>Initiator</dt><dd>{sel.actor}</dd><dt>Event</dt><dd>{sel.action}</dd><dt>Target</dt><dd>{sel.target}</dd><dt>Time</dt><dd><Time iso={sel.at} withDate /></dd><dt>Mission</dt><dd>{sel.missionId ?? "company-wide"}</dd></dl>
          <div className="ax-divider" />
          {[["request", "accepted by policy engine", "passed"], ["execute", sel.action, color[sel.result]], ["record", "event written · payload sha256 " + sel.trace.slice(3, 11), "passed"]].map(([k, v, st], i) => (
            <motion.div key={k} className="ax-flex ax-small" style={{ paddingLeft: i * 14 }} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .08 }}><ArrowDownRight size={12} className="ax-faint" aria-hidden /><b>{k}</b><span className="ax-muted" style={{ flex: 1 }}>{v}</span><StatusPill s={st as never} small /></motion.div>))}
        </div> : <Empty icon={ListTree} title="Select an event" />}
      </Panel>
    </div>
  );
}

/* ======================= REPORTS (per-agent: assigned, received, process, results) ======================= */
export function ReportsTab({ missionId }: { missionId: string }) {
  const instances = useStore((s) => s.instances.filter((i) => i.missionId === missionId)); const tasks = useStore((s) => s.tasks.filter((t) => t.missionId === missionId)); const messages = useStore((s) => s.messages.filter((m) => m.missionId === missionId));
  const [sel, setSel] = useState<string>(instances[0]?.agentId ?? "GM"); const [mode, setMode] = useState<"full" | "summary">("summary");
  const toast = useToast();
  const row = (a: string) => ({ assigned: tasks.filter((t) => t.instanceId.startsWith(a + "@")), received: messages.filter((m) => m.to === a && m.kind === "instruction"), reports: messages.filter((m) => m.from === a && (m.kind === "report" || m.kind === "result")), process: messages.filter((m) => m.from === a && (m.kind === "plan" || m.kind === "tool")) });
  const r = row(sel);
  const exportMd = () => { const md = `# ${missionId} report: ${sel}\n\n## Assigned\n${r.assigned.map((t) => `- ${t.id} ${t.title}: ${t.status} ${t.progress}%`).join("\n")}\n\n## Received\n${r.received.map((m) => `- ${m.at} ${m.from}: ${m.text}`).join("\n")}\n\n## Reports & results\n${r.reports.map((m) => `- ${m.at}: ${m.text}`).join("\n")}\n`;
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" })); const a = document.createElement("a"); a.href = url; a.download = `${missionId}-${sel}-report.md`; a.click(); URL.revokeObjectURL(url); toast("Report exported"); };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "40fr 60fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Reports by agent" icon={ClipboardCheck} help="For each agent: missions assigned, missions received, its reports and results." flush>
        <div style={{ overflow: "auto", height: "100%" }}><table className="ax-table"><thead><tr><th>Agent</th><th>Assigned</th><th>Received</th><th>Reports</th><th>Results</th><th>Status</th></tr></thead>
          <tbody>{instances.map((i) => { const x = row(i.agentId); return <tr key={i.id} className={`click ${sel === i.agentId ? "sel" : ""}`} onClick={() => setSel(i.agentId)} tabIndex={0} aria-selected={sel === i.agentId} onKeyDown={(k) => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); setSel(i.agentId); } }}><td><AgentTag id={i.agentId} size={18} /></td><td className="ax-num">{x.assigned.length}</td><td className="ax-num">{x.received.length}</td><td className="ax-num">{x.reports.length}</td><td className="ax-num">{x.assigned.filter((t) => t.status === "done").length}</td><td><StatusPill s={i.status} small /></td></tr>; })}</tbody></table></div>
      </Panel>
      <Panel i={1} title={<>Report · {sel}</>} icon={FileText} help="Summary shows assigned and received missions, reports and results. Full adds the working process (plans and tool calls)."
        actions={<><Seg label="Report view" value={mode} onChange={setMode} items={[{ id: "summary", label: "Summary", icon: ClipboardCheck }, { id: "full", label: "Full process", icon: ScrollText }]} /><IconBtn icon={Download} label="Export report (Markdown)" onClick={exportMd} /><CopyBtn text={r.reports.map((m) => m.text).join("\n")} label="Copy results" size="md" /></>}>
        <div className="ax-col" style={{ gap: 10 }}>
          {([["Assigned missions", r.assigned.map((t) => <Fragment key={t.id}><StatusPill s={t.status} small /> <b>{t.id}</b> {t.title} <span className="ax-muted">({t.progress}%)</span></Fragment>)],
            ["Received missions", r.received.map((m) => <Fragment key={m.id}><Time iso={m.at} /> <b>{m.from === "user" ? "You" : m.from}:</b> {m.text}</Fragment>)],
            ...(mode === "full" ? [["Process", r.process.map((m) => <Fragment key={m.id}><Time iso={m.at} /> <Pill c="var(--ax-accent2)" icon={Wrench}>{m.kind}</Pill> {m.text}</Fragment>)] as [string, JSX.Element[]]] : []),
            ["Reports & results", r.reports.map((m) => <Fragment key={m.id}><Time iso={m.at} /> {m.state && <StatusPill s={m.state} small />} {m.text}</Fragment>)]] as [string, JSX.Element[]][]).map(([h, items]) => (
            <section key={h}><b className="ax-small ax-gold">{h}</b><ul style={{ margin: "4px 0 0", paddingLeft: 0, listStyle: "none" }} className="ax-small">{items.length ? items.map((it, k) => <motion.li key={k} initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }} style={{ padding: "3px 0", borderBottom: "1px dashed color-mix(in srgb, var(--ax-border) 50%, transparent)" }}>{it}</motion.li>) : <li className="ax-muted">None</li>}</ul></section>))}
        </div>
      </Panel>
    </div>
  );
}
