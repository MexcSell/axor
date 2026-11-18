import { motion } from "framer-motion";
import { AlertTriangle, ArrowRight, CheckCircle2, GraduationCap, ShieldCheck } from "lucide-react";
import { Panel, Pill, Progress, StatusPill } from "../../ui/kit";
import { AgentTag } from "../../ui/widgets";
import { useStore } from "../../data/store";

export function MentoringTab() {
  const ms = useStore((s) => s.mentoring);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "62fr 38fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title={`Mentoring (${ms.length})`} icon={GraduationCap} help="Mentor agents nurture other agents by transferring a proven module. The result is assessed by a separate verifier agent: the mentor can never verify their own trainee.">
        <div className="ax-col" style={{ gap: 8 }}>
          {ms.map((m, i) => { const bad = m.mentor === m.verifier; const col = m.status === "failed" ? "var(--ax-bad)" : m.status === "passed" ? "var(--ax-ok)" : "var(--ax-info)";
            return (<motion.div key={m.id} className="ax-tile" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .07 }} whileHover={{ y: -2 }}>
              <div className="ax-flex"><AgentTag id={m.mentor} sub="mentor" /><motion.span animate={{ x: [0, 5, 0] }} transition={{ repeat: Infinity, duration: 1.4 }} aria-hidden><ArrowRight size={16} className="ax-gold" /></motion.span><AgentTag id={m.trainee} sub="trainee" /><span className="ax-spacer" /><StatusPill s={m.status} /></div>
              <div className="ax-flex ax-small" style={{ margin: "5px 0 3px" }}><b>{m.module}</b><span className="ax-muted">· {m.transfers} transfers</span><span className="ax-spacer" />{m.assessment != null && <Pill c={col} icon={m.assessment >= 70 ? CheckCircle2 : AlertTriangle}>assessment {m.assessment}/100</Pill>}</div>
              <Progress value={m.progress} c1={col} c2={col} thin label={`${m.module} progress`} />
              <div className="ax-flex ax-xs" style={{ marginTop: 4 }}><ShieldCheck size={13} className="ax-ok" aria-hidden /><span className="ax-muted">Independent verifier:</span><b>{m.verifier}</b>{bad ? <Pill c="var(--ax-bad)" icon={AlertTriangle}>mentor = verifier, invalid</Pill> : <Pill c="var(--ax-ok)">mentor ≠ verifier</Pill>}</div>
            </motion.div>); })}
        </div>
      </Panel>
      <Panel i={1} title="How mentoring works" icon={ShieldCheck} help="The mentoring rules enforced by the Lab.">
        <div className="ax-col ax-small" style={{ gap: 8 }}>
          {["A mentor transfers a verified procedure, skill or checklist to a trainee in an isolated practice mission.", "A different, independent verifier agent assesses the trainee. Mentor and verifier must never be the same agent.", "Only an assessment of 70 or more passes. A failed transfer is recorded as evidence and the trainee keeps the current version.", "Passed transfers become part of the trainee's next candidate version, which still goes through independent evaluation before promotion."].map((t, i) => <motion.div key={i} className="ax-tile ax-flex" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .08 }}><b className="ax-gold">{i + 1}</b><span>{t}</span></motion.div>)}
          <div className="ax-flex"><Pill c="var(--ax-ok)">{ms.filter((m) => m.status === "passed").length} passed</Pill><Pill c="var(--ax-info)">{ms.filter((m) => m.status === "running").length} running</Pill><Pill c="var(--ax-bad)">{ms.filter((m) => m.status === "failed").length} failed</Pill></div>
        </div>
      </Panel>
    </div>
  );
}
