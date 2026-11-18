import { useMemo, useRef, useState, type CSSProperties } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, ClipboardPlus, FileText, Github, Globe, Image as ImageIcon, Lock, Paperclip, Play, ShieldCheck, Sparkles, Trash2, Wand2 } from "lucide-react";
import { Btn, Help, IconBtn, Modal, Pill, useToast } from "../ui/kit";
import { addMission, liveMode, startLiveMission, suggestTitle } from "../data/store";
import { go } from "../app/router";

// Add Mission (readme §2; CREATE-01..06; MIS-001..006). Text, documents, images, GitHub URLs and web links.
// No GitHub URL → the GM proposes a new repository, created only after explicit approval with an authorized GitHub account.
const STEPS = ["Details", "Resources", "Budget & Policy", "Review"] as const;
const GH = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;
const MAX_MB = 25;

interface Att { name: string; size: number; kind: "doc" | "image"; file?: File }
export function AddMissionModal({ open, onClose, initialTitle }: { open: boolean; onClose: () => void; initialTitle?: string }) {
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState(initialTitle ?? ""), [text, setText] = useState("");
  const [atts, setAtts] = useState<Att[]>([]), [urls, setUrls] = useState<string[]>([]), [urlDraft, setUrlDraft] = useState("");
  const [repoMode, setRepoMode] = useState<"auto" | "new" | "none">("auto"), [repoPrivate, setRepoPrivate] = useState(true), [repoName, setRepoName] = useState("");
  const [budget, setBudget] = useState(500), [dueDays, setDueDays] = useState(14), [priority, setPriority] = useState<"High" | "Medium" | "Low">("Medium"), [autonomy, setAutonomy] = useState("L3");
  const [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const key = useRef(`mk-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const docRef = useRef<HTMLInputElement>(null), imgRef = useRef<HTMLInputElement>(null), urlRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const ghUrls = urls.filter((u) => GH.test(u)), webUrls = urls.filter((u) => !GH.test(u));
  const needsRepo = ghUrls.length === 0 && repoMode !== "none";
  const gmTitle = useMemo(() => title.trim() || suggestTitle(text), [title, text]);
  const dirty = !!(text || title || atts.length || urls.length);

  const reset = () => { setStep(0); setTitle(""); setText(""); setAtts([]); setUrls([]); setUrlDraft(""); setConsent(false); setBusy(false); setErr(null); key.current = `mk-${Date.now()}`; };
  const close = () => {
    if (busy) { toast("The mission is being started: wait for AXoR's answer.", "info"); return; }
    if (dirty && !window.confirm("Discard this mission draft?")) return; reset(); onClose();
  };
  const addFiles = (list: FileList | null, kind: Att["kind"]) => {
    const add: Att[] = []; for (const f of [...(list ?? [])]) { if (f.size > MAX_MB * 1048576) { toast(`${f.name} is over ${MAX_MB} MB`, "warn"); continue; } add.push({ name: f.name, size: f.size, kind, file: f }); }
    setAtts((a) => [...a, ...add]);
  };
  const addUrl = () => {
    const u = urlDraft.trim(); if (!u) return;
    try { const p = new URL(u); if (!/^https?:$/.test(p.protocol)) throw new Error(); } catch { setErr("Enter a full http(s) address, e.g. https://github.com/owner/repo"); return; }
    setErr(null); setUrls((x) => (x.includes(u) ? x : [...x, u])); setUrlDraft("");
  };
  const valid = [text.trim().length >= 10 || atts.length > 0, true, Number.isFinite(budget) && budget > 0 && budget <= 1e7 && Number.isFinite(dueDays) && dueDays >= 1 && dueDays <= 3650, !needsRepo || consent];
  const next = () => { if (!valid[step]) { setErr(step === 0 ? "Describe the mission (at least 10 characters) or attach a document." : "Fill in the required fields."); return; } setErr(null); setStep((s) => Math.min(3, s + 1)); };
  const start = () => {
    if (busy) return; // MIS-005: no duplicate missions
    if (!valid.every(Boolean)) { setErr(needsRepo ? "Approve the repository creation or choose “Continue without repository”." : "Check the earlier steps."); return; }
    setBusy(true);
    const draft = { key: key.current, text: text.trim(), title: title.trim() || undefined, files: atts.filter((a) => a.kind === "doc").map((a) => a.name), images: atts.filter((a) => a.kind === "image").map((a) => a.name),
      githubUrls: ghUrls, webUrls, priority, budget, dueDays, autonomy, createRepo: needsRepo, repoName: repoName || undefined, repoPrivate };
    if (liveMode()) {
      // Live: AXoR starts the mission (POST /api/mos/missions) after staging the attachments; it names it from the goal.
      toast("Starting the mission in AXoR…", "info");
      startLiveMission(draft, atts.map((a) => a.file).filter((f): f is File => !!f)).then((r) => {
        if ("error" in r) { setErr(r.error); setBusy(false); return; }
        toast(r.id ? `Mission ${r.id} started in AXoR. Opening Mission Control…` : "Mission started in AXoR.", "ok");
        reset(); onClose(); if (r.id) go("control", r.id, { tab: "overview" }); else go("missions");
      });
      return;
    }
    let id: string;
    try {
      id = addMission({ key: key.current, text: text.trim(), title: title.trim() || undefined, files: atts.filter((a) => a.kind === "doc").map((a) => a.name), images: atts.filter((a) => a.kind === "image").map((a) => a.name),
        githubUrls: ghUrls, webUrls, priority, budget, dueDays, autonomy, createRepo: needsRepo, repoName: repoName || undefined, repoPrivate });
    } catch (e) { setErr((e as Error).message); setBusy(false); return; }
    toast(`Mission ${id} started. Opening Mission Control…`);
    reset(); onClose(); go("control", id, { tab: "overview" });
  };

  return (
    <Modal open={open} onClose={close} title="Add New Mission" icon={ClipboardPlus} width={900} label="Add mission"
      foot={<>
        {step > 0 && <IconBtn icon={ArrowLeft} label="Back" onClick={() => setStep(step - 1)} />}
        {err && <span className="ax-small ax-bad" role="alert">{err}</span>}
        <span className="ax-spacer" />
        {step < 3 ? <Btn icon={ArrowRight} onClick={next}>Next</Btn> : null}
        <Btn tone="gold" lg icon={Play} onClick={step === 3 ? start : () => { if (valid[0]) setStep(3); else next(); }} disabled={busy} aria-busy={busy}>{busy ? "Starting…" : "Start Mission"}</Btn>
      </>}>
      <ol className="ax-flex" style={{ listStyle: "none", padding: 0, margin: "0 0 14px", gap: 6, justifyContent: "center" }} aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s}><motion.button type="button" className="ax-flex" onClick={() => (i <= step || valid.slice(0, i).every(Boolean)) && setStep(i)} aria-current={i === step ? "step" : undefined}
            style={{ border: 0, background: "transparent", cursor: "pointer", gap: 6, color: i === step ? "var(--ax-text)" : "var(--ax-muted)", fontWeight: i === step ? 700 : 500 }} whileHover={{ y: -1 }}>
            <motion.span animate={{ scale: i === step ? 1.12 : 1 }} style={{ width: 22, height: 22, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700,
              background: i < step ? "var(--ax-ok)" : i === step ? "var(--ax-info)" : "var(--ax-panel2)", color: i <= step ? "#fff" : "var(--ax-muted)", border: "1px solid var(--ax-border)" }}>{i + 1}</motion.span>{s}
          </motion.button>{i < 3 && <span className="ax-faint" aria-hidden> — </span>}</li>))}
      </ol>
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 18, minHeight: 300 }}>
        <motion.div aria-hidden style={{ display: "grid", placeItems: "center" }} animate={{ y: [0, -8, 0] }} transition={{ duration: 3.5, repeat: Infinity }}>
          <svg viewBox="0 0 160 180" width="170">
            <defs><linearGradient id="cb" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="var(--ax-accent)" /><stop offset="100%" stopColor="var(--ax-accent2)" /></linearGradient></defs>
            <ellipse cx="80" cy="168" rx="62" ry="9" fill="var(--ax-accent2)" opacity=".35" />
            <rect x="28" y="22" width="96" height="128" rx="12" fill="var(--ax-panel2)" stroke="url(#cb)" strokeWidth="3" />
            <rect x="56" y="12" width="40" height="18" rx="6" fill="url(#cb)" />
            {[52, 72, 92].map((y) => <rect key={y} x="44" y={y} width="62" height="6" rx="3" fill="var(--ax-faint)" />)}
            <circle cx="112" cy="132" r="22" fill="url(#cb)" /><path d="M112 121 v22 M101 132 h22" stroke="#0b1020" strokeWidth="4" strokeLinecap="round" />
          </svg>
        </motion.div>
        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: .18 }} className="ax-col" style={{ gap: 12 }}>
            {step === 0 && <>
              <div className="ax-field"><label htmlFor="am-title">Mission Title <span className="ax-faint">(optional: the GM names it from the content)</span></label>
                <input id="am-title" className="ax-input" placeholder="e.g., Build a customer portal" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
              <div className="ax-field"><label htmlFor="am-desc">Mission Description *</label>
                <textarea id="am-desc" className="ax-textarea" rows={6} placeholder="Describe the goal, expected outcome, and key requirements…" value={text} onChange={(e) => setText(e.target.value)} required aria-required /></div>
              <div className="ax-flex" style={{ flexWrap: "wrap" }}>
                <input ref={docRef} type="file" multiple hidden accept=".pdf,.doc,.docx,.md,.txt,.csv,.xlsx,.pptx,.json" onChange={(e) => addFiles(e.target.files, "doc")} />
                <input ref={imgRef} type="file" multiple hidden accept="image/*" onChange={(e) => addFiles(e.target.files, "image")} />
                <IconBtn icon={Paperclip} label="Attach files" onClick={() => docRef.current?.click()} />
                <IconBtn icon={FileText} label="Attach documents (PDF, Word, Markdown, text, spreadsheets)" onClick={() => docRef.current?.click()} />
                <IconBtn icon={ImageIcon} label="Attach images" onClick={() => imgRef.current?.click()} />
                <IconBtn icon={Github} label="Add GitHub repository address" onClick={() => { setUrlDraft("https://github.com/"); urlRef.current?.focus(); }} />
                <IconBtn icon={Globe} label="Add website / reference link" onClick={() => { setUrlDraft("https://"); urlRef.current?.focus(); }} />
                <input ref={urlRef} className="ax-input" style={{ flex: 1, minWidth: 180 }} placeholder="GitHub or web address, then Enter" value={urlDraft} onChange={(e) => setUrlDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addUrl(); } }} aria-label="GitHub or web address" />
                <span className="ax-xs ax-muted">Up to {MAX_MB} MB per file</span>
              </div>
              <AttList atts={atts} urls={urls} onRemove={(n) => setAtts(atts.filter((a) => a.name !== n))} onRemoveUrl={(u) => setUrls(urls.filter((x) => x !== u))} />
              {(text || title) && <div className="ax-flex ax-small"><Wand2 size={14} className="ax-gold" aria-hidden /> GM title: <b>{gmTitle}</b></div>}
            </>}
            {step === 1 && <>
              <div className="ax-flex"><b>GitHub repository</b><Help title="Repository" body="If you give a GitHub address, AXoR verifies access and works on a dedicated mission branch; it never force-resets or overwrites your branches. Without one, the GM proposes a new repository that is created only after you approve it, through your connected GitHub authorization (not your e-mail address)." /></div>
              {ghUrls.length ? ghUrls.map((u) => <div key={u} className="ax-tile ax-flex"><Github size={16} aria-hidden /><span className="grow ax-mono">{u}</span><Pill c="var(--ax-ok)" icon={ShieldCheck}>access check on start</Pill></div>) : (
                <div className="ax-col">
                  {([["auto", "Create a new repository (after my approval)"], ["none", "Continue without a repository (artifacts stay in AXoR storage)"]] as const).map(([v, l]) => (
                    <label key={v} className="ax-flex ax-tile click" style={{ cursor: "pointer" }}><input type="radio" name="repo" checked={repoMode === v || (v === "auto" && repoMode !== "none")} onChange={() => setRepoMode(v)} />{l}</label>))}
                  {repoMode !== "none" && <div className="ax-grid2">
                    <div className="ax-field"><label htmlFor="am-repo">Repository name</label><input id="am-repo" className="ax-input" placeholder={gmTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")} value={repoName} onChange={(e) => setRepoName(e.target.value)} /></div>
                    <div className="ax-field"><label>Visibility</label><label className="ax-flex ax-small"><input type="checkbox" checked={repoPrivate} onChange={(e) => setRepoPrivate(e.target.checked)} /><Lock size={13} aria-hidden /> Private</label></div>
                  </div>}
                </div>)}
              <div className="ax-flex"><b>Attachments</b><span className="ax-xs ax-muted">scanned and treated as untrusted input</span></div>
              <AttList atts={atts} urls={webUrls} onRemove={(n) => setAtts(atts.filter((a) => a.name !== n))} onRemoveUrl={(u) => setUrls(urls.filter((x) => x !== u))} empty="No files or links: the GM will research from the description." />
              <div className="ax-tile ax-small"><b>Permissions the mission will request</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                <li>Read/write on {ghUrls[0] ?? (repoMode === "none" ? "no repository" : "the new repository")} (mission branches only)</li><li>Web research on approved sources</li><li>Mission workspace storage (isolated)</li></ul></div>
            </>}
            {step === 2 && <>
              <div className="ax-grid2">
                <div className="ax-field"><label htmlFor="am-budget">Budget cap (USD)</label><input id="am-budget" className="ax-input" type="number" min={10} value={budget} onChange={(e) => setBudget(+e.target.value)} /></div>
                <div className="ax-field"><label htmlFor="am-due">Target completion (days)</label><input id="am-due" className="ax-input" type="number" min={1} value={dueDays} onChange={(e) => setDueDays(+e.target.value)} /></div>
                <div className="ax-field"><label htmlFor="am-pri">Priority</label><select id="am-pri" className="ax-select" value={priority} onChange={(e) => setPriority(e.target.value as typeof priority)}><option>High</option><option>Medium</option><option>Low</option></select></div>
                <div className="ax-field"><label htmlFor="am-auto">Autonomy level</label><select id="am-auto" className="ax-select" value={autonomy} onChange={(e) => setAutonomy(e.target.value)}>
                  <option value="L2">L2 – Approved tasks</option><option value="L3">L3 – Workflow autonomy (recommended)</option><option value="L4">L4 – Controlled evolution</option></select></div>
              </div>
              <div className="ax-tile ax-small ax-muted">The GM pauses non-critical work at 80% of the cap and asks you before exceeding it. Production deploys, spending above the cap, data exposure and structural changes always need your approval.</div>
            </>}
            {step === 3 && <>
              <dl className="ax-kv" style={{ gridTemplateColumns: "160px 1fr" }}>
                <dt>Title (GM)</dt><dd style={{ textAlign: "left" }}>{gmTitle}</dd>
                <dt>Objective</dt><dd style={{ textAlign: "left", fontWeight: 400 }}>{text || "—"}</dd>
                <dt>Inputs</dt><dd style={{ textAlign: "left" }}>{atts.length} file(s), {webUrls.length} link(s), {ghUrls.length} repo(s)</dd>
                <dt>Repository</dt><dd style={{ textAlign: "left" }}>{ghUrls[0] ?? (repoMode === "none" ? "None" : `New ${repoPrivate ? "private" : "public"} repo “${repoName || gmTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-")}” (needs approval)`)}</dd>
                <dt>Budget / due</dt><dd style={{ textAlign: "left" }}>${budget} · {dueDays} days (estimated) · {priority} · {autonomy}</dd>
                <dt>Plan</dt><dd style={{ textAlign: "left", fontWeight: 400 }}>GM drafts the charter → research → build on a mission branch → independent QA → version & preview → your review</dd>
              </dl>
              {needsRepo && <label className="ax-tile ax-flex" style={{ borderColor: "var(--ax-warn)", cursor: "pointer" }}>
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span className="ax-small">I approve creating a {repoPrivate ? "private" : "public"} GitHub repository with my connected GitHub account for this mission. <span className="ax-muted">(You can also approve it later in Approvals.)</span></span>
              </label>}
              <div className="ax-flex ax-small ax-muted"><Sparkles size={13} className="ax-gold" aria-hidden />After Start you land in Mission Control.</div>
            </>}
          </motion.div>
        </AnimatePresence>
      </div>
    </Modal>
  );
}

function AttList({ atts, urls, onRemove, onRemoveUrl, empty }: { atts: Att[]; urls: string[]; onRemove: (n: string) => void; onRemoveUrl: (u: string) => void; empty?: string }) {
  if (!atts.length && !urls.length) return empty ? <span className="ax-small ax-muted">{empty}</span> : null;
  return (
    <div className="ax-flex" style={{ flexWrap: "wrap", gap: 6 }}>
      {atts.map((a) => <motion.span key={a.name} className="ax-chip" initial={{ scale: .8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>{a.kind === "image" ? <ImageIcon size={11} aria-hidden /> : <FileText size={11} aria-hidden />}{a.name} <span className="ax-faint">{(a.size / 1024).toFixed(0)} KB</span>
        <button type="button" aria-label={`Remove ${a.name}`} onClick={() => onRemove(a.name)} style={{ border: 0, background: "none", color: "inherit", cursor: "pointer", padding: 0 }}><Trash2 size={11} /></button></motion.span>)}
      {urls.map((u) => <motion.span key={u} className="ax-chip" style={{ "--c": GH.test(u) ? "var(--ax-text)" : "var(--ax-accent2)" } as CSSProperties} initial={{ scale: .8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>{GH.test(u) ? <Github size={11} aria-hidden /> : <Globe size={11} aria-hidden />}{u}
        <button type="button" aria-label={`Remove ${u}`} onClick={() => onRemoveUrl(u)} style={{ border: 0, background: "none", color: "inherit", cursor: "pointer", padding: 0 }}><Trash2 size={11} /></button></motion.span>)}
    </div>
  );
}
