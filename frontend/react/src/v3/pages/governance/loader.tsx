import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowRight, Check, Cpu, Info, Pencil, Route, X } from "lucide-react";
import { Btn, Modal, Panel, Pill, Switch, useToast } from "../../ui/kit";
import { Avatar, ROLES, type Role } from "../../ui/Avatar";
import { Dropdown } from "../../ui/widgets";
import { updateModel, useStore } from "../../data/store";
import { at } from "../../data/sample";
import type { ModelReg } from "../../domain/types";
import { cols } from "./tabs";

const ROUTED: Role[] = ["gm", "architect", "developer", "research", "qa", "knowledge", "ops", "finance", "deploy", "mentor", "strategist", "security"];
const HEALTH = { ok: { c: "var(--ax-ok)", l: "Healthy", i: Check }, degraded: { c: "var(--ax-warn)", l: "Degraded", i: AlertTriangle }, down: { c: "var(--ax-bad)", l: "Down", i: X } } as const;
const ctx = (n: number) => (n >= 1e6 ? `${n / 1e6}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n));

/** Fallback chain starting at `m`, following `fallback` links through enabled models and stopping on cycles. */
export function chainOf(m: ModelReg, models: ModelReg[]): ModelReg[] {
  const out: ModelReg[] = [], seen = new Set<string>([m.id]); let cur = m.fallback ? models.find((x) => x.id === m.fallback) : undefined;
  while (cur && !seen.has(cur.id)) { seen.add(cur.id); if (cur.enabled) out.push(cur); cur = cur.fallback ? models.find((x) => x.id === cur!.fallback) : undefined; }
  return out;
}
export function routeFor(role: Role, models: ModelReg[]) {
  const cands = models.filter((m) => m.enabled && m.roles.includes(role));
  const primary = cands.find((m) => m.health !== "down") ?? cands[0];
  return { primary, cands, chain: primary ? chainOf(primary, models) : [] };
}
const TRACES = [
  { at: at(0, -.2), task: "Architecture review for M-002", role: "architect" as Role, model: "gpt-6.1", note: "primary", ms: 1840 },
  { at: at(0, -.5), task: "Implement CI cache step", role: "developer" as Role, model: "claude-opus-5-5", note: "primary (Claude Code)", ms: 2210 },
  { at: at(0, -1.1), task: "Competitor pricing research", role: "research" as Role, model: "gpt-6.1 + claude-sonnet-5-5", note: "joint synthesis", ms: 3400 },
  { at: at(0, -3.1), task: "Strategy brief", role: "strategist" as Role, model: "claude-opus-5-5", note: "fallback: gpt-6.1 degraded", ms: 2650 },
];

export function ModelLoaderTab() {
  const models = useStore((s) => s.models), ai = useStore((s) => s.settings.aiRoles), toast = useToast();
  const [rolesFor, setRolesFor] = useState<ModelReg | null>(null), [off, setOff] = useState<{ m: ModelReg; lost: Role[] } | null>(null);
  const toggle = (m: ModelReg, v: boolean) => {
    if (!v) { const lost = m.roles.filter((r) => !models.some((x) => x.id !== m.id && x.enabled && x.roles.includes(r))); if (lost.length) { setOff({ m, lost }); return; } }
    updateModel(m.id, { enabled: v }); toast(`${m.model} ${v ? "enabled" : "disabled"} (local to this session)`);
  };
  const guide: [string, string, boolean][] = [
    ["Architecture", ai.architecture, models.some((m) => m.enabled && m.provider === "OpenAI" && m.roles.includes("architect"))],
    ["Code", ai.code, models.some((m) => m.enabled && m.provider === "Anthropic" && m.roles.includes("developer"))],
    ["Research", ai.research, models.some((m) => m.enabled && m.provider === "OpenAI" && m.roles.includes("research")) && models.some((m) => m.enabled && m.provider === "Anthropic" && m.roles.includes("research"))],
    ["Creative", ai.creative, models.some((m) => m.enabled && m.provider === "OpenAI" && m.capabilities.includes("creative"))],
  ];
  return (
    <div style={{ display: "grid", gridTemplateRows: "1.15fr 1fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Model Loader: registered models" icon={Cpu} sub="Every model and agent is identified here so each agent uses the correct model. Edits are local to this session until the model registry API exists (GPT review #2, #14)."
        help={{ body: "The registry of models the company can use: provider, id, version, capabilities, context window, cost per million tokens, latency and health. Assign the roles a model may serve, pick its fallback, and enable or disable it. Provider keys are never stored in the browser.", policy: "Disabling the last model for a role asks for confirmation." }}>
        <table className="ax-table"><thead><tr><th>Model</th><th>Capabilities</th><th>Context</th><th>$ in / out (1M)</th><th>Latency</th><th>Health</th><th>Fallback</th><th>Roles</th><th>On</th></tr></thead>
          <tbody>{models.map((m, k) => { const h = HEALTH[m.health], HI = h.i; return (
            <motion.tr key={m.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: m.enabled ? 1 : .55, x: 0 }} transition={{ delay: k * .04 }}>
              <td><b>{m.model}</b><span className="ax-xs ax-faint" style={{ display: "block" }}>{m.provider} · {m.version}</span></td>
              <td>{m.capabilities.map((c) => <span key={c} className="ax-chip" style={{ marginRight: 3 }}>{c}</span>)}</td><td className="ax-num">{ctx(m.context)}</td><td className="ax-num">${m.costIn} / ${m.costOut}</td>
              <td className="ax-num">{m.latencyMs >= 1000 ? (m.latencyMs / 1000).toFixed(1) + " s" : m.latencyMs + " ms"}</td><td><Pill c={h.c} icon={HI}>{h.l}</Pill></td>
              <td><Dropdown label={`Fallback for ${m.model}`} value={m.fallback ?? "none"} onChange={(v) => { updateModel(m.id, { fallback: v === "none" ? null : v }); toast(`Fallback for ${m.model} updated (local to this session)`); }}
                options={[{ id: "none", label: "None" }, ...models.filter((x) => x.id !== m.id).map((x) => ({ id: x.id, label: x.model }))]} /></td>
              <td><span className="ax-flex" style={{ gap: 3, flexWrap: "wrap" }}>{m.roles.length ? m.roles.map((r) => <span key={r} title={ROLES[r]?.label}><Avatar role={r} size={20} name={ROLES[r]?.label} /></span>) : <span className="ax-xs ax-faint">no roles</span>}
                <button type="button" className="ax-ib sm ghost" aria-label={`Assign roles to ${m.model}`} data-tip="Assign roles" onClick={() => setRolesFor(m)}><Pencil size={12} aria-hidden /></button></span></td>
              <td><Switch label={`${m.enabled ? "Disable" : "Enable"} ${m.model}`} on={m.enabled} onChange={(v) => toggle(m, v)} /></td></motion.tr>); })}</tbody></table>
      </Panel>
      <div style={cols("1.6fr 1fr")}>
        <Panel i={1} title="Routing by role" icon={Route} help="For each role, the model that gets the work and the fallback chain used if it is down or rate-limited. Computed from the registry above, so changes appear here at once.">
          <table className="ax-table"><thead><tr><th>Role</th><th>Primary model</th><th>Fallback chain</th><th>State</th></tr></thead>
            <tbody>{ROUTED.map((r, k) => { const x = routeFor(r, models); return (
              <motion.tr key={r} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .025 }}>
                <td><span className="ax-flex"><Avatar role={r} size={18} />{ROLES[r].label}</span></td>
                <td>{x.primary ? <b className="ax-small">{x.primary.model}</b> : <span className="ax-faint">none</span>}{x.cands.length > 1 && <span className="ax-xs ax-faint"> +{x.cands.length - 1} more</span>}</td>
                <td className="ax-xs">{x.chain.length ? x.chain.map((c, j) => <span key={c.id}>{j > 0 && <ArrowRight size={10} aria-hidden />} {c.model} </span>) : <span className="ax-faint">no fallback</span>}</td>
                <td>{!x.primary ? <Pill c="var(--ax-bad)" icon={AlertTriangle}>No model assigned</Pill> : x.primary.health === "down" ? <Pill c="var(--ax-warn)" icon={AlertTriangle}>Primary down</Pill> : !x.chain.length ? <Pill c="var(--ax-warn)" icon={AlertTriangle}>No fallback</Pill> : <Pill c="var(--ax-ok)" icon={Check}>Covered</Pill>}</td></motion.tr>); })}</tbody></table>
        </Panel>
        <div style={{ display: "grid", gridTemplateRows: "auto 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
          <Panel i={2} title="Which AI does what" icon={Info} help="The owner's rule: GPT for architecture and creative work, Claude Code for code, both for research. The check shows whether the registry can currently satisfy it.">
            <div className="ax-rows">{guide.map(([l, t, ok]) => <div key={l} className="ax-row" style={{ padding: "1px 4px" }}><b className="ax-small" style={{ width: 78 }}>{l}</b><span className="grow ax-small">{t}</span>{ok ? <Pill c="var(--ax-ok)" icon={Check}>OK</Pill> : <Pill c="var(--ax-bad)" icon={AlertTriangle}>Not covered</Pill>}</div>)}</div>
          </Panel>
          <Panel i={3} title="Routing trace" icon={Route} help="Recent routing decisions. Sample entries for illustration.">
            <div className="ax-rows">{TRACES.map((t) => <div key={t.task} className="ax-row" style={{ padding: "1px 4px" }}><span className="grow"><span className="t ax-small">{t.task}</span><span className="s">{t.model} · {t.note}</span></span><span className="ax-xs ax-num ax-muted">{(t.ms / 1000).toFixed(1)} s</span></div>)}</div>
          </Panel>
        </div>
      </div>
      <Modal open={!!rolesFor} onClose={() => setRolesFor(null)} title={`Roles for ${rolesFor?.model}`} icon={Cpu} width={440} foot={<Btn tone="gold" icon={Check} onClick={() => setRolesFor(null)}>Done</Btn>}>
        <p className="ax-small" style={{ marginTop: 0 }}>Agents in the checked roles may use this model.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>{ROUTED.map((r) => { const cur = models.find((x) => x.id === rolesFor?.id); const on = !!cur?.roles.includes(r); return (
          <label key={r} className="ax-chip" style={{ cursor: "pointer", padding: "5px 8px", borderColor: on ? "var(--ax-accent)" : undefined }}>
            <input type="checkbox" checked={on} onChange={() => cur && updateModel(cur.id, { roles: on ? cur.roles.filter((x) => x !== r) : [...cur.roles, r] })} style={{ accentColor: "var(--ax-accent)" }} /> <Avatar role={r} size={16} /> {ROLES[r].label}</label>); })}</div>
      </Modal>
      <Modal open={!!off} onClose={() => setOff(null)} title={`Disable ${off?.m.model}?`} icon={AlertTriangle} width={440}
        foot={<><Btn icon={X} onClick={() => setOff(null)}>Keep enabled</Btn><Btn tone="gold" icon={Check} onClick={() => { if (off) { updateModel(off.m.id, { enabled: false }); toast(`${off.m.model} disabled. Assign another model to: ${off.lost.map((r) => ROLES[r].label).join(", ")}.`); } setOff(null); }}>Disable anyway</Btn></>}>
        <p className="ax-small">It is the only enabled model for: <b>{off?.lost.map((r) => ROLES[r].label).join(", ")}</b>. Those roles will have no model until you assign one.</p>
      </Modal>
    </div>
  );
}
