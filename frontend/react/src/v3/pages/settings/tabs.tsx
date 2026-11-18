import { useState } from "react";
import { motion } from "framer-motion";
import {
  Activity, AlertTriangle, Bell, BookOpen, Brain, Building2, Calendar, Check, CheckCircle2, Clock3, Code2, Coins, Crown, ExternalLink, Eye, Github, Globe, KeyRound, Link2, Lock, Mail,
  MessageSquare, Palette, Plug, Plus, RefreshCw, Rocket, Search, ShieldCheck, Slack, Trash2, UserCheck, Users, X, Zap, Sparkles, Repeat2, Ban,
} from "lucide-react";
import { Btn, IconBtn, Modal, Pill, StatusPill, Time, useToast } from "../../ui/kit";
import { Dropdown } from "../../ui/widgets";
import { Avatar } from "../../ui/Avatar";
import { isAdmin as isAdminOf, setSettings, toastIfErr, useStore } from "../../data/store";
import { href } from "../../app/router";
import { Card, Field, ToggleRow, grid } from "./parts";

// SAMPLE data: no real integration is connected from this preview build.
const SAMPLE = <Pill c="var(--ax-info)">Sample data</Pill>;

/* ---------------- General ---------------- */
export function GeneralTab() {
  const s = useStore((x) => x.settings), toast = useToast();
  const [f, setF] = useState({ name: "AXoR AI Company", url: "axor.company.os", tz: "UTC", lang: "English", save: true, cross: false });
  const lv: [string, string][] = [["L0", "Read-only observation"], ["L1", "Suggest changes"], ["L2", "Edit drafts and docs"], ["L3", "Run tests and builds"], ["L4", "Merge to preview"], ["L5", "Deploy to production"]];
  return (
    <div style={grid("1fr 1fr 1fr", { height: "100%" })}>
      <Card i={0} title="Workspace" icon={Building2} help="Basic details of this company workspace." actions={SAMPLE}>
        <Field label="Company name"><input className="ax-input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Workspace URL"><input className="ax-input" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>
        <div style={grid("1fr 1fr")}>
          <Field label="Time zone"><Dropdown label="Time zone" value={f.tz} onChange={(v) => setF({ ...f, tz: v })} options={["UTC", "America/New_York", "Europe/Berlin", "Asia/Seoul", "Asia/Tokyo"].map((x) => ({ id: x, label: x }))} /></Field>
          <Field label="Language"><Dropdown label="Language" value={f.lang} onChange={(v) => setF({ ...f, lang: v })} options={["English", "Korean", "Japanese", "German"].map((x) => ({ id: x, label: x }))} /></Field>
        </div>
        <ToggleRow icon={Check} label="Auto-save changes" on={f.save} onChange={(v) => setF({ ...f, save: v })} />
        <ToggleRow icon={Users} label="Cross-workspace access" hint="Off: missions are isolated per workspace" on={f.cross} onChange={(v) => setF({ ...f, cross: v })} />
        <Btn tone="gold" icon={Check} onClick={() => toast("Workspace settings saved (sample data, nothing sent)", "info")}>Save</Btn>
      </Card>
      <Card i={1} title="Agent autonomy levels" icon={Zap} help={{ body: "The highest action level agents may take without asking. Higher levels need more trust. L5 (production deploy) always keeps an owner approval.", policy: "High-impact actions are never auto-approved." }}>
        {lv.map(([k, d]) => <ToggleRow key={k} label={`${k} · ${d}`} on={!!s.autonomy[k]} onChange={(v) => setSettings({ autonomy: { ...s.autonomy, [k]: v } })} c={k === "L5" ? "var(--ax-bad)" : undefined} icon={k === "L5" ? Rocket : Activity} />)}
      </Card>
      <Card i={2} title="Data and retention" icon={Lock} help="How long records are kept. Audit logs are never shortened below the compliance minimum." actions={SAMPLE}>
        <dl className="ax-kv"><dt>Mission history</dt><dd>Keep 24 months</dd><dt>Audit log</dt><dd>Keep 7 years (fixed)</dd><dt>Agent traces</dt><dd>Keep 90 days</dd><dt>Uploaded files</dt><dd>Keep with mission</dd><dt>Encryption</dt><dd>AES-256 at rest</dd></dl>
        <span className="ax-xs ax-muted">Retention changes need the admin role and are recorded in the audit log.</span>
      </Card>
    </div>
  );
}

/* ---------------- Integrations ---------------- */
export function IntegrationsTab() {
  const models = useStore((x) => x.models), sources = useStore((x) => x.newsSources), toast = useToast();
  const [gh, setGh] = useState({ sync: true, prs: true, issues: true, notes: true }), [ask, setAsk] = useState(false);
  const provs = Array.from(new Set(models.map((m) => m.provider)));
  return (
    <div style={grid("1.2fr 1fr 1fr", { height: "100%", gridTemplateRows: "1fr 1fr" })}>
      <Card i={0} title="GitHub" icon={Github} style={{ gridRow: "1 / -1" }} help={{ body: "AXoR connects to GitHub only through OAuth or the GitHub App installation, where you choose which repositories to share. An email address alone can never authorize access.", policy: "Least privilege: repository scope is chosen at install time." }} actions={SAMPLE}>
        <div className="ax-flex" style={{ padding: 8, borderRadius: 9, border: "1px solid var(--ax-ok)", background: "color-mix(in srgb, var(--ax-ok) 10%, transparent)" }}>
          <CheckCircle2 size={18} className="ax-ok" aria-hidden /><span style={{ flex: 1 }}><b className="ax-small">Connected (sample): AXoR-Company</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Authorized through the AXoR GitHub App · 12 repositories</span></span>
          <IconBtn icon={ExternalLink} label="Open GitHub installation settings" size="sm" onClick={() => toast("Would open github.com/settings/installations (not opened in this sample)", "info")} /></div>
        <dl className="ax-kv"><dt>Authorization</dt><dd>GitHub App (OAuth)</dd><dt>Permissions</dt><dd>Contents, PRs, Issues (read/write)</dd><dt>Email-only access</dt><dd><span className="ax-ok">Not allowed</span></dd><dt>Webhook</dt><dd>Healthy · 2 min ago</dd></dl>
        <ToggleRow icon={RefreshCw} label="Auto sync repositories" on={gh.sync} onChange={(v) => setGh({ ...gh, sync: v })} />
        <ToggleRow icon={Repeat2} label="Sync branches and PRs" on={gh.prs} onChange={(v) => setGh({ ...gh, prs: v })} />
        <ToggleRow icon={Link2} label="Link issues to missions" on={gh.issues} onChange={(v) => setGh({ ...gh, issues: v })} />
        <ToggleRow icon={BookOpen} label="Release notes to Knowledge" on={gh.notes} onChange={(v) => setGh({ ...gh, notes: v })} />
        <div className="ax-flex"><Btn icon={Plug} onClick={() => setAsk(true)}>Reconnect via GitHub App</Btn><Btn icon={Trash2} onClick={() => toast("Disconnect needs owner approval (nothing changed in this sample)", "warn")}>Disconnect</Btn></div>
        <Modal open={ask} onClose={() => setAsk(false)} title="Reconnect GitHub" icon={Github} width={480} foot={<><span className="ax-spacer" /><Btn onClick={() => setAsk(false)}>Cancel</Btn><Btn tone="gold" icon={ExternalLink} onClick={() => { setAsk(false); toast("Would redirect to GitHub to authorize the AXoR App (not done in this sample)", "info"); }}>Continue to GitHub</Btn></>}>
          <span className="ax-small">You will be sent to GitHub to approve the AXoR GitHub App and choose repositories. AXoR never asks for your password or accepts an email address as proof of access.</span>
        </Modal>
      </Card>
      <Card i={1} title="Model providers" icon={Brain} help="Model providers from the Model Loader. Enable, disable and set fallbacks in Governance." actions={<a className="ax-small" href={href("governance", null, { tab: "models" })}>Manage</a>}>
        {provs.map((p) => { const ms = models.filter((m) => m.provider === p), ok = ms.every((m) => m.health === "ok" || !m.enabled); return (
          <div key={p} className="ax-flex"><Sparkles size={14} className="ax-gold" aria-hidden /><b className="ax-small" style={{ flex: 1 }}>{p}</b><span className="ax-xs ax-muted">{ms.filter((m) => m.enabled).length}/{ms.length} models</span><StatusPill s={ok ? "passed" : "failed"} label={ok ? "Healthy" : "Down"} small /></div>); })}
      </Card>
      <Card i={2} title="Slack and chat" icon={Slack} help="Send notifications to a Slack channel. Uses the Slack app OAuth flow; AXoR never stores your Slack password." actions={SAMPLE}>
        <div className="ax-flex"><StatusPill s="paused" label="Not connected" small /></div>
        <span className="ax-xs ax-muted">Connect to receive approvals and failure alerts in a channel and approve from Slack.</span>
        <Btn icon={Plug} onClick={() => toast("Would start the Slack OAuth flow (not done in this sample)", "info")}>Connect Slack</Btn>
        <div className="ax-flex"><MessageSquare size={14} className="ax-muted" aria-hidden /><span className="ax-small" style={{ flex: 1 }}>Microsoft Teams</span><StatusPill s="paused" label="Not connected" small /></div>
      </Card>
      <Card i={3} title="Website sources" icon={Globe} style={{ gridColumn: "2 / -1" }} help="Web sources the Knowledge and Research agents read on a schedule. They are managed in Knowledge." actions={<a className="ax-small" href={href("knowledge")}>Open Knowledge</a>}>
        {sources.slice(0, 5).map((x) => (
          <div key={x.id} className="ax-flex"><Rss2 /><span style={{ flex: 1, minWidth: 0 }}><b className="ax-small">{x.name}</b><span className="ax-xs ax-muted" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.url}</span></span>
            <span className="ax-xs ax-muted">{x.cadence}</span><StatusPill s={x.status === "ok" ? "passed" : x.status === "error" ? "failed" : "paused"} label={x.status} small /></div>))}
        {!sources.length && <span className="ax-small ax-muted">No sources yet.</span>}
      </Card>
    </div>
  );
}
const Rss2 = () => <Globe size={14} className="ax-gold" aria-hidden />;

/* ---------------- Approvals ---------------- */
const ACTIONS = [
  { id: "deploy", label: "Production deployment", icon: Rocket, hint: "Always owner approval", locked: true }, { id: "spend", label: "Budget and spending over limit", icon: Coins, hint: "Over $500 / mission" },
  { id: "merge", label: "Merge to main", icon: Code2, hint: "After verification passes" }, { id: "agent", label: "Agent promotion or rollback", icon: Users, hint: "Evolution Lab candidates" },
  { id: "policy", label: "Policy and permission changes", icon: ShieldCheck, hint: "Governance rules" }, { id: "delete", label: "Delete data or repositories", icon: Trash2, hint: "Destructive, always asked", locked: true },
  { id: "external", label: "Contact external services", icon: ExternalLink, hint: "New outbound integrations" }, { id: "selfren", label: "Apply a self-renewal change", icon: Repeat2, hint: "Verified candidates only" },
];
export function ApprovalsTab() {
  const [on, setOn] = useState<Record<string, boolean>>({ deploy: true, spend: true, merge: false, agent: true, policy: true, delete: true, external: true, selfren: true });
  const [scope, setScope] = useState("key"), [n, setN] = useState("1"), [wf, setWf] = useState(true);
  const toast = useToast();
  return (
    <div style={grid("1.5fr 1fr", { height: "100%" })}>
      <Card i={0} title="Actions that need your approval" icon={UserCheck} help="Pick which kinds of action pause and wait for the owner. Locked rows are required by policy and cannot be turned off." actions={SAMPLE}>
        <div style={grid("1fr 1fr", { columnGap: 18 })}>
          {ACTIONS.map((a) => <ToggleRow key={a.id} icon={a.icon} label={a.label} hint={a.hint} on={on[a.id]} disabled={a.locked} onChange={(v) => setOn({ ...on, [a.id]: v })} c={a.locked ? "var(--ax-bad)" : undefined} />)}
        </div>
        {ACTIONS.some((a) => a.locked) && <span className="ax-xs ax-muted"><Lock size={11} aria-hidden /> Locked by policy: production deploys and destructive actions always require an owner decision.</span>}
      </Card>
      <Card i={1} title="Approval workflow" icon={CheckCircle2} help="How approvals work: scope decides which actions are asked, required approvers sets how many people must agree.">
        <ToggleRow icon={CheckCircle2} label="Enable approval workflow" on={wf} onChange={setWf} />
        <Field label="Approval scope"><Dropdown label="Approval scope" value={scope} onChange={setScope} options={[{ id: "all", label: "All actions" }, { id: "key", label: "Key actions (recommended)" }, { id: "high", label: "High risk only" }]} /></Field>
        <Field label="Required approvers"><Dropdown label="Required approvers" value={n} onChange={setN} options={["1", "2", "3"].map((x) => ({ id: x, label: x }))} /></Field>
        <Field label="Escalate if no answer after"><Dropdown label="Escalation" value="24" onChange={() => {}} options={[{ id: "4", label: "4 hours" }, { id: "24", label: "24 hours" }, { id: "72", label: "3 days" }]} /></Field>
        <Btn tone="gold" icon={Check} onClick={() => toast("Approval policy saved (sample data, nothing sent)", "info")}>Save policy</Btn>
      </Card>
    </div>
  );
}

/* ---------------- Notifications ---------------- */
export function NotificationsTab() {
  const s = useStore((x) => x.settings), toast = useToast();
  const n = s.notifications;
  const [ch, setCh] = useState({ inapp: true, email: true, slack: false });
  const qh = { from: s.quietFrom ?? "22:00", to: s.quietTo ?? "07:00" }; const setQh = (v: { from: string; to: string }) => setSettings({ quietFrom: v.from, quietTo: v.to });
  const rows: [string, string, typeof Bell][] = [["decisions", "Approvals and decisions", UserCheck], ["failures", "Failures and blocked work", AlertTriangle], ["releases", "Releases and deployments", Rocket], ["digest", "Daily digest email", Mail]];
  return (
    <div style={grid("1fr 1fr 1fr", { height: "100%" })}>
      <Card i={0} title="What to notify" icon={Bell} help="Which events create a notification. High-severity items break through quiet hours." >
        {rows.map(([k, l, I]) => <ToggleRow key={k} icon={I} label={l} on={!!n[k]} onChange={(v) => setSettings({ notifications: { ...n, [k]: v } })} />)}
        <span className="ax-xs ax-muted">Saved immediately to your settings.</span>
      </Card>
      <Card i={1} title="Delivery channels" icon={MessageSquare} help="Where notifications are delivered." actions={SAMPLE}>
        <ToggleRow icon={Bell} label="In-app" on={ch.inapp} onChange={(v) => setCh({ ...ch, inapp: v })} />
        <ToggleRow icon={Mail} label="Email" on={ch.email} onChange={(v) => setCh({ ...ch, email: v })} />
        <ToggleRow icon={Slack} label="Slack" hint="Connect Slack in Integrations first" on={ch.slack} onChange={(v) => { setCh({ ...ch, slack: v }); if (v) toast("Slack is not connected yet", "warn"); }} />
      </Card>
      <Card i={2} title="Quiet hours" icon={Clock3} help="During quiet hours only high-severity items notify you; everything else waits in the Inbox.">
        <ToggleRow icon={Clock3} label="Enable quiet hours" on={s.quietHours} onChange={(v) => setSettings({ quietHours: v })} />
        <div style={grid("1fr 1fr")}><Field label="From"><input className="ax-input" type="time" value={qh.from} disabled={!s.quietHours} onChange={(e) => setQh({ ...qh, from: e.target.value })} /></Field>
          <Field label="To"><input className="ax-input" type="time" value={qh.to} disabled={!s.quietHours} onChange={(e) => setQh({ ...qh, to: e.target.value })} /></Field></div>
        <a className="ax-small" href={href("notifications", null, { tab: "rules" })}>Open full notification rules</a>
      </Card>
    </div>
  );
}

/* ---------------- Security ---------------- */
const ROLE_ROWS = [["Owner", "Everything, incl. approvals and billing", 1], ["Admin", "Settings, integrations, self-renewal", 2], ["Member", "Missions, agents, chat", 8], ["Guest", "Read-only views", 3]] as const;
export function SecurityTab() {
  const events = useStore((x) => x.events), toast = useToast();
  const [sec, setSec] = useState({ tfa: true, sso: false, ip: true });
  const [rev, setRev] = useState<string | null>(null);
  const keys = [{ id: "k1", name: "CI pipeline", mask: "axor_live_••••••••9f3a", last: "2 h ago" }, { id: "k2", name: "Read-only dashboard", mask: "axor_live_••••••••c71d", last: "6 days ago" }];
  return (
    <div style={grid("1fr 1fr 1.2fr", { height: "100%", gridTemplateRows: "1fr 1fr" })}>
      <Card i={0} title="Sign-in security" icon={ShieldCheck} help="Two-factor adds a second step at sign-in. Single sign-on lets your identity provider manage who can enter." actions={SAMPLE}>
        <ToggleRow icon={KeyRound} label="Two-factor authentication (2FA)" on={sec.tfa} onChange={(v) => setSec({ ...sec, tfa: v })} />
        <ToggleRow icon={Users} label="Single sign-on (SSO)" hint="Requires an identity provider" on={sec.sso} onChange={(v) => { setSec({ ...sec, sso: v }); if (v) toast("Configure your identity provider to finish SSO (sample)", "info"); }} />
        <ToggleRow icon={Lock} label="IP allow-list" on={sec.ip} onChange={(v) => setSec({ ...sec, ip: v })} />
        <dl className="ax-kv"><dt>Session timeout</dt><dd>8 hours</dd><dt>Encryption</dt><dd>AES-256</dd></dl>
      </Card>
      <Card i={1} title="Roles (RBAC)" icon={Users} help="Role-based access control: what each role may do. Roles are assigned per person." actions={SAMPLE}>
        {ROLE_ROWS.map(([r, d, c]) => <div key={r} className="ax-flex"><Crown size={13} className="ax-gold" aria-hidden /><span style={{ flex: 1 }}><b className="ax-small">{r}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{d}</span></span><Pill c="var(--ax-info)">{c}</Pill></div>)}
      </Card>
      <Card i={2} title="Audit log" icon={Eye} style={{ gridRow: "1 / -1" }} help="Every change to settings, approvals and agents, with who and when. Cannot be edited." >
        {events.slice(0, 12).map((e) => (
          <div key={e.id} className="ax-flex" style={{ fontSize: 12 }}><span className="ax-xs ax-muted" style={{ width: 52 }}><Time iso={e.at} /></span><span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><b>{e.actor}</b> {e.action} <span className="ax-muted">{e.target}</span></span>
            <StatusPill s={e.result === "failure" ? "failed" : e.result === "warning" ? "review" : e.result === "running" ? "running" : "passed"} label={e.result} small /></div>))}
      </Card>
      <Card i={3} title="API keys" icon={KeyRound} style={{ gridColumn: "1 / 3" }} help="Keys are shown masked and are never displayed again after creation. Revoke a key if it may have leaked." actions={SAMPLE}>
        {keys.map((k) => <div key={k.id} className="ax-flex"><KeyRound size={14} className="ax-gold" aria-hidden /><span style={{ flex: 1 }}><b className="ax-small">{k.name}</b><span className="ax-xs ax-muted ax-mono" style={{ display: "block" }}>{k.mask}</span></span><span className="ax-xs ax-muted">used {k.last}</span>
          <IconBtn icon={Trash2} label={`Revoke ${k.name}`} size="sm" tone="bad" onClick={() => setRev(k.name)} /></div>)}
        <Btn icon={Plus} onClick={() => toast("Would create a key and show it once (nothing created in this sample)", "info")}>New API key</Btn>
        <Modal open={!!rev} onClose={() => setRev(null)} title="Revoke API key" icon={Trash2} width={440} foot={<><span className="ax-spacer" /><Btn onClick={() => setRev(null)}>Cancel</Btn><Btn tone="gold" icon={Trash2} onClick={() => { toast(`Would revoke "${rev}" (sample, nothing changed)`, "warn"); setRev(null); }}>Revoke</Btn></>}>
          <span className="ax-small">Anything using <b>{rev}</b> stops working immediately. This cannot be undone.</span></Modal>
      </Card>
    </div>
  );
}

/* ---------------- Admin ---------------- */
const AI_OPTS = [
  { id: "GPT (ARC-01)", label: "GPT" }, { id: "Claude Code (DEV agents)", label: "Claude Code" }, { id: "GPT + Claude (joint synthesis)", label: "GPT + Claude together" }, { id: "GPT proposes, Claude reviews", label: "GPT proposes, Claude reviews" }];
export function AdminTab() {
  const s = useStore((x) => x.settings), models = useStore((x) => x.models), toast = useToast();
  const admin = useStore(isAdminOf); // fail closed while identity loads (GPT review #2, #4)
  const [ask, setAsk] = useState<boolean | null>(null);
  const [prov, setProv] = useState(s.verificationProvider);
  const roles: { k: keyof typeof s.aiRoles; label: string; hint: string; icon: typeof Brain; c: string }[] = [
    { k: "architecture", label: "Architecture and design", hint: "Recommended: GPT", icon: Brain, c: "#38bdf8" }, { k: "creative", label: "Creative proposals", hint: "GPT proposes, Claude reviews", icon: Sparkles, c: "#e879f9" },
    { k: "code", label: "Code writing", hint: "Recommended: Claude Code", icon: Code2, c: "#3b8cff" }, { k: "research", label: "Research synthesis", hint: "GPT and Claude together", icon: Search, c: "#22d3ee" }];
  return (
    <div style={grid("1.15fr 1fr", { height: "100%", gridTemplateRows: "1.25fr 1fr" })}>
      <Card i={0} title="Self-renewal" icon={Repeat2} help={{ body: "When On, the General Manager continuously proposes, builds and verifies improvements to agents and the platform itself. When Off, no evolution runs by itself; you can still start work manually. Verification is essential in both cases.", policy: "Admin only. Every change is recorded in the audit log." }}
        actions={<Pill c={s.selfRenewal ? "var(--ax-ok)" : "var(--ax-neutral)"} icon={s.selfRenewal ? CheckCircle2 : Ban}>{s.selfRenewal ? "On" : "Off"}</Pill>}>
        <div className="ax-flex" style={{ gap: 10 }}>
          <motion.span animate={s.selfRenewal ? { rotate: 360 } : { rotate: 0 }} transition={s.selfRenewal ? { repeat: Infinity, duration: 6, ease: "linear" } : {}} style={{ color: s.selfRenewal ? "var(--ax-ok)" : "var(--ax-neutral)", display: "grid" }}><Repeat2 size={26} aria-hidden /></motion.span>
          <span style={{ flex: 1 }}><b>Self-renewal is {s.selfRenewal ? "On" : "Off"}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{admin ? "Only admins can change this." : "Only an admin can change this."}</span></span>
          <button type="button" className="ax-switch" role="switch" aria-checked={s.selfRenewal} aria-label={`Self-renewal: ${s.selfRenewal ? "on" : "off"}`} disabled={!admin} onClick={() => setAsk(!s.selfRenewal)} data-tip="Toggle self-renewal"><i style={{ left: s.selfRenewal ? 19 : 2 }} /></button>
        </div>
        <div style={grid("1fr 1fr")}>
          <div className="ax-tile" style={{ borderColor: s.selfRenewal ? "var(--ax-ok)" : undefined }}><b className="ax-small ax-ok"><CheckCircle2 size={12} aria-hidden /> On</b><span className="ax-xs ax-muted" style={{ display: "block" }}>The GM keeps evolving: finds weak spots, builds candidate agent versions and platform changes, tests them in the Evolution Lab and proposes promotion. Anything high-impact still waits for you.</span></div>
          <div className="ax-tile" style={{ borderColor: !s.selfRenewal ? "var(--ax-neutral)" : undefined }}><b className="ax-small"><Ban size={12} aria-hidden /> Off</b><span className="ax-xs ax-muted" style={{ display: "block" }}>No automatic evolution. Agents keep their current versions. You can still start evolution work by hand.</span></div>
        </div>
        <span className="ax-xs ax-muted"><ShieldCheck size={11} aria-hidden /> Verification is essential: no self-evolved change is promoted until it passes independent verification.</span>
        <Modal open={ask !== null} onClose={() => setAsk(null)} title={ask ? "Turn self-renewal on?" : "Turn self-renewal off?"} icon={Repeat2} width={480}
          foot={<><span className="ax-spacer" /><Btn onClick={() => setAsk(null)}>Cancel</Btn><Btn tone="gold" icon={Check} onClick={() => { if (toastIfErr(setSettings({ selfRenewal: !!ask }), toast)) { setAsk(null); return; } toast(ask ? "Self-renewal is on: the GM continues self-evolution" : "Self-renewal is off: no automatic evolution", ask ? "ok" : "warn"); setAsk(null); }}>Confirm</Btn></>}>
          <span className="ax-small">{ask ? "The General Manager will continuously propose and build improvements, each one verified before it is promoted." : "The General Manager will stop self-evolution. Work in progress finishes, but no new improvements start."}</span></Modal>
      </Card>
      <Card i={1} title="AI role assignment" icon={Brain} help="Which AI does which kind of work. Defaults: GPT for architecture/design and creative proposals, Claude Code for writing code, both together for research synthesis." >
        {roles.map((r) => { const I = r.icon; return (
          <div key={r.k} className="ax-flex"><span style={{ color: r.c, display: "grid" }}><I size={15} aria-hidden /></span><span style={{ flex: 1, minWidth: 0 }}><b className="ax-small">{r.label}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{r.hint}</span></span>
            <Dropdown label={r.label} value={s.aiRoles[r.k]} onChange={(v) => setSettings({ aiRoles: { ...s.aiRoles, [r.k]: v } })} options={AI_OPTS.some((o) => o.id === s.aiRoles[r.k]) ? AI_OPTS : [...AI_OPTS, { id: s.aiRoles[r.k], label: s.aiRoles[r.k] }]} /></div>); })}
      </Card>
      <Card i={2} title="Model Loader" icon={Plug} help="Summary of the registered models. Add, enable and set fallbacks in Governance, Models tab." actions={<a className="ax-small" href={href("governance", null, { tab: "models" })}>Open Model Loader</a>}>
        <div style={grid("repeat(3, 1fr)")}>
          <div className="ax-tile"><b className="ax-num" style={{ fontSize: 20 }}>{models.filter((m) => m.enabled).length}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Enabled models</span></div>
          <div className="ax-tile"><b className="ax-num" style={{ fontSize: 20 }}>{new Set(models.map((m) => m.provider)).size}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Providers</span></div>
          <div className="ax-tile"><b className="ax-num" style={{ fontSize: 20, color: models.some((m) => m.health !== "ok" && m.enabled) ? "var(--ax-warn)" : "var(--ax-ok)" }}>{models.filter((m) => m.health !== "ok").length}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Degraded or down</span></div>
        </div>
        {models.slice(0, 3).map((m) => <div key={m.id} className="ax-flex"><span className="ax-small" style={{ flex: 1 }}>{m.model}</span><StatusPill s={m.health === "ok" ? "passed" : m.health === "degraded" ? "review" : "failed"} label={m.health} small /></div>)}
      </Card>
      <Card i={3} title="Verification framework" icon={ShieldCheck} help="Verification is essential. Self-evolved changes are checked by an independent party before promotion. You can add an external inspection company as a data source for checks." actions={SAMPLE}>
        <Field label="Verification provider (data source)"><input className="ax-input" value={prov} disabled={!admin} onChange={(e) => setProv(e.target.value)} /></Field>
        <div className="ax-flex"><Btn tone="gold" icon={Check} disabled={!admin || prov === s.verificationProvider} onClick={() => { setSettings({ verificationProvider: prov }); toast("Verification provider saved"); }}>Save</Btn>
          <span className="ax-xs ax-muted">External inspection company data is read-only evidence; it never changes code.</span></div>
        <div className="ax-flex" style={{ flexWrap: "wrap" }}>{["Independent QA agent", "Test suites", "External inspection data", "Owner sign-off"].map((x) => <Pill key={x} c="var(--ax-ok)" icon={Check}>{x}</Pill>)}</div>
      </Card>
    </div>
  );
}
void Avatar; void Calendar; void Palette; void Zap; void X; void Activity;
