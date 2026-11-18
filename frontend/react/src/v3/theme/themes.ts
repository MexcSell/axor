// AXoR UI v3 appearance system (Appearance Studio, THEME-001..003, UX-THEME-001).
// A look = style (surface treatment: glow, glass, flat…) × mode (light / dark) × accent. Every style ships a
// light and a dark palette, so "Light / Dark / System" works for each. Tokens are applied as CSS variables on
// <html>; nothing here touches stored mission data.

export type Mode = "light" | "dark";
export type ModePref = Mode | "system";
export type StyleId = "luxury" | "luminous" | "classic" | "flat" | "pretty" | "fancy" | "sakura" | "renaissance";
export type Density = "ultra" | "compact" | "comfortable";
export type IconShape = "rounded" | "circle" | "square";

export interface Palette {
  bg: string; bg2: string; panel: string; panel2: string; raised: string;
  border: string; borderStrong: string; text: string; muted: string; faint: string;
  accent: string; accent2: string; onAccent: string; glow: string;
  info: string; ok: string; warn: string; bad: string; blocked: string; neutral: string;
}

export interface StyleDef {
  id: StyleId; label: string; blurb: string; icon: string; defaultMode: Mode;
  radius: number; glow: number; blur: number; gradient: boolean; display: string; body: string;
  light: Palette; dark: Palette; accents: string[];
}

const SANS = `"Inter Variable", "Inter", "Segoe UI", system-ui, -apple-system, sans-serif`;
const STATUS_DARK = { info: "#3b8cff", ok: "#2fd27a", warn: "#f5a524", bad: "#ff4d5e", blocked: "#a97bff", neutral: "#8a93ad" };
const STATUS_LIGHT = { info: "#1f6fe0", ok: "#14935a", warn: "#b86e00", bad: "#d42d3f", blocked: "#7a4fd6", neutral: "#6b7280" };

export const STYLES: StyleDef[] = [
  {
    id: "luxury", label: "Dark Luxury", icon: "crown", defaultMode: "dark",
    blurb: "Midnight navy with gold hairlines and soft glow. The default AXoR look.",
    radius: 12, glow: 1, blur: 10, gradient: true, display: `"Cinzel", "Trajan Pro", Georgia, serif`, body: SANS,
    accents: ["#f2b84b", "#a77bff", "#3b8cff", "#2fd27a"],
    // 30-x reference: panels glow cyan/blue, gold marks what is active/selected.
    dark: { bg: "#050b16", bg2: "#0a1630", panel: "rgba(11,26,51,.82)", panel2: "rgba(8,17,31,.92)", raised: "#0e2038",
      border: "rgba(43,127,255,.42)", borderStrong: "#f2b53a", text: "#ffffff", muted: "#9fb3cf", faint: "#6f86a6",
      accent: "#f2b53a", accent2: "#22d3ee", onAccent: "#1a1203", glow: "rgba(242,181,58,.45)", ...STATUS_DARK },
    light: { bg: "#f7f3ea", bg2: "#ece3cf", panel: "rgba(255,255,255,.92)", panel2: "#fbf8f1", raised: "#ffffff",
      border: "rgba(176,132,44,.35)", borderStrong: "#b0842c", text: "#1c1a14", muted: "#5d574a", faint: "#9a917e",
      accent: "#a8761a", accent2: "#1f6fe0", onAccent: "#ffffff", glow: "rgba(200,150,60,.25)", ...STATUS_LIGHT },
  },
  {
    id: "luminous", label: "Luminous Neon", icon: "sparkles", defaultMode: "dark",
    blurb: "Deep space blue with cyan and violet neon outlines.",
    radius: 12, glow: 1.2, blur: 12, gradient: true, display: SANS, body: SANS,
    accents: ["#22d3ee", "#a855f7", "#3b82f6", "#ec4899"],
    dark: { bg: "#020617", bg2: "#0b1440", panel: "rgba(8,16,44,.82)", panel2: "rgba(12,22,58,.9)", raised: "#111c4a",
      border: "rgba(56,189,248,.35)", borderStrong: "#38bdf8", text: "#e6f6ff", muted: "#93a8c9", faint: "#566a8f",
      accent: "#22d3ee", accent2: "#a855f7", onAccent: "#00141c", glow: "rgba(34,211,238,.45)", ...STATUS_DARK },
    light: { bg: "#eef6ff", bg2: "#e3e9ff", panel: "rgba(255,255,255,.9)", panel2: "#f5f9ff", raised: "#ffffff",
      border: "rgba(14,165,233,.35)", borderStrong: "#0ea5e9", text: "#0b1a33", muted: "#4b5d7a", faint: "#8796ad",
      accent: "#0891b2", accent2: "#7c3aed", onAccent: "#ffffff", glow: "rgba(14,165,233,.3)", ...STATUS_LIGHT },
  },
  {
    id: "classic", label: "Classic", icon: "sun", defaultMode: "light",
    blurb: "Clean white surfaces, crisp blue accent (Classic Light / Midnight Dark).",
    radius: 12, glow: 0, blur: 0, gradient: false, display: SANS, body: SANS,
    accents: ["#2563eb", "#7c3aed", "#0d9488", "#ea580c"],
    light: { bg: "#f4f6fb", bg2: "#eef1f8", panel: "#ffffff", panel2: "#f8fafd", raised: "#ffffff",
      border: "#e3e7f0", borderStrong: "#c9d1e1", text: "#111827", muted: "#4b5565", faint: "#9aa3b2",
      accent: "#2563eb", accent2: "#7c3aed", onAccent: "#ffffff", glow: "rgba(37,99,235,.18)", ...STATUS_LIGHT },
    dark: { bg: "#0b0f19", bg2: "#111827", panel: "#121826", panel2: "#161d2e", raised: "#1b2336",
      border: "#253047", borderStrong: "#33415e", text: "#e8ecf4", muted: "#a2abbd", faint: "#687389",
      accent: "#4f8cff", accent2: "#a78bfa", onAccent: "#ffffff", glow: "rgba(79,140,255,.25)", ...STATUS_DARK },
  },
  {
    id: "flat", label: "Flat Minimal", icon: "square", defaultMode: "light",
    blurb: "Solid panels, no shadows, sharp geometry.",
    radius: 6, glow: 0, blur: 0, gradient: false, display: SANS, body: SANS,
    accents: ["#1d4ed8", "#0f766e", "#b91c1c", "#6d28d9"],
    light: { bg: "#f3f4f6", bg2: "#f3f4f6", panel: "#ffffff", panel2: "#f9fafb", raised: "#ffffff",
      border: "#dfe3ea", borderStrong: "#c3c9d4", text: "#101828", muted: "#475467", faint: "#98a2b3",
      accent: "#1d4ed8", accent2: "#0f766e", onAccent: "#ffffff", glow: "transparent", ...STATUS_LIGHT },
    dark: { bg: "#111316", bg2: "#111316", panel: "#1a1d22", panel2: "#20242a", raised: "#262b33",
      border: "#2e343d", borderStrong: "#3d4550", text: "#eceef1", muted: "#a6adb8", faint: "#6b7380",
      accent: "#3b82f6", accent2: "#14b8a6", onAccent: "#ffffff", glow: "transparent", ...STATUS_DARK },
  },
  {
    id: "pretty", label: "Pretty Pastel", icon: "flower", defaultMode: "light",
    blurb: "Soft lavender and peach surfaces with gentle rounded cards.",
    radius: 18, glow: .4, blur: 8, gradient: true, display: `"Quicksand", "Nunito", ${SANS}`, body: SANS,
    accents: ["#8b6cf6", "#f472b6", "#38bdf8", "#34d399"],
    light: { bg: "#f7f2ff", bg2: "#ffeef5", panel: "rgba(255,255,255,.88)", panel2: "#fbf8ff", raised: "#ffffff",
      border: "#e9defc", borderStrong: "#d4c2fa", text: "#2d2545", muted: "#6c6386", faint: "#a9a1c0",
      accent: "#8b6cf6", accent2: "#f472b6", onAccent: "#ffffff", glow: "rgba(139,108,246,.22)", ...STATUS_LIGHT },
    dark: { bg: "#1b1528", bg2: "#2a1a2e", panel: "rgba(38,29,56,.88)", panel2: "#2e2442", raised: "#352a4d",
      border: "#4a3b69", borderStrong: "#6a55a0", text: "#f5efff", muted: "#bfb2d9", faint: "#7f7399",
      accent: "#b49cff", accent2: "#f9a8d4", onAccent: "#1b1528", glow: "rgba(180,156,255,.3)", ...STATUS_DARK },
  },
  {
    id: "fancy", label: "Fancy Glass", icon: "gem", defaultMode: "dark",
    blurb: "Frosted glass panels over rich violet gradients.",
    radius: 16, glow: .9, blur: 18, gradient: true, display: SANS, body: SANS,
    accents: ["#c084fc", "#f0abfc", "#60a5fa", "#fbbf24"],
    dark: { bg: "#0d0620", bg2: "#2a0d4a", panel: "rgba(40,22,78,.55)", panel2: "rgba(52,30,96,.6)", raised: "rgba(70,40,120,.65)",
      border: "rgba(216,180,254,.28)", borderStrong: "#c084fc", text: "#f7f0ff", muted: "#c7b6e6", faint: "#8a78ad",
      accent: "#c084fc", accent2: "#60a5fa", onAccent: "#1a0933", glow: "rgba(192,132,252,.45)", ...STATUS_DARK },
    light: { bg: "#f3ecff", bg2: "#e4f0ff", panel: "rgba(255,255,255,.6)", panel2: "rgba(255,255,255,.7)", raised: "rgba(255,255,255,.85)",
      border: "rgba(147,51,234,.22)", borderStrong: "#a855f7", text: "#24113f", muted: "#5e4b7d", faint: "#9d8db8",
      accent: "#9333ea", accent2: "#2563eb", onAccent: "#ffffff", glow: "rgba(147,51,234,.25)", ...STATUS_LIGHT },
  },
  {
    id: "sakura", label: "Sakura", icon: "cherry", defaultMode: "light",
    blurb: "Blossom pink and night indigo with gold detail.",
    radius: 14, glow: .6, blur: 10, gradient: true, display: `"Noto Serif JP", Georgia, serif`, body: SANS,
    accents: ["#e86a92", "#d4a24c", "#6d5dd3", "#2f9e8f"],
    light: { bg: "#fff5f7", bg2: "#fde7ee", panel: "rgba(255,255,255,.9)", panel2: "#fff9fa", raised: "#ffffff",
      border: "#f6d3de", borderStrong: "#eaa8bd", text: "#3a1f2b", muted: "#7a5564", faint: "#b897a4",
      accent: "#e05285", accent2: "#c08a2c", onAccent: "#ffffff", glow: "rgba(232,106,146,.22)", ...STATUS_LIGHT },
    dark: { bg: "#100a1c", bg2: "#2a1030", panel: "rgba(30,17,42,.86)", panel2: "rgba(40,22,54,.9)", raised: "#3a2048",
      border: "rgba(232,106,146,.32)", borderStrong: "#d4a24c", text: "#fbeef3", muted: "#d0a9ba", faint: "#8e6b7c",
      accent: "#f08fb0", accent2: "#d4a24c", onAccent: "#2a0d18", glow: "rgba(240,143,176,.35)", ...STATUS_DARK },
  },
  {
    id: "renaissance", label: "Renaissance", icon: "landmark", defaultMode: "light",
    blurb: "Parchment, ink and gilded frames.",
    radius: 8, glow: .3, blur: 0, gradient: true, display: `"Cinzel", "Cormorant Garamond", Georgia, serif`, body: `Georgia, "Times New Roman", serif`,
    accents: ["#9c6b1e", "#7a2e2e", "#2f5d50", "#3b4a7a"],
    light: { bg: "#efe4cc", bg2: "#e2d2ad", panel: "rgba(250,243,226,.92)", panel2: "#f6ecd5", raised: "#fbf4e2",
      border: "#cdb27a", borderStrong: "#9c6b1e", text: "#2b2114", muted: "#5d4c33", faint: "#9a8665",
      accent: "#9c6b1e", accent2: "#7a2e2e", onAccent: "#fff8e8", glow: "rgba(156,107,30,.2)", ...STATUS_LIGHT },
    dark: { bg: "#1a140c", bg2: "#2b2114", panel: "rgba(40,31,19,.9)", panel2: "#30251a", raised: "#3a2d1e",
      border: "#5e4a2c", borderStrong: "#c19a52", text: "#f3e7cc", muted: "#cbb68e", faint: "#8a7656",
      accent: "#d6a957", accent2: "#c26a5a", onAccent: "#1a140c", glow: "rgba(214,169,87,.3)", ...STATUS_DARK },
  },
];

export interface Preset { id: string; label: string; style: StyleId; mode: ModePref; spec?: boolean }
// The six named in the spec's Theme gallery (Classic Light, Midnight Dark, Flat Minimal, Luminous Neon, Pretty
// Pastel, Fancy Glass) plus the looks shown in the reference images (Dark Luxury, Sakura, Renaissance).
export const PRESETS: Preset[] = [
  { id: "dark-luxury", label: "Dark Luxury", style: "luxury", mode: "dark" },
  { id: "classic-light", label: "Classic Light", style: "classic", mode: "light", spec: true },
  { id: "midnight-dark", label: "Midnight Dark", style: "classic", mode: "dark", spec: true },
  { id: "flat-minimal", label: "Flat Minimal", style: "flat", mode: "light", spec: true },
  { id: "luminous-neon", label: "Luminous Neon", style: "luminous", mode: "dark", spec: true },
  { id: "pretty-pastel", label: "Pretty Pastel", style: "pretty", mode: "light", spec: true },
  { id: "fancy-glass", label: "Fancy Glass", style: "fancy", mode: "dark", spec: true },
  { id: "sakura", label: "Sakura", style: "sakura", mode: "light" },
  { id: "sakura-night", label: "Sakura Night", style: "sakura", mode: "dark" },
  { id: "renaissance", label: "Renaissance", style: "renaissance", mode: "light" },
];

export interface Appearance {
  version: 1;
  style: StyleId; mode: ModePref; accent: string | null;
  density: Density; fontScale: number; fontFamily: "theme" | "inter" | "system" | "serif" | "mono";
  sidebar: "expanded" | "collapsed"; iconShape: IconShape;
  highContrast: boolean; reducedMotion: boolean; motion: "full" | "subtle" | "off";
  focusRing: "standard" | "bold"; avatarPack: "robots" | "glyphs";
  // 30-10: Glow Level, Icon Set, Avatar Face Style, Avatar Color Scheme
  glow: number; iconSet: IconSet; avatarFace: AvatarFace; avatarColor: AvatarColor;
}
export type IconSet = "core" | "outline" | "duotone" | "solid" | "neotech";
export type AvatarFace = "classic" | "holographic" | "expressive" | "minimal" | "analytical" | "elite";
export type AvatarColor = "role" | "cyan" | "purple" | "green" | "gold" | "pink";
export const AVATAR_COLORS: Record<Exclude<AvatarColor, "role">, string> = { cyan: "#22d3ee", purple: "#a77bff", green: "#2fd27a", gold: "#f2b53a", pink: "#f472b6" };

export const DEFAULT_APPEARANCE: Appearance = {
  version: 1, style: "luxury", mode: "dark", accent: null, density: "compact", fontScale: 100, fontFamily: "theme",
  sidebar: "expanded", iconShape: "rounded", highContrast: false, reducedMotion: false, motion: "full",
  focusRing: "standard", avatarPack: "robots", glow: 85, iconSet: "core", avatarFace: "classic", avatarColor: "role",
};

export function styleDef(id: StyleId): StyleDef { return STYLES.find((s) => s.id === id) ?? STYLES[0]; }

// Validates an imported / stored appearance object; unknown keys dropped, bad values replaced by defaults.
export function sanitizeAppearance(x: unknown): Appearance {
  const d = DEFAULT_APPEARANCE, o = (x && typeof x === "object" ? x : {}) as Record<string, unknown>;
  const pick = <T,>(k: keyof Appearance, ok: readonly T[]) => (ok.includes(o[k] as T) ? o[k] : d[k]) as T;
  const hex = typeof o.accent === "string" && /^#[0-9a-fA-F]{6}$/.test(o.accent) ? o.accent : null;
  const scale = Number(o.fontScale);
  return {
    version: 1,
    style: pick("style", STYLES.map((s) => s.id)),
    mode: pick("mode", ["light", "dark", "system"] as const),
    accent: hex,
    density: pick("density", ["ultra", "compact", "comfortable"] as const),
    fontScale: Number.isFinite(scale) ? Math.min(120, Math.max(90, Math.round(scale))) : d.fontScale,
    fontFamily: pick("fontFamily", ["theme", "inter", "system", "serif", "mono"] as const),
    sidebar: pick("sidebar", ["expanded", "collapsed"] as const),
    iconShape: pick("iconShape", ["rounded", "circle", "square"] as const),
    highContrast: o.highContrast === true, reducedMotion: o.reducedMotion === true,
    motion: pick("motion", ["full", "subtle", "off"] as const),
    focusRing: pick("focusRing", ["standard", "bold"] as const),
    avatarPack: pick("avatarPack", ["robots", "glyphs"] as const),
    glow: Number.isFinite(Number(o.glow)) && o.glow !== null && o.glow !== "" ? Math.min(100, Math.max(0, Math.round(Number(o.glow)))) : d.glow,
    iconSet: pick("iconSet", ["core", "outline", "duotone", "solid", "neotech"] as const),
    avatarFace: pick("avatarFace", ["classic", "holographic", "expressive", "minimal", "analytical", "elite"] as const),
    avatarColor: pick("avatarColor", ["role", "cyan", "purple", "green", "gold", "pink"] as const),
  };
}

// WCAG relative-luminance contrast ratio between two #rrggbb colours.
export function contrast(a: string, b: string): number {
  const lum = (h: string) => {
    const n = parseInt(h.slice(1), 16), c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
      const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

function solid(c: string, fallback: string) { return /^#[0-9a-fA-F]{6}$/.test(c) ? c : fallback; }

// CSS variables for an appearance in an effective mode.
export function tokens(a: Appearance, mode: Mode): Record<string, string> {
  const s = styleDef(a.style), p = { ...s[mode] };
  if (a.accent) { p.accent = a.accent; p.onAccent = contrast(a.accent, "#000000") > contrast(a.accent, "#ffffff") ? "#0b0b0b" : "#ffffff"; }
  if (a.highContrast) {
    p.text = mode === "dark" ? "#ffffff" : "#000000"; p.muted = mode === "dark" ? "#d6dbe6" : "#26303f";
    p.border = mode === "dark" ? "#9aa4bf" : "#4b5565"; p.panel = mode === "dark" ? "#000000" : "#ffffff"; p.panel2 = p.panel;
  }
  const dens = { ultra: [7, 6, 11.5], compact: [10, 9, 12.5], comfortable: [14, 13, 14] }[a.density];
  const font = { theme: s.body, inter: SANS, system: "system-ui, sans-serif", serif: "Georgia, serif", mono: `"JetBrains Mono", ui-monospace, monospace` }[a.fontFamily];
  const shape = { rounded: `${Math.max(6, s.radius - 4)}px`, circle: "999px", square: "4px" }[a.iconShape];
  return {
    "--ax-bg": p.bg, "--ax-bg2": p.bg2, "--ax-panel": p.panel, "--ax-panel2": p.panel2, "--ax-raised": p.raised,
    "--ax-border": p.border, "--ax-border-strong": p.borderStrong, "--ax-text": p.text, "--ax-muted": p.muted, "--ax-faint": p.faint,
    "--ax-accent": p.accent, "--ax-accent2": p.accent2, "--ax-on-accent": p.onAccent, "--ax-glow": a.highContrast ? "transparent" : p.glow,
    "--ax-info": p.info, "--ax-ok": p.ok, "--ax-warn": p.warn, "--ax-bad": p.bad, "--ax-blocked": p.blocked, "--ax-neutral": p.neutral,
    "--ax-radius": `${s.radius}px`, "--ax-radius-sm": `${Math.max(4, s.radius - 5)}px`, "--ax-icon-radius": shape,
    "--ax-glow-k": String(a.highContrast ? 0 : +(s.glow * (a.glow / 85)).toFixed(3)), "--ax-blur": `${a.highContrast ? 0 : s.blur}px`,
    "--ax-font": font, "--ax-font-display": a.fontFamily === "theme" ? s.display : font,
    "--ax-scale": String(a.fontScale / 100), "--ax-pad": `${dens[0]}px`, "--ax-gap": `${dens[1]}px`, "--ax-fs": `${dens[2]}px`,
    "--ax-accent-solid": solid(p.accent, "#3b82f6"),
    // the existing React pages (Stack / Analytics / Activity) use these names
    "--bg": p.bg, "--surface": solid(p.raised, mode === "dark" ? "#161d2e" : "#ffffff"), "--surface-2": solid(p.raised, mode === "dark" ? "#1b2336" : "#f4f6fb"),
    "--line": solid(p.borderStrong, "#33415e"), "--text": p.text, "--text-2": p.muted, "--text-3": p.faint, "--accent": p.accent,
    "--good": p.ok, "--warn": p.warn,
  };
}
