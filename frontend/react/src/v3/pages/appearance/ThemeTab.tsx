import { useState, type CSSProperties, type ReactNode } from "react";
import { motion } from "framer-motion";
import {
  Bell, Check, ChevronLeft, ChevronRight, Hexagon, Layers, ListChecks, Mail, Moon, Palette, Rows3, Slack, Sparkles, Sun, Gem, Box, SquareStack, Crown, Github, Lock, KeyRound, ShieldCheck, Globe, Building2, Cpu,
  Rows2, Rows4, Rocket, Target, Coins, Users, Activity, Home, Bot, GitBranch, Plus, RefreshCw, Link2, BookOpen, Flower2, Landmark, Cherry,
} from "lucide-react";
import { Btn, IconBtn, Progress, Switch, useToast } from "../../ui/kit";
import { Avatar, ROLES, type Role } from "../../ui/Avatar";
import { useTheme } from "../../theme/ThemeContext";
import { AVATAR_COLORS, STYLES, type AvatarColor, type AvatarFace, type IconSet, type StyleId, styleDef } from "../../theme/themes";
import { getState, rolesLosingCoverage, setSettings, updateModel, useStore } from "../../data/store";
import { Card, ToggleRow, grid } from "../settings/parts";

/* ---------- small helpers ---------- */
function Tile({ on, onClick, label, hint, children, w }: { on: boolean; onClick: () => void; label: string; hint?: string; children?: ReactNode; w?: number }) {
  return (
    <motion.button type="button" aria-pressed={on} aria-label={label} onClick={onClick} whileHover={{ y: -2, scale: 1.03 }} whileTap={{ scale: .95 }}
      style={{ position: "relative", flex: w ? `0 0 ${w}px` : 1, minWidth: 0, padding: "6px 4px", borderRadius: "var(--ax-radius-sm)", cursor: "pointer", fontFamily: "inherit", color: "var(--ax-text)", display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
        border: `1.5px solid ${on ? "var(--ax-accent)" : "var(--ax-border)"}`, background: on ? "color-mix(in srgb, var(--ax-accent) 12%, var(--ax-panel2))" : "var(--ax-panel2)", boxShadow: on ? "0 0 calc(12px * var(--ax-glow-k)) var(--ax-glow)" : undefined }}>
      {on && <span style={{ position: "absolute", top: -5, right: -5, width: 15, height: 15, borderRadius: 99, background: "var(--ax-accent)", color: "var(--ax-on-accent)", display: "grid", placeItems: "center" }}><Check size={10} aria-hidden /></span>}
      {children}<b style={{ fontSize: 11.5 }}>{label}</b>{hint && <span className="ax-xs ax-muted" style={{ textAlign: "center", lineHeight: 1.15 }}>{hint}</span>}
    </motion.button>
  );
}
const Row = ({ children }: { children: ReactNode }) => <div style={{ display: "flex", gap: 6, minWidth: 0 }}>{children}</div>;


const STYLE_ICON: Record<StyleId, typeof Sun> = { luxury: Crown, luminous: Box, classic: Sun, flat: Layers, pretty: Flower2, fancy: Gem, sakura: Cherry, renaissance: Landmark };
const STYLE_HINT: Partial<Record<StyleId, string>> = { flat: "Clean & efficient", luminous: "Glow & depth", fancy: "Ornate & premium", pretty: "Soft & friendly", luxury: "Gold & midnight", classic: "Crisp & neutral", sakura: "Blossom & indigo", renaissance: "Parchment & gilt" };

/* ---------- the Theme tab (30-10) ---------- */
export function ThemeTab() {
  const { appearance: a, set } = useTheme();
  const agents = useStore((s) => s.agents);
  const count = (r: Role) => agents.filter((x) => x.role === r).length;
  const [more, setMore] = useState(false);
  const mainStyles: StyleId[] = ["flat", "luminous", "fancy"];
  const rest = STYLES.filter((s) => !mainStyles.includes(s.id));
  const accents = [...styleDef(a.style).accents, "#ef4444", "#f2b53a"].slice(0, 6);
  const sets: { id: IconSet; label: string; hint: string; style: CSSProperties; fill?: boolean }[] = [
    { id: "core", label: "AXoR Core", hint: "(Premium)", style: {} }, { id: "outline", label: "Outline", hint: "(Clean)", style: { strokeWidth: 1.2 } },
    { id: "duotone", label: "Duotone", hint: "(Balanced)", style: { fill: "currentColor", fillOpacity: .22 } }, { id: "solid", label: "Solid", hint: "(Bold)", style: { strokeWidth: 3 } },
    { id: "neotech", label: "Neo-Tech", hint: "(Futuristic)", style: { filter: "drop-shadow(0 0 3px currentColor)" } }];
  const faces: { id: AvatarFace; label: string }[] = [{ id: "classic", label: "Classic" }, { id: "holographic", label: "Holographic" }, { id: "expressive", label: "Expressive" }, { id: "minimal", label: "Minimal" }, { id: "analytical", label: "Analytical" }, { id: "elite", label: "Elite" }];
  const cols: { id: AvatarColor; label: string; c: string }[] = [{ id: "cyan", label: "Cyan", c: AVATAR_COLORS.cyan }, { id: "purple", label: "Purple", c: AVATAR_COLORS.purple }, { id: "green", label: "Green", c: AVATAR_COLORS.green }, { id: "gold", label: "Gold", c: AVATAR_COLORS.gold }, { id: "pink", label: "Pink", c: AVATAR_COLORS.pink }];
  const roles: Role[] = ["research", "developer", "ops", "qa", "knowledge", "deploy"];
  return (
    <div style={grid("repeat(4, 1fr) 1.25fr", { height: "100%", gridTemplateRows: "auto auto auto minmax(0,1fr)", gap: 8 })}>
      <Card i={0} title="Theme Mode" icon={Moon} help="Bright (light) or Dark. System mode is in the Colors tab." style={{ gridColumn: "1", overflow: "visible" }}>
        <Row>{([["light", "Bright", "Light mode", Sun], ["dark", "Dark", "Dark mode", Moon]] as const).map(([id, l, h, I]) => <Tile key={id} on={a.mode === id} onClick={() => set({ mode: id })} label={l} hint={h}><I size={20} aria-hidden /></Tile>)}</Row>
      </Card>
      <Card i={1} title="Visual Style" icon={Sparkles} help="The surface treatment of the whole app: flat, luminous, fancy, pretty... Each works in bright and dark." style={{ gridColumn: "2 / 4", overflow: "visible" }}
        actions={<Btn onClick={() => setMore(!more)} aria-expanded={more}>{more ? "Fewer" : "More"}</Btn>}>
        <Row>{[...mainStyles.map((id) => styleDef(id)), ...(more ? rest : [])].slice(0, more ? 8 : 3).map((s) => { const I = STYLE_ICON[s.id]; return <Tile key={s.id} on={a.style === s.id} onClick={() => set({ style: s.id, accent: null })} label={s.id === "flat" ? "Flat" : s.id === "luminous" ? "Luminous" : s.id === "fancy" ? "Fancy" : s.label.split(" ")[s.label.split(" ").length - 1]} hint={more ? undefined : STYLE_HINT[s.id]}><I size={20} aria-hidden /></Tile>; })}</Row>
        {!more && <span className="ax-xs ax-muted">{rest.length} more: {rest.map((s) => s.label).join(", ")}</span>}
      </Card>
      <Card i={2} title="Accent Color" icon={Palette} help="Marks selected tabs, primary buttons and focus. A custom colour is checked for contrast in the Colors tab." style={{ gridColumn: "4", overflow: "visible" }}>
        <div className="ax-flex" style={{ gap: 7 }}>
          {accents.map((c) => <motion.button key={c} type="button" aria-label={`Accent ${c}`} aria-pressed={(a.accent ?? styleDef(a.style).accents[0]) === c} data-tip={c} onClick={() => set({ accent: c })} whileHover={{ scale: 1.18 }} whileTap={{ scale: .88 }}
            style={{ width: 24, height: 24, borderRadius: 99, background: c, cursor: "pointer", display: "grid", placeItems: "center", border: `2px solid ${(a.accent ?? styleDef(a.style).accents[0]) === c ? "var(--ax-text)" : "transparent"}` }}>{(a.accent ?? styleDef(a.style).accents[0]) === c && <Check size={12} color="#fff" aria-hidden />}</motion.button>)}
          <label data-tip="Custom colour" style={{ position: "relative", width: 24, height: 24, borderRadius: 99, background: "conic-gradient(red, yellow, lime, cyan, blue, magenta, red)", cursor: "pointer", flex: "none" }}>
            <input type="color" aria-label="Custom accent colour" value={a.accent ?? "#f2b53a"} onChange={(e) => set({ accent: e.target.value })} style={{ opacity: 0, position: "absolute", inset: 0, width: "100%", height: "100%", cursor: "pointer" }} /></label>
        </div>
        <div className="ax-flex" style={{ marginTop: 2 }}><Sparkles size={14} className="ax-gold" aria-hidden /><b className="ax-small">Glow Level</b><span className="ax-spacer" /><b className="ax-num ax-small">{a.glow}%</b></div>
        <input type="range" className="ax-range" min={0} max={100} value={a.glow} aria-label="Glow level percent" onChange={(e) => set({ glow: +e.target.value })} />
      </Card>

      <Card i={3} title="Icon Set" icon={Hexagon} help="Changes how every icon in the app is drawn: outline thin, solid bold, duotone filled, neo-tech glowing." style={{ gridColumn: "1", gridRow: "2 / 4", overflow: "visible" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 5 }}>
          {sets.map((s) => <Tile key={s.id} on={a.iconSet === s.id} onClick={() => set({ iconSet: s.id })} label={s.label} hint={s.hint}>
            {s.id === "core" ? <Rocket size={22} style={{ color: "var(--ax-accent)" }} aria-hidden /> : <Hexagon size={22} style={{ color: "var(--ax-accent2)", ...s.style }} aria-hidden />}</Tile>)}
        </div>
      </Card>
      <Card i={4} title="Agent Avatar — Role & Face Style" icon={Bot} help="The default pictures of agents by role. Numbers show how many agents have that role. Face and colour below change all of them." style={{ gridColumn: "2 / 4", overflow: "visible" }}>
        <Row>{roles.map((r) => <Tile key={r} on={false} onClick={() => {}} label={ROLES[r].label.split(" ")[0]} hint={`(${count(r)})`}><Avatar role={r} size={34} name={ROLES[r].label} /></Tile>)}</Row>
      </Card>
      <Card i={5} title="Compactness" icon={Rows3} help="How tightly the app is packed: Comfortable, Standard, or Compact (ultra)." style={{ gridColumn: "4", overflow: "visible" }}>
        <Row>{([["comfortable", "Comfortable", Rows2], ["compact", "Standard", Rows3], ["ultra", "Compact", Rows4]] as const).map(([id, l, I]) => <Tile key={id} on={a.density === id} onClick={() => set({ density: id })} label={l}><I size={20} aria-hidden /></Tile>)}</Row>
      </Card>
      <Card i={6} title="Avatar Face Style" icon={Bot} help="The face drawn on every agent robot. The role emblem stays the same so you can still tell roles apart." style={{ gridColumn: "2 / 4", overflow: "visible" }}>
        <Row>{faces.map((f) => <Tile key={f.id} on={a.avatarFace === f.id} onClick={() => set({ avatarFace: f.id })} label={f.label}><Avatar role="developer" size={36} face={f.id} name={`${f.label} face`} /></Tile>)}</Row>
      </Card>
      <Card i={7} title="Avatar Color Scheme" icon={Palette} help="The glow colour of the robot eyes. 'Role colour' (default) uses each role's own colour." style={{ gridColumn: "4", overflow: "visible" }}>
        <Row>
          <Tile on={a.avatarColor === "role"} onClick={() => set({ avatarColor: "role" })} label="Role" hint="Default"><Avatar role="qa" size={26} animate={false} /></Tile>
          {cols.map((c) => <Tile key={c.id} on={a.avatarColor === c.id} onClick={() => set({ avatarColor: c.id })} label={c.label}><span style={{ width: 18, height: 18, borderRadius: 99, background: c.c, boxShadow: `0 0 8px ${c.c}` }} /></Tile>)}
        </Row>
      </Card>

      <div style={{ gridColumn: "5", gridRow: "1 / 4", minHeight: 0 }}><MiniPreview /></div>
      <BottomCards />
    </div>
  );
}

/* ---------- Live preview carousel (mini dashboard with current tokens) ---------- */
function MiniPreview() {
  const [n, setN] = useState(0);
  const slides = ["Company Overview", "Missions", "Agents", "Approvals", "Finance"];
  const agents = useStore((s) => s.agents), missions = useStore((s) => s.missions), approvals = useStore((s) => s.approvals);
  const nav = [Home, Target, Users, GitBranch, Coins];
  return (
    <Card i={8} title="Live Preview" icon={Activity} style={{ height: "100%" }} help="A small AXoR dashboard drawn with your current look. Use the arrows or dots to see other screens."
      actions={<span className="ax-xs ax-muted">{n + 1} / {slides.length}</span>}>
      <div style={{ flex: 1, minHeight: 0, border: "1px solid var(--ax-border)", borderRadius: "var(--ax-radius)", background: "linear-gradient(160deg, var(--ax-bg), var(--ax-bg2))", padding: 7, display: "flex", flexDirection: "column", gap: 6, overflow: "hidden" }}>
        <div className="ax-flex" style={{ gap: 6 }}><b style={{ fontFamily: "var(--ax-font-display)", color: "var(--ax-accent)", fontSize: 14 }}>AXoR</b><span className="ax-xs ax-muted" style={{ flex: 1 }}>Autonomous AI Company OS</span><Bell size={11} aria-hidden /></div>
        <div style={{ display: "flex", gap: 6, flex: 1, minHeight: 0 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, padding: 4, borderRadius: "var(--ax-radius-sm)", background: "var(--ax-panel)", border: "1px solid var(--ax-border)" }}>
            {nav.map((I, i) => <span key={i} style={{ width: 22, height: 22, display: "grid", placeItems: "center", borderRadius: "var(--ax-icon-radius)", color: i === n ? "var(--ax-on-accent)" : "var(--ax-muted)", background: i === n ? "var(--ax-accent)" : "transparent" }}><I size={12} aria-hidden /></span>)}</div>
          <motion.div key={n} initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            <b style={{ fontSize: 12, fontFamily: "var(--ax-font-display)" }}>{slides[n]}</b>
            {n === 0 && <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 4 }}>{[["12", "Missions", Target, "var(--ax-blocked)"], ["38", "Agents", Users, "var(--ax-info)"], ["3", "Approvals", ListChecks, "var(--ax-warn)"], ["96%", "Success", Check, "var(--ax-ok)"], ["$2.8k", "Spend", Coins, "var(--ax-accent)"], ["98%", "Health", Activity, "var(--ax-ok)"]].map(([v, l, I, c]) => { const Ic = I as typeof Target; return <div key={String(l)} className="ax-tile" style={{ padding: 4 }}><Ic size={11} style={{ color: String(c) }} aria-hidden /><b style={{ display: "block", fontSize: 13 }}>{String(v)}</b><span className="ax-xs ax-muted">{String(l)}</span></div>; })}</div>
              <div className="ax-tile" style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: 6 }}><Avatar role="gm" size={32} /><div style={{ display: "flex", gap: 6 }}>{(["architect", "developer", "qa", "research", "deploy"] as Role[]).map((r) => <Avatar key={r} role={r} size={24} />)}</div></div>
            </>}
            {n === 1 && missions.slice(0, 4).map((m) => <div key={m.id} className="ax-tile" style={{ padding: 5 }}><b className="ax-xs">{m.title}</b><Progress value={m.progress} thin label={m.title} /></div>)}
            {n === 2 && <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 5 }}>{agents.slice(0, 12).map((x) => <Avatar key={x.id} role={x.role} size={32} status="active" />)}</div>}
            {n === 3 && approvals.slice(0, 4).map((x) => <div key={x.id} className="ax-tile ax-flex" style={{ padding: 5 }}><b className="ax-xs" style={{ flex: 1 }}>{x.title}</b><span className="ax-chip" style={{ color: "var(--ax-warn)" }}>{x.priority}</span></div>)}
            {n === 4 && <div className="ax-tile" style={{ flex: 1, display: "flex", alignItems: "flex-end", gap: 5, padding: 8 }}>{[40, 62, 50, 80, 66, 92].map((h, i) => <motion.i key={i} initial={{ height: 0 }} animate={{ height: `${h}%` }} style={{ flex: 1, borderRadius: 3, background: "linear-gradient(var(--ax-accent), var(--ax-accent2))" }} />)}</div>}
          </motion.div>
        </div>
      </div>
      <div className="ax-flex" style={{ justifyContent: "center" }}>
        <IconBtn icon={ChevronLeft} label="Previous preview screen" size="sm" onClick={() => setN((n + slides.length - 1) % slides.length)} />
        {slides.map((s, i) => <motion.button key={s} type="button" aria-label={`Show ${s}`} aria-current={i === n} onClick={() => setN(i)} whileHover={{ scale: 1.4 }} style={{ width: 9, height: 9, borderRadius: 99, border: 0, padding: 0, cursor: "pointer", background: i === n ? "var(--ax-accent)" : "var(--ax-faint)" }} />)}
        <IconBtn icon={ChevronRight} label="Next preview screen" size="sm" onClick={() => setN((n + 1) % slides.length)} />
      </div>
    </Card>
  );
}

/* ---------- bottom row: six functional setting cards ---------- */
function BottomCards() {
  const s = useStore((x) => x.settings), models = useStore((x) => x.models), toast = useToast();
  const [gh, setGh] = useState({ sync: true, prs: true, issues: true, notes: true });
  const [ap, setAp] = useState({ wf: true, deploy: true, spend: true, agent: true, policy: false });
  const [ws, setWs] = useState({ name: "AXoR AI Company", url: "axor.company.os", save: true });
  const [sec, setSec] = useState({ tfa: true, sso: true, ip: true });
  const [nx, setNx] = useState({ inapp: true, email: true, slack: true, teams: false, mission: true, approval: true });
  const provs = Array.from(new Set(models.map((m) => m.provider)));
  const nt = s.notifications;
  const S = { gridColumn: "span 1" } as CSSProperties;
  return (
    <div style={{ gridColumn: "1 / -1", gridRow: 4, ...grid("repeat(6, 1fr)", { gap: 8 }) }}>
      <Card i={9} title="GitHub Integration" icon={Github} help="Authorized through OAuth / the GitHub App, never by an email address alone. Sample connection." style={S}>
        <ToggleRow icon={RefreshCw} label="Auto Sync Repositories" on={gh.sync} onChange={(v) => setGh({ ...gh, sync: v })} />
        <ToggleRow icon={GitBranch} label="Sync Branches & PRs" on={gh.prs} onChange={(v) => setGh({ ...gh, prs: v })} />
        <ToggleRow icon={Link2} label="Link Issues to Missions" on={gh.issues} onChange={(v) => setGh({ ...gh, issues: v })} />
        <ToggleRow icon={BookOpen} label="Release Notes to Knowledge" on={gh.notes} onChange={(v) => setGh({ ...gh, notes: v })} />
        <Btn icon={Check} onClick={() => toast("Connected (sample): AXoR-Company via GitHub App", "info")}>Connected: AXoR-Company</Btn>
      </Card>
      <Card i={10} title="Model Providers" icon={Cpu} help="Turn all models of a provider on or off. Details are in Governance, Models." style={S}>
        {provs.map((p) => { const ms = models.filter((m) => m.provider === p), on = ms.some((m) => m.enabled);
          return <ToggleRow key={p} icon={Cpu} label={p} on={on} onChange={(v) => { const lost = rolesLosingCoverage(getState(), ms.map((m) => m.id), v); if (lost.length) { toast(`Disabling ${p} would leave ${lost.join(", ")} without a model. Change routing in Governance → Model Routing first.`, "warn"); return; } ms.forEach((m) => updateModel(m.id, { enabled: v })); toast(`${p} ${v ? "enabled" : "disabled"} (local to this session; no model registry API yet)`, "info"); }} />; })}
        <Btn icon={Plus} onClick={() => { window.location.hash = "#/governance?tab=models"; }}>Add Provider</Btn>
      </Card>
      <Card i={11} title="Approvals" icon={ListChecks} help="Which actions wait for an owner decision. Production deploys are always asked (locked)." style={S}>
        <ToggleRow icon={Check} label="Enable Approval Workflow" on={ap.wf} onChange={(v) => setAp({ ...ap, wf: v })} />
        <ToggleRow icon={Rocket} label="Platform Upgrade / Deploy" on={ap.deploy} disabled onChange={() => {}} />
        <ToggleRow icon={Coins} label="Budget & Spending" on={ap.spend} onChange={(v) => setAp({ ...ap, spend: v })} />
        <ToggleRow icon={Users} label="Agent Deployment" on={ap.agent} onChange={(v) => setAp({ ...ap, agent: v })} />
        <ToggleRow icon={ShieldCheck} label="Policy Changes" on={ap.policy} onChange={(v) => setAp({ ...ap, policy: v })} />
      </Card>
      <Card i={12} title="Workspace Settings" icon={Building2} help="Basic workspace details (sample, saved on this device only)." style={S}>
        <label className="ax-field"><span className="ax-label">Company Name</span><input className="ax-input" value={ws.name} onChange={(e) => setWs({ ...ws, name: e.target.value })} /></label>
        <label className="ax-field"><span className="ax-label">Workspace URL</span><input className="ax-input" value={ws.url} onChange={(e) => setWs({ ...ws, url: e.target.value })} /></label>
        <ToggleRow icon={Check} label="Auto-Save Changes" on={ws.save} onChange={(v) => setWs({ ...ws, save: v })} />
      </Card>
      <Card i={13} title="Notification Preferences" icon={Bell} help="Decisions, failures, releases and digest are saved to your settings; channels are sample toggles." style={S}>
        <ToggleRow icon={Bell} label="In-App Notifications" on={nx.inapp} onChange={(v) => setNx({ ...nx, inapp: v })} />
        <ToggleRow icon={Mail} label="Email Notifications" on={nx.email} onChange={(v) => setNx({ ...nx, email: v })} />
        <ToggleRow icon={Slack} label="Slack Notifications" on={nx.slack} onChange={(v) => setNx({ ...nx, slack: v })} />
        <ToggleRow icon={ListChecks} label="Approval Requests" on={!!nt.decisions} onChange={(v) => setSettings({ notifications: { ...nt, decisions: v } })} />
        <ToggleRow icon={Activity} label="Weekly Reports" on={!!nt.digest} onChange={(v) => setSettings({ notifications: { ...nt, digest: v } })} />
      </Card>
      <Card i={14} title="Security" icon={Lock} help="Sign-in protections (sample toggles). Full RBAC, API keys and audit log are in the Security tab." style={S}>
        <ToggleRow icon={KeyRound} label="Two-Factor Authentication" on={sec.tfa} onChange={(v) => setSec({ ...sec, tfa: v })} />
        <ToggleRow icon={Globe} label="Single Sign-On (SSO)" on={sec.sso} onChange={(v) => setSec({ ...sec, sso: v })} />
        <ToggleRow icon={Lock} label="IP Allowlist" on={sec.ip} onChange={(v) => setSec({ ...sec, ip: v })} />
        <a className="ax-small" href="#/appearance?tab=security">Access Control (RBAC), Audit Log, Security Policy</a>
      </Card>
    </div>
  );
}
void Switch; void SquareStack;
