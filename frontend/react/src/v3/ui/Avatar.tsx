import { useId, type CSSProperties } from "react";
import { motion } from "framer-motion";
import {
  BookOpen, Code2, Coins, Compass, Crown, DraftingCompass, GraduationCap, Rocket, Search, Settings2, ShieldCheck, User, Lock, Palette,
  type LucideIcon,
} from "lucide-react";
import { useTheme } from "../theme/ThemeContext";
import { AVATAR_COLORS, type AvatarColor, type AvatarFace } from "../theme/themes";

// Role-specific default avatars (readme: "agents have icons that fit their missions as their default images"; UX-006, AT-11).
// The emblem says what the agent does; the text alternative names the role. A custom avatar never changes agent identity.
export type Role = "gm" | "research" | "developer" | "qa" | "ops" | "finance" | "knowledge" | "deploy" | "architect" | "mentor"
  | "strategist" | "security" | "designer" | "user";

export const ROLES: Record<Role, { label: string; icon: LucideIcon; c: string; emblem: string }> = {
  gm: { label: "General Manager", icon: Crown, c: "#f2b53a", emblem: "crown: strategy and command" },
  research: { label: "Researcher", icon: Search, c: "#22d3ee", emblem: "magnifier: research" },
  developer: { label: "Developer", icon: Code2, c: "#3b8cff", emblem: "code brackets: development" },
  qa: { label: "QA / Verifier", icon: ShieldCheck, c: "#2fd27a", emblem: "shield with check: verification" },
  ops: { label: "Operations", icon: Settings2, c: "#94a3b8", emblem: "gear: operations" },
  finance: { label: "Finance", icon: Coins, c: "#fbbf24", emblem: "coins: finance ledger" },
  knowledge: { label: "Knowledge", icon: BookOpen, c: "#a77bff", emblem: "open book: knowledge" },
  deploy: { label: "Deployment", icon: Rocket, c: "#fb7185", emblem: "rocket: deployment" },
  architect: { label: "Architect", icon: DraftingCompass, c: "#38bdf8", emblem: "drafting compass: architecture blueprint" },
  mentor: { label: "Mentor", icon: GraduationCap, c: "#f472b6", emblem: "graduation cap: mentoring" },
  strategist: { label: "Strategist", icon: Compass, c: "#f59e0b", emblem: "compass: strategy" },
  security: { label: "Security", icon: Lock, c: "#ef4444", emblem: "lock: security" },
  designer: { label: "Designer", icon: Palette, c: "#e879f9", emblem: "palette: design" },
  user: { label: "You", icon: User, c: "#e2e8f0", emblem: "person: the user" },
};

export function Avatar({ role, size = 36, name, status, animate = true, ring, face: faceOverride, tint }: {
  role: Role; size?: number; name?: string; status?: "active" | "idle" | "busy" | "offline" | "error"; animate?: boolean; ring?: boolean;
  face?: AvatarFace; tint?: AvatarColor; // per-instance preview (Appearance Studio tiles); default = the user's setting
}) {
  const { appearance } = useTheme();
  const r = ROLES[role] ?? ROLES.developer; const I = r.icon; const id = useId().replace(/:/g, "");
  const alt = `${name ? name + ", " : ""}${r.label} (${r.emblem})`;
  const dot = status ? { active: "var(--ax-ok)", idle: "var(--ax-neutral)", busy: "var(--ax-info)", offline: "var(--ax-faint)", error: "var(--ax-bad)" }[status] : null;
  const wrap: CSSProperties = { position: "relative", width: size, height: size, flex: "none", display: "inline-block" };

  if ((appearance.avatarPack === "glyphs" && !faceOverride) || role === "user") {
    return (
      <motion.span role="img" aria-label={alt} style={wrap} whileHover={{ scale: 1.08, rotate: -4 }}>
        <span style={{ width: size, height: size, borderRadius: "50%", display: "grid", placeItems: "center", color: r.c,
          background: `color-mix(in srgb, ${r.c} 18%, var(--ax-panel2))`, border: `1.5px solid color-mix(in srgb, ${r.c} 70%, transparent)`,
          boxShadow: ring ? `0 0 0 2px var(--ax-accent), 0 0 12px var(--ax-glow)` : `0 0 calc(10px * var(--ax-glow-k)) color-mix(in srgb, ${r.c} 50%, transparent)` }}>
          <I size={size * .5} aria-hidden />
        </span>
        {dot && <i style={{ position: "absolute", right: 0, bottom: 0, width: size * .26, height: size * .26, borderRadius: "50%", background: dot, boxShadow: "0 0 0 2px var(--ax-bg)" }} aria-hidden />}
      </motion.span>
    );
  }

  const blink = animate ? { scaleY: [1, 1, .1, 1, 1] } : undefined;
  // 30-10 "Avatar Face Style" and "Avatar Color Scheme": the face changes, the role emblem never does.
  const face = faceOverride ?? appearance.avatarFace; const col = tint ?? appearance.avatarColor; const eye = col === "role" ? r.c : AVATAR_COLORS[col];
  const holo = face === "holographic", elite = face === "elite";
  return (
    <motion.span role="img" aria-label={alt} style={wrap} whileHover={{ scale: 1.1, y: -2 }} transition={{ type: "spring", stiffness: 400, damping: 18 }}>
      <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
        <defs>
          <radialGradient id={`h${id}`} cx="40%" cy="30%" r="75%"><stop offset="0%" stopColor="#ffffff" /><stop offset="55%" stopColor="#dfe6f2" /><stop offset="100%" stopColor="#8f9bb3" /></radialGradient>
          <linearGradient id={`v${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0b1530" /><stop offset="100%" stopColor="#1b2b55" /></linearGradient>
          <filter id={`g${id}`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {ring && <circle cx="32" cy="32" r="30.5" fill="none" stroke="var(--ax-accent)" strokeWidth="2" />}
        {/* antenna (not on the minimal face) */}
        {face !== "minimal" && <><line x1="32" y1="9" x2="32" y2="4" stroke="#aab4c8" strokeWidth="2" />
          <motion.circle cx="32" cy="4" r="2.6" fill={eye} filter={`url(#g${id})`} animate={animate ? { opacity: [1, .35, 1] } : undefined} transition={{ duration: 1.8, repeat: Infinity }} /></>}
        {elite && <path d="M22 10 l5 -6 l5 4 l5 -4 l5 6z" fill="#f2b53a" stroke="#ffe08a" strokeWidth=".8" />}
        {/* ears */}
        <rect x="6" y="25" width="7" height="14" rx="3" fill={elite ? "#f2b53a" : r.c} opacity=".9" />
        <rect x="51" y="25" width="7" height="14" rx="3" fill={elite ? "#f2b53a" : r.c} opacity=".9" />
        {/* head */}
        <rect x="10" y="9" width="44" height="40" rx={face === "analytical" ? 12 : 17} fill={holo ? "rgba(34,211,238,.18)" : `url(#h${id})`} stroke={holo ? eye : elite ? "#f2b53a" : "#ffffff"} strokeOpacity={holo ? 1 : .6} strokeWidth={elite || holo ? 1.8 : 1} />
        {/* visor */}
        <rect x="16" y="19" width="32" height="18" rx="9" fill={`url(#v${id})`} stroke={eye} strokeOpacity=".8" />
        {face === "analytical" ? (
          <motion.rect x="19" y="26" width="26" height="4" rx="2" fill={eye} filter={`url(#g${id})`} animate={animate ? { opacity: [.5, 1, .5], scaleX: [.6, 1, .6] } : undefined} transition={{ duration: 2.2, repeat: Infinity }} style={{ originX: "32px" }} />
        ) : face === "expressive" ? (
          <motion.g animate={animate ? { y: [0, -1, 0] } : undefined} transition={{ duration: 2.4, repeat: Infinity }}>
            <path d="M21 30 q4 -6 8 0" stroke={eye} strokeWidth="2.6" fill="none" strokeLinecap="round" filter={`url(#g${id})`} />
            <path d="M35 30 q4 -6 8 0" stroke={eye} strokeWidth="2.6" fill="none" strokeLinecap="round" filter={`url(#g${id})`} />
          </motion.g>
        ) : (
          <motion.g animate={blink} transition={{ duration: 4.2, repeat: Infinity, times: [0, .46, .5, .54, 1] }} style={{ originX: "32px", originY: "28px" }}>
            <ellipse cx="25" cy="28" rx={face === "minimal" ? 2 : 3.6} ry={face === "minimal" ? 2 : 4} fill={eye} filter={`url(#g${id})`} />
            <ellipse cx="39" cy="28" rx={face === "minimal" ? 2 : 3.6} ry={face === "minimal" ? 2 : 4} fill={eye} filter={`url(#g${id})`} />
          </motion.g>
        )}
        {face !== "minimal" && <path d={face === "expressive" ? "M25 41 q7 6 14 0" : "M27 42 q5 3 10 0"} stroke={holo ? eye : "#7d8aa5"} strokeWidth="1.6" fill="none" strokeLinecap="round" />}
        {holo && <motion.line x1="12" x2="52" y1="14" y2="14" stroke={eye} strokeWidth=".8" opacity=".7" animate={animate ? { y1: [14, 46, 14], y2: [14, 46, 14] } : undefined} transition={{ duration: 3, repeat: Infinity }} />}
        {/* body */}
        <path d="M18 64 q2-13 14-13 q12 0 14 13z" fill={holo ? "rgba(34,211,238,.18)" : `url(#h${id})`} stroke={holo ? eye : "none"} />
      </svg>
      {/* emblem badge */}
      <motion.span style={{ position: "absolute", right: -size * .06, bottom: -size * .04, width: size * .42, height: size * .42, borderRadius: "50%",
        display: "grid", placeItems: "center", background: r.c, color: "#0b1020", boxShadow: "0 0 0 1.5px var(--ax-bg), 0 0 8px " + r.c }}
        initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: .2, type: "spring" }}>
        <I size={size * .26} strokeWidth={2.4} aria-hidden />
      </motion.span>
      {dot && <i style={{ position: "absolute", left: 0, bottom: 0, width: size * .22, height: size * .22, borderRadius: "50%", background: dot, boxShadow: "0 0 0 2px var(--ax-bg)" }} aria-hidden />}
    </motion.span>
  );
}

// The holographic AI guardian under the sidebar (30-x shell): armoured mask with gold trim, glowing cyan eyes and
// forehead emblem, gold halo arcs, standing on a holographic platform with a light beam. Decorative.
export function Mascot() {
  const gold = "url(#mgold)", silver = "url(#msil)";
  return (
    <svg viewBox="0 0 200 400" role="img" aria-label="AXoR guardian mascot (decorative)">
      <defs>
        <linearGradient id="msil" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#c9d3e2" /><stop offset="40%" stopColor="#6f7d95" /><stop offset="100%" stopColor="#252f42" /></linearGradient>
        <radialGradient id="mback" cx="50%" cy="45%" r="50%"><stop offset="0%" stopColor="#1aa7ff" stopOpacity=".55" /><stop offset="100%" stopColor="#1aa7ff" stopOpacity="0" /></radialGradient>
        <linearGradient id="mgold" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ffe9a8" /><stop offset="50%" stopColor="#e2a93a" /><stop offset="100%" stopColor="#9a6a17" /></linearGradient>
        <radialGradient id="meye" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#ffffff" /><stop offset="45%" stopColor="#7fe8ff" /><stop offset="100%" stopColor="#1aa7ff" stopOpacity="0" /></radialGradient>
        <radialGradient id="mplat" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#7fe8ff" stopOpacity=".95" /><stop offset="60%" stopColor="#1aa7ff" stopOpacity=".35" /><stop offset="100%" stopColor="#1aa7ff" stopOpacity="0" /></radialGradient>
        <linearGradient id="mbeam" x1="0" y1="1" x2="0" y2="0"><stop offset="0%" stopColor="#7fe8ff" stopOpacity=".7" /><stop offset="100%" stopColor="#7fe8ff" stopOpacity="0" /></linearGradient>
        <filter id="mglow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <ellipse cx="100" cy="130" rx="95" ry="120" fill="url(#mback)" />
      {/* halo arcs */}
      <motion.g style={{ originX: "100px", originY: "120px" }} animate={{ rotate: [0, 360] }} transition={{ duration: 60, repeat: Infinity, ease: "linear" }} opacity={.75}>
        <circle cx="100" cy="120" r="92" fill="none" stroke={gold} strokeWidth="1.2" strokeDasharray="120 40 30 60" />
        <circle cx="100" cy="120" r="80" fill="none" stroke="#1aa7ff" strokeOpacity=".5" strokeWidth=".8" strokeDasharray="4 6" />
      </motion.g>
      {/* light beam */}
      <motion.path d="M84 300 L100 210 L116 300 Z" fill="url(#mbeam)" animate={{ opacity: [.35, .8, .35] }} transition={{ duration: 2.6, repeat: Infinity }} />
      <motion.g animate={{ y: [0, -5, 0] }} transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut" }}>
        {/* ear modules */}
        <rect x="28" y="108" width="20" height="44" rx="9" fill={silver} stroke={gold} strokeWidth="2" />
        <rect x="152" y="108" width="20" height="44" rx="9" fill={silver} stroke={gold} strokeWidth="2" />
        <motion.rect x="33" y="118" width="6" height="24" rx="3" fill="#7fe8ff" filter="url(#mglow)" animate={{ opacity: [.5, 1, .5] }} transition={{ duration: 2, repeat: Infinity }} />
        <motion.rect x="161" y="118" width="6" height="24" rx="3" fill="#7fe8ff" filter="url(#mglow)" animate={{ opacity: [.5, 1, .5] }} transition={{ duration: 2, repeat: Infinity, delay: .5 }} />
        {/* helmet and crest */}
        <path d="M100 26 L126 40 L146 76 L150 128 L138 176 L114 206 L100 214 L86 206 L62 176 L50 128 L54 76 L74 40 Z" fill={silver} stroke={gold} strokeWidth="2.5" />
        <path d="M74 40 L66 22 L82 34 M126 40 L134 22 L118 34" stroke={gold} strokeWidth="3" fill="none" strokeLinecap="round" />
        <path d="M100 26 L112 70 L100 82 L88 70 Z" fill="#0b1a33" stroke={gold} strokeWidth="2" />
        <motion.path d="M100 50 L109 66 L91 66 Z" fill="none" stroke="#7fe8ff" strokeWidth="2.4" filter="url(#mglow)" animate={{ opacity: [.6, 1, .6] }} transition={{ duration: 2.2, repeat: Infinity }} />
        {/* gold trim / cheek plates */}
        <path d="M54 92 L82 102 L76 128 M146 92 L118 102 L124 128" stroke={gold} strokeWidth="3" fill="none" strokeLinejoin="round" />
        <path d="M62 150 L84 162 L90 196 M138 150 L116 162 L110 196" stroke={gold} strokeWidth="2.5" fill="none" />
        {/* face */}
        <path d="M80 104 Q100 96 120 104 L122 150 Q100 176 78 150 Z" fill="url(#msil)" opacity=".95" />
        <path d="M60 96 L86 108 L84 150 L100 176 L116 150 L114 108 L140 96" stroke={gold} strokeWidth="3.4" fill="none" strokeLinejoin="round" />
        {/* eyes */}
        <motion.g filter="url(#mglow)" animate={{ opacity: [.75, 1, .75] }} transition={{ duration: 2.8, repeat: Infinity }}>
          <path d="M70 116 Q80 106 92 114 Q82 122 70 116 Z" fill="#7fe8ff" />
          <path d="M130 116 Q120 106 108 114 Q118 122 130 116 Z" fill="#7fe8ff" />
          <ellipse cx="81" cy="115" rx="13" ry="7" fill="url(#meye)" />
          <ellipse cx="119" cy="115" rx="13" ry="7" fill="url(#meye)" />
        </motion.g>
        <path d="M100 118 L97 140 L103 140 Z" fill="#8995a8" opacity=".7" />
        <path d="M91 152 Q100 157 109 152" stroke="#6c7891" strokeWidth="2" fill="none" strokeLinecap="round" />
        {/* collar */}
        <path d="M70 206 L100 226 L130 206 L136 236 L100 254 L64 236 Z" fill={silver} stroke={gold} strokeWidth="2" />
        <motion.path d="M100 226 L100 252" stroke="#7fe8ff" strokeWidth="2" filter="url(#mglow)" animate={{ opacity: [.4, 1, .4] }} transition={{ duration: 1.8, repeat: Infinity }} />
      </motion.g>
      {/* holographic platform */}
      <motion.ellipse cx="100" cy="320" rx="86" ry="20" fill="url(#mplat)" style={{ originX: "100px", originY: "320px" }} animate={{ opacity: [.55, 1, .55], scaleX: [.94, 1.03, .94] }} transition={{ duration: 3.4, repeat: Infinity }} />
      <ellipse cx="100" cy="320" rx="70" ry="14" fill="none" stroke={gold} strokeWidth="2" />
      <motion.ellipse cx="100" cy="320" rx="52" ry="10" fill="none" stroke="#7fe8ff" strokeWidth="1.6" strokeDasharray="6 5" animate={{ strokeDashoffset: [0, -44] }} transition={{ duration: 3, repeat: Infinity, ease: "linear" }} />
      <ellipse cx="100" cy="320" rx="30" ry="6" fill="#bff4ff" opacity=".8" filter="url(#mglow)" />
      <path d="M22 334 Q100 362 178 334 L178 344 Q100 374 22 344 Z" fill="#0b1a33" stroke={gold} strokeOpacity=".7" />
    </svg>
  );
}

// Header hero (30-x): a glowing "A" pyramid on a holographic disc with concentric gold/cyan rings, flanked by two
// floating-island skylines with lit windows, light streaks to the sides. Decorative.
// [x, height, width, kind]: kind 0 glass tower (cyan), 1 lit tower (gold), 2 spire
const SKY_L: number[][] = [[22, 18, 8, 0], [32, 30, 7, 1], [41, 44, 9, 2], [52, 26, 8, 0], [62, 52, 10, 1], [74, 34, 7, 0], [83, 60, 9, 2], [94, 40, 8, 1], [104, 28, 7, 0], [113, 48, 9, 0], [124, 22, 8, 1], [134, 36, 7, 2], [143, 20, 8, 0], [153, 30, 7, 1], [163, 16, 8, 0]];
const SKY_R: number[][] = [[318, 16, 8, 0], [328, 28, 7, 1], [337, 40, 9, 0], [348, 24, 8, 2], [358, 50, 10, 1], [370, 32, 7, 0], [379, 58, 9, 2], [390, 38, 8, 0], [400, 46, 9, 1], [411, 26, 7, 0], [420, 34, 8, 2], [430, 20, 7, 1], [439, 28, 8, 0], [449, 18, 7, 0]];
export function HeroCity() {
  const tower = ([x, h, w, kind]: number[], i: number, side: string) => {
    const top = 56 - h, fill = kind === 1 ? "url(#hgoldt)" : "url(#htower)";
    return (
      <g key={side + i}>
        {kind === 2 && <path d={`M${x + w / 2} ${top - 10} L${x + w / 2 + 1.2} ${top} L${x + w / 2 - 1.2} ${top} Z`} fill="#bff4ff" />}
        <path d={kind === 2 ? `M${x} 56 L${x} ${top + 4} L${x + w / 2} ${top} L${x + w} ${top + 4} L${x + w} 56 Z` : `M${x} 56 L${x} ${top + 1} L${x + w} ${top + 1} L${x + w} 56 Z`}
          fill={fill} stroke={kind === 1 ? "#ffd36b" : "#7fe8ff"} strokeOpacity=".45" strokeWidth=".5" />
        {Array.from({ length: Math.floor(h / 12) }, (_, k) => (
          <motion.rect key={k} x={x + 1.5} y={top + 5 + k * 12} width={w - 3} height="1.4" fill={kind === 1 ? "#fff1c2" : "#d9f7ff"}
            animate={{ opacity: [.25, .9, .25] }} transition={{ duration: 2.4 + ((i + k) % 5) * .6, repeat: Infinity, delay: ((i * 3 + k) % 7) * .35 }} />
        ))}
      </g>
    );
  };
  return (
    <svg className="ax-hero" viewBox="0 0 490 82" aria-hidden>
      <defs>
        <linearGradient id="htower" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#bfe9ff" /><stop offset="40%" stopColor="#2f7bd6" /><stop offset="100%" stopColor="#0b2550" /></linearGradient>
        <linearGradient id="hpyr" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#ffffff" /><stop offset="40%" stopColor="#7fe8ff" /><stop offset="100%" stopColor="#1a6fd6" /></linearGradient>
        <linearGradient id="hisle" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5a9c4a" /><stop offset="18%" stopColor="#3b4f63" /><stop offset="100%" stopColor="#0b1a33" stopOpacity="0" /></linearGradient>
        <linearGradient id="hgoldt" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#fff1c2" /><stop offset="45%" stopColor="#d9a441" /><stop offset="100%" stopColor="#4a3410" /></linearGradient>
        <radialGradient id="hdisc" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#bff4ff" stopOpacity=".95" /><stop offset="55%" stopColor="#1aa7ff" stopOpacity=".45" /><stop offset="100%" stopColor="#1aa7ff" stopOpacity="0" /></radialGradient>
        <filter id="hglow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {/* light streaks */}
      {[[330, 10, 470, 2], [360, 30, 490, 18], [20, 30, 150, 8], [0, 52, 120, 40]].map(([x1, y1, x2, y2], i) => (
        <motion.line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={i < 2 ? "#ffd36b" : "#7fe8ff"} strokeWidth="1.1" strokeLinecap="round"
          animate={{ opacity: [0, .9, 0] }} transition={{ duration: 3.2, repeat: Infinity, delay: i * .8 }} />
      ))}
      {/* floating islands */}
      <path d="M14 56 Q100 50 196 56 L176 64 L150 68 L132 82 L112 70 L84 76 L60 66 L34 64 Z" fill="url(#hisle)" />
      <path d="M294 56 Q390 50 478 56 L458 64 L430 68 L410 82 L392 70 L362 76 L338 66 L312 64 Z" fill="url(#hisle)" />
      {[24, 46, 70, 118, 150, 176, 304, 330, 364, 420, 452].map((x, i) => <circle key={i} cx={x} cy={55} r={2.4} fill="#4f9a45" opacity=".9" />)}
      {SKY_L.map((t, i) => tower(t, i, "l"))}
      {SKY_R.map((t, i) => tower(t, i, "r"))}
      {/* disc and rings */}
      <ellipse cx="245" cy="62" rx="112" ry="17" fill="url(#hdisc)" />
      <ellipse cx="245" cy="64" rx="104" ry="14" fill="none" stroke="#ffd36b" strokeWidth="2.6" opacity=".9" filter="url(#hglow)" />
      <motion.ellipse cx="245" cy="62" rx="98" ry="13" fill="none" stroke="#e2a93a" strokeWidth="2" strokeDasharray="40 8 12 8" animate={{ strokeDashoffset: [0, -136] }} transition={{ duration: 8, repeat: Infinity, ease: "linear" }} />
      <motion.ellipse cx="245" cy="62" rx="76" ry="10" fill="none" stroke="#7fe8ff" strokeWidth="1.4" strokeDasharray="6 5" animate={{ strokeDashoffset: [0, 44] }} transition={{ duration: 4, repeat: Infinity, ease: "linear" }} />
      <ellipse cx="245" cy="62" rx="52" ry="7" fill="none" stroke="#ffd36b" strokeOpacity=".8" strokeWidth="1" />
      {/* the A pyramid */}
      <motion.g filter="url(#hglow)" animate={{ opacity: [.85, 1, .85] }} transition={{ duration: 2.6, repeat: Infinity }}>
        <path d="M245 -2 L284 58 L265 58 L245 24 L225 58 L206 58 Z" fill="url(#hpyr)" stroke="#ffffff" strokeOpacity=".8" strokeWidth=".8" />
        <path d="M236 48 L254 48 L250 54 L240 54 Z" fill="#bff4ff" />
      </motion.g>
      <motion.ellipse cx="245" cy="58" rx="26" ry="4" fill="#ffffff" opacity=".9" filter="url(#hglow)" style={{ transformBox: "fill-box", transformOrigin: "center" }} animate={{ scaleX: [.85, 1.08, .85] }} transition={{ duration: 2.6, repeat: Infinity }} />
    </svg>
  );
}

// AXoR "A" logo mark.
export function LogoMark({ size = 34 }: { size?: number }) {
  return (
    <motion.svg width={size} height={size} viewBox="0 0 40 40" aria-hidden initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} transition={{ duration: .8 }}>
      <defs><linearGradient id="lm" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#ffffff" /><stop offset="45%" stopColor="var(--ax-accent2)" /><stop offset="100%" stopColor="var(--ax-info)" /></linearGradient></defs>
      <path d="M20 3 L37 36 H28 L20 19 L12 36 H3 Z" fill="url(#lm)" style={{ filter: "drop-shadow(0 0 calc(6px * var(--ax-glow-k)) var(--ax-accent2))" }} />
      <path d="M14 30 h12" stroke="var(--ax-accent)" strokeWidth="2.5" />
    </motion.svg>
  );
}
