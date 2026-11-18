import { useState } from "react";
import { motion } from "framer-motion";
import {
  Activity, CheckCircle2, ClipboardList, Coins, FlaskConical, GitBranch, Inbox, LayoutDashboard, ListChecks, MessagesSquare, Pause, Play, Plus, RefreshCw, ScrollText, Sparkles,
  Star, Target, Trophy, Users, Workflow, Kanban, X,
} from "lucide-react";
import { Empty, Gauge, IconBtn, Kpi, Panel, StatusPill, TabBody, Tabs, useToast, Help, SampleMark } from "../ui/kit";
import { Avatar } from "../ui/Avatar";
import { liveMode, missionAction, taskAction, useStore } from "../data/store";
import { FINANCE } from "../data/sample";
import { go, useQueryParam, useRoute } from "../app/router";
import { TaskFlowTab } from "./control/TaskFlow";
import { ActivityTab, AgentsTab, ApprovalsTab, ConversationsTab, OverviewTab, ReportsTab } from "./control/Tabs";

// Mission Control (readme §3; Detailed UI v3 §4.3–4.7; 30-3). Every tab is a separate, populated view.
export default function MissionControl() {
  const route = useRoute();
  const missions = useStore((s) => s.missions);
  const missionId = route.param && missions.some((m) => m.id === route.param) ? route.param : missions[0]?.id ?? "";
  const m = missions.find((x) => x.id === missionId);
  const tasks = useStore((s) => s.tasks.filter((t) => t.missionId === missionId));
  const inst = useStore((s) => s.instances.filter((i) => i.missionId === missionId));
  const pending = useStore((s) => s.approvals.filter((a) => a.missionId === missionId && a.status === "pending").length);
  const threads = useStore((s) => s.threads.filter((t) => t.missionId === missionId));
  const unread = threads.reduce((n, t) => n + t.unread, 0);
  const [tab, setTab] = useQueryParam("tab", "flow");
  const [fav, setFav] = useState(false);
  const toast = useToast();
  const phases: [string, number][] = (() => {
    const groups = [["Core Integration", ["T-002", "T-007"]], ["Platform Upgrade", ["T-007", "T-008", "T-009"]], ["QA & Test", ["T-005", "T-006"]], ["Deployment", ["T-010", "T-015"]]] as const;
    if (missionId !== "M-001") return tasks.slice(0, 4).map((t) => [t.title, t.progress]);
    return groups.map(([l, ids]) => [l, Math.round(ids.reduce((s, id) => s + (tasks.find((t) => t.id === id)?.progress ?? 0), 0) / ids.length)]);
  })();
  const failed = tasks.filter((t) => t.status === "failed");
  const TABS = [
    { id: "overview", label: "Overview", icon: LayoutDashboard }, { id: "flow", label: "Task Flow", icon: Kanban }, { id: "agents", label: "Agents", icon: Users },
    { id: "conversations", label: "Conversations", icon: MessagesSquare, alert: unread }, { id: "approvals", label: "Approvals", icon: Inbox, alert: pending },
    { id: "activity", label: "Activity", icon: Activity }, { id: "reports", label: "Reports", icon: ScrollText },
  ];
  if (!m) return (
    <div className="ax-panel" style={{ height: "100%", display: "grid", placeItems: "center" }}>
      <Empty icon={Target} title="No mission to control yet">Mission Control opens a mission's agents, task flow, conversations and decisions. Start one from Missions.
        <span style={{ display: "block", marginTop: 10 }}><button type="button" className="ax-btn gold" onClick={() => go("missions")}>Go to Missions</button></span></Empty>
    </div>
  );
  return (
    <div className="ax-page" style={{ gridTemplateRows: "auto auto minmax(0, 1fr)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "77fr 18fr", gap: "var(--ax-gap)" }}>
        <motion.section className="ax-panel" style={{ padding: "8px 12px", gap: 8 }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} aria-label="Mission header">
          <div className="ax-flex" style={{ gap: 12 }}>
            <motion.span animate={{ rotate: [0, 8, 0] }} transition={{ duration: 4, repeat: Infinity }}><Target size={40} className="ax-gold" aria-hidden /></motion.span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="ax-flex" style={{ gap: 8 }}>
                <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Mission Control — {m.title}</h1>
                <Help title="Mission Control" body="Everything about one mission: agents and their hierarchy, the task flow, conversations, decisions waiting for you, the audit log and reports. Use the mission switcher to change mission." />
              </div>
              <div className="ax-small ax-muted" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.summary}</div>
            </div>
            <select className="ax-select" style={{ width: 200 }} value={missionId} onChange={(e) => go("control", e.target.value, { tab })} aria-label="Switch mission">
              {missions.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.title}</option>)}</select>
            <StatusPill s={m.status} solid={m.status === "running"} /><b style={{ fontSize: 20 }} className="ax-num">{m.progress}%</b>
            <IconBtn icon={Star} label={fav ? "Remove from favourites" : "Add to favourites"} tone={fav ? "gold" : undefined} onClick={() => setFav(!fav)} />
            <div className="ax-tile ax-flex" style={{ gap: 8, padding: "4px 10px" }}><Avatar role="gm" size={34} status="busy" /><div className="ax-small"><div className="ax-xs ax-muted">Mission Owner</div><b>General Manager (GM)</b></div></div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1.45fr", gap: "var(--ax-gap)", marginTop: 8 }}>
            <Kpi i={0} icon={Target} c="#a77bff" value={tasks.length} label="Total Tasks" delta="↑ +2" onClick={() => setTab("flow")} />
            <Kpi i={1} icon={Users} c="#3b8cff" value={new Set(inst.map((i) => i.agentId)).size} label="Assigned Agents" delta="↑ +0" onClick={() => setTab("agents")} />
            <Kpi i={2} icon={ClipboardList} c="#f2b53a" value={pending} label="Pending Approvals" onClick={() => setTab("approvals")} />
            <Kpi i={3} icon={Trophy} c="#2fd27a" value={96.4} decimals={1} suffix="%" sample label="Mission Success" delta="↑ +2.1 pp" />
            <Kpi i={4} icon={Coins} c="#c084fc" value={FINANCE.month} prefix="$" sample label="This Month Spend" onClick={() => go("finance")} extra={<small style={{ color: "var(--ax-muted)" }}>76% of Budget</small>} />
            <div className="ax-tile ax-flex" style={{ gap: 10 }}>
              <Gauge value={98} size={74} stroke={8} /><SampleMark />
              <div className="ax-col" style={{ gap: 2, flex: 1, minWidth: 0 }}>{phases.map(([l, v]) => <div key={l} className="ax-flex ax-xs"><CheckCircle2 size={12} className={v >= 100 ? "ax-ok" : "ax-faint"} aria-hidden /><span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{l}</span><b className="ax-num">{v}%</b></div>)}</div>
            </div>
          </div>
        </motion.section>
        <Panel i={1} title="Quick Actions" icon={Workflow} help="Mission-level actions. Pausing stops new work and lets running jobs reach a safe checkpoint.">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6, justifyItems: "center" }}>
            <IconBtn icon={Plus} label="Add a new mission" size="lg" onClick={() => go("missions")} />
            <IconBtn icon={m.status === "paused" ? Play : Pause} label={m.status === "paused" ? "Resume mission" : "Pause mission"} size="lg" tone="gold" onClick={() => { const e = missionAction(m.id, m.status === "paused" ? "resume" : "pause"); if (e) toast(e, "warn"); else if (!liveMode()) toast(m.status === "paused" ? "Mission resumed" : "Mission paused: running jobs stop at their next checkpoint", "info"); }} />
            <IconBtn icon={RefreshCw} label={failed.length ? `Retry ${failed.length} failed task(s)` : "Retry failed tasks (none)"} size="lg" disabled={!failed.length} onClick={() => { const errs = failed.map((t) => taskAction(t.id, "retry")).filter(Boolean); if (errs.length) toast(errs[0]!, "warn"); else if (!liveMode()) toast(`Retrying ${failed.length}`); }} />
            <IconBtn icon={GitBranch} label="Versions & branches of this mission" size="lg" onClick={() => go("versions", null, { m: m.id })} />
            <IconBtn icon={FlaskConical} label="Evolution experiments from this mission" size="lg" onClick={() => go("evolution")} />
            <IconBtn icon={Sparkles} label="Ask the GM" size="lg" onClick={() => go("control", m.id, { tab: "agents", agent: "GM" })} />
          </div>
          <div className="ax-flex" style={{ marginTop: 6, justifyContent: "center" }}><IconBtn icon={X} label="Cancel mission (asks for confirmation)" size="sm" tone="bad" onClick={() => { if (window.confirm(`Cancel ${m.title}? Running tasks are stopped and the cancellation is audited.`)) { const e = missionAction(m.id, "cancel"); if (e) toast(e, "warn"); else if (!liveMode()) toast("Mission cancelled", "warn"); } }} />
            <IconBtn icon={ListChecks} label="Open in Missions list" size="sm" onClick={() => go("missions", null, { m: m.id })} /></div>
        </Panel>
      </div>
      <Tabs label="Mission Control tabs" value={tab} onChange={setTab} tabs={TABS} />
      <div style={{ minHeight: 0 }}>
        <TabBody k={`${missionId}-${tab}`}>
          {tab === "overview" && <OverviewTab missionId={missionId} />}
          {tab === "flow" && <TaskFlowTab missionId={missionId} />}
          {tab === "agents" && <AgentsTab missionId={missionId} />}
          {tab === "conversations" && <ConversationsTab missionId={missionId} />}
          {tab === "approvals" && <ApprovalsTab missionId={missionId} />}
          {tab === "activity" && <ActivityTab missionId={missionId} />}
          {tab === "reports" && <ReportsTab missionId={missionId} />}
        </TabBody>
      </div>
    </div>
  );
}
