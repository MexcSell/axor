import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, AlertTriangle, Bell, BellRing, Bot, CheckCheck, CheckCircle2, Clock3, Inbox, Info, ListChecks, Mail, Rocket, ScrollText, Settings2, Slack, Target, XCircle, ExternalLink, Newspaper, Check, Radio, ArrowRight, Play, Zap, CircleDot,
} from "lucide-react";
import { Count, Donut, IconBtn, Legend, Pill, Seg, StatusPill, Switch, TabBody, Tabs, Time, Empty, Btn, useToast, Panel } from "../ui/kit";
import { DecisionRows } from "../ui/widgets";
import { Avatar } from "../ui/Avatar";
import { roleOf } from "../ui/widgets";
import { markNotice, setSettings, useStore } from "../data/store";
import { href, useQueryParam } from "../app/router";
import type { Notice } from "../domain/types";
import { Card, ToggleRow, grid } from "./settings/parts";

// Notifications & Activity (40-14): inbox of notices, approvals waiting for you, resolved history and delivery rules.
const KIND: Record<Notice["kind"], { label: string; icon: typeof Bell; c: string }> = {
  decision: { label: "Decision", icon: ListChecks, c: "var(--ax-warn)" }, failure: { label: "Failure", icon: XCircle, c: "var(--ax-bad)" }, release: { label: "Release", icon: Rocket, c: "var(--ax-ok)" },
  agent: { label: "Update", icon: Bot, c: "var(--ax-info)" }, system: { label: "System", icon: Settings2, c: "var(--ax-info)" }, mission: { label: "Mission", icon: Target, c: "var(--ax-ok)" },
};
const SEV: Record<Notice["severity"], { label: string; c: string; icon: typeof Bell }> = {
  high: { label: "Critical", c: "var(--ax-bad)", icon: AlertTriangle }, medium: { label: "Warning", c: "var(--ax-warn)", icon: AlertTriangle }, low: { label: "Low", c: "var(--ax-info)", icon: Info }, info: { label: "Info", c: "var(--ax-info)", icon: Info },
};

function NoticeRows({ list, onRead }: { list: Notice[]; onRead?: (id: string) => void }) {
  return (
    <div className="ax-rows">
      <AnimatePresence initial={false}>
        {list.map((n, i) => { const k = KIND[n.kind], sv = SEV[n.severity], I = k.icon; return (
          <motion.div key={n.id} layout initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }} transition={{ delay: Math.min(i, 8) * .03 }} whileHover={{ x: 2 }}
            className="ax-row" style={{ padding: "7px 8px", border: "1px solid var(--ax-border)", borderRadius: "var(--ax-radius-sm)", opacity: n.read ? .72 : 1 }}>
            <span style={{ color: k.c, display: "grid" }}><I size={18} aria-hidden /></span>
            <Pill c={sv.c} icon={sv.icon}>{sv.label}</Pill>
            <span className="grow"><span className="t">{n.title}{!n.read && <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}> (unread)</span>}</span><span className="s">{k.label} · {n.detail}</span></span>
            <span className="ax-xs ax-muted"><Time iso={n.at} /></span>
            {!n.read ? <><span aria-label="Unread" style={{ width: 8, height: 8, borderRadius: 8, background: "var(--ax-accent)", flex: "none" }} />{onRead && <IconBtn icon={Check} label={`Mark as read: ${n.title}`} size="sm" onClick={() => onRead(n.id)} />}</> : <CheckCircle2 size={14} className="ax-faint" aria-label="Read" />}
            {n.missionId && <a href={href("control", n.missionId)} aria-label={`Open mission for ${n.title}`} data-tip="Open mission" className="ax-ib sm"><ExternalLink size={12} aria-hidden /></a>}
          </motion.div>); })}
      </AnimatePresence>
      {!list.length && <Empty icon={CheckCheck} title="Nothing here" />}
    </div>
  );
}

export default function Notifications() {
  const [tab, setTab] = useQueryParam("tab", "inbox");
  const notices = useStore((s) => s.notices), approvals = useStore((s) => s.approvals), events = useStore((s) => s.events), settings = useStore((s) => s.settings);
  const toast = useToast();
  const [sev, setSev] = useState<"all" | Notice["severity"]>("all");
  const pending = approvals.filter((a) => a.status === "pending"), resolvedA = approvals.filter((a) => a.status !== "pending");
  const unread = notices.filter((n) => !n.read);
  const sevCount = useMemo(() => ({ high: notices.filter((n) => n.severity === "high").length, medium: notices.filter((n) => n.severity === "medium").length, low: notices.filter((n) => n.severity === "low" || n.severity === "info").length, resolved: notices.filter((n) => n.read).length }), [notices]);
  const shown = notices.filter((n) => sev === "all" || n.severity === sev);
  const tabs = [{ id: "inbox", label: "Inbox", icon: Inbox, count: unread.length }, { id: "pending", label: "Pending", icon: ListChecks, alert: pending.length || undefined }, { id: "resolved", label: "Resolved", icon: CheckCheck }, { id: "rules", label: "Rules", icon: ScrollText }];
  const agentVersions = useStore((s) => s.agentVersions), missions = useStore((s) => s.missions);
  const sysEvents = events.filter((e) => e.actor === "system" || e.result === "info");
  const liveMissions = missions.filter((m) => !m.archived);
  const tiles = [
    { l: "Active Alerts", v: sevCount.high + sevCount.medium, I: AlertTriangle, c: "var(--ax-bad)", d: "needs attention" }, { l: "System Events", v: sysEvents.length, I: Radio, c: "var(--ax-info)", d: "recorded" },
    { l: "Agent Updates", v: agentVersions.length, I: Bot, c: "var(--ax-blocked)", d: "versions" }, { l: "Mission Updates", v: liveMissions.length, I: Target, c: "var(--ax-ok)", d: "tracked" },
  ];
  const bottom = { agentVersions, sysEvents, liveMissions };
  return (
    <div className="ax-page">
      <Panel i={0} title="Notifications & Activity" icon={Bell} sub="Alerts, system events, agent updates and approvals that need you"
        help={{ body: "Everything that wants your attention in one place. Inbox shows new items, Pending lists approvals only you can decide, Resolved is the history and Rules controls how you are notified.", source: "Notices and approvals from the company store (sample data)." }}
        actions={<><IconBtn icon={CheckCheck} label="Mark all as read" disabled={!unread.length} onClick={() => { markNotice("all"); toast("All notifications marked as read", "info"); }} /></>}
        tabs={<Tabs tabs={tabs} value={tab} onChange={setTab} label="Notification sections" />}>
        <TabBody k={tab}>
          {tab === "inbox" && <InboxView bottom={bottom} events={events} notices={notices} unread={unread.length} sev={sev} setSev={setSev} shown={shown} sevCount={sevCount} tiles={tiles} />}
          {tab === "pending" && (
            <div style={grid("1.5fr 1fr", { height: "100%" })}>
              <Card i={0} title={`Waiting for your decision (${pending.length})`} icon={ListChecks} help="Approvals that only you can answer. Open one in Mission Control for the full evidence, or approve and reject quickly here."
                actions={<a className="ax-small" href={href("control", "M-001", { tab: "approvals" })}>Mission Control approvals</a>}>
                <DecisionRows approvals={[...pending].sort((a, b) => ["High", "Medium", "Low"].indexOf(a.priority) - ["High", "Medium", "Low"].indexOf(b.priority))} />
              </Card>
              <Card i={1} title="Needs you, by area" icon={Clock3} help="Pending approvals grouped by area and how long they have been waiting.">
                {Object.entries(pending.reduce<Record<string, number>>((m, a) => ({ ...m, [a.area]: (m[a.area] ?? 0) + 1 }), {})).map(([k, v]) => <div key={k} className="ax-flex"><span className="ax-small" style={{ flex: 1 }}>{k}</span><Pill c="var(--ax-warn)">{v}</Pill></div>)}
                {pending[0] && <span className="ax-xs ax-muted">Oldest waiting since <Time iso={[...pending].sort((a, b) => a.at.localeCompare(b.at))[0].at} withDate /></span>}
                {!pending.length && <Empty icon={CheckCheck} title="Nothing waiting for you" />}
              </Card>
            </div>)}
          {tab === "resolved" && (
            <div style={grid("1.2fr 1fr", { height: "100%" })}>
              <Card i={0} title={`Read notifications (${notices.filter((n) => n.read).length})`} icon={CheckCheck} help="Notifications you have already seen."><NoticeRows list={notices.filter((n) => n.read)} /></Card>
              <Card i={1} title={`Decided approvals (${resolvedA.length})`} icon={ListChecks} help="Approvals that were answered, with the outcome.">
                {resolvedA.map((a) => <div key={a.id} className="ax-flex"><span style={{ flex: 1, minWidth: 0 }}><b className="ax-small">{a.title}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{a.ref} · {a.response?.by ?? "recorded"}</span></span><StatusPill s={a.status === "approved" ? "passed" : a.status === "rejected" ? "failed" : "review"} label={a.status} small /></div>)}
                {!resolvedA.length && <Empty icon={Newspaper} title="No decided approvals yet" />}
              </Card>
            </div>)}
          {tab === "rules" && <Rules quiet={settings.quietHours} notif={settings.notifications} />}
        </TabBody>
      </Panel>
    </div>
  );
}

function Rules({ quiet, notif }: { quiet: boolean; notif: Record<string, boolean> }) {
  const digest = !!notif.digest;
  const toast = useToast();
  // SAMPLE rule matrix, local state: severity x delivery channel.
  const [m, setM] = useState<Record<string, Record<string, boolean>>>({ high: { app: true, email: true, slack: true }, medium: { app: true, email: true, slack: false }, low: { app: true, email: false, slack: false }, info: { app: true, email: false, slack: false } });
  const [d, setD] = useState({ at: "08:00", freq: "daily" }), [qh, setQh] = useState({ from: "22:00", to: "07:00" });
  const sevs = [["high", "Critical"], ["medium", "Warning"], ["low", "Low"], ["info", "Info"]] as const;
  const chans = [["app", "In-app", Bell], ["email", "Email", Mail], ["slack", "Slack", Slack]] as const;
  return (
    <div style={grid("1.4fr 1fr", { height: "100%" })}>
      <Card i={0} title="Severity and delivery channels" icon={BellRing} help="Pick where each severity is delivered. Critical items always reach the In-app inbox." actions={<Pill c="var(--ax-info)">Sample rules</Pill>}>
        <div style={grid("1.1fr repeat(3, 1fr)", { alignItems: "center", rowGap: 10 })}>
          <span />{chans.map(([k, l, I]) => <b key={k} className="ax-small ax-flex" style={{ justifyContent: "center" }}><I size={14} aria-hidden />{l}</b>)}
          {sevs.map(([s, l]) => (<>
            <Pill key={s} c={SEV[s].c} icon={SEV[s].icon}>{l}</Pill>
            {chans.map(([c, cl]) => <span key={s + c} style={{ display: "grid", placeItems: "center" }}><Switch on={m[s][c]} disabled={s === "high" && c === "app"} label={`${l} via ${cl}`} onChange={(v) => setM({ ...m, [s]: { ...m[s], [c]: v } })} /></span>)}
          </>))}
        </div>
        <Btn tone="gold" icon={Check} onClick={() => toast("Rules saved (sample data, nothing sent)", "info")}>Save rules</Btn>
      </Card>
      <div className="ax-col">
        <Card i={1} title="Quiet hours" icon={Clock3} help="Between these times only Critical items notify you.">
          <ToggleRow icon={Clock3} label="Enable quiet hours" on={quiet} onChange={(v) => setSettings({ quietHours: v })} />
          <div style={grid("1fr 1fr")}>{(["from", "to"] as const).map((k) => <label key={k} className="ax-field"><span className="ax-label">{k === "from" ? "From" : "To"}</span><input className="ax-input" type="time" disabled={!quiet} value={qh[k]} onChange={(e) => setQh({ ...qh, [k]: e.target.value })} /></label>)}</div>
        </Card>
        <Card i={2} title="Digest" icon={Mail} help="Bundle non-critical items into one summary instead of many separate messages.">
          <ToggleRow icon={Mail} label="Send a digest" on={digest} onChange={(v) => { setSettings({ notifications: { ...notif, digest: v } }); }} />
          <div style={grid("1fr 1fr")}><label className="ax-field"><span className="ax-label">Frequency</span><select className="ax-select" value={d.freq} onChange={(e) => setD({ ...d, freq: e.target.value })}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
            <label className="ax-field"><span className="ax-label">Send at</span><input className="ax-input" type="time" value={d.at} onChange={(e) => setD({ ...d, at: e.target.value })} /></label></div>
        </Card>
      </div>
    </div>
  );
}

// Inbox view reproducing 40-14: four count tiles, notifications + live activity stream, then alert summary and the three update lists.
const iconFor = (e: { result: string; icon?: string }) => e.result === "failure" ? XCircle : e.result === "success" ? CheckCircle2 : e.result === "running" ? Play : e.result === "warning" ? AlertTriangle : e.icon === "rocket" ? Rocket : e.icon === "book" ? Newspaper : Zap;
type Bottom = { agentVersions: import("../domain/types").AgentVersion[]; sysEvents: import("../domain/types").Event[]; liveMissions: import("../domain/types").Mission[] };
function InboxView({ notices, events, unread, sev, setSev, shown, sevCount, tiles, bottom }: {
  notices: Notice[]; events: import("../domain/types").Event[]; unread: number; sev: "all" | Notice["severity"]; setSev: (v: "all" | Notice["severity"]) => void; shown: Notice[];
  sevCount: { high: number; medium: number; low: number; resolved: number }; tiles: { l: string; v: number; I: typeof Bell; c: string; d: string }[]; bottom: Bottom;
}) {
  const alertParts = [{ label: "Critical", value: sevCount.high, c: "var(--ax-bad)" }, { label: "Warning", value: sevCount.medium, c: "var(--ax-warn)" }, { label: "Info", value: sevCount.low, c: "var(--ax-info)" }];
  const stream = [...events].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 7);
  return (
    <div style={grid("repeat(4, 1fr)", { height: "100%", gridTemplateRows: "auto minmax(0,1.5fr) minmax(0,1fr)" })}>
      {tiles.map((t, i) => (
        <motion.div key={t.l} className="ax-tile" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }} whileHover={{ y: -2, scale: 1.01 }} style={{ display: "flex", alignItems: "center", gap: 12, borderColor: t.c }}>
          <motion.span animate={{ scale: [1, 1.08, 1] }} transition={{ duration: 2.6, repeat: Infinity, delay: i * .3 }} style={{ color: t.c, display: "grid" }}><t.I size={34} aria-hidden /></motion.span>
          <span><b className="ax-num" style={{ fontSize: 24 }}><Count value={t.v} /></b><span className="ax-small" style={{ display: "block" }}>{t.l}</span><span className="ax-xs ax-muted">{t.d}</span></span></motion.div>))}
      <div style={{ gridColumn: "1 / 3", minHeight: 0, display: "flex" }}>
        <Card i={1} title={<>Notifications <span className="ax-muted" style={{ fontWeight: 500 }}>({unread} New)</span></>} icon={Bell} style={{ minHeight: 0, flex: 1 }}
          help="Newest first. Click the check to mark one read. High-severity items are marked Critical and never hidden by quiet hours."
          actions={<Seg label="Filter by severity" value={sev} onChange={setSev} items={[{ id: "all", label: "All" }, { id: "high", label: "Critical" }, { id: "medium", label: "Warning" }, { id: "info", label: "Info" }]} />}>
          <NoticeRows list={shown} onRead={markNotice} />
          <a className="ax-small ax-flex" href={href("notifications", undefined, { tab: "resolved" })} style={{ justifyContent: "flex-end", marginTop: 4 }}>View All Notifications <ArrowRight size={14} aria-hidden /></a>
        </Card>
      </div>
      <div style={{ gridColumn: "3 / 5", minHeight: 0, display: "flex" }}>
        <Card i={2} title="Live Activity Stream" icon={Activity} style={{ minHeight: 0, flex: 1 }} help="The latest actions by agents and the system, as they are recorded." actions={<Pill c="var(--ax-ok)" icon={CircleDot}>Sample feed</Pill>}>
          {!stream.length && <Empty icon={Activity} title="No activity recorded yet" />}
          <div style={{ position: "relative", paddingLeft: 4 }}>
            {stream.length > 1 && <span aria-hidden style={{ position: "absolute", left: 11, top: 12, bottom: 12, width: 1, background: "var(--ax-border)" }} />}
            {stream.map((e, k) => { const I = iconFor(e); return (
              <motion.div key={e.id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }} whileHover={{ x: 2 }} className="ax-flex" style={{ fontSize: 12, padding: "5px 0", position: "relative" }}>
                <span aria-hidden style={{ width: 15, height: 15, borderRadius: 15, border: "2px solid var(--ax-accent)", background: "var(--ax-panel)", flex: "none", zIndex: 1 }} />
                <span className="ax-xs ax-muted ax-mono" style={{ width: 54 }}><Time iso={e.at} /></span>
                <I size={15} className={e.result === "failure" ? "ax-bad" : e.result === "success" ? "ax-ok" : "ax-info"} aria-hidden />
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.actor !== "system" && <b>{e.actor} </b>}{e.action} <span className="ax-muted">{e.target}</span></span>
              </motion.div>); })}
          </div>
        </Card>
      </div>
      <Card i={3} title="Alert Summary" icon={AlertTriangle} help="How the current notifications split by severity.">
        <div className="ax-flex" style={{ gap: 14 }}>
          <Donut label="Alerts by severity" size={104} stroke={13} center={<span style={{ textAlign: "center", lineHeight: 1.1 }}><b className="ax-num" style={{ fontSize: 22 }}>{notices.length}</b><br /><small className="ax-muted">Total</small></span>} parts={alertParts} />
          <Legend items={[...alertParts, { label: "Resolved", value: sevCount.resolved, c: "var(--ax-neutral)" }]} />
        </div>
      </Card>
      <Card i={4} title={`Agent Updates (${bottom.agentVersions.length})`} icon={Bot} help="Recent agent version changes. The arrow opens the Evolution Lab.">
        {!bottom.agentVersions.length && <Empty icon={Bot} title="No agent updates yet" />}
        {[...bottom.agentVersions].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 3).map((v) => (
          <motion.div key={v.agentId + v.version} whileHover={{ x: 2 }} className="ax-flex" style={{ fontSize: 12, padding: "3px 0" }}>
            <Avatar role={roleOf(v.agentId)} size={26} /><b style={{ width: 62 }}>{v.agentId}</b><span className="ax-muted ax-num" style={{ flex: 1 }}>{v.parent ?? "-"} → {v.version}</span><span className="ax-ok ax-num">score {v.score}</span>
            <a href={href("evolution")} aria-label={`Open evolution for ${v.agentId}`} data-tip="Open Evolution Lab" className="ax-ib sm"><ArrowRight size={12} aria-hidden /></a></motion.div>))}
        <a className="ax-small ax-flex" href={href("agents")} style={{ justifyContent: "flex-end", marginTop: "auto" }}>View All Agent Updates <ArrowRight size={14} aria-hidden /></a>
      </Card>
      <Card i={5} title={`System Events (${bottom.sysEvents.length})`} icon={Settings2} help="System-level events such as backups, syncs and merges.">
        {!bottom.sysEvents.length && <Empty icon={Settings2} title="No system events yet" />}
        {bottom.sysEvents.slice(0, 4).map((e) => (
          <motion.div key={e.id} whileHover={{ x: 2 }} className="ax-flex" style={{ fontSize: 12, padding: "3px 0" }}>{(() => { const I = iconFor(e); return <I size={15} className={e.result === "failure" ? "ax-bad" : "ax-ok"} aria-hidden />; })()}<span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.action} <span className="ax-muted">{e.target}</span></span><span className="ax-xs ax-muted ax-mono"><Time iso={e.at} /></span></motion.div>))}
        <a className="ax-small ax-flex" href={href("activity")} style={{ justifyContent: "flex-end", marginTop: "auto" }}>View All System Events <ArrowRight size={14} aria-hidden /></a>
      </Card>
      <Card i={6} title={`Mission Updates (${bottom.liveMissions.length})`} icon={Target} help="The most recently active missions and where they stand.">
        {!bottom.liveMissions.length && <Empty icon={Target} title="No missions yet" />}
        {[...bottom.liveMissions].sort((a, b) => b.lastActivityAt.localeCompare(a.lastActivityAt)).slice(0, 3).map((m) => (
          <motion.a key={m.id} href={href("control", m.id)} whileHover={{ x: 2 }} className="ax-flex" style={{ fontSize: 12, padding: "3px 0", color: "inherit" }}>
            <b style={{ width: 46 }}>{m.id}</b><span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.title}</span><StatusPill s={m.status} small /></motion.a>))}
        <a className="ax-small ax-flex" href={href("missions")} style={{ justifyContent: "flex-end", marginTop: "auto" }}>View All Mission Updates <ArrowRight size={14} aria-hidden /></a>
      </Card>
    </div>
  );
}
