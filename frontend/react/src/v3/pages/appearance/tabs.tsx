import { useEffect, useRef, useState, type CSSProperties } from "react";
import { motion } from "framer-motion";
import {
  Accessibility, AlertTriangle, Sparkles, Check, CheckCircle2, Circle, Download, FileJson, Info, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Redo2, RotateCcw, Square,
  Sun, Type, Undo2, Upload, XCircle, Ban, Building2, Layers3, Gauge as GaugeIc, Hash, MousePointerClick,
} from "lucide-react";
import { Btn, IconBtn, Pill, Seg, useToast } from "../../ui/kit";
import { Avatar, ROLES, type Role } from "../../ui/Avatar";
import { useTheme } from "../../theme/ThemeContext";
import { DEFAULT_APPEARANCE, PRESETS, STYLES, contrast, sanitizeAppearance, styleDef, tokens, type Appearance, type Density, type IconShape, type Mode, type Preset } from "../../theme/themes";
import { Card, ToggleRow, grid } from "../settings/parts";

const presetAppearance = (p: Preset): Appearance => ({ ...DEFAULT_APPEARANCE, style: p.style, mode: p.mode });
const presetMode = (p: Preset): Mode => (p.mode === "system" ? styleDef(p.style).defaultMode : p.mode);

/* ---------------- Themes ---------------- */
export function ThemesTab() {
  const { appearance, set, setPreview, undo, canUndo, reset, saved } = useTheme();
  const toast = useToast();
  useEffect(() => () => setPreview(null), [setPreview]);
  const isActive = (p: Preset) => appearance.style === p.style && appearance.mode === p.mode;
  const apply = (p: Preset) => { setPreview(null); set({ style: p.style, mode: p.mode, accent: null }); toast(`Theme applied: ${p.label}`); };
  const flavour: Record<string, string> = { luxury: "Luxury", luminous: "Luminous", classic: "Classic", flat: "Flat", pretty: "Pretty", fancy: "Fancy", sakura: "Pretty", renaissance: "Fancy" };
  return (
    <div className="ax-col" style={{ height: "100%" }}>
      <div className="ax-flex">
        <span className="ax-small ax-muted">Hover a look to preview it, click to apply. Every tile is drawn with that look's own colours.</span>
        <span className="ax-spacer" />
        <Pill c={saved === "server" ? "var(--ax-ok)" : saved === "error" ? "var(--ax-bad)" : "var(--ax-info)"} icon={saved === "error" ? XCircle : Check}>{saved === "server" ? "Saved to your account" : saved === "saving" ? "Saving..." : saved === "error" ? "Not saved: this browser blocks storage" : "Saved on this device"}</Pill>
        <IconBtn icon={Undo2} label="Undo last change" disabled={!canUndo} onClick={undo} />
        <IconBtn icon={RotateCcw} label="Reset to the default look" onClick={() => { reset(); toast("Appearance reset to Dark Luxury", "info"); }} />
        <IconBtn icon={Download} label="Export appearance JSON" onClick={() => { exportJson(appearance); toast("Exported appearance.json"); }} />
      </div>
      <div style={grid("repeat(5, 1fr)", { gridAutoRows: "minmax(0, 178px)" })}>
        {PRESETS.map((p, i) => {
          const a = presetAppearance(p), m = presetMode(p), vars = tokens(a, m) as CSSProperties, on = isActive(p);
          return (
            <motion.button key={p.id} type="button" aria-pressed={on} aria-label={`${p.label}${on ? " (current)" : ""}`}
              onMouseEnter={() => setPreview({ ...appearance, style: p.style, mode: p.mode, accent: null })} onMouseLeave={() => setPreview(null)}
              onFocus={() => setPreview({ ...appearance, style: p.style, mode: p.mode, accent: null })} onBlur={() => setPreview(null)} onClick={() => apply(p)}
              initial={{ opacity: 0, scale: .94 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * .04 }} whileHover={{ y: -3, scale: 1.02 }} whileTap={{ scale: .97 }}
              style={{ ...vars, cursor: "pointer", textAlign: "left", padding: 8, display: "flex", flexDirection: "column", gap: 6, minHeight: 0, position: "relative",
                background: "linear-gradient(135deg, var(--ax-bg), var(--ax-bg2))", color: "var(--ax-text)", borderRadius: "var(--ax-radius)", fontFamily: "var(--ax-font)",
                border: `2px solid ${on ? "var(--ax-accent)" : "var(--ax-border)"}`, boxShadow: on ? "0 0 14px var(--ax-glow)" : undefined } as CSSProperties}>
              {on && <span style={{ position: "absolute", top: 5, right: 5, background: "var(--ax-accent)", color: "var(--ax-on-accent)", borderRadius: 999, width: 18, height: 18, display: "grid", placeItems: "center" }}><Check size={12} aria-hidden /></span>}
              <div style={{ display: "flex", gap: 5, flex: 1, minHeight: 0 }}>
                <div style={{ width: 14, borderRadius: "var(--ax-radius-sm)", background: "var(--ax-panel2)", border: "1px solid var(--ax-border)", display: "flex", flexDirection: "column", gap: 3, padding: 2 }}>
                  {[0, 1, 2].map((k) => <i key={k} style={{ height: 5, borderRadius: 2, background: k === 0 ? "var(--ax-accent)" : "var(--ax-faint)" }} />)}</div>
                <div style={{ flex: 1, minWidth: 0, borderRadius: "var(--ax-radius-sm)", background: "var(--ax-panel)", border: "1px solid var(--ax-border)", padding: 5, display: "flex", flexDirection: "column", gap: 4 }}>
                  <b style={{ fontSize: 10, fontFamily: "var(--ax-font-display)", color: "var(--ax-text)" }}>{p.label}</b>
                  <i style={{ height: 3, width: "70%", borderRadius: 2, background: "var(--ax-muted)" }} />
                  <div style={{ display: "flex", gap: 3, marginTop: "auto" }}>
                    <i style={{ height: 9, width: 24, borderRadius: 4, background: "var(--ax-accent)" }} />
                    {["ok", "warn", "bad", "info"].map((s) => <i key={s} style={{ height: 9, width: 9, borderRadius: 9, background: `var(--ax-${s})` }} />)}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ fontSize: 11.5, fontWeight: 700, flex: 1 }}>{p.label}</span>
                <span style={{ fontSize: 10, color: "var(--ax-muted)" }}>{m === "dark" ? <Moon size={11} aria-label="dark" /> : <Sun size={11} aria-label="light" />}</span>
              </div>
              <span style={{ fontSize: 10, color: "var(--ax-muted)", marginTop: -3 }}>{flavour[p.style]} · {p.spec ? "spec preset" : "reference look"}</span>
            </motion.button>
          );
        })}
      </div>
      <div className="ax-tile" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Sparkles size={20} className="ax-gold" aria-hidden />
        <span style={{ flex: 1 }}><b className="ax-small">Current look: {styleDef(appearance.style).label} · {appearance.mode}{appearance.accent ? ` · accent ${appearance.accent}` : ""}</b>
          <span className="ax-xs ax-muted" style={{ display: "block" }}>{styleDef(appearance.style).blurb}</span></span>
        <span className="ax-xs ax-muted">{STYLES.length} styles x light / dark: every style works in both modes (Colors tab).</span>
      </div>
    </div>
  );
}

function exportJson(a: Appearance) {
  const blob = new Blob([JSON.stringify(a, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob), el = document.createElement("a");
  el.href = url; el.download = "axor-appearance.json"; el.click(); setTimeout(() => URL.revokeObjectURL(url), 500);
}

/* ---------------- Colors ---------------- */
const EXTRA = ["#ef4444", "#10b981", "#f97316", "#06b6d4"];
function Ratio({ label, a, b }: { label: string; a: string; b: string }) {
  const r = contrast(a, b), lvl = r >= 7 ? "AAA" : r >= 4.5 ? "AA" : r >= 3 ? "AA large / UI only" : "Fails";
  const I = r >= 4.5 ? CheckCircle2 : r >= 3 ? AlertTriangle : XCircle, c = r >= 4.5 ? "var(--ax-ok)" : r >= 3 ? "var(--ax-warn)" : "var(--ax-bad)";
  return <div className="ax-flex" style={{ fontSize: 12 }}><I size={14} style={{ color: c }} aria-hidden /><span style={{ flex: 1 }}>{label}</span><b className="ax-num">{r.toFixed(2)}:1</b><Pill c={c}>{lvl}</Pill></div>;
}
export function ColorsTab() {
  const { appearance, mode, set } = useTheme();
  const [hex, setHex] = useState(appearance.accent ?? "");
  const s = styleDef(appearance.style), p = s[mode];
  const valid = /^#[0-9a-fA-F]{6}$/.test(hex);
  const accent = valid ? hex : p.accent.startsWith("#") ? p.accent : "#3b82f6";
  const on = tokens({ ...appearance, accent: valid ? hex : appearance.accent }, mode)["--ax-on-accent"];
  const swatches = [...s.accents, ...EXTRA];
  const modes: { id: Appearance["mode"]; label: string; icon: typeof Sun; hint: string }[] = [
    { id: "light", label: "Bright", icon: Sun, hint: "Light mode" }, { id: "dark", label: "Dark", icon: Moon, hint: "Dark mode" }, { id: "system", label: "System", icon: Monitor, hint: "Follows your OS" }];
  const bg = p.bg;
  return (
    <div style={grid("1fr 1fr", { height: "100%", gridTemplateRows: "auto 1fr" })}>
      <Card i={0} title="Theme mode" icon={Sun} help="Bright, Dark, or System (follows your operating system). Every style has both palettes.">
        <div style={grid("repeat(3, 1fr)")}>
          {modes.map((m) => { const I = m.icon, act = appearance.mode === m.id; return (
            <motion.button key={m.id} type="button" className="ax-tile click" aria-pressed={act} onClick={() => set({ mode: m.id })} whileHover={{ y: -2 }} whileTap={{ scale: .96 }}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, borderColor: act ? "var(--ax-accent)" : undefined, color: "var(--ax-text)", cursor: "pointer", fontFamily: "inherit" }}>
              <I size={20} aria-hidden /><b style={{ fontSize: 12.5 }}>{m.label}</b><span className="ax-xs ax-muted">{m.hint}</span>{act && <Check size={13} className="ax-gold" aria-label="selected" />}
            </motion.button>); })}
        </div>
      </Card>
      <Card i={1} title="Accent colour" icon={Hash} help={{ body: "The accent marks selected tabs, primary buttons and focus. The contrast check uses the WCAG formula: 4.5:1 for normal text, 3:1 for large text and icons.", source: "WCAG 2.2 success criterion 1.4.3" }}>
        <div className="ax-flex" style={{ flexWrap: "wrap", gap: 8 }}>
          <motion.button type="button" aria-label="Theme default accent" aria-pressed={!appearance.accent} onClick={() => { setHex(""); set({ accent: null }); }} whileHover={{ scale: 1.12 }} whileTap={{ scale: .9 }}
            className="ax-ib" style={{ width: 30, height: 30, borderRadius: 999, borderColor: !appearance.accent ? "var(--ax-accent)" : undefined }} data-tip="Theme default"><Layers3 size={14} aria-hidden /></motion.button>
          {swatches.map((c) => (
            <motion.button key={c} type="button" aria-label={`Accent ${c}`} aria-pressed={appearance.accent === c} data-tip={c} onClick={() => { setHex(c); set({ accent: c }); }} whileHover={{ scale: 1.15 }} whileTap={{ scale: .9 }}
              style={{ width: 30, height: 30, borderRadius: 999, background: c, cursor: "pointer", display: "grid", placeItems: "center", border: `2px solid ${appearance.accent === c ? "var(--ax-text)" : "var(--ax-border)"}` }}>
              {appearance.accent === c && <Check size={14} color={contrast(c, "#000000") > contrast(c, "#ffffff") ? "#000" : "#fff"} aria-hidden />}</motion.button>))}
        </div>
        <div className="ax-flex">
          <input type="color" aria-label="Pick a custom accent" value={valid ? hex : accent} onChange={(e) => setHex(e.target.value)} style={{ width: 34, height: 30, border: "none", background: "none", padding: 0 }} />
          <input className="ax-input" aria-label="Custom accent hex" placeholder="#RRGGBB" value={hex} onChange={(e) => setHex(e.target.value)} style={{ width: 110 }} aria-invalid={hex !== "" && !valid} />
          <Btn tone="gold" icon={Check} disabled={!valid} onClick={() => set({ accent: hex.toLowerCase() })}>Apply</Btn>
          {hex !== "" && !valid && <span className="ax-xs ax-bad">Use six hex digits, e.g. #22d3ee</span>}
        </div>
        <Ratio label={`Text on accent (${on})`} a={accent} b={on} />
        <Ratio label="Accent on page background" a={accent} b={bg} />
        {contrast(accent, bg) < 3 && <span className="ax-xs ax-warn">Low contrast: this accent may be hard to see on {mode} backgrounds. Pick a lighter or darker shade.</span>}
      </Card>
      <Card i={2} title="Status colours" icon={Info} style={{ gridColumn: "1 / -1" }} help="Status is never shown by colour alone: each state has an icon and a word. These colours are fixed per mode so that meaning stays the same in every theme.">
        <div style={grid("repeat(6, 1fr)")}>
          {([["ok", "Success / passed", CheckCircle2], ["info", "Running / info", Info], ["warn", "Needs you / warning", AlertTriangle], ["bad", "Failed / error", XCircle], ["blocked", "Blocked", Ban], ["neutral", "Paused / idle", Circle]] as const).map(([k, l, I], i) => (
            <motion.div key={k} className="ax-tile" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .04 }} style={{ borderColor: `var(--ax-${k})`, display: "flex", flexDirection: "column", gap: 3 }}>
              <span className="ax-flex" style={{ color: `var(--ax-${k})` }}><I size={16} aria-hidden /><b style={{ fontSize: 12 }}>{l}</b></span>
              <span className="ax-mono ax-xs">{p[k]}</span><span className="ax-xs ax-muted">{contrast(p[k].startsWith("#") ? p[k] : "#888888", bg).toFixed(1)}:1 on background</span>
            </motion.div>))}
        </div>
      </Card>
    </div>
  );
}

/* ---------------- Typography ---------------- */
const FONTS: { id: Appearance["fontFamily"]; label: string; css: string; note: string }[] = [
  { id: "theme", label: "Theme default", css: "var(--ax-font)", note: "Each look brings its own font pairing" },
  { id: "inter", label: "Inter", css: `"Inter Variable", Inter, sans-serif`, note: "Neutral, very readable UI sans" },
  { id: "system", label: "System UI", css: "system-ui, sans-serif", note: "Your device's own font" },
  { id: "serif", label: "Serif", css: "Georgia, serif", note: "Classic, editorial" },
  { id: "mono", label: "Monospace", css: `"JetBrains Mono", ui-monospace, monospace`, note: "Technical, fixed width" },
];
export function TypographyTab() {
  const { appearance, set } = useTheme();
  return (
    <div style={grid("1.3fr 1fr", { height: "100%" })}>
      <Card i={0} title="Font family" icon={Type} help="Applies to all pages. The theme default keeps each look's heading font (for example Cinzel in Dark Luxury).">
        <div className="ax-col" style={{ gap: 6 }}>
          {FONTS.map((f, i) => { const on = appearance.fontFamily === f.id; return (
            <motion.button key={f.id} type="button" className="ax-tile click" aria-pressed={on} onClick={() => set({ fontFamily: f.id })} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }} whileHover={{ x: 3 }}
              style={{ display: "flex", alignItems: "center", gap: 10, textAlign: "left", fontFamily: f.css, color: "var(--ax-text)", cursor: "pointer", borderColor: on ? "var(--ax-accent)" : undefined }}>
              <b style={{ fontSize: 22, width: 36 }}>Aa</b><span style={{ flex: 1 }}><b style={{ fontSize: 13 }}>{f.label}</b><span className="ax-xs ax-muted" style={{ display: "block", fontFamily: "var(--ax-font)" }}>{f.note}</span></span>
              {on && <Check size={15} className="ax-gold" aria-label="selected" />}
            </motion.button>); })}
        </div>
      </Card>
      <Card i={1} title="Text size" icon={Type} help="Scales all text from 90% to 120%. Use 110-120% for easier reading; the layout adapts without breaking.">
        <div className="ax-flex"><span className="ax-small">90%</span>
          <input type="range" className="ax-range" min={90} max={120} step={5} value={appearance.fontScale} aria-label="Text scale percent" onChange={(e) => set({ fontScale: +e.target.value })} />
          <span className="ax-small">120%</span><b className="ax-num" style={{ minWidth: 44 }}>{appearance.fontScale}%</b></div>
        <div className="ax-tile" style={{ lineHeight: 1.5 }}>
          <b style={{ fontSize: 15, fontFamily: "var(--ax-font-display)" }}>Mission M-001 needs your decision</b>
          <p className="ax-small ax-muted" style={{ margin: "4px 0" }}>The release candidate passed 124 of 126 checks. Two Safari end-to-end tests were quarantined; review the evidence before approving.</p>
          <span className="ax-xs ax-faint">Caption text · updated 4 min ago</span>
        </div>
        <Seg label="Quick text size" value={String(appearance.fontScale)} onChange={(v) => set({ fontScale: +v })} items={[{ id: "90", label: "90" }, { id: "100", label: "100" }, { id: "110", label: "110" }, { id: "120", label: "120" }]} />
      </Card>
    </div>
  );
}

/* ---------------- Layout ---------------- */
export function LayoutTab() {
  const { appearance, set } = useTheme();
  const dens: { id: Density; label: string; hint: string; rows: number }[] = [
    { id: "ultra", label: "Ultra-compact", hint: "Most data on one screen", rows: 6 }, { id: "compact", label: "Compact", hint: "Default balance", rows: 4 }, { id: "comfortable", label: "Comfortable", hint: "Roomy and relaxed", rows: 3 }];
  return (
    <div style={grid("1.4fr 1fr", { height: "100%", gridTemplateRows: "1fr auto" })}>
      <Card i={0} title="Density" icon={Layers3} help="Controls padding and text size across every page. Ultra-compact fits the most information without scrolling.">
        <div style={grid("repeat(3, 1fr)", { flex: 1 })}>
          {dens.map((d, i) => { const on = appearance.density === d.id; return (
            <motion.button key={d.id} type="button" className="ax-tile click" aria-pressed={on} onClick={() => set({ density: d.id })} whileHover={{ y: -2 }} whileTap={{ scale: .96 }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * .05 }}
              style={{ display: "flex", flexDirection: "column", gap: 6, color: "var(--ax-text)", cursor: "pointer", textAlign: "left", borderColor: on ? "var(--ax-accent)" : undefined, fontFamily: "inherit" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: d.rows === 6 ? 2 : d.rows === 4 ? 4 : 7, flex: 1, justifyContent: "center" }}>
                {Array.from({ length: d.rows }).map((_, k) => <i key={k} style={{ height: d.rows === 6 ? 5 : d.rows === 4 ? 7 : 9, borderRadius: 3, background: k === 0 ? "var(--ax-accent)" : "var(--ax-border)" }} />)}</div>
              <b style={{ fontSize: 12.5 }}>{d.label} {on && <Check size={12} className="ax-gold" aria-label="selected" />}</b><span className="ax-xs ax-muted">{d.hint}</span>
            </motion.button>); })}
        </div>
      </Card>
      <Card i={1} title="Sidebar" icon={PanelLeftClose} help="Expanded shows icons with names; collapsed shows icons only and gives pages more width.">
        <div className="ax-col" style={{ gap: 6 }}>
          {([["expanded", "Expanded (icons + names)", PanelLeftOpen], ["collapsed", "Collapsed (icons only)", PanelLeftClose]] as const).map(([id, l, I]) => (
            <motion.button key={id} type="button" className="ax-tile click" aria-pressed={appearance.sidebar === id} onClick={() => set({ sidebar: id })} whileHover={{ x: 3 }}
              style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--ax-text)", cursor: "pointer", borderColor: appearance.sidebar === id ? "var(--ax-accent)" : undefined, fontFamily: "inherit" }}>
              <I size={18} aria-hidden /><b style={{ fontSize: 12.5, flex: 1, textAlign: "left" }}>{l}</b>{appearance.sidebar === id && <Check size={14} className="ax-gold" aria-label="selected" />}</motion.button>))}
        </div>
      </Card>
      <Card i={2} title="One screen, no scrolling" icon={Monitor} style={{ gridColumn: "1 / -1" }} help="Design rule from the owner: every page fits one screen at 1600x900 and above. Only long lists scroll inside their own panel.">
        <span className="ax-small ax-muted">AXoR pages are laid out to fit the whole screen at 1600x900 and larger. Tables, logs and chat scroll inside their own panel, never the page. Ultra-compact density and a collapsed sidebar give you the most room on smaller displays.</span>
      </Card>
    </div>
  );
}

/* ---------------- Icons & Avatars ---------------- */
export function IconsTab() {
  const { appearance, set } = useTheme();
  const shapes: { id: IconShape; label: string; r: string }[] = [{ id: "rounded", label: "Rounded", r: "10px" }, { id: "circle", label: "Circle", r: "999px" }, { id: "square", label: "Square", r: "3px" }];
  const roles = Object.keys(ROLES) as Role[];
  return (
    <div style={grid("1fr 1.6fr", { height: "100%" })}>
      <div className="ax-col">
        <Card i={0} title="Icon shape" icon={Square} help="The container shape behind icon buttons and avatars.">
          <div style={grid("repeat(3, 1fr)")}>
            {shapes.map((s) => (
              <motion.button key={s.id} type="button" className="ax-tile click" aria-pressed={appearance.iconShape === s.id} onClick={() => set({ iconShape: s.id })} whileHover={{ y: -2 }} whileTap={{ scale: .95 }}
                style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5, color: "var(--ax-text)", cursor: "pointer", borderColor: appearance.iconShape === s.id ? "var(--ax-accent)" : undefined, fontFamily: "inherit" }}>
                <span style={{ width: 34, height: 34, borderRadius: s.r, border: "2px solid var(--ax-accent)", display: "grid", placeItems: "center", color: "var(--ax-accent)" }}><MousePointerClick size={16} aria-hidden /></span>
                <b className="ax-small">{s.label}</b></motion.button>))}
          </div>
        </Card>
        <Card i={1} title="Avatar pack" icon={GaugeIc} help="Robots: friendly robot faces with a role emblem (default). Glyphs: a clean emblem only. A custom avatar never changes who an agent is.">
          <div style={grid("1fr 1fr")}>
            {(["robots", "glyphs"] as const).map((k) => (
              <motion.button key={k} type="button" className="ax-tile click" aria-pressed={appearance.avatarPack === k} onClick={() => set({ avatarPack: k })} whileHover={{ y: -2 }}
                style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--ax-text)", cursor: "pointer", borderColor: appearance.avatarPack === k ? "var(--ax-accent)" : undefined, fontFamily: "inherit" }}>
                <PackPreview pack={k} /><b className="ax-small" style={{ textTransform: "capitalize" }}>{k}</b>{appearance.avatarPack === k && <Check size={13} className="ax-gold" aria-label="selected" />}</motion.button>))}
          </div>
        </Card>
      </div>
      <Card i={2} title="Role avatars and their meaning" icon={Building2} help="Each agent's default picture shows what it does: the emblem is the meaning. Screen readers hear the role name.">
        <div style={grid("repeat(2, 1fr)", { gap: 6 })}>
          {roles.map((r, i) => (
            <motion.div key={r} className="ax-flex" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .025 }} whileHover={{ x: 2 }}
              style={{ padding: "4px 6px", border: "1px solid var(--ax-border)", borderRadius: "var(--ax-radius-sm)" }}>
              <Avatar role={r} size={32} name={ROLES[r].label} /><span style={{ minWidth: 0 }}><b className="ax-small">{ROLES[r].label}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{ROLES[r].emblem}</span></span></motion.div>))}
        </div>
      </Card>
    </div>
  );
}
function PackPreview({ pack }: { pack: "robots" | "glyphs" }) {
  const { appearance, set, setPreview } = useTheme(); void set; void setPreview;
  return <span style={{ display: "flex", gap: 3 }}>{(["gm", "developer", "qa"] as Role[]).map((r) => <PackAvatar key={r} r={r} pack={pack} cur={appearance} />)}</span>;
}
function PackAvatar({ r, pack }: { r: Role; pack: "robots" | "glyphs"; cur: Appearance }) {
  if (pack === "glyphs") { const I = ROLES[r].icon; return <span style={{ width: 26, height: 26, display: "grid", placeItems: "center", borderRadius: "var(--ax-icon-radius)", color: ROLES[r].c, border: `1px solid ${ROLES[r].c}`, background: `color-mix(in srgb, ${ROLES[r].c} 14%, transparent)` }}><I size={14} aria-hidden /></span>; }
  return <Avatar role={r} size={26} />;
}

/* ---------------- Accessibility ---------------- */
export function AccessibilityTab() {
  const { appearance, set } = useTheme();
  return (
    <div style={grid("1fr 1fr", { height: "100%", gridTemplateRows: "auto 1fr" })}>
      <Card i={0} title="Contrast and motion" icon={Accessibility} help="High contrast uses pure black/white text and strong borders and turns off glow. Reduced motion stops animations; it also follows your operating system setting automatically.">
        <ToggleRow icon={Sun} label="High contrast" hint="Pure text, strong borders, no glow" on={appearance.highContrast} onChange={(v) => set({ highContrast: v })} />
        <ToggleRow icon={Ban} label="Reduce motion" hint="Same as the OS setting; stops all animation" on={appearance.reducedMotion} onChange={(v) => set({ reducedMotion: v })} />
        <div className="ax-flex"><span style={{ flex: 1, fontSize: 12.5, fontWeight: 600 }}>Motion level</span>
          <Seg label="Motion level" value={appearance.motion} onChange={(v) => set({ motion: v })} items={[{ id: "full", label: "Full" }, { id: "subtle", label: "Subtle" }, { id: "off", label: "Off" }]} /></div>
      </Card>
      <Card i={1} title="Focus ring" icon={MousePointerClick} help="The outline shown when you move through the page with the keyboard (Tab). Bold is easier to see.">
        <Seg label="Focus ring" value={appearance.focusRing} onChange={(v) => set({ focusRing: v })} items={[{ id: "standard", label: "Standard" }, { id: "bold", label: "Bold" }]} />
        <span className="ax-small ax-muted">Try it: press Tab to move to the buttons below.</span>
        <div className="ax-flex"><Btn>First</Btn><Btn>Second</Btn><Btn tone="gold">Third</Btn></div>
      </Card>
      <Card i={2} title="What is always on" icon={CheckCircle2} style={{ gridColumn: "1 / -1" }} help="Accessibility rules that apply in every theme and cannot be switched off.">
        <div style={grid("repeat(3, 1fr)")}>
          {["Status is shown by icon + text + colour, never colour alone", "Every icon-only button has a tooltip and an accessible name", "Tabs and menus work with the keyboard (arrow keys, Enter, Esc)", "Text contrast meets WCAG AA in all 10 looks", "Animations respect your system's reduced-motion setting", "Every ? icon explains a term in plain words"].map((t, i) => (
            <motion.div key={t} className="ax-flex" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * .05 }} style={{ alignItems: "flex-start", fontSize: 12 }}><CheckCircle2 size={14} className="ax-ok" style={{ flex: "none", marginTop: 1 }} aria-hidden />{t}</motion.div>))}
        </div>
      </Card>
    </div>
  );
}

/* ---------------- Presets ---------------- */
export function PresetsTab() {
  const { appearance, replace } = useTheme();
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [report, setReport] = useState<{ name: string; fixed: string[]; next: Appearance } | null>(null);
  const [err, setErr] = useState("");
  const json = JSON.stringify(appearance, null, 2);
  const onFile = async (f: File | undefined) => {
    setErr(""); setReport(null); if (!f) return;
    try {
      if (f.size > 20000) throw new Error("File is too large for an appearance file (max 20 KB).");
      const raw = JSON.parse(await f.text());
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("The file must contain a JSON object.");
      const next = sanitizeAppearance(raw), fixed = (Object.keys(next) as (keyof Appearance)[]).filter((k) => k !== "version" && JSON.stringify((raw as Record<string, unknown>)[k]) !== JSON.stringify(next[k]) && k in raw ? true : k !== "version" && !(k in raw));
      setReport({ name: f.name, fixed: fixed.map(String), next });
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not read the file."); }
    if (file.current) file.current.value = "";
  };
  return (
    <div style={grid("1fr 1fr", { height: "100%" })}>
      <div className="ax-col">
        <Card i={0} title="Export" icon={Download} help="Download your current look as a small JSON file you can share or keep as a backup.">
          <div className="ax-flex"><Btn tone="gold" icon={Download} onClick={() => { exportJson(appearance); toast("Exported axor-appearance.json"); }}>Export JSON</Btn><span className="ax-xs ax-muted">{json.length} bytes</span></div>
          <pre className="ax-mono ax-xs" style={{ margin: 0, padding: 8, borderRadius: 8, border: "1px solid var(--ax-border)", background: "var(--ax-bg)", overflow: "auto", maxHeight: 170 }}>{json}</pre>
        </Card>
      </div>
      <div className="ax-col">
        <Card i={1} title="Import" icon={Upload} help="Choose a JSON file. Unknown fields are dropped and invalid values are replaced by defaults before anything is applied, so a bad file cannot break the UI.">
          <input ref={file} type="file" accept="application/json,.json" hidden onChange={(e) => onFile(e.target.files?.[0])} aria-label="Appearance JSON file" />
          <div className="ax-flex"><Btn icon={FileJson} onClick={() => file.current?.click()}>Choose JSON file</Btn></div>
          {err && <div role="alert" className="ax-flex ax-bad" style={{ fontSize: 12 }}><XCircle size={14} aria-hidden />{err}</div>}
          {report && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="ax-col" style={{ gap: 6 }}>
              <span className="ax-small"><b>{report.name}</b> validated: style <b>{styleDef(report.next.style).label}</b>, mode <b>{report.next.mode}</b>, accent <b>{report.next.accent ?? "theme default"}</b>.</span>
              {report.fixed.length > 0 && <span className="ax-xs ax-warn"><AlertTriangle size={11} aria-hidden /> Corrected or defaulted: {report.fixed.join(", ")}</span>}
              <div className="ax-flex"><Btn tone="gold" icon={Check} onClick={() => { replace(report.next); setReport(null); toast("Imported appearance applied"); }}>Apply</Btn><Btn icon={Redo2} onClick={() => setReport(null)}>Discard</Btn></div>
            </motion.div>)}
        </Card>
        <Card i={2} title="Organization default" icon={Building2} help="Admins can set a default look for the whole organization. Your personal choice always wins for you.">
          <span className="ax-small ax-muted">New members start with the organization default (currently <b style={{ color: "var(--ax-text)" }}>Dark Luxury</b>). Your own appearance is stored per user and overrides it. Setting the organization default requires the admin role in Settings.</span>
        </Card>
      </div>
    </div>
  );
}
