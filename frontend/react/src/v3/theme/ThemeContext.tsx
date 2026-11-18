import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { MotionConfig } from "framer-motion";
import { DEFAULT_APPEARANCE, sanitizeAppearance, tokens, type Appearance, type Mode } from "./themes";

// Per-user appearance (THEME-001): server-side under /api/ui/preferences when signed in, localStorage as the
// offline fallback. Applying a theme only rewrites CSS variables / data-attributes on <html>.
const KEY = "axor.v3.appearance";

interface Ctx {
  appearance: Appearance; mode: Mode; set: (patch: Partial<Appearance>) => void; replace: (a: Appearance) => void;
  undo: () => void; canUndo: boolean; reset: () => void; preview: Appearance | null; setPreview: (a: Appearance | null) => void;
  saved: "local" | "server" | "saving" | "error";
}
const ThemeCtx = createContext<Ctx | null>(null);

function readLocal(): Appearance {
  try { const raw = localStorage.getItem(KEY); return raw ? sanitizeAppearance(JSON.parse(raw)) : DEFAULT_APPEARANCE; } catch { return DEFAULT_APPEARANCE; }
}
function systemMode(): Mode {
  try { return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; } catch { return "dark"; }
}
function systemReducedMotion(): boolean {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

export function applyAppearance(a: Appearance, el: HTMLElement = document.documentElement): Mode {
  const mode: Mode = a.mode === "system" ? systemMode() : a.mode;
  const t = tokens(a, mode);
  for (const [k, v] of Object.entries(t)) el.style.setProperty(k, v);
  el.dataset.axStyle = a.style; el.dataset.axMode = mode; el.dataset.theme = mode;
  el.dataset.axDensity = a.density; el.dataset.axContrast = a.highContrast ? "high" : "normal";
  el.dataset.axMotion = a.reducedMotion || systemReducedMotion() ? "off" : a.motion;
  el.dataset.axFocus = a.focusRing; el.dataset.axSidebar = a.sidebar; el.dataset.axIcons = a.iconSet;
  return mode;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Pure state transitions; persistence happens in an effect after commit, and saves are serialised (GPT review #1, #10/#11).
  const [st, setSt] = useState<{ a: Appearance; history: Appearance[]; rev: number }>(() => ({ a: readLocal(), history: [], rev: 0 }));
  const appearance = st.a;
  const [preview, setPreview] = useState<Appearance | null>(null);
  const [saved, setSaved] = useState<Ctx["saved"]>("local");
  const [mode, setMode] = useState<Mode>("dark");
  const edited = useRef(false);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const effective = preview ?? appearance;

  useEffect(() => { setMode(applyAppearance(effective)); }, [effective]);
  useEffect(() => {
    if (effective.mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setMode(applyAppearance(effective));
    mq.addEventListener("change", on); return () => mq.removeEventListener("change", on);
  }, [effective]);

  // The server copy wins on first load, unless the user already changed something meanwhile.
  useEffect(() => {
    fetch("/api/ui/preferences", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (edited.current || !d || !d.appearance) return;
        const a = sanitizeAppearance(d.appearance);
        setSt((cur) => ({ ...cur, a })); setSaved("server");
        try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { /* private mode */ }
      })
      .catch(() => {});
  }, []);

  // Persist every user change (rev > 0), one request at a time, newest last.
  useEffect(() => {
    if (st.rev === 0) return;
    const a = st.a, rev = st.rev;
    let localOk = true;
    try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { localOk = false; /* private mode / blocked storage */ }
    setSaved("saving");
    // "local" only if the browser really stored it; "error" when neither destination did (GPT review #2, #19)
    queue.current = queue.current.then(() =>
      fetch("/api/ui/preferences", { method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Requested-With": "scout" }, body: JSON.stringify({ appearance: a }) })
        .then((r) => { if (rev === revRef.current) setSaved(r.ok ? "server" : localOk ? "local" : "error"); })
        .catch(() => { if (rev === revRef.current) setSaved(localOk ? "local" : "error"); }));
  }, [st.rev, st.a]);
  const revRef = useRef(0); revRef.current = st.rev;

  const replace = useCallback((a: Appearance) => {
    edited.current = true;
    setSt((cur) => ({ a, history: [...cur.history.slice(-19), cur.a], rev: cur.rev + 1 }));
  }, []);
  const set = useCallback((patch: Partial<Appearance>) => {
    edited.current = true;
    setSt((cur) => ({ a: sanitizeAppearance({ ...cur.a, ...patch }), history: [...cur.history.slice(-19), cur.a], rev: cur.rev + 1 }));
  }, []);
  const undo = useCallback(() => {
    setSt((cur) => (cur.history.length ? { a: cur.history[cur.history.length - 1], history: cur.history.slice(0, -1), rev: cur.rev + 1 } : cur));
  }, []);
  const reset = useCallback(() => replace(DEFAULT_APPEARANCE), [replace]);
  const history = st.history;

  const motionOff = effective.reducedMotion || effective.motion === "off";
  const value = useMemo<Ctx>(() => ({ appearance, mode, set, replace, undo, canUndo: history.length > 0, reset, preview, setPreview, saved }),
    [appearance, mode, set, replace, undo, history.length, reset, preview, saved]);
  return (
    <ThemeCtx.Provider value={value}>
      <MotionConfig reducedMotion={motionOff ? "always" : "user"}>{children}</MotionConfig>
    </ThemeCtx.Provider>
  );
}

export function useTheme(): Ctx {
  const c = useContext(ThemeCtx);
  if (!c) throw new Error("useTheme outside ThemeProvider");
  return c;
}
