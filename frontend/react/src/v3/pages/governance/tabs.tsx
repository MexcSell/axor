import { useMemo, useState, type CSSProperties } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Ban, Check, Crown, Download, FileCode2, Hourglass, Info, KeyRound, Lock, ScrollText, ShieldCheck } from "lucide-react";
import { Gauge, IconBtn, Panel, Pill, Seg, StatusPill, Time, useToast } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import { useStore } from "../../data/store";
import { sha } from "../../data/sample";
import { APPROVAL_CLASSES, AUDIT_EXTRA, CAPS, CONSTITUTION, ESCALATION, POLICIES, RBAC, TIMELINE, type Grant } from "./data";

export const cols = (c: string): CSSProperties => ({ display: "grid", gridTemplateColumns: c, gap: "var(--ax-gap)", height: "100%", minHeight: 0 });

/* ---------- Autonomy ---------- */
export function GovOverview({ i = 0 }: { i?: number }) {
  const aut = useStore((s) => s.settings.autonomy), renewal = useStore((s) => s.settings.selfRenewal);
  const on = Object.values(aut).filter(Boolean).length;
  const rows: [string, string, boolean][] = [["Policies Enforced", `${POLICIES.filter((p) => p.status === "Active").length} / ${POLICIES.length}`, true], ["Access Permissions", "128 / 128", true], ["Autonomy Controls", `${on} / 6 levels on`, true],
    ["Model Routing Rules", "16 / 16", true], ["Audit Logs (30d)", "2,841", true], ["Self-Renewal Health", renewal ? "Up to date" : "Off", renewal]];
  return (
    <Panel i={i} title="Governance Overview" icon={ShieldCheck} help="Compliance across policies, access, autonomy, model routing and audit. Figures other than autonomy levels and policy counts are sample values.">
      <div className="ax-flex" style={{ gap: 14 }}>
        <Gauge value={98.7} size={124} stroke={13} label="Compliance" />
        <div className="ax-rows" style={{ flex: 1 }}>{rows.map(([l, v, ok]) => (
          <div key={l} className="ax-row" style={{ padding: "2px 4px" }}>{ok ? <Check size={14} style={{ color: "var(--ax-ok)" }} aria-hidden /> : <Info size={14} style={{ color: "var(--ax-neutral)" }} aria-hidden />}<span className="grow ax-small">{l}</span><b className="ax-small ax-num">{v}</b></div>))}</div>
      </div>
    </Panel>
  );
}

export function TimelinePanel({ i = 0 }: { i?: number }) {
  const C: Record<string, string> = { policy: "#3b8cff", access: "#a77bff", model: "#f2b53a", audit: "#2fd27a", renewal: "#22d3ee" };
  return (
    <Panel i={i} title="Compliance & Audit Timeline" icon={ScrollText} help="Recent governance events, oldest to newest. Colour and the label both show the kind of event.">
      <div className="ax-flex" style={{ justifyContent: "space-between", alignItems: "flex-start", position: "relative", paddingTop: 4 }}>
        <div aria-hidden style={{ position: "absolute", left: 20, right: 20, top: 17, height: 2, background: "var(--ax-border)" }} />
        {TIMELINE.map((e, k) => (
          <motion.div key={k} style={{ textAlign: "center", flex: 1, position: "relative" }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * .07 }}>
            <span style={{ display: "inline-grid", placeItems: "center", width: 36, height: 36, borderRadius: "50%", border: `2px solid ${C[e.k]}`, background: "var(--ax-panel)", color: C[e.k] }}><ShieldCheck size={16} aria-hidden /></span>
            <div className="ax-xs" style={{ fontWeight: 700 }}>{e.t}</div><div className="ax-xs ax-muted">{e.d.replace(/^.*\((.*)\)$/, "$1")}</div><div className="ax-xs ax-faint">{new Date(e.at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</div></motion.div>))}
      </div>
      <div className="ax-flex ax-xs" style={{ justifyContent: "center", flexWrap: "wrap", gap: 12 }} aria-label="Legend">{[["Policy Update", "policy"], ["Access Change", "access"], ["Model Route", "model"], ["Audit Check", "audit"], ["Self-Renewal", "renewal"]].map(([l, k]) => <span key={k} className="ax-flex" style={{ gap: 4 }}><i style={{ width: 8, height: 8, borderRadius: "50%", background: C[k], display: "inline-block" }} aria-hidden />{l}</span>)}</div>
    </Panel>
  );
}

/* ---------- Permissions ---------- */
const G: Record<Grant, { icon: typeof Check; c: string; t: string }> = { yes: { icon: Check, c: "var(--ax-ok)", t: "Allowed" }, approval: { icon: Hourglass, c: "var(--ax-warn)", t: "Needs approval" }, no: { icon: Ban, c: "var(--ax-faint)", t: "Not allowed" } };
export function PermissionsTab() {
  return (
    <div style={{ display: "grid", gridTemplateRows: "1.25fr 1fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Permissions (RBAC)" icon={KeyRound} help="Who can do what. Each cell shows an icon and a word: allowed, needs approval, or not allowed. Per-tool scopes narrow these further.">
        <table className="ax-table"><thead><tr><th>Role</th>{CAPS.map((c) => <th key={c} style={{ whiteSpace: "normal", textAlign: "center", fontSize: 10.5 }}>{c}</th>)}</tr></thead>
          <tbody>{RBAC.map((r, k) => (
            <motion.tr key={r.role} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .04 }}>
              <td><b className="ax-small">{r.role}</b><span className="ax-xs ax-faint" style={{ display: "block" }}>{r.who}</span></td>
              {r.grants.map((g, j) => { const d = G[g], I = d.icon; return <td key={j} style={{ textAlign: "center" }}><span className="ax-xs" style={{ color: d.c, display: "inline-flex", flexDirection: "column", alignItems: "center" }} title={d.t}><I size={14} aria-hidden />{d.t.split(" ")[0]}</span></td>; })}</motion.tr>))}</tbody></table>
      </Panel>
      <div style={cols("1.7fr 1fr")}>
        <Panel i={1} title="Human approval classes" icon={Hourglass} help="Every action belongs to a class. The class decides who must approve and how fast.">
          <table className="ax-table"><thead><tr><th>Class</th><th>Examples</th><th>Approver</th><th>SLA</th></tr></thead>
            <tbody>{APPROVAL_CLASSES.map((a) => <tr key={a.k}><td><Pill c={a.k === "A3" ? "var(--ax-bad)" : a.k === "A2" ? "var(--ax-warn)" : "var(--ax-ok)"}>{a.k} {a.name}</Pill></td><td className="ax-small">{a.examples}</td><td className="ax-small">{a.who}</td><td className="ax-small">{a.sla}</td></tr>)}</tbody></table>
        </Panel>
        <Panel i={2} title="Escalation path" icon={AlertTriangle} help="What happens when a request needs a human.">
          <ol className="ax-small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>{ESCALATION.map((e) => <li key={e}>{e}</li>)}</ol>
        </Panel>
      </div>
    </div>
  );
}

/* ---------- Policies ---------- */
export function PoliciesTab() {
  const [sel, setSel] = useState(POLICIES[0].id), toast = useToast();
  const p = POLICIES.find((x) => x.id === sel)!;
  return (
    <div style={cols("1.2fr 1fr")}>
      <div style={{ display: "grid", gridTemplateRows: "1.4fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="Policies" icon={ScrollText} help="Company policies as code. Select one to read it. Changes need owner approval (class A3) and create an audit entry.">
          <table className="ax-table"><thead><tr><th>Policy</th><th>Status</th><th>Version</th><th>Last updated</th><th>Owner</th></tr></thead>
            <tbody>{POLICIES.map((x, k) => (
              <motion.tr key={x.id} className={`click ${x.id === sel ? "sel" : ""}`} tabIndex={0} onClick={() => setSel(x.id)} onKeyDown={(e) => e.key === "Enter" && setSel(x.id)} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .03 }}>
                <td><b>{x.name}</b></td><td><Pill c={x.status === "Active" ? "var(--ax-ok)" : "var(--ax-warn)"} icon={x.status === "Active" ? Check : Hourglass}>{x.status}</Pill></td><td className="ax-num">v{x.version}</td><td><Time iso={x.updated} withDate /></td><td className="ax-small">{x.owner}</td></motion.tr>))}</tbody></table>
        </Panel>
        <Panel i={1} title="Company constitution" icon={Crown} help="Principles no agent, candidate or automation can override. Only the owner can change them.">
          <div className="ax-rows ax-small">{CONSTITUTION.map((t) => <div key={t} className="ax-row"><Lock size={12} style={{ color: "var(--ax-accent)" }} aria-hidden /><span className="grow" style={{ whiteSpace: "normal" }}>{t}</span></div>)}</div>
        </Panel>
      </div>
      <Panel i={2} title={`Policy as code: ${p.name}`} icon={FileCode2} help="The machine-readable policy that is enforced. Edits are proposals until the owner approves them." actions={<IconBtn icon={Download} label="Export this policy (sample)" size="sm" onClick={() => toast("Sample mode: policy export is simulated.")} />}>
        <motion.pre key={p.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="ax-small" style={{ margin: 0, padding: 10, borderRadius: 9, background: "var(--ax-panel2)", border: "1px solid var(--ax-border)", overflow: "auto", fontFamily: "ui-monospace, monospace", whiteSpace: "pre-wrap" }}>{p.code}</motion.pre>
        <p className="ax-xs ax-faint">Version {p.version}. Sample policy text for illustration; it is not enforced by a live policy engine in sample mode.</p>
      </Panel>
    </div>
  );
}

/* ---------- Audit ---------- */
export function AuditTab() {
  const events = useStore((s) => s.events), toast = useToast();
  const [f, setF] = useState<"all" | "gov" | "act">("all");
  const rows = useMemo(() => {
    const all = [...AUDIT_EXTRA.map((g) => ({ id: g.id, at: g.at, actor: g.actor, action: g.action, target: g.target, result: g.result, gov: true })),
      ...events.map((e) => ({ id: e.id, at: e.at, actor: e.actor as string, action: e.action, target: e.target, result: e.result as string, gov: false }))].sort((a, b) => +new Date(a.at) - +new Date(b.at));
    let prev = "0000000"; const withHash = all.map((r) => { prev = sha(prev + r.id + r.action + r.at, 7); return { ...r, hash: prev }; });
    return withHash.reverse().filter((r) => f === "all" || (f === "gov" ? r.gov : !r.gov));
  }, [events, f]);
  return (
    <div style={cols("2.2fr 1fr")}>
      <Panel i={0} title="Audit Logs & Compliance" icon={ScrollText} help="An append-only record of policy, budget, model and permission changes and of agent activity. Each entry carries a hash of the one before it, so edits to history are detectable."
        actions={<><Seg label="Audit filter" value={f} onChange={setF} items={[{ id: "all", label: "All" }, { id: "gov", label: "Governance changes" }, { id: "act", label: "Agent activity" }]} /><IconBtn icon={Download} label="Export audit log (sample)" size="sm" onClick={() => toast(`Sample mode: ${rows.length} entries would be exported.`)} /></>}>
        <table className="ax-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Result</th><th>Chain hash</th></tr></thead>
          <tbody>{rows.slice(0, 60).map((r, k) => (
            <motion.tr key={r.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(k, 12) * .02 }}>
              <td><Time iso={r.at} withDate /></td><td><AgentTag id={r.actor} size={16} /></td><td className="ax-small">{r.action}</td><td className="ax-xs ax-muted">{r.target}</td>
              <td>{r.result === "success" ? <StatusPill small s="passed" label="Success" /> : r.result === "blocked" || r.result === "failure" ? <StatusPill small s="failed" label={r.result === "blocked" ? "Blocked" : "Failed"} /> : <StatusPill small s="running" label="Info" />}</td>
              <td className="ax-xs ax-num ax-faint">{r.hash}</td></motion.tr>))}</tbody></table>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={1} title="Integrity" icon={ShieldCheck} help="Hash chain verification of the visible entries. In sample mode it is computed in the browser, so it demonstrates the idea but is not tamper-proof on its own.">
          <div className="ax-flex" style={{ gap: 10 }}><Gauge value={98.4} size={84} stroke={9} label="98.4%" /><span className="ax-small">Audit check: {rows.length} entries chained, none altered in this view. Server-side signing is needed for real immutability.</span></div>
        </Panel>
        <Panel i={2} title="Retention" icon={Lock} help="How long records are kept.">
          <div className="ax-rows ax-small">{["Policy, budget, model and permission changes: kept indefinitely", "Agent activity: 400 days", "Entries cannot be edited or deleted, only superseded by a new entry"].map((t) => <div key={t} className="ax-row"><Check size={13} style={{ color: "var(--ax-ok)" }} aria-hidden /><span className="grow" style={{ whiteSpace: "normal" }}>{t}</span></div>)}</div>
        </Panel>
      </div>
    </div>
  );
}
