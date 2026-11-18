import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bell, Bot, BookOpen, Database, CheckCircle2, ChevronsLeft, ChevronsRight, Coins, Dna, GitBranch, HelpCircle, Home, Keyboard, LayoutDashboard, LogOut, Network,
  Palette, Search, Server, Settings as SettingsIcon, ShieldCheck, Target, TriangleAlert, Users, Workflow, BarChart3, ExternalLink, FlaskConical,
  MessageSquare, type LucideIcon,
} from "lucide-react";
import { HeroCity, LogoMark, Mascot } from "../ui/Avatar";
import { IconBtn, Modal, Seg, Time, useToast } from "../ui/kit";
import { useTheme } from "../theme/ThemeContext";
import { setDataMode, useStore } from "../data/store";
import { go, href, useRoute } from "./router";
import { GmChat } from "./GmChat";

export interface NavItem { page: string; label: string; icon: LucideIcon; count?: (s: ReturnType<typeof useCounts>) => number }
export const NAV: NavItem[] = [
  { page: "overview", label: "Overview", icon: Home },
  { page: "missions", label: "Missions", icon: Target },
  { page: "control", label: "Mission Control", icon: Workflow, count: (c) => c.pending },
  { page: "agents", label: "Agents", icon: Bot },
  { page: "organization", label: "Organization", icon: Network },
  { page: "versions", label: "Versions & GitHub", icon: GitBranch },
  { page: "evolution", label: "Evolution Lab", icon: Dna },
  { page: "knowledge", label: "Knowledge", icon: BookOpen },
  { page: "finance", label: "Finance", icon: Coins },
  { page: "governance", label: "Governance", icon: ShieldCheck },
  { page: "appearance", label: "Appearance", icon: Palette },
  { page: "settings", label: "Settings", icon: SettingsIcon },
];
export const MORE_NAV: NavItem[] = [
  { page: "notifications", label: "Notifications", icon: Bell, count: (c) => c.unread },
  { page: "analytics", label: "Analytics", icon: BarChart3 },
  { page: "system", label: "System (stack)", icon: Server },
];

function useCounts() {
  const pending = useStore((s) => s.approvals.filter((a) => a.status === "pending").length);
  const unread = useStore((s) => s.notices.filter((n) => !n.read).length);
  return { pending, unread };
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), 15000); return () => window.clearInterval(t); }, []);
  const s = now.toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  return <time className="ax-clock" dateTime={now.toISOString()} title={now.toString()}>{s} (UTC)</time>;
}

// Signed in: the real /api/health (the server's own view). Otherwise the sample model registry, labelled as such.
function Health() {
  const models = useStore((s) => s.models), me = useStore((s) => s.me);
  const [live, setLive] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    if (!me) { setLive(null); return; }
    const load = () => fetch("/api/health", { credentials: "same-origin" }).then((r) => r.json()).then((d) => {
      const st = String(d?.status ?? ""); setLive({ ok: st === "live" || st === "ok", text: st.startsWith("error") ? "chain data unreachable" : st || "unknown" });
    }).catch(() => setLive({ ok: false, text: "health check failed" }));
    load(); const t = window.setInterval(load, 60000); return () => window.clearInterval(t);
  }, [me]);
  const bad = live ? (live.ok ? 0 : 1) : models.filter((m) => m.enabled && m.health !== "ok").length;
  const tip = live ? (live.ok ? "AXoR reports healthy (live /api/health)" : `AXoR reports a problem: ${live.text} (live /api/health)`) : bad ? `${bad} provider(s) degraded (sample data)` : "Sample data: health is illustrative until you sign in";
  return (
    <motion.a href={href("overview", null, { tab: "health" })} className={`ax-health ${bad ? "warn" : ""}`} data-tip={tip}
      initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} whileHover={{ scale: 1.04 }} style={{ textDecoration: "none" }}>
      {bad ? <TriangleAlert size={14} aria-hidden /> : <CheckCircle2 size={14} aria-hidden />}<span>{bad ? "System Degraded" : "System Healthy"}{live ? "" : " ·"}</span>{!live && <span className="ax-xs" style={{ opacity: .8 }}>sample</span>}
    </motion.a>
  );
}

// Live / Sample switch when the hubs answered; otherwise a plain "Sample data" badge.
function SampleBadge() {
  const sources = useStore((s) => s.sources), mode = useStore((s) => s.dataMode), avail = useStore((s) => s.liveAvailable);
  const sample = ["candidates", "releases", "branches", "threads", "messages", "knowledge", "news", "models", "notices", "instances"].filter((k) => sources[k as keyof typeof sources] !== "live");
  const status = useStore((s) => s.liveStatus);
  if (!avail) return (
    <span className="ax-sample" tabIndex={0} data-tip={status === "unavailable" ? "Live missions and agents are administrator-only in this AXoR: your screens show illustrative sample data (your settings, theme and news sources are live)"
      : "No live AXoR data here: every screen shows illustrative sample data from the design references"}><FlaskConical size={12} aria-hidden />Sample data</span>
  );
  return (
    <span className="ax-flex" style={{ gap: 6 }}>
      <Seg label="Data source" value={mode} onChange={(v) => setDataMode(v)} items={[{ id: "live", label: "Live AXoR data: actions here change AXoR", icon: Database }, { id: "sample", label: "Design sample data", icon: FlaskConical }]} />
      {mode === "live" && <span className="ax-sample" tabIndex={0} data-tip={`Live: missions, tasks, agents, departments, approvals, audit. Still sample: ${sample.join(", ")}`}><FlaskConical size={12} aria-hidden />Partly sample</span>}
    </span>
  );
}

function NotificationsPop({ onClose }: { onClose: () => void }) {
  const notices = useStore((s) => s.notices);
  return (
    <motion.div className="ax-pop" style={{ right: 70, top: 58, left: "auto", width: 340 }} role="dialog" aria-label="Notifications"
      initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
      <h4>Notifications</h4>
      <div className="ax-rows">
        {notices.slice(0, 6).map((n) => (
          <a key={n.id} href={n.kind === "decision" ? href("control", n.missionId, { tab: "approvals" }) : href("notifications")} onClick={onClose} className="ax-row click" style={{ textDecoration: "none", color: "inherit" }}>
            <span style={{ width: 8, height: 8, borderRadius: 9, background: n.read ? "transparent" : "var(--ax-bad)", flex: "none" }} aria-label={n.read ? "read" : "unread"} />
            <span className="grow"><span className="t">{n.title}</span><span className="s">{n.detail}</span></span>
            <span className="ax-xs ax-faint"><Time iso={n.at} /></span>
          </a>
        ))}
      </div>
      <a href={href("notifications")} onClick={onClose} className="ax-small ax-gold">Open all notifications →</a>
    </motion.div>
  );
}

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState(""); const [ix, setIx] = useState(0);
  const missions = useStore((s) => s.missions), agents = useStore((s) => s.agents);
  const results = useMemo(() => {
    const t = q.toLowerCase().trim();
    const pages = [...NAV, ...MORE_NAV].map((n) => ({ key: "p" + n.page, label: n.label, kind: "Page", icon: n.icon, go: () => go(n.page) }));
    const ms = missions.map((m) => ({ key: m.id, label: `${m.title}`, kind: `Mission ${m.id}`, icon: Target, go: () => go("control", m.id) }));
    const as = agents.map((a) => ({ key: a.id, label: `${a.id} · ${a.name}`, kind: "Agent", icon: Bot, go: () => go("agents", a.id) }));
    const all = [...pages, ...ms, ...as];
    return (t ? all.filter((r) => (r.label + " " + r.kind).toLowerCase().includes(t)) : pages).slice(0, 9);
  }, [q, missions, agents]);
  useEffect(() => { setIx(0); }, [q]);
  useEffect(() => { if (open) setQ(""); }, [open]);
  const run = (k: number) => { results[k]?.go(); onClose(); };
  return (
    <Modal open={open} onClose={onClose} title="Search AXoR" icon={Search} width={560}>
      <div className="ax-search"><Search size={15} aria-hidden />
        <input className="ax-input" placeholder="Search pages, missions, agents…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search"
          onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setIx((i) => Math.min(results.length - 1, i + 1)); } if (e.key === "ArrowUp") { e.preventDefault(); setIx((i) => Math.max(0, i - 1)); } if (e.key === "Enter") run(ix); }} />
      </div>
      <div className="ax-rows" style={{ marginTop: 10 }} role="listbox" aria-label="Results">
        {results.map((r, k) => { const I = r.icon; return (
          <div key={r.key} role="option" aria-selected={k === ix} className={`ax-row click ${k === ix ? "sel" : ""}`} onMouseEnter={() => setIx(k)} onClick={() => run(k)}>
            <I size={16} className="ax-gold" aria-hidden /><span className="grow t">{r.label}</span><span className="ax-xs ax-muted">{r.kind}</span>
          </div>); })}
        {!results.length && <p className="ax-muted">Nothing matches “{q}”.</p>}
      </div>
    </Modal>
  );
}

function HelpModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const rows: [string, string][] = [["Ctrl / ⌘ + K or /", "Search pages, missions and agents"], ["← →", "Move between tabs when a tab is focused"], ["Esc", "Close dialogs and help"], ["?", "Every panel has a ? button with the definition, an example and the source of its numbers"], ["g then o / m / c", "Go to Overview / Missions / Mission Control"]];
  return (
    <Modal open={open} onClose={onClose} title="Help & keyboard" icon={Keyboard} width={600}>
      <p className="ax-muted" style={{ marginTop: 0 }}>AXoR is an autonomous AI company. You give it missions; the General Manager plans, staffs agents, researches, builds, verifies and asks you only when a decision is yours.
        Buttons are icons: hover or focus one to see what it does. Status is always shown as icon + text + colour.</p>
      <dl className="ax-kv" style={{ gridTemplateColumns: "auto 1fr" }}>{rows.map(([k, v]) => <Fragment key={k}><dt><kbd className="ax-mono">{k}</kbd></dt><dd style={{ textAlign: "left", fontWeight: 400 }}>{v}</dd></Fragment>)}</dl>
    </Modal>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const route = useRoute();
  const counts = useCounts();
  const { appearance, set } = useTheme();
  const me = useStore((s) => s.me);
  const toast = useToast();
  const [palette, setPalette] = useState(false), [help, setHelp] = useState(false), [bell, setBell] = useState(false), [menu, setMenu] = useState(false);
  const [gm, setGm] = useState(false), [gmNeeds, setGmNeeds] = useState(0);  // General Manager chat (GmChat.tsx, D-039)
  const gPressed = useRef(0);
  const liveMode = useStore((s) => s.dataMode === "live");
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const typing = /input|textarea|select/i.test((e.target as HTMLElement)?.tagName) || (e.target as HTMLElement)?.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(true); return; }
      if (typing) return;
      if (e.key === "/") { e.preventDefault(); setPalette(true); }
      if (e.key === "g") { gPressed.current = Date.now(); return; }
      if (Date.now() - gPressed.current < 900) { const to = { o: "overview", m: "missions", c: "control", a: "agents", v: "versions" }[e.key]; if (to) go(to); gPressed.current = 0; }
    };
    document.addEventListener("keydown", key); return () => document.removeEventListener("keydown", key);
  }, []);
  const active = route.page === "preview" ? "versions" : route.page;
  const navLink = (n: NavItem, i: number) => {
    const I = n.icon; const c = n.count?.(counts) ?? 0; const on = active === n.page;
    return (
      <motion.a key={n.page} href={href(n.page)} className={on ? "active" : ""} aria-current={on ? "page" : undefined} data-tip={appearance.sidebar === "collapsed" ? n.label : undefined}
        initial={{ opacity: 0, x: -14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .04 * i }} whileHover={{ x: 3 }} whileTap={{ scale: .97 }}>
        <motion.span animate={on ? { scale: [1, 1.18, 1] } : { scale: 1 }} transition={{ duration: .5 }} style={{ display: "grid" }}><I size={20} aria-hidden /></motion.span>
        <span>{n.label}</span>{c > 0 && <span className="ax-nav-count" aria-label={`${c} pending`}>{c}</span>}
      </motion.a>
    );
  };
  return (
    <div className="ax-app">
      <div className="ax-backdrop" aria-hidden />
      <header className="ax-head">
        <a className="ax-brand" href={href("overview")} aria-label="AXoR home"><LogoMark /><span className="ax-brand-word">AXOR</span></a>
        <span className="ax-brand-sep" aria-hidden />
        <div className="ax-brand-title"><b>Autonomous AI Company OS</b><small>A Self-Sustaining · Self-Evolving · Goal-Driven AI Company</small></div>
        <HeroCity />
        <div className="ax-head-right">
          <SampleBadge />
          <Health />
          <Clock />
          <IconBtn icon={Search} label="Search (Ctrl+K)" className="ax-round keep" onClick={() => setPalette(true)} />
          <div style={{ position: "relative" }}>
            <IconBtn icon={Bell} label={`Notifications (${counts.unread} unread)`} className="ax-round keep" badge={counts.unread} onClick={() => setBell((b) => !b)} aria-expanded={bell} />
          </div>
          <IconBtn icon={MessageSquare} label={gmNeeds ? `Chat with the General Manager (${gmNeeds} mission(s) need you)` : "Chat with the General Manager"} className="ax-round keep"
            badge={gmNeeds} onClick={() => setGm((g) => !g)} aria-expanded={gm} aria-controls="ax-gm" />
          <IconBtn icon={HelpCircle} label="Help & keyboard shortcuts" className="ax-round" onClick={() => setHelp(true)} />
          <IconBtn icon={SettingsIcon} label="Settings" className="ax-round" onClick={() => go("settings")} />
          <motion.button type="button" className="ax-me" aria-label={`Account: ${me?.name ?? "not signed in"}`} data-tip={me ? `${me.name} (${me.role})` : "Account"} onClick={() => setMenu((m) => !m)}
            whileHover={{ scale: 1.06, rotate: 4 }} whileTap={{ scale: .94 }}><LogoMark size={22} /></motion.button>
        </div>
      </header>
      <AnimatePresence>{bell && <NotificationsPop onClose={() => setBell(false)} />}</AnimatePresence>
      <AnimatePresence>{gm && <GmChat onClose={() => setGm(false)} onNeeds={setGmNeeds} />}</AnimatePresence>
      <AnimatePresence>{menu && (
        <motion.div className="ax-pop" style={{ right: 14, top: 58, left: "auto", width: 260 }} role="menu" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          <h4>{me?.name ?? "Guest"} <span className="ax-xs ax-muted">{me?.role ?? "not signed in"}</span></h4>
          <div className="ax-rows">
            <a className="ax-row click" href="/" style={{ color: "inherit", textDecoration: "none" }}><LayoutDashboard size={15} aria-hidden /> Classic AXoR UI <ExternalLink size={12} aria-hidden /></a>
            <a className="ax-row click" href={href("appearance")} onClick={() => setMenu(false)} style={{ color: "inherit", textDecoration: "none" }}><Palette size={15} aria-hidden /> Appearance</a>
            <a className="ax-row click" href={href("agents")} onClick={() => setMenu(false)} style={{ color: "inherit", textDecoration: "none" }}><Users size={15} aria-hidden /> My agents</a>
            <button type="button" className="ax-row click" style={{ border: 0, background: "transparent", textAlign: "left" }} onClick={() => { setMenu(false); toast(me ? "Use the classic UI to sign out" : "Sign in from the classic UI", "info"); }}><LogOut size={15} aria-hidden /> {me ? "Sign out" : "Sign in"}</button>
          </div>
        </motion.div>)}</AnimatePresence>
      <nav className="ax-side" aria-label="Main">
        <div className="ax-nav">
          {NAV.map(navLink)}
          <div className="ax-nav-sep" aria-hidden />
          {MORE_NAV.map((n, i) => navLink(n, NAV.length + i))}
        </div>
        <div className="ax-mascot"><Mascot /></div>
        <IconBtn icon={appearance.sidebar === "collapsed" ? ChevronsRight : ChevronsLeft} label={appearance.sidebar === "collapsed" ? "Expand sidebar" : "Collapse sidebar"} size="sm" className="ax-collapse"
          onClick={() => set({ sidebar: appearance.sidebar === "collapsed" ? "expanded" : "collapsed" })} />
      </nav>
      <main className="ax-main" id="main" style={liveMode ? { paddingTop: 30, position: "relative" } : undefined}>
        {liveMode && <div role="note" className="ax-small" style={{ position: "absolute", top: 6, left: 4, right: 12, height: 20, display: "flex", alignItems: "center", gap: 6, color: "var(--ax-muted)", overflow: "hidden", whiteSpace: "nowrap" }}>
          <Database size={13} className="ax-ok" aria-hidden /><b style={{ color: "var(--ax-ok)" }}>Live AXoR</b> (actions are real): missions, tasks, agents, approvals, audit, messages you send.
          <FlaskConical size={13} className="ax-warn" aria-hidden /><b className="ax-warn">Sample</b>: KPIs, health, finance, versions, evolution, knowledge, models, past conversations.
        </div>}
        {/* Enter animation only: an exit-wait would render the new page inside the old wrapper and then mount it a
            second time, losing anything clicked during the transition. */}
        <motion.div key={route.page + (route.param ?? "")} style={{ height: "100%" }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .22 }}>
          {children}
        </motion.div>
      </main>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <HelpModal open={help} onClose={() => setHelp(false)} />
    </div>
  );
}
