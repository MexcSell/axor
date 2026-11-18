import { useCallback, useEffect, useState } from "react";

// Hash routes: #/<page>[/<param>][?tab=..&k=v]. Tabs live in the URL so Back/Forward and reload keep the selected tab (UX-003).
export interface Route { page: string; param: string | null; q: URLSearchParams }
export function parse(hash = window.location.hash): Route {
  const h = hash.replace(/^#/, "") || "/overview";
  const [path, query = ""] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  let param: string | null = null;
  try { param = parts[1] ? decodeURIComponent(parts[1]) : null; } catch { param = null; } // malformed %-encoding (review #1, #23)
  return { page: parts[0] ?? "overview", param, q: new URLSearchParams(query) };
}
export function href(page: string, param?: string | null, q?: Record<string, string | undefined | null>) {
  const qs = new URLSearchParams(); for (const [k, v] of Object.entries(q ?? {})) if (v) qs.set(k, v);
  return `#/${page}${param ? "/" + encodeURIComponent(param) : ""}${qs.toString() ? "?" + qs.toString() : ""}`;
}
export function go(page: string, param?: string | null, q?: Record<string, string | undefined | null>) { window.location.hash = href(page, param, q); }

export function useRoute(): Route {
  const [r, setR] = useState(parse);
  useEffect(() => { const on = () => setR(parse()); window.addEventListener("hashchange", on); return () => window.removeEventListener("hashchange", on); }, []);
  return r;
}
// A URL-backed tab/query value. replaceState keeps the history clean when switching tabs.
export function useQueryParam(key: string, fallback: string): [string, (v: string) => void] {
  const r = useRoute();
  const value = r.q.get(key) ?? fallback;
  const setValue = useCallback((v: string) => {
    const cur = parse(); const q = new URLSearchParams(cur.q); if (v === fallback) q.delete(key); else q.set(key, v);
    const next = `#/${cur.page}${cur.param ? "/" + encodeURIComponent(cur.param) : ""}${q.toString() ? "?" + q.toString() : ""}`;
    window.history.replaceState(null, "", next); window.dispatchEvent(new HashChangeEvent("hashchange"));
  }, [key, fallback]);
  return [value, setValue];
}
