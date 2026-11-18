import { useStore } from "../data/store";
import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type CSSProperties, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion, type HTMLMotionProps } from "framer-motion";
import {
  AlertTriangle, Ban, Check, CheckCircle2, CircleDashed, CircleDot, Clock3, Copy, Eye, Hourglass, Loader2, PauseCircle,
  RotateCcw, ShieldAlert, X, XCircle, type LucideIcon,
} from "lucide-react";

/* ============ tooltip layer: any element with data-tip gets a tooltip on hover and keyboard focus (UX-004) ============ */
export function TooltipLayer() {
  const [tip, setTip] = useState<{ text: string; x: number; y: number; below: boolean } | null>(null);
  useEffect(() => {
    let cur: Element | null = null;
    const show = (el: Element | null) => {
      const t = el?.closest?.("[data-tip]");
      if (!t) { cur = null; setTip(null); return; }
      if (t === cur) return; cur = t;
      const r = t.getBoundingClientRect(), text = t.getAttribute("data-tip") || "";
      if (!text) { setTip(null); return; }
      const below = r.top < 48;
      setTip({ text, x: Math.min(window.innerWidth - 12, Math.max(12, r.left + r.width / 2)), y: below ? r.bottom + 8 : r.top - 8, below });
    };
    const over = (e: Event) => show(e.target as Element);
    const out = (e: MouseEvent) => { if (!(e.relatedTarget as Element | null)?.closest?.("[data-tip]")) { cur = null; setTip(null); } };
    const focus = (e: FocusEvent) => { const el = e.target as HTMLElement; if (el.matches?.(":focus-visible")) show(el); };
    const hide = () => { cur = null; setTip(null); };
    document.addEventListener("mouseover", over); document.addEventListener("mouseout", out);
    document.addEventListener("focusin", focus); document.addEventListener("focusout", hide);
    document.addEventListener("scroll", hide, true); document.addEventListener("mousedown", hide);
    return () => {
      document.removeEventListener("mouseover", over); document.removeEventListener("mouseout", out);
      document.removeEventListener("focusin", focus); document.removeEventListener("focusout", hide);
      document.removeEventListener("scroll", hide, true); document.removeEventListener("mousedown", hide);
    };
  }, []);
  return createPortal(
    <AnimatePresence>
      {tip && (
        <motion.div key={tip.text + tip.x} className="ax-tip" role="tooltip"
          initial={{ opacity: 0, y: tip.below ? -4 : 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: .12 }}
          style={{ left: tip.x, top: tip.y, translateX: "-50%", translateY: tip.below ? "0%" : "-100%" }}>{tip.text}</motion.div>
      )}
    </AnimatePresence>, document.body);
}

/* ============ "?" help popover (UX-HELP-001) ============ */
export interface HelpText { title?: string; body: ReactNode; example?: ReactNode; source?: ReactNode; policy?: ReactNode }
export function Help({ title, body, example, source, policy, label }: HelpText & { label?: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const btn = useRef<HTMLButtonElement>(null), pop = useRef<HTMLDivElement>(null);
  const id = useId();
  const place = useCallback(() => {
    const r = btn.current?.getBoundingClientRect(); if (!r) return;
    const w = 300, h = pop.current?.offsetHeight ?? 160;
    const x = Math.min(window.innerWidth - w - 10, Math.max(10, r.left - 20));
    const y = r.bottom + h + 12 > window.innerHeight ? Math.max(10, r.top - h - 8) : r.bottom + 8;
    setPos({ x, y });
  }, []);
  useLayoutEffect(() => { if (open) place(); }, [open, place]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!pop.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <>
      <motion.button ref={btn} type="button" className="ax-help" aria-label={`Help: ${label ?? title ?? "explanation"}`} aria-expanded={open} aria-controls={id}
        whileHover={{ scale: 1.15, rotate: 8 }} whileTap={{ scale: .9 }} onClick={() => setOpen((o) => !o)}>?</motion.button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.div ref={pop} id={id} role="dialog" aria-label={title ?? label ?? "Help"} className="ax-pop" style={{ left: pos.x, top: pos.y }}
              initial={{ opacity: 0, scale: .95, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .97 }} transition={{ duration: .15 }}>
              {title && <h4>{title}</h4>}
              <p style={{ color: "var(--ax-text)" }}>{body}</p>
              {(example || source || policy) && (
                <dl>
                  {example && <><dt>Example</dt><dd>{example}</dd></>}
                  {source && <><dt>Source</dt><dd>{source}</dd></>}
                  {policy && <><dt>Policy</dt><dd>{policy}</dd></>}
                </dl>
              )}
            </motion.div>
          )}
        </AnimatePresence>, document.body)}
    </>
  );
}

/* ============ icon-only button (tooltip + aria-label + motion) ============ */
type IBProps = Omit<HTMLMotionProps<"button">, "children"> & { icon: LucideIcon; label: string; tone?: "gold" | "ok" | "bad" | "info" | "ghost"; size?: "sm" | "md" | "lg"; iconSize?: number; badge?: number | string };
export function IconBtn({ icon: I, label, tone, size = "md", iconSize, badge, className = "", ...rest }: IBProps) {
  const s = iconSize ?? (size === "sm" ? 13 : size === "lg" ? 22 : 16);
  return (
    <motion.button type="button" aria-label={label} data-tip={label} className={`ax-ib ${size !== "md" ? size : ""} ${tone ?? ""} ${className}`}
      whileHover={{ scale: 1.08, y: -1 }} whileTap={{ scale: .9 }} transition={{ type: "spring", stiffness: 500, damping: 22 }} {...rest}>
      <I size={s} strokeWidth={2.1} aria-hidden />
      {badge != null && badge !== 0 && <span className="ax-dot-badge" aria-hidden>{badge}</span>}
    </motion.button>
  );
}
export function Btn({ icon: I, children, tone, lg, className = "", ...rest }: Omit<HTMLMotionProps<"button">, "children"> & { icon?: LucideIcon; children: ReactNode; tone?: "gold"; lg?: boolean }) {
  return (
    <motion.button type="button" className={`ax-btn ${tone ?? ""} ${lg ? "lg" : ""} ${className}`} whileHover={{ scale: 1.03, y: -1 }} whileTap={{ scale: .96 }} {...rest}>
      {I && <I size={15} aria-hidden />}{children}
    </motion.button>
  );
}

/* ============ panel (title + ? help + actions + tabs; animated entrance) ============ */
export function Panel({ title, icon: I, help, sub, actions, tabs, children, className = "", style, i = 0, flush, area, hl, headExtra, id }: {
  title: ReactNode; icon?: LucideIcon; help?: HelpText | string; sub?: ReactNode; actions?: ReactNode; tabs?: ReactNode; children?: ReactNode;
  className?: string; style?: CSSProperties; i?: number; flush?: boolean; area?: string; hl?: boolean; headExtra?: ReactNode; id?: string;
}) {
  const h: HelpText | null = typeof help === "string" ? { body: help } : help ?? null;
  return (
    <motion.section id={id} className={`ax-panel ${hl ? "hl" : ""} ${className}`} style={{ gridArea: area, ...style }}
      initial={{ opacity: 0, y: 14, scale: .985 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: .42, delay: Math.min(i, 14) * .045, ease: [.2, .8, .2, 1] }}
      aria-label={typeof title === "string" ? title : undefined}>
      <div className="ax-panel-head">
        {I && <motion.span className="ax-pi" initial={{ rotate: -20, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} transition={{ delay: .15 + i * .045 }}><I size={18} aria-hidden /></motion.span>}
        <h2>{title}</h2>
        {h && <Help {...h} label={typeof title === "string" ? title : h.title} title={h.title ?? (typeof title === "string" ? title : undefined)} />}
        {sub && <span className="ax-sub">{sub}</span>}
        {headExtra}
        {actions && <div className="ax-panel-actions">{actions}</div>}
      </div>
      {tabs && <div className="ax-panel-tabs">{tabs}</div>}
      <div className={`ax-panel-body ${flush ? "flush" : ""}`}>{children}</div>
    </motion.section>
  );
}

/* ============ tabs (keyboard arrows, animated highlight) ============ */
export interface TabDef { id: string; label: ReactNode; icon?: LucideIcon; count?: number; alert?: number }
export function Tabs({ tabs, value, onChange, label, variant, wrap }: { tabs: TabDef[]; value: string; onChange: (id: string) => void; label: string; variant?: "under"; wrap?: boolean }) {
  const layout = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const key = (e: KeyboardEvent, ix: number) => {
    const n = tabs.length; let j = -1;
    if (e.key === "ArrowRight") j = (ix + 1) % n; else if (e.key === "ArrowLeft") j = (ix - 1 + n) % n; else if (e.key === "Home") j = 0; else if (e.key === "End") j = n - 1;
    if (j >= 0) { e.preventDefault(); onChange(tabs[j].id); refs.current[j]?.focus(); }
  };
  return (
    <div className={`ax-tabs ${variant ?? ""} ${wrap ? "wrap" : ""}`} role="tablist" aria-label={label}>
      {tabs.map((t, ix) => {
        const on = t.id === value; const I = t.icon;
        return (
          <motion.button key={t.id} ref={(el) => { refs.current[ix] = el; }} type="button" role="tab" aria-selected={on} tabIndex={on ? 0 : -1}
            className="ax-tab" onClick={() => onChange(t.id)} onKeyDown={(e) => key(e, ix)} whileHover={{ y: -1 }} whileTap={{ scale: .95 }}>
            {on && <motion.i className="ax-tab-hl" layoutId={`tab-${layout}`} transition={{ type: "spring", stiffness: 420, damping: 34 }} aria-hidden />}
            {I && <I size={13} aria-hidden />}
            <span>{t.label}{t.count != null && <> ({t.count})</>}</span>
            {t.alert ? <span className="ax-count" aria-label={`${t.alert} need attention`}>{t.alert}</span> : null}
          </motion.button>
        );
      })}
    </div>
  );
}
// Animated swap of tab contents.
export function TabBody({ k, children, className = "", style }: { k: string; children: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={k} role="tabpanel" className={className} style={{ height: "100%", minHeight: 0, ...style }}
        initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: .18 }}>
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
export function Seg<T extends string>({ value, onChange, items, label }: { value: T; onChange: (v: T) => void; items: { id: T; label: string; icon?: LucideIcon }[]; label: string }) {
  return (
    <div className="ax-seg" role="group" aria-label={label}>
      {items.map((it) => { const I = it.icon; return (
        <motion.button key={it.id} type="button" aria-pressed={value === it.id} onClick={() => onChange(it.id)} whileTap={{ scale: .93 }}
          aria-label={it.label} data-tip={I ? it.label : undefined}>
          {I ? <I size={14} aria-hidden /> : it.label}
        </motion.button>); })}
    </div>
  );
}

/* ============ status (never colour alone: icon + text + colour, UX-005) ============ */
export type Status = "queued" | "ready" | "running" | "review" | "verifying" | "passed" | "done" | "failed" | "blocked" | "paused" | "waiting_user"
  | "waiting_agent" | "cancelled" | "rolled_back" | "draft" | "awaiting_approval";
const ST: Record<Status, { label: string; c: string; icon: LucideIcon; spin?: boolean }> = {
  queued: { label: "Queued", c: "var(--ax-neutral)", icon: Clock3 },
  ready: { label: "Ready", c: "var(--ax-accent2)", icon: CircleDot },
  running: { label: "In Progress", c: "var(--ax-info)", icon: Loader2, spin: true },
  review: { label: "Review", c: "var(--ax-warn)", icon: Eye },
  verifying: { label: "Verification", c: "var(--ax-warn)", icon: ShieldAlert },
  passed: { label: "Passed", c: "var(--ax-ok)", icon: CheckCircle2 },
  done: { label: "Done", c: "var(--ax-ok)", icon: CheckCircle2 },
  failed: { label: "Failed", c: "var(--ax-bad)", icon: XCircle },
  blocked: { label: "Blocked", c: "var(--ax-blocked)", icon: Ban },
  paused: { label: "Paused", c: "var(--ax-neutral)", icon: PauseCircle },
  waiting_user: { label: "Needs your decision", c: "var(--ax-warn)", icon: Hourglass },
  waiting_agent: { label: "Waiting on agent", c: "var(--ax-accent2)", icon: Hourglass },
  cancelled: { label: "Cancelled", c: "var(--ax-neutral)", icon: X },
  rolled_back: { label: "Rolled back", c: "var(--ax-blocked)", icon: RotateCcw },
  draft: { label: "Draft", c: "var(--ax-neutral)", icon: CircleDashed },
  awaiting_approval: { label: "Awaiting approval", c: "var(--ax-warn)", icon: AlertTriangle },
};
export function statusInfo(s: Status) { return ST[s] ?? ST.queued; }
export function StatusPill({ s, label, solid, small }: { s: Status; label?: string; solid?: boolean; small?: boolean }) {
  const d = statusInfo(s); const I = d.icon;
  return (
    <motion.span className={`ax-pill ${solid ? "solid" : ""}`} style={{ "--c": d.c, fontSize: small ? 10.5 : undefined } as CSSProperties}
      initial={{ opacity: 0, scale: .8 }} animate={{ opacity: 1, scale: 1 }} layout>
      <I size={small ? 10 : 12} className={d.spin ? "ax-spin" : ""} aria-hidden />{label ?? d.label}
    </motion.span>
  );
}
export function Pill({ c, children, solid, icon: I }: { c: string; children: ReactNode; solid?: boolean; icon?: LucideIcon }) {
  return <motion.span className={`ax-pill ${solid ? "solid" : ""}`} style={{ "--c": c } as CSSProperties} initial={{ opacity: 0, scale: .85 }} animate={{ opacity: 1, scale: 1 }}>{I && <I size={11} aria-hidden />}{children}</motion.span>;
}
export const PRIORITY: Record<string, string> = { High: "var(--ax-bad)", Critical: "var(--ax-bad)", Medium: "var(--ax-warn)", Low: "var(--ax-info)" };

/* ============ progress / numbers ============ */
export function Progress({ value, c1, c2, thin, thick, label }: { value: number; c1?: string; c2?: string; thin?: boolean; thick?: boolean; label?: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div className={`ax-bar ${thin ? "thin" : ""} ${thick ? "thick" : ""}`} role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? "Progress"}
      style={{ "--c1": c1, "--c2": c2 } as CSSProperties}>
      <motion.i initial={{ width: 0 }} animate={{ width: `${v}%` }} transition={{ duration: .9, ease: [.2, .8, .2, 1] }} />
    </div>
  );
}
export function progressColors(p: number, status?: Status): [string, string] {
  if (status === "blocked") return ["var(--ax-blocked)", "var(--ax-blocked)"];
  if (status === "failed") return ["var(--ax-bad)", "var(--ax-bad)"];
  if (p >= 100 || status === "done" || status === "passed") return ["var(--ax-ok)", "#5eead4"];
  if (status === "review" || status === "waiting_user") return ["var(--ax-warn)", "#fde68a"];
  return ["var(--ax-info)", "var(--ax-accent2)"];
}
export function useCountUp(target: number, ms = 900): number {
  const reduce = useReducedMotion();
  const [v, setV] = useState(reduce ? target : 0);
  useEffect(() => {
    if (reduce || document.documentElement.dataset.axMotion === "off") { setV(target); return; }
    let raf = 0; const t0 = performance.now(), from = 0;
    const step = (t: number) => { const k = Math.min(1, (t - t0) / ms); const e = 1 - (1 - k) ** 3; setV(from + (target - from) * e); if (k < 1) raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step); return () => cancelAnimationFrame(raf);
  }, [target, ms, reduce]);
  return v;
}
export function Count({ value, decimals = 0, prefix = "", suffix = "" }: { value: number; decimals?: number; prefix?: string; suffix?: string }) {
  const v = useCountUp(value);
  return <span className="ax-num">{prefix}{v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>;
}
export function Kpi({ icon: I, c, value, label, delta, decimals, prefix, suffix, extra, onClick, i = 0, help, sample }: {
  icon: LucideIcon; c: string; value: number; label: string; delta?: ReactNode; decimals?: number; prefix?: string; suffix?: string; extra?: ReactNode; onClick?: () => void; i?: number; help?: string; sample?: boolean;
}) {
  const liveData = useStore((s) => s.dataMode === "live");
  return (
    <motion.button type="button" className="ax-kpi" onClick={onClick} style={{ "--c": c } as CSSProperties} aria-label={`${label}: ${prefix ?? ""}${value}${suffix ?? ""}`}
      data-tip={help} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 + i * .06 }} whileHover={{ y: -2, scale: 1.02 }} whileTap={{ scale: .97 }}>
      <motion.span className="ax-kpi-ic" animate={{ boxShadow: ["0 0 0px transparent", `0 0 16px ${c}`, "0 0 0px transparent"] }} transition={{ duration: 3.2, repeat: Infinity, delay: i * .4 }}>
        <I size={22} aria-hidden />
      </motion.span>
      <span style={{ minWidth: 0 }}>
        <b><Count value={value} decimals={decimals} prefix={prefix} suffix={suffix} /></b>
        <span className="lbl">{label}</span>
        {sample && liveData ? <small><SampleMark /></small> : delta && !liveData && <small>{delta}</small>}
        {extra}
      </span>
    </motion.button>
  );
}

/* ============ SVG gauge + donut (animated) ============ */
export function Gauge({ value, size = 104, stroke = 10, label, c1 = "var(--ax-ok)", c2 = "var(--ax-accent2)", suffix = "%", center }: { value: number; size?: number; stroke?: number; label?: string; c1?: string; c2?: string; suffix?: string; center?: ReactNode }) {
  const r = (size - stroke) / 2, C = 2 * Math.PI * r, id = useId().replace(/:/g, "");
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }} role="img" aria-label={`${label ?? "Value"} ${value}${suffix}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs><linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor={c1} /><stop offset="100%" stopColor={c2} /></linearGradient></defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--ax-border)" strokeWidth={stroke} opacity={.5} />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#g${id})`} strokeWidth={stroke} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`} strokeDasharray={C} initial={{ strokeDashoffset: C }} animate={{ strokeDashoffset: C * (1 - value / 100) }}
          transition={{ duration: 1.2, ease: [.2, .8, .2, 1] }} style={{ filter: "drop-shadow(0 0 calc(6px * var(--ax-glow-k)) var(--ax-ok))" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
        {center ?? <div><b style={{ fontSize: size * .24, fontWeight: 750 }}><Count value={value} suffix={suffix} /></b>{label && <div className="ax-xs ax-muted">{label}</div>}</div>}
      </div>
    </div>
  );
}
export function Donut({ parts, size = 110, stroke = 14, center, label }: { parts: { label: string; value: number; c: string }[]; size?: number; stroke?: number; center?: ReactNode; label: string }) {
  const r = (size - stroke) / 2, C = 2 * Math.PI * r, total = parts.reduce((s, p) => s + p.value, 0) || 1;
  let acc = 0;
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }} role="img" aria-label={`${label}: ${parts.map((p) => `${p.label} ${p.value}`).join(", ")}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--ax-border)" strokeWidth={stroke} opacity={.35} />
        {parts.map((p, ix) => {
          const len = (p.value / total) * C, off = acc; acc += len;
          return <motion.circle key={p.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.c} strokeWidth={stroke}
            transform={`rotate(-90 ${size / 2} ${size / 2})`} strokeDasharray={`${Math.max(0, len - 1.5)} ${C}`} initial={{ strokeDashoffset: C, opacity: 0 }}
            animate={{ strokeDashoffset: -off, opacity: 1 }} transition={{ duration: .9, delay: ix * .08, ease: [.2, .8, .2, 1] }}>
            <title>{`${p.label}: ${p.value}`}</title></motion.circle>;
        })}
      </svg>
      {center && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center", lineHeight: 1.1 }}>{center}</div>}
    </div>
  );
}
export function Legend({ items }: { items: { label: string; value?: ReactNode; c: string }[] }) {
  return <div className="ax-legend">{items.map((it, ix) => (
    <motion.div key={it.label} className="ax-flex" initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .1 + ix * .05 }}>
      <span style={{ "--c": it.c } as CSSProperties}><i /></span><span className="ax-spacer" style={{ flex: 1 }}>{it.label}</span><b className="ax-num">{it.value}</b>
    </motion.div>))}</div>;
}

/* ============ switch ============ */
export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <motion.button type="button" role="switch" aria-checked={on} aria-label={label} data-tip={label} className="ax-switch" disabled={disabled} onClick={() => onChange(!on)} whileTap={{ scale: .9 }}>
      <motion.i layout transition={{ type: "spring", stiffness: 600, damping: 30 }} style={{ left: on ? 19 : 2 }} />
    </motion.button>
  );
}

/* ============ list row helper with stagger ============ */
export function Row({ children, i = 0, sel, onClick, className = "", label }: { children: ReactNode; i?: number; sel?: boolean; onClick?: () => void; className?: string; label?: string }) {
  return (
    <motion.div className={`ax-row ${onClick ? "click" : ""} ${sel ? "sel" : ""} ${className}`} onClick={onClick}
      role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined} aria-label={label} aria-pressed={onClick ? !!sel : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i, 12) * .035 }} whileHover={onClick ? { x: 2 } : undefined} layout="position">
      {children}
    </motion.div>
  );
}

/* ============ modal ============ */
export function Modal({ open, onClose, title, icon: I, children, foot, width, label }: { open: boolean; onClose: () => void; title: ReactNode; icon?: LucideIcon; children: ReactNode; foot?: ReactNode; width?: number; label?: string }) {
  const box = useRef<HTMLDivElement>(null);
  // the latest onClose without re-running the focus effect on every parent render (review #1, #3)
  const closeRef = useRef(onClose); closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => {
      const b = box.current; if (!b) return;
      const first = b.querySelector<HTMLElement>("input, textarea, select, button:not(.ax-modal-x)") ?? b.querySelector<HTMLElement>("button, [href], [tabindex]:not([tabindex='-1'])");
      (first ?? b).focus();
    }, 60);
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); }
      if (e.key === "Tab" && box.current) { // keep focus inside
        const f = [...box.current.querySelectorAll<HTMLElement>("button, [href], input, textarea, select, [tabindex]:not([tabindex='-1'])")].filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return; const first = f[0], last = f[f.length - 1];
        if (!box.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; } // recover escaped focus (#21)
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    return () => { window.clearTimeout(t); document.removeEventListener("keydown", key); prev?.focus?.(); };
  }, [open]);
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="ax-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
          <motion.div ref={box} tabIndex={-1} className="ax-modal" role="dialog" aria-modal="true" aria-label={label ?? (typeof title === "string" ? title : "Dialog")} style={{ width: width ? `min(${width}px, calc(100vw - 32px))` : undefined }}
            initial={{ opacity: 0, y: 24, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12, scale: .98 }} transition={{ type: "spring", stiffness: 380, damping: 32 }}>
            <div className="ax-modal-head">{I && <I size={20} className="ax-gold" aria-hidden />}<h2>{title}</h2><span className="ax-spacer" />
              <IconBtn icon={X} label="Close" tone="ghost" className="ax-modal-x" onClick={onClose} /></div>
            <div className="ax-modal-body">{children}</div>
            {foot && <div className="ax-modal-foot">{foot}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>, document.body);
}

/* ============ toasts ============ */
type ToastT = { id: number; text: string; kind: "ok" | "info" | "warn" | "bad" };
const ToastCtx = createContext<(text: string, kind?: ToastT["kind"]) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<ToastT[]>([]);
  const push = useCallback((text: string, kind: ToastT["kind"] = "ok") => {
    const id = Date.now() + Math.random(); setList((l) => [...l.slice(-3), { id, text, kind }]);
    window.setTimeout(() => setList((l) => l.filter((t) => t.id !== id)), 3200);
  }, []);
  const ic = { ok: CheckCircle2, info: CircleDot, warn: AlertTriangle, bad: XCircle };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="ax-toasts" role="status" aria-live="polite">
          <AnimatePresence>{list.map((t) => { const I = ic[t.kind]; return (
            <motion.div key={t.id} className="ax-toast" layout initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }}>
              <I size={16} className={`ax-${t.kind === "info" ? "gold" : t.kind}`} aria-hidden />{t.text}
            </motion.div>); })}</AnimatePresence>
        </div>, document.body)}
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ============ copy (icon only, CTRL-06) ============ */
export function CopyBtn({ text, label = "Copy", size = "sm" }: { text: string; label?: string; size?: "sm" | "md" }) {
  const toast = useToast(); const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch {
      const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } finally { ta.remove(); }
    }
    setDone(true); toast("Copied to clipboard"); window.setTimeout(() => setDone(false), 1400);
  };
  return <IconBtn icon={done ? Check : Copy} label={label} size={size} tone="ghost" onClick={copy} />;
}

/* ============ empty / sample ============ */
// Marks an illustrative constant while the page otherwise shows live AXoR data (advisor review: fabricated figures).
export function SampleMark() {
  const live = useStore((s) => s.dataMode === "live");
  if (!live) return null;
  return <span className="ax-sample" style={{ padding: "0 6px", fontSize: 10, marginLeft: 4 }} tabIndex={0} data-tip="Illustrative sample value: not connected to live data yet">sample</span>;
}
export function Empty({ icon: I = CircleDashed, title, children, action }: { icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <motion.div className="ax-empty" initial={{ opacity: 0, scale: .96 }} animate={{ opacity: 1, scale: 1 }}>
      <motion.span animate={{ y: [0, -4, 0] }} transition={{ duration: 2.4, repeat: Infinity }}><I size={30} aria-hidden /></motion.span>
      <b style={{ color: "var(--ax-text)" }}>{title}</b>{children && <span className="ax-small">{children}</span>}{action}
    </motion.div>
  );
}
export function Skeleton({ h = 14, w = "100%" }: { h?: number; w?: number | string }) { return <div className="ax-skel" style={{ height: h, width: w }} aria-hidden />; }

export function fmtTime(iso: string, withDate = false): string {
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso;
  return withDate ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
    : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}
export function tzTitle(iso: string): string {
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso;
  return `${d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "long" })} (${Intl.DateTimeFormat().resolvedOptions().timeZone})`;
}
export function Time({ iso, withDate }: { iso: string; withDate?: boolean }) {
  return <time dateTime={iso} title={tzTitle(iso)} className="ax-num">{fmtTime(iso, withDate)}</time>;
}
