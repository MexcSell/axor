import { useState } from "react";
import { motion } from "framer-motion";
import { AlertOctagon, Check, Dna, Info, Lock, Octagon, PauseCircle, RefreshCw, ShieldCheck, Snowflake, X, Wallet } from "lucide-react";
import { Btn, Modal, Panel, Pill, Switch, useToast } from "../../ui/kit";
import { isAdmin as isAdminOf, isSampleMode, setSettings, toastIfErr, useStore } from "../../data/store";
import { GATES, STOPS, VERIFIERS } from "./data";
import { cols } from "./tabs";

const STOP_ICON = { freeze: Snowflake, spend: Wallet, quarantine: Lock, mission: PauseCircle, kill: Octagon } as const;
const SOURCES = ["Independent QA (internal)", "Independent QA (internal) + external vendor on approval", "External inspection company only"];

export function SelfRenewalTab() {
  const s = useStore((x) => x.settings), me = useStore((x) => x.me), candidates = useStore((x) => x.candidates), toast = useToast();
  // fail closed while identity is loading (GPT review #2, #4)
  const sampleMode = useStore(isSampleMode), isAdmin = useStore(isAdminOf);
  const [confirmOn, setConfirmOn] = useState(false);
  const [stopReq, setStopReq] = useState<{ st: (typeof STOPS)[number]; on: boolean } | null>(null); const stop = stopReq?.st ?? null; const setStop = (st: (typeof STOPS)[number] | null) => setStopReq(st ? { st, on: true } : null), [active, setActive] = useState<Record<string, boolean>>({});
  const proposing = candidates.filter((c) => ["proposed", "experiment", "evaluating"].includes(c.status)).length;
  const set = (v: boolean) => { if (toastIfErr(setSettings({ selfRenewal: v }), toast)) return; toast(v ? "Self-renewal is ON: the GM may continuously evolve the company within budget and safety gates." : "Self-renewal is OFF: improvements only happen during mission work."); };
  return (
    <div style={cols("1.25fr 1fr")}>
      <div style={{ display: "grid", gridTemplateRows: "auto 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="Self-Renewal" icon={Dna} help={{ body: "A company-wide switch for how the General Manager improves the company. Only an admin can change it.", policy: "Never allows an unrestricted production rewrite, and never lets a candidate change its own evaluation, approver or governance policy." }}
          actions={<Pill c={s.selfRenewal ? "var(--ax-ok)" : "var(--ax-neutral)"} icon={s.selfRenewal ? Check : PauseCircle}>{s.selfRenewal ? "On" : "Off"}</Pill>}>
          <div className="ax-flex" style={{ alignItems: "flex-start", gap: 14 }}>
            <div style={{ flex: 1 }}>
              <div className="ax-flex" style={{ marginBottom: 6 }}>
                <Switch label={isAdmin ? "Self-renewal (admin only)" : "Self-renewal is admin-only: you are not an admin"} on={s.selfRenewal} disabled={!isAdmin} onChange={(v) => (v ? setConfirmOn(true) : set(false))} />
                <b>Self-renewal {s.selfRenewal ? "on" : "off"}</b>
                {!isAdmin && <Pill c="var(--ax-warn)" icon={Lock}>Admin only</Pill>}
              </div>
              {!isAdmin && <p className="ax-small" style={{ margin: "0 0 6px", color: "var(--ax-warn)" }}>Your role is {me?.role}. Only an admin can change this setting; ask an admin if it should change.</p>}
              {sampleMode && <p className="ax-xs ax-muted" style={{ margin: "0 0 6px" }}><Info size={11} aria-hidden /> Sample mode: no signed-in user, so this page assumes an admin. A real session enforces the role on the server.</p>}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {[{ on: true, t: "On", d: "The GM continuously self-evolves the company structure and agents, within budget and safety gates: proposals, sandbox experiments, evaluations." }, { on: false, t: "Off", d: "Improvements only happen during mission work. No background experiments." }].map((o) => (
                  <motion.div key={o.t} animate={{ opacity: s.selfRenewal === o.on ? 1 : .55 }} className="ax-row" style={{ flexDirection: "column", alignItems: "flex-start", border: `1px solid ${s.selfRenewal === o.on ? "var(--ax-accent)" : "var(--ax-border)"}`, padding: 8 }}>
                    <b className="ax-small">{o.t}{s.selfRenewal === o.on && " (current)"}</b><span className="ax-small ax-muted">{o.d}</span></motion.div>))}
              </div>
              <p className="ax-xs ax-faint" style={{ margin: "6px 0 0" }}>{proposing} candidate improvements are in the pipeline now. Safety gates apply either way.</p>
            </div>
          </div>
        </Panel>
        <div style={cols("1fr 1fr")}>
          <Panel i={1} title="Verification sources" icon={ShieldCheck} help="Who independently checks that improvements are safe and real. External inspection company data adds a check that the company does not control itself. All of it is untrusted until verified.">
            <label className="ax-xs ax-muted" htmlFor="vp">Verification provider</label>
            <select id="vp" className="ax-select" value={SOURCES.includes(s.verificationProvider) ? s.verificationProvider : "custom"} onChange={(e) => { if (toastIfErr(setSettings({ verificationProvider: e.target.value }), toast)) return; toast("Verification provider updated"); }} style={{ marginBottom: 6 }}>
              {!SOURCES.includes(s.verificationProvider) && <option value="custom">{s.verificationProvider}</option>}{SOURCES.map((x) => <option key={x}>{x}</option>)}</select>
            <div className="ax-rows">{VERIFIERS.map((v) => (
              <div key={v.id} className="ax-row" style={{ alignItems: "flex-start" }}><span className="grow"><span className="t ax-small" style={{ whiteSpace: "normal" }}>{v.name}</span><span className="s" style={{ whiteSpace: "normal" }}>{v.note}</span></span>
                <Pill c={v.status === "Active" ? "var(--ax-ok)" : "var(--ax-neutral)"} icon={v.status === "Active" ? Check : Info}>{v.kind}</Pill></div>))}</div>
          </Panel>
          <Panel i={2} title="Safety gates" icon={Check} help="Every improvement must pass all of these before it can be promoted (EVO-002).">
            <div className="ax-rows">{GATES.map((g, k) => <motion.div key={g} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .05 }}><Check size={13} style={{ color: "var(--ax-ok)" }} aria-hidden /><span className="grow ax-small">{g}</span></motion.div>)}</div>
          </Panel>
        </div>
      </div>
      <Panel i={3} title="Stop controls" icon={AlertOctagon} help={{ body: "Emergency controls that work independently of the agent runtime. Each asks for confirmation.", policy: "In sample mode they change what this page shows; no real agent is stopped." }}>
        <div className="ax-rows">{STOPS.map((st, k) => { const I = STOP_ICON[st.id]; const on = active[st.id]; return (
          <motion.div key={st.id} className="ax-row" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * .06 }} style={{ borderColor: st.tone === "bad" ? "var(--ax-bad)" : undefined }}>
            <I size={18} style={{ color: st.tone === "bad" ? "var(--ax-bad)" : "var(--ax-warn)", flex: "none" }} aria-hidden />
            <span className="grow"><span className="t ax-small">{st.label}</span><span className="s" style={{ whiteSpace: "normal" }}>{st.detail}</span></span>
            {on ? <Btn icon={RefreshCw} onClick={() => setStopReq({ st, on: false })}>Release</Btn> : <Btn icon={st.tone === "bad" ? Octagon : PauseCircle} onClick={() => setStop(st)} style={st.tone === "bad" ? { borderColor: "var(--ax-bad)", color: "var(--ax-bad)" } : undefined}>{st.tone === "bad" ? "Stop all" : "Activate"}</Btn>}
          </motion.div>); })}</div>
        <p className="ax-xs ax-faint" style={{ marginTop: 6 }}>Active now: {Object.entries(active).filter(([, v]) => v).map(([k]) => STOPS.find((x) => x.id === k)?.label).join(", ") || "nothing is stopped"}.</p>
      </Panel>
      <Modal open={confirmOn} onClose={() => setConfirmOn(false)} title="Turn self-renewal on?" icon={Dna} width={460}
        foot={<><Btn icon={X} onClick={() => setConfirmOn(false)}>Keep it off</Btn><Btn tone="gold" icon={Check} onClick={() => { set(true); setConfirmOn(false); }}>Turn on</Btn></>}>
        <p className="ax-small">The General Manager will continuously propose and test improvements to the company structure and agents, within budget and safety gates. Promotions still need the approvals your policies require. You can turn this off at any time.</p>
      </Modal>
      <Modal open={!!stop} onClose={() => setStop(null)} title={stop ? `${stopReq?.on ? "" : "Release: "}${stop.label}?` : ""} icon={AlertOctagon} width={460}
        foot={<><Btn icon={X} onClick={() => setStop(null)}>Cancel</Btn><Btn tone="gold" icon={Check} onClick={() => { if (stop && stopReq) { if (!isAdmin) { toast("Only an administrator can change stop controls.", "warn"); setStop(null); return; } setActive({ ...active, [stop.id]: stopReq.on }); toast(`${stop.label}: ${stopReq.on ? "activated" : "released"}. Sample mode: no real agent was affected.`, stopReq.on ? "ok" : "warn"); } setStop(null); }}>Confirm</Btn></>}>
        <p className="ax-small">{stopReq?.on ? stop?.detail : "Releasing lets the stopped work resume."}</p><p className="ax-xs ax-muted">The action is written to the audit log. Sample mode: this changes the page state only.</p>
      </Modal>
    </div>
  );
}
