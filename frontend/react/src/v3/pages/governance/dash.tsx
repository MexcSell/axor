// The Governance default tab: the governance half of the 30-9 reference (Governance Overview, Autonomy Levels, Model Routing, Policies, Permissions, Audit Logs, Timeline).
import { useMemo, useState, type CSSProperties } from "react";
import { motion } from "framer-motion";
import { Check, Crown, KeyRound, ListChecks, ScrollText, Route, X, ShieldCheck, Users, Cpu, FileCheck2 } from "lucide-react";
import { Btn, Kpi, Modal, Panel, Pill, Seg, StatusPill, Switch, Time, useToast } from "../../ui/kit";
import { type Role } from "../../ui/Avatar";
import { AgentTag } from "../../ui/widgets";
import { setSettings, toastIfErr, useStore } from "../../data/store";
import { sha } from "../../data/sample";
import { AUDIT_EXTRA, LEVELS, POLICIES, RBAC } from "./data";
import { GovOverview, TimelinePanel } from "./tabs";
import { routeFor } from "./loader";

const row = (c: string): CSSProperties => ({ display: "grid", gridTemplateColumns: c.split(" ").map((x) => `minmax(0,${x})`).join(" "), gridTemplateRows: "minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 });

export function GovKpis() {
  const aut = useStore((s) => s.settings.autonomy), renewal = useStore((s) => s.settings.selfRenewal);
  const on = Object.values(aut).filter(Boolean).length, active = POLICIES.filter((p) => p.status === "Active").length;
  return (
    <div className="ax-kpis" style={{ gridTemplateColumns: "repeat(6, 1fr)" }}>
      <Kpi i={0} icon={ShieldCheck} c="#2fd27a" value={98.7} decimals={1} suffix="%" label="Compliance Score" delta="↑ +0.9 pp" />
      <Kpi i={1} icon={ScrollText} c="#3b8cff" value={active} suffix={` / ${POLICIES.length}`} label="Policies Enforced" delta="1 in review" />
      <Kpi i={2} icon={Crown} c="#f2b53a" value={on} suffix=" / 6" label="Autonomy Levels On" delta={`Highest: L${Math.max(...Object.entries(aut).filter(([, v]) => v).map(([k]) => +k.slice(1)), 0)}`} />
      <Kpi i={3} icon={Users} c="#a77bff" value={128} label="Access Permissions" delta="128 / 128 valid" />
      <Kpi i={4} icon={Route} c="#22d3ee" value={16} label="Model Routing Rules" delta="16 / 16 active" />
      <Kpi i={5} icon={FileCheck2} c={renewal ? "#2fd27a" : "#94a3b8"} value={2841} label="Audit Logs (30d)" delta={renewal ? "Self-renewal on" : "Self-renewal off"} />
    </div>
  );
}

function AutonomyPanel({ i }: { i: number }) {
  const aut = useStore((s) => s.settings.autonomy), toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const flip = (k: string, v: boolean) => {
    const idx = LEVELS.findIndex((l) => l.k === k), next = { ...aut };
    LEVELS.forEach((l, j) => { if (v ? j === idx : j >= idx) next[l.k] = v; });
    if (toastIfErr(setSettings({ autonomy: next }), toast)) return; toast(v ? `${k} enabled` : `${k} and every higher level disabled`);
  };
  return (
    <Panel i={i} title="Autonomy Levels" icon={Crown} help={{ body: "How much the agents may do on their own, from L0 (observe) to L5 (charter autonomy). A level can only be on if all lower levels are on. Effective permission for any action is the intersection of organization, mission, agent, tool and action limits, never their union. Hover a row for the human role each level requires.", policy: "Autonomy never overrides explicit approval gates." }}>
      <table className="ax-table"><thead><tr><th>Level</th><th>Scope</th><th>Active Agents</th><th>On</th></tr></thead>
        <tbody>{[...LEVELS].reverse().map((l, k) => {
          const idx = LEVELS.findIndex((x) => x.k === l.k), canOn = idx === 0 || aut[LEVELS[idx - 1].k];
          return (
            <motion.tr key={l.k} title={`Human role: ${l.human}`} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
              <td><span className="ax-flex" style={{ gap: 5 }}><Crown size={14} style={{ color: aut[l.k] ? "var(--ax-accent)" : "var(--ax-faint)" }} aria-hidden /><b>{l.k}</b></span></td>
              <td className="ax-small" style={{ whiteSpace: "nowrap" }}>{l.name}</td><td><Pill c="var(--ax-accent2)">{l.agents}</Pill></td>
              <td><Switch label={`${aut[l.k] ? "Disable" : "Enable"} ${l.k} ${l.name}${idx === 0 ? " (always on)" : !canOn ? " (enable the lower level first)" : ""}`} on={!!aut[l.k]} disabled={idx === 0 || (!aut[l.k] && !canOn)} onChange={(v) => (v && l.k === "L5" ? setConfirm(true) : flip(l.k, v))} /></td></motion.tr>); })}</tbody></table>
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Enable L5 Charter autonomy?" icon={Crown} width={440}
        foot={<><Btn icon={X} onClick={() => setConfirm(false)}>Keep L5 off</Btn><Btn tone="gold" icon={Check} onClick={() => { flip("L5", true); setConfirm(false); }}>Enable L5</Btn></>}>
        <p className="ax-small">At L5 agents may continually improve the company under defined budgets and immutable governance. You still keep strategic, financial, policy and security authority, and the stop controls still work.</p>
      </Modal>
    </Panel>
  );
}

const TASKS: [string, Role][] = [["Planning", "gm"], ["Architecture", "architect"], ["Coding", "developer"], ["Analysis", "qa"], ["Research", "research"], ["General", "knowledge"]];
function RoutingPanel({ i, open }: { i: number; open: () => void }) {
  const models = useStore((s) => s.models);
  const [off, setOff] = useState<Record<string, boolean>>({});
  const tier = (c: number) => (c >= 4 ? "$$$" : c >= 2 ? "$$" : "$");
  return (
    <Panel i={i} title="Model Routing" icon={Route} help="Which model each kind of task goes to, with its fallback, from the Model Loader registry. The rule switch pauses a routing rule in this view only (sample mode); manage models in the Model Routing tab."
      actions={<Btn icon={Cpu} onClick={open}>Model Loader</Btn>}>
      <table className="ax-table"><thead><tr><th>Task Type</th><th>Primary Model</th><th>Fallback</th><th>Cost</th><th>Rule</th></tr></thead>
        <tbody>{TASKS.map(([t, r], k) => { const x = routeFor(r, models); return (
          <motion.tr key={t} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
            <td>{t}</td><td className="ax-small">{x.primary?.model ?? <span className="ax-faint">none</span>}</td><td className="ax-small">{x.chain[0]?.model ?? <span className="ax-faint">none</span>}</td>
            <td className="ax-num">{x.primary ? tier(x.primary.costOut) : "-"}</td><td><Switch label={`Routing rule for ${t}`} on={!off[t]} onChange={(v) => setOff({ ...off, [t]: !v })} /></td></motion.tr>); })}</tbody></table>
    </Panel>
  );
}

function PoliciesPanel({ i, open }: { i: number; open: () => void }) {
  return (
    <Panel i={i} title="Policies" icon={ScrollText} help="Company policies as code. Open the Policies tab to read or propose changes." actions={<Btn icon={ScrollText} onClick={open}>All policies</Btn>}>
      <table className="ax-table"><thead><tr><th>Policy</th><th>Status</th><th>Updated</th></tr></thead>
        <tbody>{POLICIES.slice(0, 5).map((p, k) => (
          <motion.tr key={p.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
            <td className="ax-small" style={{ whiteSpace: "nowrap" }}><b>{p.name}</b></td><td><Pill c={p.status === "Active" ? "var(--ax-ok)" : "var(--ax-warn)"} icon={p.status === "Active" ? Check : ListChecks}>{p.status}</Pill></td><td className="ax-small" style={{ whiteSpace: "nowrap" }}>{new Date(p.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</td></motion.tr>))}</tbody></table>
    </Panel>
  );
}

const AGENTS_N: Record<string, number> = { "Owner / Admin": 1, Member: 4, "General Manager (GM)": 1, "Department lead": 7, Agent: 33, "Viewer / Guest": 22 };
function PermissionsPanel({ i, open }: { i: number; open: () => void }) {
  const KEY: Record<string, string> = { "Owner / Admin": "All (Policy, Budget, Models, Evolution)", Member: "Create missions, approve decisions", "General Manager (GM)": "Plan, allocate, delegate, propose", "Department lead": "Plan, allocate, approve, monitor", Agent: "Execute, report, request resources", "Viewer / Guest": "Read-only (reports, logs, metrics)" };
  return (
    <Panel i={i} title="Permissions" icon={KeyRound} help="Who can do what, in short. The Permissions tab has the full matrix and approval classes." actions={<Btn icon={KeyRound} onClick={open}>Full matrix</Btn>}>
      <table className="ax-table"><thead><tr><th>Role</th><th>Agents</th><th>Key Permissions</th></tr></thead>
        <tbody>{RBAC.map((r, k) => (
          <motion.tr key={r.role} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
            <td className="ax-small" style={{ whiteSpace: "nowrap" }}><b>{r.role.replace("General Manager (GM)", "GM (Admin)").replace("Owner / Admin", "Owner").replace("Viewer / Guest", "Viewer")}</b></td><td className="ax-num">{AGENTS_N[r.role]}</td><td className="ax-xs ax-muted">{KEY[r.role]}</td></motion.tr>))}</tbody></table>
    </Panel>
  );
}

function AuditPanel({ i, open }: { i: number; open: () => void }) {
  const events = useStore((s) => s.events);
  const [v, setV] = useState<"logs" | "compliance" | "history">("logs");
  const logs = useMemo(() => [...AUDIT_EXTRA.map((g) => ({ id: g.id, at: g.at, actor: g.actor, action: g.action, result: g.result })), ...events.map((e) => ({ id: e.id, at: e.at, actor: e.actor as string, action: e.action, result: e.result as string }))].sort((a, b) => +new Date(b.at) - +new Date(a.at)), [events]);
  const hist = AUDIT_EXTRA.filter((g) => g.cat !== "renewal");
  const CH: [string, string][] = [["Policies enforced", "42 / 42"], ["Access reviews", "128 / 128"], ["Evaluation gates", "6 / 6"], ["Audit chain intact", "Yes"], ["External inspection data", "Not connected (sample)"]];
  return (
    <Panel i={i} title="Audit Logs & Compliance" icon={ScrollText} help="An append-only record. Each entry carries a hash of the one before it. The Audit tab has the full log." actions={<Btn icon={ScrollText} onClick={open}>Full log</Btn>}
      tabs={<Seg label="Audit views" value={v} onChange={setV} items={[{ id: "logs", label: "Audit Logs" }, { id: "compliance", label: "Compliance" }, { id: "history", label: "Change History" }]} />}>
      {v === "compliance" ? <div className="ax-rows ax-small">{CH.map(([l, x]) => <div key={l} className="ax-row"><Check size={13} style={{ color: "var(--ax-ok)" }} aria-hidden /><span className="grow">{l}</span><b>{x}</b></div>)}</div> : (
        <table className="ax-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Result</th></tr></thead>
          <tbody>{(v === "logs" ? logs : hist).slice(0, 5).map((r, k) => (
            <motion.tr key={r.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
              <td className="ax-small" style={{ whiteSpace: "nowrap" }}><Time iso={r.at} withDate /></td><td style={{ whiteSpace: "nowrap" }}><AgentTag id={r.actor} size={16} /></td><td className="ax-small" title={`chain hash ${sha(r.id + r.at, 6)}`}>{r.action.slice(0, 34)}</td>
              <td>{r.result === "success" ? <StatusPill small s="passed" label="Success" /> : r.result === "blocked" || r.result === "failure" ? <StatusPill small s="failed" label={r.result === "blocked" ? "Blocked" : "Failed"} /> : <StatusPill small s="running" label="Info" />}</td></motion.tr>))}</tbody></table>)}
    </Panel>
  );
}

export function GovDashboard({ go }: { go: (tab: string) => void }) {
  return (
    <>
      <div style={row("1fr 1.1fr 1.35fr")}><GovOverview i={1} /><AutonomyPanel i={2} /><RoutingPanel i={3} open={() => go("routing")} /></div>
      <div style={row("1.35fr 1fr 1.4fr 1.15fr")}><PoliciesPanel i={4} open={() => go("policies")} /><PermissionsPanel i={5} open={() => go("permissions")} /><AuditPanel i={6} open={() => go("audit")} /><TimelinePanel i={7} /></div>
    </>
  );
}
