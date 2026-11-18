import type { CSSProperties, ReactNode } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { Help, Switch, type HelpText } from "../../ui/kit";

// Small layout helpers shared by Appearance, Settings and Notifications (own files, no shared-file edits).
export function Card({ title, icon: I, help, children, actions, i = 0, style, c }: {
  title: ReactNode; icon?: LucideIcon; help: HelpText | string; children: ReactNode; actions?: ReactNode; i?: number; style?: CSSProperties; c?: string;
}) {
  const h: HelpText = typeof help === "string" ? { body: help } : help;
  return (
    <motion.div className="ax-tile" style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0, overflow: "auto", ...style }}
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 10) * .05 }}>
      <div className="ax-flex" style={{ gap: 7 }}>
        {I && <span style={{ color: c ?? "var(--ax-accent)", display: "grid" }}><I size={16} aria-hidden /></span>}
        <b style={{ fontSize: 13 }}>{title}</b>
        <Help {...h} label={typeof title === "string" ? title : h.title} title={h.title ?? (typeof title === "string" ? title : undefined)} />
        <span className="ax-spacer" />{actions}
      </div>
      {children}
    </motion.div>
  );
}

export function ToggleRow({ icon: I, label, hint, on, onChange, disabled, c }: {
  icon?: LucideIcon; label: string; hint?: string; on: boolean; onChange: (v: boolean) => void; disabled?: boolean; c?: string;
}) {
  return (
    <div className="ax-flex" style={{ gap: 8, padding: "3px 0", opacity: disabled ? .6 : 1 }}>
      {I && <span style={{ color: c ?? "var(--ax-muted)", display: "grid" }}><I size={15} aria-hidden /></span>}
      <span style={{ flex: 1, minWidth: 0 }}><span style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</span>
        {hint && <span className="ax-xs ax-muted" style={{ display: "block" }}>{hint}</span>}</span>
      <Switch on={on} onChange={onChange} label={`${label}: ${on ? "on" : "off"}`} disabled={disabled} />
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <div className="ax-field"><span className="ax-label">{label}</span>{children}{hint && <span className="ax-xs ax-muted">{hint}</span>}</div>;
}

export const grid = (cols: string, extra?: CSSProperties): CSSProperties => ({ display: "grid", gridTemplateColumns: cols, gap: "var(--ax-gap)", minHeight: 0, ...extra });
