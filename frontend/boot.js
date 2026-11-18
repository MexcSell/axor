// Loaded in <head> before CSS paints: applies the saved theme mode and accent color with no flash.
const Theme = (() => {
  const DEFAULT = "#10b981", LEGACY = "#2a78d6";  // the old default blue, still saved for anyone who once pressed Reset: treated as unset
  const SWATCHES = [
    ["Emerald", "#10b981"], ["Blue", "#2b7de0"], ["Violet", "#6250d6"], ["Teal", "#0f9d8a"], ["Green", "#1a8a4a"],
    ["Orange", "#e0621f"], ["Gold", "#c08a00"], ["Rose", "#d5487a"], ["Red", "#d33b3b"], ["Graphite", "#5b6170"],
  ];
  const read = k => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };

  const hex2rgb = h => { h = h.replace("#", ""); if (h.length === 3) h = [...h].map(c => c + c).join(""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  const rgb2hex = c => "#" + c.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

  // Keep the accent readable on the current surface (>= 3.2:1) by nudging it lighter/darker.
  function fit(hex, dark) {
    let c = hex2rgb(/^#[0-9a-f]{3,6}$/i.test(hex) ? hex : DEFAULT);
    const surface = hex2rgb(dark ? "#101722" : "#ffffff"), toward = dark ? [255, 255, 255] : [0, 0, 0];
    for (let i = 0; i < 20 && contrast(c, surface) < 3.2; i++) c = mix(c, toward, 0.08);
    return rgb2hex(c);
  }
  const accent = () => { const a = read("accent"); return a && String(a).toLowerCase() !== LEGACY ? a : DEFAULT; };
  function mode() { return read("theme") || "system"; }
  function isDark() {
    const m = mode();
    return m === "dark" || (m === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function apply() {
    const root = document.documentElement, m = mode();
    if (m === "system") delete root.dataset.theme; else root.dataset.theme = m;
    const a = fit(accent(), isDark());
    root.style.setProperty("--accent", a);
    root.style.setProperty("--series-1", a);
    root.style.setProperty("--accent-ink", contrast(hex2rgb(a), [255, 255, 255]) >= contrast(hex2rgb(a), [6, 18, 13]) ? "#ffffff" : "#06120d");  // text on accent fills
    root.style.setProperty("--accent-soft", `color-mix(in srgb, ${a} ${isDark() ? 22 : 13}%, var(--surface))`);
  }
  function set(k, v) { write(k, v); apply(); }
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", apply);
  apply();
  return { apply, set, mode, isDark, accent, DEFAULT, SWATCHES };
})();
