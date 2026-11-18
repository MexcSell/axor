import { Component, lazy, Suspense, useEffect, type ComponentType, type ReactNode } from "react";
import Stack from "./pages/Stack";
import Analytics from "./pages/Analytics";
import Activity from "./pages/Activity";
import { ThemeProvider } from "./v3/theme/ThemeContext";
import { ToastProvider, TooltipLayer, Skeleton, useToast } from "./v3/ui/kit";
import { Shell, NAV, MORE_NAV } from "./v3/app/Shell";
import { useRoute } from "./v3/app/router";
import { bootstrap, ensureLive, setDataMode, useStore } from "./v3/data/store";
// Pages that show hub data (missions, tasks, agents, approvals, audit): only these trigger the live load.
const LIVE_PAGES = new Set(["overview", "missions", "control", "agents", "organization", "notifications", "analytics"]);
import { Empty } from "./v3/ui/kit";
import { DatabaseZap } from "lucide-react";

// A view that needs data live AXoR doesn't have yet must not blank the app: offer sample data or a retry.
class PageBoundary extends Component<{ children: ReactNode; k: string }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  componentDidUpdate(prev: { k: string }) { if (prev.k !== this.props.k && this.state.err) this.setState({ err: null }); }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="ax-panel" style={{ height: "100%", display: "grid", placeItems: "center" }}>
        <Empty icon={DatabaseZap} title="This view needs data that isn't connected yet">
          {`It expects records the live AXoR doesn't have (${this.state.err.message.slice(0, 120)}).`}
          <span style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 10 }}>
            <button type="button" className="ax-btn gold" onClick={() => { setDataMode("sample"); this.setState({ err: null }); }}>Show sample data</button>
            <button type="button" className="ax-btn" onClick={() => this.setState({ err: null })}>Retry</button>
          </span>
        </Empty>
      </div>
    );
  }
}
import { useRef } from "react";

// Any server refusal recorded by the store (settings, news sources, ...) is shown, so a rejected change never looks
// accepted (GPT review #2, #13). The bootstrap error only means "sample mode" and isn't shown as a failure.
// Outcomes of live writes (store.flash): "sending…", AXoR's confirmation, or its own refusal text.
function FlashToaster() {
  const f = useStore((s) => s.flash); const toast = useToast(); const seen = useRef(0);
  useEffect(() => { if (f && f.n !== seen.current) { seen.current = f.n; toast(f.text, f.tone); } }, [f, toast]);
  return null;
}
function ErrorToaster() {
  const errors = useStore((s) => s.errors); const toast = useToast(); const seen = useRef<Record<string, string>>({});
  useEffect(() => {
    for (const [k, v] of Object.entries(errors)) if (k !== "bootstrap" && v && seen.current[k] !== v) { seen.current[k] = v; toast(`Not saved: ${v}`, "bad"); }
  }, [errors, toast]);
  return null;
}
import Overview from "./v3/pages/Overview";

// AXoR UI v3 (docs/ui-v3/ROADMAP.md). Hash routes, so /app serves every page: /app#/missions, /app#/control/M-001?tab=flow.
// The earlier React pages (Stack, Analytics, Activity) stay reachable inside the new shell.
const lazyPage = (f: () => Promise<{ default: ComponentType }>) => lazy(f);
const PAGES: Record<string, ComponentType> = {
  overview: Overview,
  missions: lazyPage(() => import("./v3/pages/Missions")),
  control: lazyPage(() => import("./v3/pages/MissionControl")),
  agents: lazyPage(() => import("./v3/pages/Agents")),
  organization: lazyPage(() => import("./v3/pages/Organization")),
  versions: lazyPage(() => import("./v3/pages/Versions")),
  preview: lazyPage(() => import("./v3/pages/Versions")),
  evolution: lazyPage(() => import("./v3/pages/Evolution")),
  knowledge: lazyPage(() => import("./v3/pages/Knowledge")),
  finance: lazyPage(() => import("./v3/pages/Finance")),
  governance: lazyPage(() => import("./v3/pages/Governance")),
  appearance: lazyPage(() => import("./v3/pages/Appearance")),
  settings: lazyPage(() => import("./v3/pages/Settings")),
  notifications: lazyPage(() => import("./v3/pages/Notifications")),
  analytics: lazyPage(() => import("./v3/pages/AnalyticsV3")),
  "analytics-classic": () => <div className="ax-legacy ax-panel"><Analytics /></div>,
  system: () => <div className="ax-legacy ax-panel"><Stack /></div>,
  activity: () => <div className="ax-legacy ax-panel"><Activity /></div>,
};

function Routed() {
  const r = useRoute();
  const Page = PAGES[r.page] ?? Overview;
  const me = useStore((s) => s.me);
  useEffect(() => { if (LIVE_PAGES.has(r.page) || !PAGES[r.page]) ensureLive(); }, [r.page, me]);
  const label = [...NAV, ...MORE_NAV].find((n) => n.page === r.page)?.label ?? (r.page === "preview" ? "Preview" : "Overview");
  useEffect(() => { document.title = `AXoR · ${label}`; }, [label]);
  return (
    <Suspense fallback={<div style={{ display: "grid", gap: 10, padding: 10 }}><Skeleton h={120} /><Skeleton h={260} /><Skeleton h={180} /></div>}>
      <PageBoundary k={r.page + (r.param ?? "") + useStore((s) => s.dataMode)}><Page /></PageBoundary>
    </Suspense>
  );
}

export default function App() {
  useEffect(() => { document.documentElement.classList.add("ax-v3"); bootstrap(); }, []);
  return (
    <ThemeProvider>
      <ToastProvider>
        <Shell><Routed /></Shell>
        <TooltipLayer />
        <ErrorToaster />
        <FlashToaster />
      </ToastProvider>
    </ThemeProvider>
  );
}
