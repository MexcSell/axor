// General Manager chat (gm_chat.py, D-039): the header's chat button opens it on every page. Same thread and API as the classic UI
// (frontend/gm-chat.js): an assignment becomes a real mission (/api/mos), shown as a card that follows its status; a mission
// waiting for answers is answered in the card. Signed out, or without Mission Control access, it says so and sends nothing:
// there is no sample mode for this chat, because every message here can start real work.
import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { motion } from "framer-motion";
import { FileText, Image as ImageIcon, Paperclip, RotateCcw, Send, Target, X } from "lucide-react";
import { IconBtn, useToast } from "../ui/kit";
import { useStore } from "../data/store";
import { go, useRoute } from "./router";

interface GmFile { id: number; name: string; kind: string; url?: string | null }
interface GmMsg { id: number; role: "user" | "gm"; text: string; kind: string; mission_id: number | null; files: GmFile[]; at: number; pending?: boolean }
interface GmCard { id: number; gone?: boolean; title?: string; status?: string; status_label?: string; stage?: string; doing?: string; pause_reason?: string | null;
  summary?: string; error?: string | null; approval?: string | null; questions?: (string | { question?: string; text?: string })[] }
interface Thread { messages: GmMsg[]; missions: Record<string, GmCard>; limits?: { files: number; image_mb: number; file_mb: number }; kept_files?: boolean }

const ACTIVE = ["queued", "running", "needs_input", "paused"];
const TONE: Record<string, string> = { queued: "run", running: "run", needs_input: "wait", paused: "warn", delivered: "ok", failed: "bad", cancelled: "off" };

async function call<T>(url: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(url, { method, credentials: "same-origin", headers: { "X-Requested-With": "scout", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(typeof d?.detail === "string" ? d.detail : `AXoR answered ${r.status}.`) as Error & { status?: number }; e.status = r.status; throw e; }
  return d as T;
}

const readUrl = (f: File) => new Promise<string>((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = () => bad(r.error); r.readAsDataURL(f); });
const when = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Card({ c, onOpen, onAnswered }: { c?: GmCard; onOpen: (id: number) => void; onAnswered: (id: number) => void }) {
  const toast = useToast();
  const [ans, setAns] = useState<string[]>([]), [sending, setSending] = useState(false);
  if (!c) return null;
  if (c.gone) return <div className="ax-gm-card"><span className="ax-gm-st off">Removed</span> Mission #{c.id} is no longer in Mission Control.</div>;
  const q = c.questions ?? [];
  const active = ACTIVE.includes(c.status ?? "");
  const submit = async () => {
    const a = q.map((_, i) => (ans[i] ?? "").trim());
    if (a.some((x) => !x)) { toast("Answer every question (\"you decide\" is an answer).", "info"); return; }
    setSending(true);
    try { await call(`/api/mos/missions/${c.id}/answer`, "POST", { answers: a }); toast(`Mission #${c.id} goes on`, "ok"); onAnswered(c.id); }
    catch (e) { toast((e as Error).message, "warn"); }
    finally { setSending(false); }
  };
  return (
    <div className="ax-gm-card">
      <div className="ax-gm-card-top"><span className={`ax-gm-st ${TONE[c.status ?? ""] ?? "off"}`}>{c.status_label ?? c.status}</span><b>#{c.id} {c.title}</b></div>
      {c.doing ? <p>{c.doing}</p> : active && c.stage ? <p>Stage: {c.stage}</p> : null}
      {c.pause_reason && <p className="ax-warn">{c.pause_reason}</p>}
      {c.summary && !active && <p>{c.summary}</p>}
      {c.error && c.status === "failed" && <p className="ax-bad">{c.error}</p>}
      {q.length > 0 && (
        <form className="ax-gm-answer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          {q.map((x, i) => (
            <label key={i}>{typeof x === "string" ? x : x.question ?? x.text ?? ""}
              <textarea className="ax-textarea" rows={2} maxLength={1000} placeholder="Your answer (or: you decide)" value={ans[i] ?? ""}
                onChange={(e) => setAns((p) => { const n = [...p]; n[i] = e.target.value; return n; })} /></label>))}
          <button type="submit" className="ax-btn gold" disabled={sending}>Send answers</button>
        </form>)}
      {c.status === "needs_input" && !q.length && <p className="ax-warn">A decision waits for you in Mission Control.</p>}
      {c.approval && c.status !== "needs_input" && <p className="ax-warn">Waiting for your approval in Mission Control: {c.approval}.</p>}
      <button type="button" className="ax-btn" onClick={() => onOpen(c.id)}><Target size={14} aria-hidden /> Open in Mission Control</button>
    </div>
  );
}

export function GmChat({ onClose, onNeeds }: { onClose: () => void; onNeeds?: (n: number) => void }) {
  const me = useStore((s) => s.me);
  const route = useRoute();
  const toast = useToast();
  const [msgs, setMsgs] = useState<GmMsg[]>([]), [cards, setCards] = useState<Record<string, GmCard>>({});
  const [files, setFiles] = useState<GmFile[]>([]), [text, setText] = useState("");
  const [busy, setBusy] = useState(false), [uploading, setUploading] = useState(0), [state, setState] = useState<"loading" | "ready" | "off" | "signin">("loading");
  const [offWhy, setOffWhy] = useState(""), [drop, setDrop] = useState(false);
  const limits = useRef({ files: 10, image_mb: 5, file_mb: 20 });
  const log = useRef<HTMLDivElement>(null), box = useRef<HTMLTextAreaElement>(null), picker = useRef<HTMLInputElement>(null);
  const cardsRef = useRef(cards); cardsRef.current = cards;

  const take = useCallback((d: Thread, all: boolean) => {
    setMsgs((p) => all ? d.messages : [...p.filter((m) => !m.pending), ...d.messages.filter((m) => !p.some((x) => x.id === m.id))]);
    setCards((p) => ({ ...p, ...d.missions }));
    if (d.limits) limits.current = d.limits;
  }, []);

  useEffect(() => {
    if (!me) { setState("signin"); return; }
    call<Thread>("/api/gm").then((d) => { take(d, true); setState("ready"); })
      .catch((e: Error & { status?: number }) => { setState(e.status === 401 ? "signin" : "off"); setOffWhy(e.message); });
  }, [me, take]);

  useEffect(() => {  // while open: the cards follow their missions
    if (state !== "ready") return;
    const t = window.setInterval(async () => {
      const ids = Object.values(cardsRef.current).filter((c) => ACTIVE.includes(c.status ?? "") || c.approval).map((c) => c.id);
      if (!ids.length) return;
      try { const got = await call<Record<string, GmCard>>("/api/gm/missions", "POST", { ids }); setCards((p) => ({ ...p, ...got })); } catch { /* next tick */ }
    }, 8000);
    return () => window.clearInterval(t);
  }, [state]);

  useEffect(() => { onNeeds?.(Object.values(cards).filter((c) => c.status === "needs_input" || c.approval).length); }, [cards, onNeeds]);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [msgs, busy]);
  useEffect(() => { if (state === "ready") box.current?.focus(); }, [state]);

  const where = () => ({ page: route.page, path: window.location.pathname + window.location.hash });

  const send = async (extra?: { mission?: boolean }) => {
    const t = text.trim();
    if (busy || uploading || (!t && !files.length)) return;
    const keep = files;
    setBusy(true); setText(""); setFiles([]);
    setMsgs((p) => [...p, { id: -1, role: "user", text: t, kind: "", mission_id: null, files: keep, at: Date.now() / 1000, pending: true }]);
    try {
      const d = await call<Thread>("/api/gm/messages", "POST", { text: t, attachments: keep.map((f) => f.id), ...where(), ...extra });
      take(d, false);
      if (d.kept_files) setFiles(keep);
    } catch (e) {
      setMsgs((p) => p.filter((m) => !m.pending)); setText(t); setFiles(keep);
      toast((e as Error).message, "warn");
    } finally { setBusy(false); box.current?.focus(); }
  };

  const asMission = async (id: number) => {
    if (busy) return; setBusy(true);
    try { take(await call<Thread>(`/api/gm/messages/${id}/mission`, "POST", where()), false); }
    catch (e) { toast((e as Error).message, "warn"); }
    finally { setBusy(false); }
  };

  const addFiles = async (list: FileList | File[]) => {
    for (const f of Array.from(list)) {
      if (files.length + uploading >= limits.current.files) { toast(`Up to ${limits.current.files} files with one message.`, "info"); break; }
      const img = f.type.startsWith("image/");
      if (f.size > (img ? limits.current.image_mb : limits.current.file_mb) * 1e6) { toast(`${f.name}: too large.`, "warn"); continue; }
      const name = f.name && f.name !== "image.png" ? f.name : `pasted-${Date.now()}.${(f.type.split("/")[1] || "png").replace("jpeg", "jpg")}`;
      setUploading((n) => n + 1);
      try {
        const url = await readUrl(f);
        const u = await call<{ id: number; name?: string; kind?: string }>("/api/mos/uploads", "POST", { filename: name, data: url.split(",")[1] ?? "" });
        setFiles((p) => [...p, { id: u.id, name: u.name ?? name, kind: u.kind ?? (img ? "image" : "document"), url: img && /^data:image\/(png|jpe?g|gif|webp);base64,/.test(url) ? url : null }]);
      } catch (e) { toast((e as Error).message, "warn"); }
      finally { setUploading((n) => n - 1); }
    }
  };

  const unfile = (id: number) => { setFiles((p) => p.filter((f) => f.id !== id)); call(`/api/mos/uploads/${id}`, "DELETE").catch(() => {}); };
  const clear = async () => {
    if (!window.confirm("Clear this chat? Your missions stay in Mission Control.")) return;
    try { await call("/api/gm", "DELETE"); setMsgs([]); setCards({}); } catch (e) { toast((e as Error).message, "warn"); }
  };
  const open = (id: number) => { go("control", `mx:${id}`); if (window.innerWidth < 760) onClose(); };
  const answered = async (id: number) => { try { const got = await call<Record<string, GmCard>>("/api/gm/missions", "POST", { ids: [id] }); setCards((p) => ({ ...p, ...got })); } catch { /* the poll catches up */ } };

  const onPaste = (e: ClipboardEvent) => { const fs = Array.from(e.clipboardData?.files ?? []); if (fs.length) { e.preventDefault(); addFiles(fs); } };
  const onDrop = (e: DragEvent) => { if (e.dataTransfer?.files?.length) { e.preventDefault(); setDrop(false); addFiles(e.dataTransfer.files); } };

  const last = msgs[msgs.length - 1], prev = msgs[msgs.length - 2];
  const offerId = last?.role === "gm" && last.kind === "reply" && prev?.role === "user" && !prev.mission_id && prev.id > 0 ? prev.id : null;

  return (
    <motion.section id="ax-gm" className={`ax-gm ${drop ? "drop" : ""}`} role="dialog" aria-label="General Manager chat" initial={{ opacity: 0, y: -8, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6 }} transition={{ duration: .16 }} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      onPaste={onPaste} onDragOver={(e) => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); setDrop(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDrop(false); }} onDrop={onDrop}>
      <header className="ax-gm-head">
        <span className="ax-gm-av" aria-hidden>GM</span>
        <span className="ax-gm-who"><b>General Manager</b><small>Give an assignment: it becomes a mission</small></span>
        {state === "ready" && <IconBtn icon={RotateCcw} label="Clear this chat" size="sm" onClick={clear} />}
        <IconBtn icon={X} label="Close the chat" size="sm" onClick={onClose} />
      </header>
      <div className="ax-gm-log" ref={log} aria-live="polite">
        {state === "loading" && <p className="ax-muted">Loading…</p>}
        {state === "signin" && <div className="ax-gm-msg gm"><span className="ax-gm-av sm" aria-hidden>GM</span><div className="ax-gm-bub"><p>Sign in to AXoR (classic UI) to give me assignments: each one starts real work, so this chat has no sample mode.</p>
          <a className="ax-btn" href="/">Open the classic UI</a></div></div>}
        {state === "off" && <div className="ax-gm-msg gm err"><span className="ax-gm-av sm" aria-hidden>GM</span><div className="ax-gm-bub"><p>{offWhy || "The General Manager isn't available to your account."}</p></div></div>}
        {state === "ready" && !msgs.length && (
          <div className="ax-gm-msg gm"><span className="ax-gm-av sm" aria-hidden>GM</span><div className="ax-gm-bub">
            <p>Hi {me?.name ?? "there"}! I'm the General Manager. Tell me what you need: update or fix a page, correct an error, add a feature, build a program, research something.
              Each assignment becomes a mission the company plans, builds and checks; you'll see its progress here.</p>
            <p className="ax-gm-note">Changes to AXoR itself come back ready to review; putting them on the live site needs the Owner's approval.</p></div></div>)}
        {msgs.map((m) => (
          <div key={`${m.id}-${m.at}`} className={`ax-gm-msg ${m.role === "user" ? "me" : "gm"} ${m.kind === "error" ? "err" : ""}`}>
            {m.role === "gm" && <span className="ax-gm-av sm" aria-hidden>GM</span>}
            <div className="ax-gm-bub">
              {m.text && <p>{m.text}</p>}
              {m.files.length > 0 && <div className="ax-gm-chips">{m.files.map((f) => <span key={f.id} className="ax-gm-chip">{f.kind === "image" ? <ImageIcon size={13} aria-hidden /> : <FileText size={13} aria-hidden />}{f.name}</span>)}</div>}
              {m.kind === "mission" && m.mission_id != null && <Card c={cards[String(m.mission_id)]} onOpen={open} onAnswered={answered} />}
              {offerId != null && m === last && <button type="button" className="ax-btn" disabled={busy} onClick={() => asMission(offerId)}><Target size={14} aria-hidden /> Start as a mission</button>}
              <small className="ax-gm-at">{m.pending ? "Sending…" : when(m.at)}</small>
            </div>
          </div>))}
        {busy && <div className="ax-gm-msg gm"><span className="ax-gm-av sm" aria-hidden>GM</span><div className="ax-gm-bub"><p className="ax-gm-typing">Thinking<span>.</span><span>.</span><span>.</span></p></div></div>}
      </div>
      {state === "ready" && (
        <form className="ax-gm-compose" onSubmit={(e) => { e.preventDefault(); send(); }}>
          {(files.length > 0 || uploading > 0) && <div className="ax-gm-chips">
            {files.map((f) => <span key={f.id} className="ax-gm-chip">{f.url ? <img src={f.url} alt="" /> : <FileText size={13} aria-hidden />}{f.name}
              <button type="button" aria-label={`Remove ${f.name}`} onClick={() => unfile(f.id)}><X size={12} aria-hidden /></button></span>)}
            {uploading > 0 && <span className="ax-gm-chip">Uploading…</span>}</div>}
          <div className="ax-gm-row">
            <IconBtn icon={Paperclip} label="Attach pictures or documents" onClick={() => picker.current?.click()} />
            <input ref={picker} type="file" multiple hidden onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
            <textarea ref={box} className="ax-textarea" rows={2} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} aria-label="Message to the General Manager"
              placeholder="Tell the General Manager what you need… (paste a screenshot, Enter to send)"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
            <IconBtn icon={Send} label="Send" tone="gold" type="submit" disabled={busy || uploading > 0} />
          </div>
        </form>)}
    </motion.section>
  );
}
