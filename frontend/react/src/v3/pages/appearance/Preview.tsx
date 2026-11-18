import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Bell, Check, GitBranch, Lock, Plus, Search, Send, Settings2, Share2 } from "lucide-react";
import { Btn, IconBtn, StatusPill, Switch, Tabs, type Status } from "../../ui/kit";
import { Avatar } from "../../ui/Avatar";

// THEME-003: the same representative states in every look. All real kit components, so the preview is the truth.
const Sec = ({ t, children, i = 0 }: { t: string; children: React.ReactNode; i?: number }) => (
  <motion.div className="ax-tile" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .04 }} style={{ display: "flex", flexDirection: "column", gap: 7 }}>
    <span className="ax-xs ax-muted" style={{ textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 700 }}>{t}</span>{children}
  </motion.div>
);

export function LivePreview() {
  const [tab, setTab] = useState("overview");
  const [sw, setSw] = useState(true);
  const badges: Status[] = ["running", "passed", "failed", "blocked", "waiting_user", "paused"];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--ax-gap)", height: "100%", gridAutoRows: "minmax(auto, 1fr)" }}>
      <Sec t="Toolbar" i={0}>
        <div className="ax-flex" style={{ gap: 5 }}>
          <IconBtn icon={Search} label="Search" size="sm" /><IconBtn icon={Bell} label="Notifications" size="sm" badge={3} /><IconBtn icon={Share2} label="Share" size="sm" />
          <IconBtn icon={Settings2} label="Settings" size="sm" /><span className="ax-spacer" /><Btn tone="gold" icon={Plus}>New</Btn>
        </div>
      </Sec>
      <Sec t="Selected tab" i={1}>
        <Tabs label="Preview tabs" value={tab} onChange={setTab} tabs={[{ id: "overview", label: "Overview" }, { id: "tasks", label: "Tasks", count: 4 }, { id: "logs", label: "Logs" }]} />
      </Sec>
      <Sec t="Card" i={2}>
        <div className="ax-flex" style={{ gap: 8 }}><Avatar role="developer" size={30} /><span><b style={{ fontSize: 13 }}>Mission M-001</b><span className="ax-xs ax-muted" style={{ display: "block" }}>Mobile app v2 · 72% done</span></span></div>
        <div style={{ height: 6, borderRadius: 4, background: "var(--ax-border)" }}><div style={{ width: "72%", height: "100%", borderRadius: 4, background: "linear-gradient(90deg,var(--ax-accent),var(--ax-accent2))" }} /></div>
      </Sec>
      <Sec t="Form" i={3}>
        <input className="ax-input" placeholder="Mission title" aria-label="Preview text field" defaultValue="Launch beta" />
        <div className="ax-flex"><span className="ax-small">Auto-verify</span><span className="ax-spacer" /><Switch on={sw} onChange={setSw} label="Preview switch" /></div>
      </Sec>
      <Sec t="Chat bubble" i={4}>
        <div className="ax-chat" style={{ gap: 6 }}>
          <div className="ax-msg"><Avatar role="gm" size={22} /><div className="ax-bubble">Release candidate is ready for review.</div></div>
          <div className="ax-msg me"><div className="ax-bubble">Approved. Ship it.</div><Send size={12} className="ax-faint" aria-hidden /></div>
        </div>
      </Sec>
      <Sec t="Status badges" i={5}>
        <div className="ax-flex" style={{ flexWrap: "wrap", gap: 5 }}>{badges.map((s) => <StatusPill key={s} s={s} small />)}</div>
      </Sec>
      <Sec t="Alert" i={6}>
        <div role="alert" className="ax-flex" style={{ padding: "7px 9px", borderRadius: "var(--ax-radius-sm)", border: "1px solid var(--ax-warn)", background: "color-mix(in srgb, var(--ax-warn) 14%, transparent)", alignItems: "flex-start" }}>
          <AlertTriangle size={15} className="ax-warn" aria-hidden /><span className="ax-small">Production release needs your approval.</span>
        </div>
      </Sec>
      <Sec t="Graph node" i={7}>
        <div className="ax-flex" style={{ gap: 6, justifyContent: "center" }}>
          <GNode icon={GitBranch} label="Plan" tone="var(--ax-ok)" /><i style={{ width: 22, borderTop: "2px dashed var(--ax-accent2)" }} aria-hidden />
          <GNode icon={Check} label="Build" tone="var(--ax-info)" sel /><i style={{ width: 22, borderTop: "2px dashed var(--ax-border)" }} aria-hidden />
          <GNode icon={Lock} label="Ship" tone="var(--ax-neutral)" />
        </div>
      </Sec>
      <Sec t="Disabled controls" i={8}>
        <div className="ax-flex" style={{ gap: 6 }}><Btn disabled>Deploy</Btn><input className="ax-input" disabled defaultValue="Locked" aria-label="Disabled field" style={{ width: 90 }} /><Switch on={false} onChange={() => {}} label="Disabled switch" disabled /></div>
      </Sec>
      <Sec t="Focus ring" i={9}>
        <Btn>Tab to me to see the focus ring</Btn>
      </Sec>
    </div>
  );
}
function GNode({ icon: I, label, tone, sel }: { icon: typeof Check; label: string; tone: string; sel?: boolean }) {
  return (
    <motion.span whileHover={{ y: -2 }} className="ax-flex" style={{ gap: 4, padding: "5px 8px", borderRadius: "var(--ax-radius-sm)", border: `1.5px solid ${sel ? "var(--ax-accent)" : tone}`, background: "var(--ax-raised)", boxShadow: sel ? "0 0 calc(10px * var(--ax-glow-k)) var(--ax-glow)" : undefined }}>
      <I size={12} style={{ color: tone }} aria-hidden /><b className="ax-xs">{label}</b></motion.span>
  );
}
