const PAL = ["#22d3ee", "#a77bff", "#f2b53a", "#2fd27a", "#fb7185", "#3b8cff", "#f472b6"];
export const missionColor = (id: string) => PAL[[...id].reduce((a, c) => a + c.charCodeAt(0), 0) % PAL.length];
import { go, useRoute } from "../../app/router";
// Selected agent lives in the route param (#/agents/<ID>); the query (tab, ptab, filters) is preserved when it changes.
export function useSelected() {
  const r = useRoute();
  const id = r.param ?? "DEV-01";
  const q = Object.fromEntries(r.q.entries());
  return {
    id,
    select: (next: string) => go("agents", next, q),
    open: (next: string, ptab?: string) => go("agents", next, { ...q, tab: "profile", ...(ptab ? { ptab } : {}) }),
  };
}
