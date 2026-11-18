import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Ban, Check, ExternalLink, Globe, Loader2, Newspaper, Plus, RefreshCw, Rss, Send, ShieldAlert, Trash2, Undo2, X } from "lucide-react";
import { Btn, IconBtn, Modal, Pill, Progress, Seg, StatusPill, Switch, Time, useToast, Empty, progressColors } from "../../ui/kit";
import { AgentTag, Dropdown } from "../../ui/widgets";
import { addNewsSource, removeNewsSource, updateNewsSource, useStore } from "../../data/store";
// Only http(s) links are opened (GPT review #2, #6): external article URLs are untrusted.
function openSafe(url: string, toast: (t: string, k?: "ok" | "info" | "warn" | "bad") => void) {
  try { const u = new URL(url); if (u.protocol === "http:" || u.protocol === "https:") { window.open(u.toString(), "_blank", "noopener,noreferrer"); return; } } catch { /* fall through */ }
  toast("This link isn't a web address, so it won't be opened.", "warn");
}
import type { NewsSource } from "../../domain/types";
import { CITATIONS, CONCLUSIONS, CONTRADICTIONS, RECIPIENTS, RESEARCH_JOBS } from "./data";
import { KIND_C, KSTATUS, KStatus, host, type Learning } from "./shared";
import { go } from "../../app/router";

const wrap = { overflow: "auto", height: "100%" } as const;
const UNTRUSTED = "External content is untrusted input: it is scanned for prompt injection and instruction-like text, never executed, and only learned by the company after verification.";

/* ---------- Library ---------- */
export interface LibFilter { kind: string; owner: string; mission: string; time: string }
export function LibraryTab({ q, f, sel, setSel }: { q: string; f: LibFilter; sel: string; setSel: (id: string) => void }) {
  const items = useStore((s) => s.knowledge);
  const t = q.toLowerCase(), now = Date.now(), win = f.time === "24h" ? 864e5 : f.time === "7d" ? 7 * 864e5 : f.time === "30d" ? 30 * 864e5 : Infinity;
  const rows = items.filter((k) => (f.kind === "all" || k.kind === f.kind) && (f.owner === "all" || k.owner === f.owner) && (f.mission === "all" || k.scope === f.mission) && now - +new Date(k.updated) <= win
    && (!t || (k.title + k.tags.join(" ") + k.kind).toLowerCase().includes(t)));
  return (
    <div style={wrap}>
      <table className="ax-table"><thead><tr><th>Title</th><th>Type</th><th>Updated</th><th>Usage</th><th>Tags</th></tr></thead>
        <tbody>
          {rows.map((k, i) => (
            <motion.tr key={k.id} className={`click ${sel === k.id ? "sel" : ""}`} onClick={() => setSel(k.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(k.id)}
              initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .03 }} aria-label={`${k.title}, ${k.status}`}>
              <td><span className="ax-flex" style={{ gap: 5 }}><span style={{ color: KSTATUS[k.status].c }} title={KSTATUS[k.status].label}>{(() => { const I = KSTATUS[k.status].icon; return <I size={13} aria-label={KSTATUS[k.status].label} />; })()}</span><b className="ax-small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 150 }}>{k.title}</b></span></td>
              <td><Pill c={KIND_C[k.kind]}>{k.kind}</Pill></td><td className="ax-small" style={{ whiteSpace: "nowrap" }}><Time iso={k.updated} withDate /></td>
              <td className="ax-num">{k.citations * 4 + 10}</td>
              <td style={{ whiteSpace: "nowrap" }}>{k.tags.slice(0, 2).map((x) => <span key={x} className="ax-chip" style={{ marginRight: 3 }}>{x}</span>)}</td>
            </motion.tr>
          ))}
        </tbody></table>
      {!rows.length && <Empty icon={Globe} title="Nothing matches">Clear the search or filters to see the full library.</Empty>}
    </div>
  );
}

/* ---------- Research ---------- */
export function ResearchTab() {
  const toast = useToast();
  return (
    <div style={{ ...wrap, display: "grid", gridTemplateColumns: "1.1fr 1.1fr 1fr", gap: 12 }}>
      <section aria-label="Research jobs"><h3 className="ax-small ax-muted">Source collection jobs</h3>
        <div className="ax-rows">{RESEARCH_JOBS.map((j, i) => (
          <motion.div key={j.id} className="ax-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 3 }} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }}>
            <div className="ax-flex"><b className="grow ax-small" style={{ flex: 1 }}>{j.id} · {j.title}</b>
              <StatusPill small s={j.status === "running" ? "running" : j.status === "done" ? "done" : j.status === "review" ? "review" : "queued"} /></div>
            <Progress value={j.progress} label={`${j.title} ${j.progress}%`} thin />
            <div className="ax-flex ax-xs ax-muted"><AgentTag id={j.agent} size={16} /><span>{j.mission}</span><span>{j.sources} sources</span><span>data quality {j.quality || "n/a"}{j.quality ? "%" : ""}</span>
              <IconBtn icon={RefreshCw} label={`Re-run ${j.id} (sample: no live crawler)`} size="sm" tone="ghost" onClick={() => toast(`Sample mode: ${j.id} would be re-queued; no external fetch happens.`)} /></div>
          </motion.div>))}</div>
      </section>
      <section aria-label="Conclusions"><h3 className="ax-small ax-muted">Conclusions and their evidence</h3>
        <div className="ax-rows">{CONCLUSIONS.map((c, i) => (
          <motion.div key={c.id} className="ax-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 3 }} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }}>
            <span className="ax-small">{c.text}</span>
            <div className="ax-flex ax-xs"><Pill c="var(--ax-ok)" icon={Check}>{c.supports} supporting</Pill><Pill c={c.against ? "var(--ax-bad)" : "var(--ax-neutral)"} icon={c.against ? AlertTriangle : Ban}>{c.against} contradicting</Pill>
              <span className="ax-muted">confidence {c.conf}% · job {c.job}</span></div>
          </motion.div>))}</div>
        <p className="ax-xs ax-faint" style={{ marginTop: 8 }}>Conclusions below 70% confidence cannot be distributed to agents until a human verifies them.</p>
      </section>
      <section aria-label="Contradicting evidence"><h3 className="ax-small ax-muted">Contradicting evidence</h3>
        <div className="ax-rows">{CONTRADICTIONS.map((c, i) => (
          <motion.div key={c.id} className="ax-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 2, borderColor: c.state === "open" ? "var(--ax-warn)" : undefined }} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05 }}>
            <div className="ax-flex"><b className="ax-small" style={{ flex: 1 }}>{c.claim}</b><Pill c={c.state === "open" ? "var(--ax-warn)" : "var(--ax-ok)"} icon={c.state === "open" ? AlertTriangle : Check}>{c.state}</Pill></div>
            <span className="ax-xs ax-muted">A: {c.a}</span><span className="ax-xs ax-muted">B: {c.b}</span>
          </motion.div>))}</div>
      </section>
    </div>
  );
}

/* ---------- News feed ---------- */
export function NewsTab({ openSources }: { openSources: () => void }) {
  const news = useStore((s) => s.news), srcs = useStore((s) => s.newsSources), toast = useToast();
  const [cat, setCat] = useState("all");
  const cats = ["all", ...Array.from(new Set(news.map((n) => n.category)))];
  const list = news.filter((n) => cat === "all" || n.category === cat);
  return (
    <div style={wrap}>
      <div className="ax-flex" style={{ marginBottom: 6, flexWrap: "wrap" }}>
        <Seg label="News category" value={cat} onChange={setCat} items={cats.map((c) => ({ id: c, label: c === "all" ? "All" : c }))} />
        <span className="ax-xs ax-muted" style={{ flex: 1 }}>{list.length} headlines from {srcs.filter((s) => s.status !== "disabled").length} enabled sources</span>
        <IconBtn icon={Rss} label="Manage news sources" size="sm" onClick={openSources} />
      </div>
      <table className="ax-table"><thead><tr><th>Headline</th><th>Source</th><th>Time</th><th>Category</th><th>Relevance to missions</th><th /></tr></thead>
        <tbody>{list.map((n, i) => {
          const s = srcs.find((x) => x.id === n.sourceId);
          return (
            <motion.tr key={n.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}>
              <td><b>{n.title}</b></td>
              <td><span className="ax-small">{s?.name ?? n.sourceId}</span>{s && <span className="ax-xs ax-faint" style={{ display: "block" }}>trust {s.trust}%</span>}</td>
              <td><Time iso={n.at} withDate /></td><td><Pill c="var(--ax-accent2)">{n.category}</Pill></td>
              <td style={{ minWidth: 190 }}><div className="ax-flex"><span style={{ width: 70 }}><Progress value={n.relevance} thin label={`Relevance ${n.relevance}%`} /></span><span className="ax-num ax-small">{n.relevance}%</span>
                {n.missionIds.map((m) => <button key={m} className="ax-chip" style={{ cursor: "pointer" }} onClick={() => go("missions", null, { m })} aria-label={`Open mission ${m}`}>{m}</button>)}</div></td>
              <td><IconBtn icon={ExternalLink} label={n.url === "#" ? "Open original article (sample item has no live link)" : "Open original article in a new tab"} size="sm" tone="ghost"
                onClick={() => (n.url === "#" ? toast("Sample item: there is no live article behind this headline.") : openSafe(n.url, toast))} /></td>
            </motion.tr>);
        })}</tbody></table>
      <p className="ax-xs ax-faint" style={{ marginTop: 6 }}>{UNTRUSTED}</p>
    </div>
  );
}

/* ---------- Sources (user-editable) ---------- */
const CADENCE = ["Every 15 min", "Every 30 min", "Every 6 h", "Daily", "Weekly"];
export function SourcesTab() {
  const srcs = useStore((s) => s.newsSources), toast = useToast();
  const missions = useStore((x) => x.missions);
  const [f, setF] = useState({ name: "", url: "", cadence: "Daily", scope: "organization" as NewsSource["scope"], topics: "", missionId: "" });
  const run = (e: string | null) => { if (e) toast(e, "warn"); return !!e; };
  const liveSrc = useStore((x) => x.sources.newsSources === "live");
  const [err, setErr] = useState<string | null>(null);
  const [del, setDel] = useState<NewsSource | null>(null);
  const add = () => {
    if (!f.url.trim()) { setErr("Enter the website or feed address (for example https://example.com/rss)."); return; }
    const e = addNewsSource({ name: f.name.trim(), url: f.url.trim(), cadence: f.cadence, scope: f.scope, topics: f.topics.split(",").map((x) => x.trim()).filter(Boolean), missionId: f.scope === "mission" ? f.missionId || undefined : undefined });
    setErr(e); if (!e) { toast(`Source added: ${host(f.url.trim())}. It is fetched on the next cycle (sample mode simulates the first fetch).`); setF({ ...f, name: "", url: "", topics: "" }); }
  };
  return (
    <div style={{ ...wrap, display: "flex", flexDirection: "column", gap: 8 }}>
      <form className="ax-flex" style={{ flexWrap: "wrap", alignItems: "flex-start" }} onSubmit={(e) => { e.preventDefault(); add(); }} aria-label="Add a news source">
        <input className="ax-input" style={{ flex: "2 1 240px" }} placeholder="https://site.example/feed (website or RSS address)" value={f.url} onChange={(e) => { setF({ ...f, url: e.target.value }); setErr(null); }} aria-label="Source URL" aria-invalid={!!err} aria-describedby="src-err" />
        <input className="ax-input" style={{ flex: "1 1 140px" }} placeholder="Name (optional)" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Source name" />
        <input className="ax-input" style={{ flex: "1 1 140px" }} placeholder="Topics, comma separated" value={f.topics} onChange={(e) => setF({ ...f, topics: e.target.value })} aria-label="Topics" />
        <Dropdown label="Fetch cadence" value={f.cadence} onChange={(v) => setF({ ...f, cadence: v })} options={CADENCE.map((c) => ({ id: c, label: c }))} />
        <Dropdown label="Scope" value={f.scope} onChange={(v) => setF({ ...f, scope: v as NewsSource["scope"] })} options={[{ id: "organization", label: "Whole company" }, { id: "mission", label: "Mission only" }]} />
        {f.scope === "mission" && <Dropdown label="Mission for this source" value={f.missionId} onChange={(v) => { setF({ ...f, missionId: v }); setErr(null); }} options={[{ id: "", label: "Choose mission" }, ...missions.map((m) => ({ id: m.id, label: m.id + " " + m.title.slice(0, 24) }))]} />}
        <IconBtn icon={Plus} label="Add this source" tone="gold" type="submit" />
        <span className="ax-xs" id="src-err" role="alert" style={{ flexBasis: "100%", color: "var(--ax-bad)", minHeight: 14 }}>{err && <><AlertTriangle size={12} aria-hidden /> {err}</>}</span>
      </form>
      <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
        <table className="ax-table"><thead><tr><th>Source</th><th>Cadence</th><th>Trust</th><th>Last fetch</th><th>Items</th><th>Status</th><th>Scope</th><th>On</th><th /></tr></thead>
          <tbody>{srcs.map((s, i) => (
            <motion.tr key={s.id} layout initial={{ opacity: 0, x: -8 }} animate={{ opacity: s.status === "disabled" ? .6 : 1, x: 0 }} transition={{ delay: i * .03 }}>
              <td><b>{s.name}</b><span className="ax-xs ax-faint" style={{ display: "block", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.url}</span></td>
              <td><Dropdown label={`Cadence for ${s.name}`} value={s.cadence} onChange={(v) => run(updateNewsSource(s.id, { cadence: v }))} options={(CADENCE.includes(s.cadence) ? CADENCE : [s.cadence, ...CADENCE]).map((c) => ({ id: c, label: c }))} /></td>
              <td style={{ width: 130 }}><div className="ax-flex"><input type="range" min={0} max={100} value={s.trust} aria-label={`Trust for ${s.name}`} disabled={liveSrc} title={liveSrc ? "Trust is computed by the fetcher on the server" : undefined} onChange={(e) => run(updateNewsSource(s.id, { trust: +e.target.value }))} style={{ width: 70, accentColor: progressColors(s.trust)[0] }} /><span className="ax-num ax-small">{s.trust}%</span></div></td>
              <td>{s.lastFetched ? <Time iso={s.lastFetched} withDate /> : <span className="ax-faint">never</span>}</td><td className="ax-num">{s.items}</td>
              <td>{s.status === "ok" ? <StatusPill small s="passed" label="OK" /> : s.status === "error" ? <StatusPill small s="failed" label="Fetch error" /> : s.status === "pending" ? <StatusPill small s="queued" label="Pending first fetch" /> : <StatusPill small s="paused" label="Disabled" />}</td>
              <td className="ax-small">{s.scope === "organization" ? "Company" : "Mission"}</td>
              <td><Switch label={`${s.status === "disabled" ? "Enable" : "Disable"} ${s.name}`} on={s.status !== "disabled"} onChange={(v) => run(updateNewsSource(s.id, { status: v ? "pending" : "disabled" }))} /></td>
              <td className="ax-flex" style={{ gap: 2 }}>
                <IconBtn icon={RefreshCw} label={`Fetch ${s.name} now (sample mode: simulated)`} size="sm" tone="ghost" disabled={s.status === "disabled"}
                  onClick={() => { if (liveSrc) { toast("Fetching on demand isn't available yet; the server fetcher runs on the source's cadence.", "info"); return; } if (!run(updateNewsSource(s.id, { status: "ok", lastFetched: new Date().toISOString() }))) toast("Sample mode: fetch simulated, nothing was downloaded."); }} />
                <IconBtn icon={Trash2} label={`Remove ${s.name}`} size="sm" tone="ghost" onClick={() => setDel(s)} /></td>
            </motion.tr>))}</tbody></table>
        {!srcs.length && <Empty icon={Rss} title="No news sources">Add a website or feed address above.</Empty>}
      </div>
      <p className="ax-xs ax-faint" style={{ margin: 0 }}>Only http(s) addresses are accepted; private and internal addresses are blocked. {UNTRUSTED}</p>
      <Modal open={!!del} onClose={() => setDel(null)} title="Remove this news source?" icon={Trash2} width={420}
        foot={<><Btn onClick={() => setDel(null)} icon={X}>Keep it</Btn><Btn tone="gold" icon={Trash2} onClick={() => { if (del) { const e = removeNewsSource(del.id); toast(e ?? `Removed ${del.name}. Headlines already learned stay in the library.`); } setDel(null); }}>Remove source</Btn></>}>
        <p className="ax-small">{del?.name} ({del && host(del.url)}) will stop being fetched. Headlines already imported are kept; you can add the source again at any time.</p>
      </Modal>
    </div>
  );
}

/* ---------- Citations ---------- */
export function CitationsTab() {
  const toast = useToast();
  return (
    <div style={wrap}>
      <table className="ax-table"><thead><tr><th>Cited finding</th><th>Source</th><th>Retrieved</th><th>License</th><th>Reliability</th><th>Used by</th><th>Verified</th><th /></tr></thead>
        <tbody>{CITATIONS.map((c, i) => (
          <motion.tr key={c.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}>
            <td><b>{c.claim}</b></td><td className="ax-small">{c.source}<span className="ax-xs ax-faint" style={{ display: "block" }}>{host(c.url)}</span></td><td><Time iso={c.retrieved} withDate /></td>
            <td className="ax-small">{c.license}{c.license === "Unknown" && <Pill c="var(--ax-bad)" icon={AlertTriangle}>quote blocked</Pill>}</td>
            <td style={{ width: 110 }}><Progress value={c.reliability} thin label={`Reliability ${c.reliability}%`} /></td>
            <td>{c.usedBy.map((m) => <span key={m} className="ax-chip" style={{ marginRight: 3 }}>{m}</span>)}</td>
            <td>{c.verified ? <StatusPill small s="passed" label="Verified" /> : <StatusPill small s="waiting_user" label="Unverified" />}</td>
            <td><IconBtn icon={ExternalLink} label="Open source (sample citation, not a live link)" size="sm" tone="ghost" onClick={() => toast("Sample citation: the link is illustrative.")} /></td>
          </motion.tr>))}</tbody></table>
      <p className="ax-xs ax-faint" style={{ marginTop: 6 }}>Every finding keeps source, retrieval time, license and reliability. Findings with an unknown license cannot be quoted verbatim.</p>
    </div>
  );
}

/* ---------- Learning queue ---------- */
export function QueueTab({ L }: { L: Learning }) {
  const toast = useToast();
  const [sel, setSel] = useState(L.queue[0]?.id ?? "");
  const [to, setTo] = useState<string[]>(["all"]);
  const it = L.queue.find((x) => x.id === sel) ?? L.queue[0];
  if (!it) return <Empty title="Queue is empty">No candidate knowledge is waiting for verification.</Empty>;
  const d = L.decided[it.id], recips = L.dist[it.id];
  const toggle = (id: string) => setTo((x) => id === "all" ? ["all"] : x.includes(id) ? x.filter((y) => y !== id) : [...x.filter((y) => y !== "all"), id]);
  const stateOf = (x: typeof it) => L.decided[x.id] ?? "waiting";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1.1fr)", gap: 12, height: "100%", minHeight: 0 }}>
      <div className="ax-rows" style={{ overflow: "auto" }} aria-label="Candidate knowledge">
        {L.queue.map((x, i) => (
          <motion.button key={x.id} type="button" className={`ax-row click ${x.id === it.id ? "sel" : ""}`} onClick={() => setSel(x.id)} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .03 }}
            style={{ textAlign: "left", font: "inherit", color: "inherit", background: "none" }}>
            <span className="grow"><span className="t">{x.title}</span><span className="s">{x.origin === "external" ? "External" : "Internal"} · {x.confidence}% · {x.flags[0] ?? "No flags"}</span></span>
            {stateOf(x) === "approved" ? <Pill c="var(--ax-ok)" icon={Check}>Approved</Pill> : stateOf(x) === "rejected" ? <Pill c="var(--ax-bad)" icon={Ban}>Rejected</Pill> : <Pill c="var(--ax-warn)" icon={Loader2}>Waiting</Pill>}
          </motion.button>))}
      </div>
      <motion.div key={it.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} style={{ overflow: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="ax-flex"><b style={{ flex: 1 }}>{it.title}</b>{it.base && <KStatus s={it.base} />}</div>
        <p className="ax-small" style={{ margin: 0 }}>{it.summary}</p>
        <div className="ax-xs ax-muted">Source: {it.source} · License: {it.license} · Confidence {it.confidence}%{it.missions.length > 0 && <> · Needed by {it.missions.join(", ")}</>}</div>
        <div className="ax-flex" style={{ flexWrap: "wrap" }}>
          {it.flags.map((f) => <Pill key={f} c="var(--ax-warn)" icon={ShieldAlert}>{f}</Pill>)}{!it.flags.length && <Pill c="var(--ax-ok)" icon={Check}>All checks passed</Pill>}
          {it.origin === "external" && <Pill c="var(--ax-info)" icon={Globe}>Untrusted external content</Pill>}
        </div>
        <div className="ax-flex" style={{ gap: 6 }}>
          <IconBtn icon={Check} tone="ok" label="Approve: mark as verified company knowledge" disabled={d === "approved"} onClick={() => { L.decide(it.id, "approved"); toast(`Approved "${it.title}". Choose who learns it.`); }} />
          <IconBtn icon={X} tone="bad" label="Reject: keep out of company knowledge" disabled={d === "rejected"} onClick={() => { L.decide(it.id, "rejected"); L.revoke(it.id); toast("Rejected. It will not be distributed."); }} />
          <span className="ax-xs ax-muted">{d === "approved" ? "Approved by you" : d === "rejected" ? "Rejected by you" : "Needs a human decision before any agent learns it"}</span>
        </div>
        <fieldset disabled={d !== "approved"} style={{ border: "1px solid var(--ax-border)", borderRadius: 9, padding: "6px 8px", margin: 0 }}>
          <legend className="ax-xs ax-muted">Distribute to agents</legend>
          <div className="ax-flex" style={{ flexWrap: "wrap", gap: 4 }}>{RECIPIENTS.map((r) => (
            <label key={r.id} className="ax-chip" style={{ cursor: "pointer", borderColor: to.includes(r.id) ? "var(--ax-accent)" : undefined }}>
              <input type="checkbox" checked={to.includes(r.id)} onChange={() => toggle(r.id)} style={{ accentColor: "var(--ax-accent)" }} /> {r.label}</label>))}</div>
          <div className="ax-flex" style={{ marginTop: 6 }}>
            <IconBtn icon={Send} tone="gold" label="Distribute to selected agents (sample: recorded only)" disabled={d !== "approved" || !to.length} onClick={() => { L.distribute(it.id, to); toast("Distribution recorded. Sample mode: no live agents received it."); }} />
            {recips && <><span className="ax-xs">Distributed to: {recips.map((r) => RECIPIENTS.find((x) => x.id === r)?.label ?? r).join(", ")}</span><IconBtn icon={Undo2} size="sm" label="Revoke distribution" onClick={() => { L.revoke(it.id); toast("Distribution revoked."); }} /></>}
          </div>
        </fieldset>
        {d !== "approved" && <span className="ax-xs ax-faint"><Newspaper size={11} aria-hidden /> Approve first to enable distribution. {it.origin === "external" ? UNTRUSTED : ""}</span>}
      </motion.div>
    </div>
  );
}
