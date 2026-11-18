import { useMemo, useRef, useState, useEffect, type CSSProperties } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, Check, CheckCircle2, ChevronDown, Circle, Download, Code2, Github, Hourglass, Image as ImageIcon, MessageSquarePlus, Paperclip, Play, Send, X,
} from "lucide-react";
import { Avatar, ROLES, type Role } from "./Avatar";
import { CopyBtn, IconBtn, Modal, PRIORITY, Pill, Progress, Row, StatusPill, Time, progressColors, statusInfo, useToast, Btn, Empty } from "./kit";
import { iconFor } from "./icons";
import { STAGES, type Approval, type Branch, type Event, type Message, type Mission, type Release, type Stage, type Task, type Thread } from "../domain/types";
import { liveMode, decide, getState, nameOf, toastIfErr, readThread, sendMessage, useStore, agentById } from "../data/store";
import { href } from "../app/router";

/* ---------- agent chip ---------- */
export function roleOf(id: string): Role {
  if (id === "user") return "user";
  // non-reactive read: agent roles don't change at runtime
  const a = getState().agents.find((x) => x.id === id.split("@")[0]);
  return a?.role ?? "developer";
}

export function AgentTag({ id, size = 22, sub }: { id: string; size?: number; sub?: string }) {
  const base = id.split("@")[0];
  return <span className="ax-flex" style={{ gap: 6 }}><Avatar role={roleOf(base)} size={size} name={base} /><span style={{ minWidth: 0 }}><b className="ax-small">{base === "user" ? "You" : base}</b>{sub && <span className="ax-xs ax-muted" style={{ display: "block" }}>{sub}</span>}</span></span>;
}

/* ---------- mission rows (HOME-002/003) ---------- */
export function IssuesBadge({ m }: { m: Mission }) {
  if (!m.issuesOpen && !m.decisionsPending) return <span className="ax-faint" aria-label="No open issues">–</span>;
  return (
    <span className="ax-flex" style={{ gap: 4 }} aria-label={`${m.issuesOpen} open issues, ${m.decisionsPending} need your decision`}>
      {m.issuesOpen > 0 && <span className="ax-flex ax-warn" style={{ gap: 2 }} data-tip={`${m.issuesOpen} open issue(s)`}><AlertTriangle size={13} aria-hidden /><b className="ax-small">{m.issuesOpen}</b></span>}
      {m.decisionsPending > 0 && <a href={href("control", m.id, { tab: "approvals" })} onClick={(e) => e.stopPropagation()} className="ax-pill solid" style={{ "--c": "var(--ax-blocked)", textDecoration: "none", padding: "0 6px" } as CSSProperties}
        data-tip={`${m.decisionsPending} need your decision`}><Hourglass size={10} aria-hidden />{m.decisionsPending}</a>}
    </span>
  );
}
export function MissionIcon({ m, size = 30 }: { m: Mission; size?: number }) {
  const I = iconFor(m.icon);
  return <motion.span style={{ width: size, height: size, borderRadius: 8, display: "grid", placeItems: "center", flex: "none", color: m.color, background: `color-mix(in srgb, ${m.color} 16%, transparent)`, border: `1px solid color-mix(in srgb, ${m.color} 45%, transparent)` }}
    whileHover={{ rotate: -8, scale: 1.1 }} aria-hidden><I size={size * .55} /></motion.span>;
}
export function MissionRows({ missions, onOpen, selected }: { missions: Mission[]; onOpen: (m: Mission) => void; selected?: string }) {
  return (
    <div className="ax-rows">
      {missions.map((m, i) => { const [c1, c2] = progressColors(m.progress, m.status); return (
        <Row key={m.id} i={i} onClick={() => onOpen(m)} sel={selected === m.id} label={`${m.title}, ${m.progress}%`}>
          <MissionIcon m={m} size={26} />
          <span className="grow"><span className="t">{m.title}</span><span className="s">{m.summary}</span></span>
          <span style={{ width: 82, flex: "none" }}><b className="ax-small ax-num">{m.progress}%</b><Progress value={m.progress} c1={c1} c2={c2} thin label={`${m.title} progress`} /></span>
          <span className="ax-small ax-num" style={{ width: 44, flex: "none" }}>{m.version}</span>
          <span style={{ width: 50, flex: "none", display: "flex", justifyContent: "flex-end" }}><IssuesBadge m={m} /></span>
        </Row>); })}
    </div>
  );
}

/* ---------- stage stepper ---------- */
export function StageStepper({ stage, compact }: { stage: Stage; compact?: boolean }) {
  const cur = STAGES.findIndex((s) => s.id === stage);
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${STAGES.length}, 1fr)`, position: "relative", alignItems: "start" }} role="list" aria-label="Mission stages">
      <div style={{ position: "absolute", top: compact ? 9 : 11, left: `${50 / STAGES.length}%`, right: `${50 / STAGES.length}%`, height: 2, background: "var(--ax-border)" }} aria-hidden>
        <motion.div style={{ height: "100%", background: "linear-gradient(90deg, var(--ax-ok), var(--ax-info))" }} initial={{ width: 0 }} animate={{ width: `${(cur / (STAGES.length - 1)) * 100}%` }} transition={{ duration: 1 }} />
      </div>
      {STAGES.map((s, i) => { const done = i < cur, now = i === cur; const sz = compact ? 20 : 24; return (
        <div key={s.id} role="listitem" aria-label={`${s.label}: ${done ? "done" : now ? "current" : "pending"}`} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, position: "relative" }}>
          <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .1 * i, type: "spring" }} style={{ width: sz, height: sz, borderRadius: "50%", display: "grid", placeItems: "center",
            background: done ? "var(--ax-ok)" : now ? "var(--ax-panel2)" : "var(--ax-panel2)", border: `2px solid ${done ? "var(--ax-ok)" : now ? "var(--ax-info)" : "var(--ax-faint)"}`,
            boxShadow: now ? "0 0 12px var(--ax-info)" : done ? "0 0 8px color-mix(in srgb, var(--ax-ok) 60%, transparent)" : "none", color: "#fff" }}>
            {done ? <Check size={sz * .6} strokeWidth={3} aria-hidden /> : now ? <motion.i className="ax-pulse" style={{ width: sz * .4, height: sz * .4, borderRadius: "50%", background: "var(--ax-info)" }} /> : null}
          </motion.span>
          <span className="ax-small" style={{ color: now ? "var(--ax-text)" : done ? "var(--ax-text)" : "var(--ax-muted)", fontWeight: now ? 700 : 500 }}>{s.label}</span>
        </div>); })}
    </div>
  );
}

/* ---------- Gantt / timeline with Today marker ---------- */
export function Gantt({ tasks, onSelect, selected, rowH = 24, labelW = 140, days }: { tasks: Task[]; onSelect?: (t: Task) => void; selected?: string; rowH?: number; labelW?: number; days?: number }) {
  const { from, to } = useMemo(() => {
    const now = Date.now(); const D = 864e5;
    if (days) return { from: now - Math.floor(days * .55) * D, to: now + Math.ceil(days * .45) * D };
    const s = Math.min(...tasks.map((t) => +new Date(t.start))), e = Math.max(...tasks.map((t) => +new Date(t.end)));
    return { from: Math.min(s, now - D), to: Math.max(e, now + D) };
  }, [tasks, days]);
  const span = to - from, pct = (t: number) => ((t - from) / span) * 100;
  const dayTicks = useMemo(() => { const out: number[] = []; const d = new Date(from); d.setHours(0, 0, 0, 0); for (let t = +d; t <= to; t += 864e5) if (t >= from) out.push(t); return out; }, [from, to]);
  const step = Math.max(1, Math.ceil(dayTicks.length / 9));
  const today = pct(Date.now());
  return (
    <div style={{ display: "grid", gridTemplateColumns: `${labelW}px 1fr`, fontSize: 12, minWidth: 0 }} role="table" aria-label="Timeline">
      <div />
      <div style={{ position: "relative", height: 20, borderBottom: "1px solid var(--ax-border)" }} role="row">
        {dayTicks.map((t, i) => i % step === 0 && <span key={t} className="ax-muted ax-num" style={{ position: "absolute", left: `${pct(t)}%`, transform: "translateX(-10%)", fontSize: 11, whiteSpace: "nowrap" }}>
          {i === 0 || new Date(t).getDate() === 1 ? new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : new Date(t).getDate()}</span>)}
        <motion.span initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} style={{ position: "absolute", left: `${today}%`, top: -1, transform: "translateX(-50%)", padding: "0 6px", borderRadius: 5, fontSize: 10.5, fontWeight: 700, background: "var(--ax-blocked)", color: "#fff", zIndex: 2 }}>Today</motion.span>
      </div>
      {tasks.map((t, i) => { const d = statusInfo(t.status); const L = pct(+new Date(t.start)), W = Math.max(1.5, pct(+new Date(t.end)) - L); const I = d.icon; return (
        <div key={t.id} role="row" style={{ display: "contents" }}>
          <button type="button" onClick={() => onSelect?.(t)} className="ax-flex" aria-label={`${t.title}: ${d.label}`}
            style={{ height: rowH, border: 0, background: selected === t.id ? "color-mix(in srgb, var(--ax-accent) 14%, transparent)" : "transparent", cursor: onSelect ? "pointer" : "default", padding: "0 4px", borderRadius: 6, gap: 6, textAlign: "left" }}>
            <I size={13} style={{ color: d.c, flex: "none" }} className={d.spin ? "ax-spin" : ""} aria-hidden /><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</span>
          </button>
          <div style={{ position: "relative", height: rowH, borderBottom: "1px dashed color-mix(in srgb, var(--ax-border) 40%, transparent)" }}>
            {i === 0 && <div style={{ position: "absolute", left: `${today}%`, top: 0, height: rowH * tasks.length, borderLeft: "1.5px dashed var(--ax-blocked)", zIndex: 1 }} aria-hidden />}
            <motion.div onClick={() => onSelect?.(t)} data-tip={`${t.title} · ${d.label} · ${t.progress}%`}
              initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ delay: .05 * i, duration: .6, ease: [.2, .8, .2, 1] }}
              style={{ position: "absolute", left: `${L}%`, width: `${W}%`, top: rowH * .22, height: rowH * .56, borderRadius: 999, originX: 0, cursor: onSelect ? "pointer" : "default",
                background: `linear-gradient(90deg, ${d.c}, color-mix(in srgb, ${d.c} 60%, #fff))`, boxShadow: `0 0 calc(10px * var(--ax-glow-k)) ${d.c}`, opacity: t.status === "queued" ? .55 : 1,
                outline: selected === t.id ? "2px solid var(--ax-accent)" : "none" }}>
              <div style={{ width: `${t.progress}%`, height: "100%", borderRadius: 999, background: "rgb(255 255 255 / .25)" }} />
            </motion.div>
          </div>
        </div>); })}
    </div>
  );
}

/* ---------- Org tree (GM → departments) ---------- */
export function OrgTree({ onSelect, compact }: { onSelect?: (deptId: string) => void; compact?: boolean }) {
  const depts = useStore((s) => s.departments); const agents = useStore((s) => s.agents);
  const count = (d: string) => agents.filter((a) => a.dept === d).length;
  const n = depts.length;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", height: "100%", minHeight: 0 }}>
      <motion.button type="button" className="ax-tile click" onClick={() => onSelect?.("executive")} style={{ display: "flex", gap: 10, alignItems: "center", borderColor: "var(--ax-accent)", boxShadow: "0 0 14px var(--ax-glow)" }}
        initial={{ y: -10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} whileHover={{ scale: 1.04 }} aria-label="General Manager: strategy, planning, control">
        <Avatar role="gm" size={compact ? 34 : 42} name="GM" status="busy" />
        <span style={{ textAlign: "left" }}><b>General Manager (GM)</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Strategy · Planning · Control</span></span>
      </motion.button>
      <svg width="100%" height="26" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden style={{ flex: "none" }}>
        <path d="M50 0 V10" stroke="var(--ax-accent)" strokeWidth=".6" />
        <path d={`M${50 / n} 10 H${100 - 50 / n}`} stroke="var(--ax-accent)" strokeWidth=".6" />
        {depts.map((_, i) => <motion.path key={i} d={`M${(100 / n) * i + 50 / n} 10 V26`} stroke="var(--ax-accent)" strokeWidth=".6" className="ax-flow-dash" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .2 + i * .05 }} />)}
      </svg>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${n}, 1fr)`, gap: 6, width: "100%" }}>
        {depts.map((d, i) => (
          <motion.button key={d.id} type="button" className="ax-tile click" onClick={() => onSelect?.(d.id)} aria-label={`${d.name}: ${count(d.id)} agents`}
            initial={{ y: 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: .25 + i * .05 }} whileHover={{ y: -3 }}
            style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, padding: "6px 2px" }}>
            <Avatar role={d.role} size={compact ? 30 : 36} name={d.name} />
            <span style={{ fontWeight: 600, textAlign: "center", lineHeight: 1.1, fontSize: 9.5, maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.name.replace(" / Verifier", "/QA")}</span>
            <span className="ax-xs ax-muted">({count(d.id)})</span>
          </motion.button>))}
      </div>
    </div>
  );
}

/* ---------- git graph (main ↔ feature ↔ merge) ---------- */
export function GitGraph({ branches, onSelect, selected, rowH = 30 }: { branches: Branch[]; onSelect?: (b: Branch) => void; selected?: string; rowH?: number }) {
  const feats = branches.filter((b) => b.kind !== "main");
  const H = (feats.length + 2) * rowH;
  const colOf = (b: Branch) => (b.kind === "release" ? 2 : b.kind === "agent" ? 3 : 1);
  const color = (b: Branch) => ({ merged: "var(--ax-blocked)", open: "var(--ax-info)", conflict: "var(--ax-bad)", staged: "var(--ax-warn)", protected: "var(--ax-ok)" }[b.status]);
  return (
    <div style={{ position: "relative", height: H, minWidth: 0 }} role="list" aria-label="Branch graph">
      <svg width="100%" height={H} style={{ position: "absolute", inset: 0 }} aria-hidden>
        <motion.line x1="16" y1={rowH / 2} x2="16" y2={H - rowH / 2} stroke="var(--ax-ok)" strokeWidth="3" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: .8 }} />
        {feats.map((b, i) => { const y = (i + 1.5) * rowH, x = 16 + colOf(b) * 22; const c = color(b);
          return <g key={b.name}>
            <motion.path d={`M16 ${y - rowH * .9} C16 ${y - rowH * .4}, ${x} ${y - rowH * .6}, ${x} ${y}`} fill="none" stroke={c} strokeWidth="2" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .1 * i, duration: .6 }} />
            {b.status === "merged" && <motion.path d={`M${x} ${y} C${x} ${y + rowH * .5}, 16 ${y + rowH * .3}, 16 ${y + rowH * .8}`} fill="none" stroke={c} strokeWidth="2" strokeDasharray="4 3" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .2 + .1 * i }} />}
            <motion.circle cx={x} cy={y} r="6" fill="var(--ax-panel2)" stroke={c} strokeWidth="2.5" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .15 + .1 * i, type: "spring" }} />
          </g>; })}
        <circle cx="16" cy={rowH / 2} r="7" fill="var(--ax-ok)" />
        <circle cx="16" cy={H - rowH / 2} r="7" fill="var(--ax-panel2)" stroke="var(--ax-ok)" strokeWidth="3" />
      </svg>
      <div style={{ position: "absolute", left: 30, top: 0, right: 0 }}>
        <div className="ax-flex" style={{ height: rowH }}><b className="ax-small">main ({branches.find((b) => b.kind === "main")?.version})</b><Pill c="var(--ax-ok)">Stable</Pill></div>
        {feats.map((b) => (
          <motion.button key={b.name} type="button" role="listitem" onClick={() => onSelect?.(b)} className="ax-flex" whileHover={{ x: 3 }}
            style={{ height: rowH, paddingLeft: colOf(b) * 22 + 4, border: 0, background: selected === b.name ? "color-mix(in srgb, var(--ax-accent) 14%, transparent)" : "transparent", borderRadius: 6, width: "100%", cursor: onSelect ? "pointer" : "default", textAlign: "left" }}
            aria-label={`${b.name} ${b.version}, ${b.status}`}>
            <span className="ax-small" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.name} <span className="ax-muted">({b.version})</span></span>
            {b.status !== "merged" && <Pill c={color(b)}>{b.status}</Pill>}
          </motion.button>))}
        <div className="ax-flex" style={{ height: rowH }}><b className="ax-small">main ({branches.find((b) => b.kind === "main")?.version})</b></div>
      </div>
    </div>
  );
}

export function ReleaseCard({ r, compact }: { r: Release; compact?: boolean }) {
  const toast = useToast();
  return (
    <div className="ax-tile" style={{ height: "100%", display: "flex", flexDirection: "column", gap: 6 }}>
      <div className="ax-flex"><b style={{ fontSize: compact ? 18 : 22 }}>{r.version}</b><Pill c={r.status === "failed" ? "var(--ax-bad)" : "var(--ax-ok)"} solid={r.status === "current" || r.status === "candidate"}>{r.status === "candidate" ? "Current" : r.status}</Pill></div>
      <div className="ax-col" style={{ gap: 3 }}>{r.notes.map((n, i) => <motion.span key={n} className="ax-flex ax-small" initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .1 + i * .06 }}><CheckCircle2 size={13} className="ax-ok" aria-hidden />{n}</motion.span>)}</div>
      <div className="ax-flex" style={{ marginTop: "auto" }}>
        <IconBtn icon={Download} label={`Download ${r.version} artifacts`} onClick={() => toast(`${r.artifacts[0].name} · sha256 ${r.artifacts[0].sha256.slice(0, 12)}… (sample artifact)`, "info")} />
        <IconBtn icon={compact ? Code2 : Play} label={compact ? "View source diff" : `Run ${r.version} preview`} onClick={() => { window.location.hash = compact ? href("versions", null, { tab: "compare" }) : href("versions", null, { tab: "preview", v: r.version }); }} />
        <IconBtn icon={Github} label="Open on GitHub" onClick={() => toast("Repository link opens GitHub (sample mission repo)", "info")} />
      </div>
    </div>
  );
}

/* ---------- activity list ---------- */
export function ActivityList({ events, compact, limit }: { events: Event[]; compact?: boolean; limit?: number }) {
  const list = limit ? events.slice(0, limit) : events;
  const color = { success: "var(--ax-ok)", failure: "var(--ax-bad)", running: "var(--ax-info)", info: "var(--ax-accent2)", warning: "var(--ax-warn)" };
  return (
    <div className="ax-rows" role="feed" aria-label="Activity">
      {list.map((e, i) => { const I = iconFor(e.icon); return (
        <Row key={e.id} i={i}>
          <span style={{ color: color[e.result], display: "grid", flex: "none" }} aria-label={e.result}><I size={15} aria-hidden /></span>
          <span className="grow"><span className="t" style={{ fontWeight: 500 }}><b>{e.actor === "user" ? "You" : e.actor}</b> {e.action}{!compact && <> · <span className="ax-muted">{e.target}</span></>}</span></span>
          <span className="ax-xs ax-muted"><Time iso={e.at} /></span>
        </Row>); })}
      {!list.length && <Empty title="No activity yet" />}
    </div>
  );
}

/* ---------- decision inbox rows (quick approve/reject; CTRL-009) ---------- */
export function DecisionRows({ approvals, compact }: { approvals: Approval[]; compact?: boolean }) {
  const [confirm, setConfirm] = useState<{ a: Approval; ok: boolean } | null>(null);
  const toast = useToast();
  const act = (a: Approval, ok: boolean) => {
    if (a.risk === "high" || a.destructive || !ok) { setConfirm({ a, ok }); return; }
    if (!toastIfErr(decide(a.id, a.options.find((o) => o.recommended)?.id ?? a.options[0]?.id, "Approved from the inbox", []), toast) && !liveMode()) toast(`Approved: ${a.title}`);
  };
  return (
    <>
      <div className="ax-rows">
        <AnimatePresence initial={false}>
          {approvals.map((a, i) => (
            <motion.div key={a.id} layout exit={{ opacity: 0, x: 40, height: 0 }}>
              <Row i={i}>
                <span className="ax-gold" style={{ display: "grid" }}><MessageSquarePlus size={16} aria-hidden /></span>
                <a className="grow" href={getState().missions.some((m) => m.id === a.missionId) ? href("control", a.missionId, { tab: "approvals", a: a.id }) : href("notifications", null, { tab: "pending" })} style={{ color: "inherit", textDecoration: "none", minWidth: 0 }}>
                  <span className="t">{a.title}</span><span className="s">{a.area} · {a.ref}</span></a>
                <Pill c={PRIORITY[a.priority]}>{a.priority}</Pill>
                {!compact && <span className="ax-xs ax-muted"><Time iso={a.at} /></span>}
                {a.status === "pending" ? <>
                  <IconBtn icon={Check} label={`Approve: ${a.title}`} tone="ok" size="sm" onClick={() => act(a, true)} />
                  <IconBtn icon={X} label={`Reject: ${a.title}`} tone="bad" size="sm" onClick={() => act(a, false)} />
                </> : <StatusPill s={a.status === "approved" ? "passed" : a.status === "rejected" ? "failed" : "review"} label={a.status} small />}
              </Row>
            </motion.div>))}
        </AnimatePresence>
        {!approvals.length && <Empty icon={CheckCircle2} title="Nothing waiting for you" />}
      </div>
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm?.ok ? "Confirm approval" : "Reject request"} icon={confirm?.ok ? Check : X} width={520}
        foot={<><span className="ax-spacer" /><Btn onClick={() => setConfirm(null)}>Cancel</Btn>
          <Btn tone="gold" icon={confirm?.ok ? Check : X} onClick={() => { if (!confirm) return; const err = decide(confirm.a.id, confirm.ok ? (confirm.a.options.find((o) => o.recommended)?.id ?? confirm.a.options[0].id) : "reject", confirm.ok ? "Approved after confirmation" : "Rejected from the inbox", []); if (!toastIfErr(err, toast) && !liveMode()) toast(confirm.ok ? "Approved" : "Rejected", confirm.ok ? "ok" : "warn"); setConfirm(null); }}>
            {confirm?.ok ? "Approve" : "Reject"}</Btn></>}>
        {confirm && <div className="ax-col">
          <b>{confirm.a.title}</b><span className="ax-muted">{confirm.a.question}</span>
          <dl className="ax-kv"><dt>Impact</dt><dd>{confirm.a.impact}</dd><dt>Risk</dt><dd>{confirm.a.risk}</dd>{confirm.ok && <><dt>Option</dt><dd>{confirm.a.options.find((o) => o.recommended)?.label ?? confirm.a.options[0].label}</dd></>}</dl>
          <span className="ax-xs ax-muted">High-impact decisions are never auto-approved. This decision is recorded with your name and time.</span>
        </div>}
      </Modal>
    </>
  );
}

/* ---------- chat (thread list + transcript + composer; CTRL-002..006) ---------- */
export function threadTitle(t: Thread) { return `${t.a === "user" ? "User" : t.a} ↔ ${t.b === "user" ? "User" : t.b}`; }
export function ThreadList({ threads, value, onChange, compact }: { threads: Thread[]; value: string | null; onChange: (id: string) => void; compact?: boolean }) {
  return (
    <div className="ax-rows" role="listbox" aria-label="Conversations">
      {threads.map((t, i) => (
        <Row key={t.id} i={i} sel={value === t.id} onClick={() => { onChange(t.id); readThread(t.id); }} label={threadTitle(t)}>
          <Avatar role={roleOf(t.a === "user" ? t.b : t.a)} size={compact ? 20 : 26} animate={false} />
          <span className="grow"><span className="t ax-small">{threadTitle(t)}</span>{!compact && <span className="s">{t.kind}</span>}</span>
          {t.unread > 0 && <span className="ax-count" style={{ background: "var(--ax-bad)", color: "#fff", borderRadius: 999, fontSize: 10, padding: "0 5px" }} aria-label={`${t.unread} unread`}>{t.unread}</span>}
          <span className="ax-xs ax-muted"><Time iso={t.lastAt} /></span>
        </Row>))}
    </div>
  );
}
const KIND_LABEL: Record<Message["kind"], string> = { instruction: "Instruction", report: "Report", message: "Message", plan: "Plan", tool: "Tool call", result: "Result", system: "System", thought: "GM note" };
export function Transcript({ messages, me = "user", showMeta = true }: { messages: Message[]; me?: string; showMeta?: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages.length]);
  const sorted = [...messages].sort((a, b) => +new Date(a.at) - +new Date(b.at) || a.id.localeCompare(b.id));
  return (
    <div className="ax-chat" aria-live="polite">
      {sorted.map((m, i) => { const mine = m.from === me || (me !== "user" && m.from === "user"); const sys = m.kind === "tool" || m.kind === "system" || m.kind === "thought"; return (
        <motion.div key={m.id} className={`ax-msg ${mine ? "me" : ""} ${sys ? "sys" : ""}`} initial={{ opacity: 0, y: 10, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ delay: Math.min(i, 8) * .03 }}>
          <Avatar role={roleOf(m.from)} size={26} animate={false} />
          <div style={{ minWidth: 0 }}>
            <div className="ax-bubble">
              {showMeta && <div className="ax-xs ax-muted" style={{ marginBottom: 2 }}><b style={{ color: "var(--ax-text)" }}>{m.from === "user" ? "You" : m.from}</b> → {m.to === "user" ? "You" : m.to} · {KIND_LABEL[m.kind]}</div>}
              <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{m.text}</span>
              {m.attachments?.length ? <div className="ax-flex" style={{ marginTop: 4, flexWrap: "wrap" }}>{m.attachments.map((f) => <span key={f} className="ax-chip"><Paperclip size={10} aria-hidden />{f}</span>)}</div> : null}
            </div>
            <div className="ax-bubble-meta" style={{ justifyContent: mine ? "flex-end" : "flex-start" }}>
              <Time iso={m.at} />{m.state && <StatusPill s={m.state} small />}<CopyBtn text={`[${new Date(m.at).toISOString()}] ${m.from} → ${m.to}: ${m.text}`} label="Copy message" />
            </div>
          </div>
        </motion.div>); })}
      <div ref={end} />
    </div>
  );
}
export function Composer({ missionId, to, threadId, onSent, compact }: { missionId: string; to: string; threadId: string | null; onSent?: (tid: string) => void; compact?: boolean }) {
  const [text, setText] = useState(""); const [files, setFiles] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null), imgRef = useRef<HTMLInputElement>(null);
  const send = () => { if (!text.trim()) return; const tid = sendMessage(missionId, threadId, to, text.trim(), files); setText(""); setFiles([]); onSent?.(tid); };
  return (
    <div className="ax-col" style={{ gap: 4 }}>
      {files.length > 0 && <div className="ax-flex" style={{ flexWrap: "wrap" }}>{files.map((f) => <span key={f} className="ax-chip">{f}<button type="button" aria-label={`Remove ${f}`} onClick={() => setFiles(files.filter((x) => x !== f))} style={{ border: 0, background: "none", cursor: "pointer", padding: 0, color: "inherit" }}><X size={10} /></button></span>)}</div>}
      <div className="ax-composer">
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder={liveMode() ? `Message ${to} (real AXoR chat; uses model credits)…` : compact ? "Type a message..." : `Message ${to === "user" ? "" : to} (mission ${missionId})…`} aria-label={`Message to ${to} in mission ${missionId}`} />
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => setFiles([...files, ...[...(e.target.files ?? [])].map((f) => f.name)])} />
        <input ref={imgRef} type="file" accept="image/*" multiple hidden onChange={(e) => setFiles([...files, ...[...(e.target.files ?? [])].map((f) => f.name)])} />
        <IconBtn icon={Paperclip} label="Attach file" tone="ghost" size="sm" onClick={() => fileRef.current?.click()} />
        {!compact && <IconBtn icon={ImageIcon} label="Attach image" tone="ghost" size="sm" onClick={() => imgRef.current?.click()} />}
        <IconBtn icon={Send} label="Send" tone="info" size="sm" onClick={send} disabled={!text.trim()} />
      </div>
    </div>
  );
}

/* ---------- small things ---------- */
export function Dropdown({ value, options, onChange, label }: { value: string; options: { id: string; label: string }[]; onChange: (v: string) => void; label: string }) {
  return (
    <span style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
      <select className="ax-select" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} style={{ paddingRight: 26, appearance: "none", width: "auto", fontSize: 12, padding: "4px 26px 4px 9px" }}>
        {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
      <ChevronDown size={13} style={{ position: "absolute", right: 8, pointerEvents: "none" }} aria-hidden />
    </span>
  );
}
export function Check2({ on }: { on: boolean }) { return on ? <CheckCircle2 size={14} className="ax-ok" aria-label="yes" /> : <Circle size={14} className="ax-faint" aria-label="no" />; }
export function roleLabel(r: Role) { return ROLES[r]?.label ?? r; }
export { agentById, nameOf };
