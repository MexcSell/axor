import { motion } from "framer-motion";
import { Beaker, BarChart3, Bird, FlaskConical, GraduationCap, History, Lightbulb, Rocket, ShieldCheck, RefreshCw, ArrowRight } from "lucide-react";
import { Pill, TabBody, Tabs, Help, useToast, Switch } from "../ui/kit";
import { setSettings, useStore } from "../data/store";
import { useQueryParam } from "../app/router";
import { ExperimentsTab } from "./evolution/Experiments";
import { BenchmarksTab } from "./evolution/Benchmarks";
import { LifecycleTab } from "./evolution/Lifecycle";
import { QueueTab } from "./evolution/Queue";
import { MentoringTab } from "./evolution/MentoringTab";
import { HistoryTab } from "./evolution/History";
import { EvoDashboard, VerifiersPanel, AssignmentPanel } from "./evolution/Dashboard";

// Evolution Lab (Detailed UI v3 §4.12, §5–6; EVO-001..004; canonical reference 30-7). Agents renew themselves from experience; mentors nurture;
// independent verifiers verify; a version verified better than the previous is used from next time. Tab + candidate live in the URL (?tab=, ?c=).
const Stat = ({ v, l, i }: { v: number; l: string; i: number }) => (
  <motion.div className="ax-tile" style={{ textAlign: "center", padding: "4px 14px" }} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 + i * .06 }}><div className="ax-xs ax-muted">{l}</div><b className="ax-num" style={{ fontSize: 22 }}>{v}</b></motion.div>
);
export default function Evolution() {
  const toast = useToast();
  const cands = useStore((s) => s.candidates), mentoring = useStore((s) => s.mentoring), renewal = useStore((s) => s.settings.selfRenewal);
  const [tab, setTab] = useQueryParam("tab", "proposals"); const [cq, setC] = useQueryParam("c", cands[0].id);
  const sel = cands.some((c) => c.id === cq) ? cq : cands[0].id;
  const n = (st: string[]) => cands.filter((c) => st.includes(c.status)).length;
  const lead = cands.find((c) => c.id === sel) ?? cands[0];
  const TABS = [
    { id: "proposals", label: "Proposals", icon: Lightbulb, count: cands.length }, { id: "experiments", label: "Experiments", icon: FlaskConical, count: n(["experiment", "evaluating"]) },
    { id: "benchmarks", label: "Evaluation", icon: BarChart3, count: n(["passed", "failed", "promoted"]) }, { id: "verifiers", label: "Verifiers", icon: ShieldCheck, count: 7 },
    { id: "history", label: "Promotion History", icon: History, count: n(["promoted", "rejected", "rolled_back"]) },
    { id: "lifecycle", label: "Agent Lifecycle", icon: Bird }, { id: "queue", label: "Promotion Queue", icon: Rocket, count: n(["passed"]) }, { id: "mentoring", label: "Mentoring", icon: GraduationCap, count: mentoring.length },
  ];
  return (
    <div className="ax-page" style={{ gridTemplateRows: "auto auto minmax(0, 1fr)" }}>
      <motion.section className="ax-panel" style={{ padding: "8px 12px" }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} aria-label="Evolution Lab header">
        <div className="ax-flex" style={{ gap: 12, flexWrap: "wrap" }}>
          <motion.span animate={{ rotate: [-6, 6, -6] }} transition={{ duration: 3, repeat: Infinity }}><Beaker size={38} className="ax-gold" aria-hidden /></motion.span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="ax-flex"><h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Evolution Lab</h1><Help title="Evolution Lab" body="Agents renew themselves as experience accumulates, including their own code. Mentor agents nurture other agents and independent verifier agents verify. If the updated version is verified better than the previous one, it is used from next time." /></div>
            <div className="ax-small ax-muted">Self-Renewal · Verified Evolution · Continuous Capability Improvement</div>
          </div>
          <span className="ax-chip" style={{ gap: 8 }}><RefreshCw size={14} aria-hidden />Self-Renewal: {renewal ? "ON" : "OFF"}<Switch on={renewal} onChange={(v) => { setSettings({ selfRenewal: v }); toast(`Self-renewal ${v ? "enabled" : "disabled"}`, "info"); }} label="Self-renewal" /></span>
          <Pill c="var(--ax-ok)" icon={ShieldCheck} solid>Verified Evolution: ON</Pill><Pill c="var(--ax-warn)">Sample data</Pill>
          <Stat i={0} v={cands.length} l="Total Proposals" /><Stat i={1} v={n(["experiment", "evaluating"])} l="Running" /><Stat i={2} v={n(["passed", "promoted"])} l="Verified" /><Stat i={3} v={n(["promoted"])} l="Promoted" />
          <div className="ax-tile ax-flex ax-small" style={{ padding: "4px 12px" }}><div><div className="ax-xs ax-muted">{lead.agentId} version</div><b>{lead.from} (current)</b></div><ArrowRight size={16} className="ax-gold" aria-hidden /><div><div className="ax-xs ax-muted">&nbsp;</div><b>{lead.to} ({lead.status === "promoted" ? "promoted" : "candidate"})</b></div></div>
        </div>
      </motion.section>
      <Tabs label="Evolution Lab tabs" value={tab} onChange={setTab} tabs={TABS} />
      <div style={{ minHeight: 0 }}>
        <TabBody k={tab}>
          {tab === "proposals" && <EvoDashboard sel={sel} onSel={setC} />}
          {tab === "verifiers" && <div style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}><VerifiersPanel big /><AssignmentPanel /></div>}
          {tab === "experiments" && <ExperimentsTab sel={sel} onSel={setC} />}
          {tab === "benchmarks" && <BenchmarksTab sel={sel} onSel={setC} />}
          {tab === "lifecycle" && <LifecycleTab sel={sel} onSel={setC} />}
          {tab === "queue" && <QueueTab sel={sel} onSel={setC} />}
          {tab === "mentoring" && <MentoringTab />}
          {tab === "history" && <HistoryTab onSel={(id) => { setC(id); setTab("benchmarks"); }} />}
        </TabBody>
      </div>
    </div>
  );
}
