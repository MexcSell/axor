import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ExternalLink, HeartPulse, Laptop, Loader2, Monitor, RefreshCw, ScrollText, ShieldCheck, Smartphone, Tablet, Terminal, XCircle, GitCommit, Zap, Bug } from "lucide-react";
import { IconBtn, Panel, Pill, Seg, useToast } from "../../ui/kit";
import type { Release } from "../../domain/types";
import { href } from "../../app/router";
import { BUILD_STAGES } from "./data";

type Phase = "idle" | "building" | "restarting" | "ok" | "failed";
const VIEWPORTS = { desktop: { w: 1280, h: 800, label: "Desktop 1280", icon: Monitor }, laptop: { w: 1024, h: 700, label: "Laptop 1024", icon: Laptop }, tablet: { w: 768, h: 1000, label: "Tablet 768", icon: Tablet }, mobile: { w: 390, h: 780, label: "Mobile 390", icon: Smartphone } } as const;
type VP = keyof typeof VIEWPORTS;

/** A static, in-page mock of the product (a mini AXoR landing page). It loads nothing external. */
export function MockSite({ version, commit }: { version: string; commit: string }) {
  return (
    <div style={{ background: "#0b1224", color: "#e8eefc", height: "100%", fontFamily: "system-ui, sans-serif", overflow: "hidden", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "16px 36px", borderBottom: "1px solid #1f2d52" }}>
        <b style={{ fontSize: 22, color: "#f2b53a", letterSpacing: 2 }}>▲ AXoR</b><span style={{ flex: 1 }} />
        {["Product", "Agents", "Pricing", "Docs"].map((x) => <span key={x} style={{ fontSize: 15, color: "#9fb0d8" }}>{x}</span>)}
        <span style={{ background: "#f2b53a", color: "#1b1405", padding: "8px 18px", borderRadius: 9, fontWeight: 700, fontSize: 15 }}>Start a mission</span>
      </div>
      <div style={{ padding: "56px 36px 30px", textAlign: "center", background: "radial-gradient(ellipse at 50% 0%, #1d3a8a55, transparent 70%)" }}>
        <div style={{ fontSize: 14, letterSpacing: 3, color: "#22d3ee" }}>AUTONOMOUS AI COMPANY OS · {version}</div>
        <h1 style={{ fontSize: 50, margin: "14px 0 10px", lineHeight: 1.1 }}>Run, build, verify, evolve.</h1>
        <p style={{ fontSize: 19, color: "#9fb0d8", maxWidth: 640, margin: "0 auto" }}>A self-sustaining, self-evolving AI company. Give it a goal; agents plan, research, develop, test and deploy it.</p>
        <div style={{ marginTop: 26, display: "inline-flex", gap: 12 }}><span style={{ background: "linear-gradient(90deg,#3b8cff,#a77bff)", padding: "13px 26px", borderRadius: 11, fontWeight: 700 }}>Get started</span><span style={{ border: "1px solid #345", padding: "13px 26px", borderRadius: 11 }}>Watch demo</span></div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, padding: "10px 36px" }}>
        {[["Missions", "Goal-driven work with milestones", "#3b8cff"], ["Agents", "Isolated per mission, always improving", "#2fd27a"], ["Verified", "Independent QA before every release", "#f2b53a"]].map(([t, d, c]) => (
          <div key={t} style={{ border: `1px solid ${c}55`, borderRadius: 14, padding: 18, background: "#101a35" }}><b style={{ color: c, fontSize: 18 }}>{t}</b><div style={{ color: "#9fb0d8", marginTop: 6, fontSize: 14 }}>{d}</div></div>))}
      </div>
      <div style={{ position: "absolute", bottom: 10, left: 0, right: 0, textAlign: "center", fontSize: 12, color: "#6b7fb0" }}>sample page · commit {commit}</div>
    </div>
  );
}

export function PreviewTab({ release, releases, onPick }: { release: Release; releases: Release[]; onPick: (v: string) => void }) {
  const toast = useToast();
  const [phase, setPhase] = useState<Phase>("ok"); const [stage, setStage] = useState<number>(BUILD_STAGES.length); const [vp, setVp] = useState<VP>("desktop");
  const [shown, setShown] = useState<{ version: string; commit: string }>(() => { const ok = release.runnable ? release : releases.find((r) => r.runnable) ?? release; return { version: ok.version, commit: ok.commit }; }); // last verified preview
  const [failNext, setFailNext] = useState(false); const [logs, setLogs] = useState<string[]>([`${new Date().toLocaleTimeString()} preview service ready (sample): ${release.version} @ ${release.commit}`]);
  const [auto, setAuto] = useState(0); const timers = useRef<number[]>([]); const frame = useRef<HTMLDivElement>(null); const [scale, setScale] = useState(.5);
  const log = useCallback((t: string) => setLogs((l) => [...l.slice(-60), `${new Date().toLocaleTimeString()} ${t}`]), []);
  const clear = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => clear, []);
  const size = VIEWPORTS[vp];
  useEffect(() => {
    const el = frame.current; if (!el) return;
    const f = () => setScale(Math.min(1, (el.clientWidth - 24) / size.w, (el.clientHeight - 24) / size.h)); f();
    const ro = new ResizeObserver(f); ro.observe(el); return () => ro.disconnect();
  }, [size.w, size.h]);

  const build = useCallback((why: string) => {
    clear(); setPhase("building"); setStage(0); log(`${why}: building ${release.version} @ ${release.commit}`);
    let t = 0; const willFail = failNext || !release.runnable;
    BUILD_STAGES.forEach((s, i) => {
      t += s.ms;
      timers.current.push(window.setTimeout(() => {
        if (willFail && s.id === "test") { setStage(i); setPhase("failed"); log(`ERROR test: ${release.tests.total - release.tests.passed || 3} failing tests. Keeping last verified preview ${shown.version} @ ${shown.commit}.`); setFailNext(false); clear(); return; }
        setStage(i + 1); log(`${s.label}: ${s.log.replace("{commit}", release.commit).replace("{tests}", String(release.tests.total))}`);
        if (s.id === "test") timers.current.push(window.setTimeout(() => setPhase("restarting"), 50));
        if (i === BUILD_STAGES.length - 1) { setPhase("ok"); setShown({ version: release.version, commit: release.commit }); log("Preview verified and swapped in."); }
      }, t));
    });
  }, [release, failNext, log, shown]);
  // Selecting another edition restarts the preview (Run).
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } build("Run"); /* eslint-disable-next-line */ }, [release.version]);
  const stageCommit = () => { setAuto((n) => n + 1); build("GM stored results in GitHub (stage commit)"); toast("Simulated stage commit: the preview service restarts so the results show up", "info"); };

  const health = phase === "ok" ? ["ok", "Healthy"] : phase === "failed" ? ["bad", "Build failed"] : ["warn", "Restarting"];
  const hc = health[0] === "ok" ? "var(--ax-ok)" : health[0] === "bad" ? "var(--ax-bad)" : "var(--ax-warn)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(300px, 32%) 1fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateRows: "auto auto 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="Preview environment" icon={ShieldCheck} help="The preview window reflects updates made during development. The GM stores results in GitHub at certain stages; the preview service machine then restarts so the results are reflected. It is isolated: it shows a sample page only and never loads an external URL."
          actions={<Pill c="var(--ax-info)" solid>Preview</Pill>}>
          <div className="ax-kv">
            <span className="ax-muted">Edition</span><select className="ax-select" style={{ padding: "3px 8px" }} value={release.version} onChange={(e) => onPick(e.target.value)} aria-label="Edition to preview">{releases.map((r) => <option key={r.id} value={r.version}>{r.version}{r.runnable ? "" : " (failed)"}</option>)}</select>
            <span className="ax-muted">Branch</span><span className="ax-mono">{release.branch}</span>
            <span className="ax-muted">Commit</span><span className="ax-mono ax-flex"><GitCommit size={13} aria-hidden />{release.commit}</span>
            <span className="ax-muted">Shown now</span><span className="ax-mono">{shown.version} @ {shown.commit}</span>
            <span className="ax-muted">Health</span><span className="ax-flex" style={{ color: hc }}><HeartPulse size={14} aria-hidden /><b>{health[1]}</b>{health[0] === "ok" && <motion.i style={{ width: 8, height: 8, borderRadius: 8, background: hc }} animate={{ opacity: [1, .3, 1] }} transition={{ repeat: Infinity, duration: 1.5 }} />}</span>
          </div>
          <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 3 }} role="list" aria-label="Build stages">
            {BUILD_STAGES.map((s, i) => { const done = i < stage, cur = i === stage && phase === "building", bad = i === stage && phase === "failed"; const c = bad ? "var(--ax-bad)" : done ? "var(--ax-ok)" : cur ? "var(--ax-info)" : "var(--ax-faint)";
              return (<div key={s.id} role="listitem" style={{ flex: 1, textAlign: "center", minWidth: 0 }}>
                <motion.div style={{ margin: "0 auto", width: 22, height: 22, borderRadius: 22, display: "grid", placeItems: "center", border: `2px solid ${c}`, color: c }} animate={cur ? { scale: [1, 1.15, 1] } : {}} transition={{ repeat: Infinity, duration: 1 }}>
                  {bad ? <XCircle size={13} aria-label="failed" /> : done ? <CheckCircle2 size={13} aria-label="done" /> : cur ? <Loader2 size={13} className="ax-spin" aria-label="running" /> : <span className="ax-xs">{i + 1}</span>}</motion.div>
                <div className="ax-xs" style={{ color: c, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.label}</div></div>); })}
          </div>
        </Panel>
        <Panel i={1} title="Controls" icon={Zap} help="Refresh rebuilds this edition. Stage commit simulates the GM storing results in GitHub, which restarts the preview. Fail next build shows how the last verified preview stays on screen when a build fails.">
          <div className="ax-flex" style={{ flexWrap: "wrap" }}>
            <IconBtn icon={RefreshCw} label="Refresh preview (rebuild)" onClick={() => build("Refresh")} />
            <IconBtn icon={Zap} label="Simulate stage commit (GM stores results; preview restarts)" tone="gold" onClick={stageCommit} />
            <IconBtn icon={Bug} label={failNext ? "Next build will fail (click to cancel)" : "Make the next build fail (demo)"} tone={failNext ? "bad" : undefined} onClick={() => setFailNext(!failNext)} />
            <IconBtn icon={ExternalLink} label="Open preview in a new tab" onClick={() => window.open(window.location.pathname + href("preview", release.version), "_blank", "noopener")} />
            <span className="ax-spacer" /><span className="ax-xs ax-muted">{auto} stage commits this session</span>
          </div>
        </Panel>
        <Panel i={2} title="Build log" icon={Terminal} help="Output of the preview build (sample, generated in the browser)." >
          <LogView logs={logs} />
        </Panel>
      </div>
      <Panel i={1} title="Live Preview" icon={Monitor} hl sub={<><Pill c="var(--ax-warn)" solid>PREVIEW</Pill> sample, isolated</>}
        help="A sandboxed in-page mock of the mission's product (a mini AXoR landing page). It loads no real external site. Use the device presets to check responsive layouts."
        actions={<Seg label="Device viewport" value={vp} onChange={setVp} items={(Object.keys(VIEWPORTS) as VP[]).map((k) => ({ id: k, label: VIEWPORTS[k].label, icon: VIEWPORTS[k].icon }))} />}>
        <div ref={frame} style={{ height: "100%", display: "grid", placeItems: "center", background: "repeating-conic-gradient(color-mix(in srgb, var(--ax-border) 25%, transparent) 0 25%, transparent 0 50%) 0 0 / 18px 18px", borderRadius: 10, overflow: "hidden", position: "relative" }}>
          <motion.div layout style={{ width: size.w * scale, height: size.h * scale, position: "relative", borderRadius: 10, border: "2px solid var(--ax-accent)", overflow: "hidden", boxShadow: "0 8px 30px rgb(0 0 0 / .35)", background: "#000" }}>
            <div style={{ width: size.w, height: size.h, transform: `scale(${scale})`, transformOrigin: "0 0" }}><MockSite version={shown.version} commit={shown.commit} /></div>
            <div style={{ position: "absolute", bottom: 6, left: 6, background: "var(--ax-warn)", color: "#1b1405", fontSize: 10.5, fontWeight: 800, padding: "2px 8px", borderRadius: 6, letterSpacing: 1 }}>PREVIEW · SAMPLE</div>
            <AnimatePresence>
              {(phase === "building" || phase === "restarting") && <motion.div key="r" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} style={{ position: "absolute", inset: 0, background: "rgb(6 10 24 / .82)", display: "grid", placeItems: "center", color: "#e8eefc", textAlign: "center" }} role="status">
                <div><motion.span style={{ display: "inline-block" }} animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.1, ease: "linear" }}><RefreshCw size={34} aria-hidden /></motion.span>
                  <div style={{ fontWeight: 700, marginTop: 8, fontSize: 15 }}>Restarting after stage commit…</div><div style={{ fontSize: 12, color: "#9fb0d8" }}>{BUILD_STAGES[Math.min(stage, BUILD_STAGES.length - 1)].label} · {release.version}</div></div></motion.div>}
            </AnimatePresence>
          </motion.div>
          {phase === "failed" && <motion.div initial={{ y: -20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="ax-tile ax-flex" style={{ position: "absolute", top: 8, left: 8, right: 8, borderColor: "var(--ax-bad)", background: "var(--ax-panel2)", zIndex: 3 }} role="alert">
            <AlertTriangle size={16} className="ax-bad" aria-hidden /><span className="ax-small"><b>Build of {release.version} failed.</b> Still showing the last verified preview ({shown.version} @ {shown.commit}).</span></motion.div>}
        </div>
      </Panel>
    </div>
  );
}
function LogView({ logs }: { logs: string[] }) {
  const r = useRef<HTMLDivElement>(null); useEffect(() => { r.current?.scrollTo({ top: 1e5 }); }, [logs.length]);
  return <div ref={r} className="ax-mono ax-xs" style={{ height: "100%", overflow: "auto" }} role="log" aria-label="Build log">{logs.map((l, i) => <motion.div key={i} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} style={{ color: l.includes("ERROR") ? "var(--ax-bad)" : undefined }}><ScrollText size={0} aria-hidden />{l}</motion.div>)}</div>;
}
