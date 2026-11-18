import { useState, type CSSProperties } from "react";
import { motion } from "framer-motion";
import {
  BookOpen, Database, FileText, FlaskConical, GitBranch, Grid2x2, Layers, Library, Link2, List, Plus, Quote, RefreshCw, Rss, Search, Share2, ShieldCheck, Sparkles, Star, Upload, Check, Globe,
  ListChecks, Newspaper, Zap, Lightbulb, SlidersHorizontal,
} from "lucide-react";
import { IconBtn, Kpi, Panel, Pill, Seg, TabBody, Tabs, Time, useToast } from "../ui/kit";
import { Dropdown } from "../ui/widgets";
import { useStore } from "../data/store";
import { KNOWLEDGE_TILES } from "../data/sample";
import { go, useQueryParam } from "../app/router";
import { BEST_PRACTICES, CITATIONS, IMPORTED_DOCS } from "./knowledge/data";
import { useLearning } from "./knowledge/shared";
import { CitationsTab, LibraryTab, NewsTab, QueueTab, ResearchTab, SourcesTab, type LibFilter } from "./knowledge/Tabs";
import { AgentOrgPanel, DetailPanel, ExternalPanel, GraphPanel, LessonsTab, OrgMemoryPanel } from "./knowledge/panels";

const tile = (name: string) => KNOWLEDGE_TILES.find((t) => t[0] === name)?.[1] ?? 0;
const POPULAR = ["Architecture", "Evaluation", "Optimization", "Release", "Cost", "Security"];
const row = (c: string): CSSProperties => ({ display: "grid", gridTemplateColumns: c.split(" ").map((x) => `minmax(0,${x})`).join(" "), gridTemplateRows: "minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 });
const CSS = `.kn-tabs .ax-tabs{display:grid;grid-template-columns:repeat(7,1fr);gap:8px}.kn-tabs .ax-tab{justify-content:center;padding:7px 10px;font-size:14px;font-weight:600}
.kn-mem .ax-row{padding:0 4px;gap:6px;min-height:0}.kn-mem .ax-panel-body{padding-top:2px}.kn-lib td,.kn-lib th{padding:2px 6px}.kn-lib .ax-pill{font-size:10px;padding:0 6px}.kn-ext .ax-row{padding:0 4px}.kn-bot .ax-row{padding:1px 4px}.kn-kpis .ax-kpi{padding:6px 8px;gap:8px}.kn-kpis .ax-kpi-ic{width:34px;height:34px}.kn-kpis .ax-kpi b{font-size:21px}.kn-kpis .ax-kpi .lbl{font-size:11px}`;

export default function Knowledge() {
  const [tab, setTab] = useQueryParam("tab", "library");
  const items = useStore((s) => s.knowledge), news = useStore((s) => s.news), srcs = useStore((s) => s.newsSources), missions = useStore((s) => s.missions);
  const L = useLearning(items);
  const toast = useToast();
  const [q, setQ] = useState(""), [f, setF] = useState<LibFilter>({ kind: "all", owner: "all", mission: "all", time: "all" }), [sel, setSel] = useState(items[0]?.id ?? ""), [view, setView] = useState<"list" | "grid">("list");
  const lib = tab === "library";
  const waiting = L.queue.filter((x) => !L.decided[x.id]).length;
  const owners = Array.from(new Set(items.map((k) => k.owner))), scopes = Array.from(new Set(items.map((k) => k.scope)));
  const openLib = (p: Partial<LibFilter>, query?: string) => { setF({ ...f, ...p }); if (query != null) setQ(query); setTab("library"); };

  const help = {
    library: "Searchable verified knowledge with owner, citations and confidence. Click a row for provenance and use on the right.", research: "Research jobs agents run while carrying out missions, their conclusions, and evidence that contradicts them.",
    news: "Headlines pulled from your sources, ranked by relevance to running missions.", sources: "The websites news is retrieved from. Add your own address, set how often it is fetched, how much it is trusted, and switch it off or remove it.",
    lessons: "Lessons agents learned on missions (retros, failures, optimizations) and which of them are shared with the whole company.", citations: "Every cited finding with its source, retrieval time, license and reliability.",
    queue: "Candidate knowledge waiting for a human decision. Approved items can be distributed so the whole company learns them.",
  } as Record<string, string>;
  const title = { library: "Knowledge Library", research: "Research", news: "News Feed", sources: "News Sources", lessons: "Lessons Learned", citations: "Citations", queue: "Learning Queue" }[tab] ?? "Knowledge Library";
  const icon = { library: Library, research: FlaskConical, news: Newspaper, sources: Globe, lessons: Lightbulb, citations: Quote, queue: ListChecks }[tab] ?? Library;

  return (
    <div className="ax-page" style={{ gridTemplateColumns: "1112fr 350fr", gridTemplateRows: "minmax(0,12fr) minmax(0,30fr) 44px minmax(0,21fr) minmax(0,21fr)", gridTemplateAreas: `"head quick" "mid search" "tabs detail" "main detail" "${lib ? "bottom" : "main"} detail"` }}>
      <style>{CSS}</style>
      <Panel i={0} area="head" title="Knowledge & News" icon={BookOpen} sub="Organizational memory, external research, and real-time intelligence for the AXoR AI Company."
        help={{ body: "Everything the company knows, and where it came from. While missions run, agents research internal data and external websites. Imported material is verified, then learned by the whole company and reused for missions.", policy: "External content is untrusted input and is never executed.", source: "Knowledge store (sample)" }}>
        <div className="ax-kpis kn-kpis" style={{ gridTemplateColumns: "repeat(7, 1fr)" }}>
          <Kpi i={0} icon={Layers} c="#22d3ee" value={tile("Project Knowledge")} label="Knowledge Items" delta="↑ +36 (24h)" />
          <Kpi i={1} icon={BookOpen} c="#a77bff" value={tile("Research Reports")} label="Research Reports" delta="↑ +12 (24h)" />
          <Kpi i={2} icon={Star} c="#f2b53a" value={tile("Best Practices")} label="Best Practices" delta="↑ +5 (24h)" />
          <Kpi i={3} icon={FileText} c="#3b8cff" value={87} label="Imported Docs" delta="↑ +18 (24h)" />
          <Kpi i={4} icon={Share2} c="#22d3ee" value={Math.max(srcs.length, tile("External Sources"))} label="External Sources" delta="↑ +3 (24h)" />
          <Kpi i={5} icon={ShieldCheck} c="#2fd27a" value={95.4} decimals={1} suffix="%" label="Knowledge Reuse" delta="↑ +2.7 pp" />
          <Kpi i={6} icon={Database} c="#a77bff" value={76} suffix=" GB" label="Org Memory" delta="42,160 chunks" />
        </div>
      </Panel>
      <Panel i={1} area="quick" title="Quick Actions" icon={Zap} help="Shortcuts. Importing or fetching external material always goes through the Learning Queue.">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, justifyItems: "center" }}>
          <IconBtn icon={Plus} label="Add a news source" onClick={() => setTab("sources")} />
          <IconBtn icon={Upload} label="Import documents (sample: no upload backend)" onClick={() => toast("Sample mode: documents would be scanned, then queued for verification.")} />
          <IconBtn icon={Link2} label="Add a research link" onClick={() => setTab("sources")} />
          <IconBtn icon={RefreshCw} label="Fetch all enabled sources (sample: simulated)" onClick={() => toast("Sample mode: fetch simulated; no external requests were made.")} />
          <IconBtn icon={GitBranch} label="Knowledge versions and lineage" onClick={() => go("versions")} />
          <IconBtn icon={FlaskConical} label="Research jobs" onClick={() => setTab("research")} />
          <IconBtn icon={ListChecks} label={`Learning queue (${waiting} waiting)`} onClick={() => setTab("queue")} />
          <IconBtn icon={Sparkles} label="Ask the Knowledge agent" tone="gold" onClick={() => go("agents")} />
        </div>
      </Panel>

      <div style={{ gridArea: "mid", ...row("1fr 1.1fr") }}><OrgMemoryPanel i={2} /><AgentOrgPanel i={3} /></div>
      <Panel i={4} area="search" title="Knowledge Search & Filter" icon={Search} help="Searches titles, tags and types of the library. Filters apply to the Library tab.">
        <div className="ax-search"><Search size={14} aria-hidden /><input className="ax-input" placeholder="Search knowledge, research, news, best practices..." value={q} onChange={(e) => { setQ(e.target.value); if (!lib) setTab("library"); }} aria-label="Search knowledge" /></div>
        <div className="ax-flex" style={{ marginTop: 8, flexWrap: "wrap", gap: 6 }}>
          <Dropdown label="Filter by type" value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={[{ id: "all", label: "All Types" }, ...["fact", "procedure", "decision", "lesson", "research", "skill"].map((x) => ({ id: x, label: x }))]} />
          <Dropdown label="Filter by agent" value={f.owner} onChange={(v) => setF({ ...f, owner: v })} options={[{ id: "all", label: "All Agents" }, ...owners.map((o) => ({ id: o, label: o }))]} />
          <Dropdown label="Filter by mission" value={f.mission} onChange={(v) => setF({ ...f, mission: v })} options={[{ id: "all", label: "All Missions" }, ...scopes.filter((s) => s.startsWith("M-")).map((s) => ({ id: s, label: s + " " + (missions.find((m) => m.id === s)?.title.slice(0, 14) ?? "") })), ...(scopes.includes("organization") ? [{ id: "organization", label: "Organization" }] : [])]} />
          <Dropdown label="Filter by time" value={f.time} onChange={(v) => setF({ ...f, time: v })} options={[{ id: "all", label: "All Time" }, { id: "24h", label: "Last 24 h" }, { id: "7d", label: "Last 7 days" }, { id: "30d", label: "Last 30 days" }]} />
          <IconBtn icon={SlidersHorizontal} label="Reset filters" size="sm" onClick={() => { setF({ kind: "all", owner: "all", mission: "all", time: "all" }); setQ(""); }} />
        </div>
        <div className="ax-flex" style={{ marginTop: 8, flexWrap: "wrap", gap: 4 }}><span className="ax-xs ax-muted">Popular Filters:</span>
          {POPULAR.map((p) => <motion.button key={p} type="button" className="ax-chip" style={{ cursor: "pointer" }} whileHover={{ y: -1 }} whileTap={{ scale: .95 }} onClick={() => openLib({}, p.toLowerCase())}>{p}</motion.button>)}</div>
      </Panel>

      <div style={{ gridArea: "tabs" }} className="kn-tabs">
        <Tabs label="Knowledge tabs" value={tab} onChange={setTab} tabs={[
          { id: "library", label: "Library", icon: BookOpen }, { id: "research", label: "Research", icon: FlaskConical }, { id: "news", label: "News Feed", icon: Rss }, { id: "sources", label: "Sources", icon: Globe },
          { id: "lessons", label: "Lessons Learned", icon: Lightbulb }, { id: "citations", label: "Citations", icon: Quote }, { id: "queue", label: "Learning Queue", icon: ListChecks, alert: waiting }]} />
      </div>

      {lib ? (
        <div style={{ gridArea: "main", ...row("440fr 345fr 312fr") }}>
          <Panel i={5} className="kn-lib" title="Knowledge Library" sub="(Org Memory)" icon={Library} help={{ body: help.library, policy: "External content is untrusted: scanned for prompt injection, never executed, and learned only after verification." }}
            actions={<><Seg label="Library view" value={view} onChange={setView} items={[{ id: "grid", label: "Grid view", icon: Grid2x2 }, { id: "list", label: "List view", icon: List }]} /><IconBtn icon={Plus} label="Add knowledge (goes to the Learning Queue)" size="sm" onClick={() => setTab("queue")} /><IconBtn icon={Upload} label="Import (sample)" size="sm" onClick={() => toast("Sample mode: no upload backend.")} /></>}>
            <LibraryTab q={q} f={f} sel={sel} setSel={setSel} />
          </Panel>
          <ExternalPanel i={6} onAdd={() => setTab("sources")} />
          <GraphPanel i={7} onTopic={(t) => openLib({}, t.split(" ")[0].toLowerCase())} />
        </div>
      ) : (
        <Panel i={5} area="main" title={title} icon={icon} help={{ body: help[tab], policy: "External content is untrusted: scanned for prompt injection, never executed, and learned only after verification." }}>
          <TabBody k={tab}>
            {tab === "research" && <ResearchTab />}{tab === "news" && <NewsTab openSources={() => setTab("sources")} />}{tab === "sources" && <SourcesTab />}
            {tab === "lessons" && <LessonsTab />}{tab === "citations" && <CitationsTab />}{tab === "queue" && <QueueTab L={L} />}
          </TabBody>
        </Panel>
      )}

      <DetailPanel i={8} id={sel} setSel={setSel} />

      {lib && (
        <div className="kn-bot" style={{ gridArea: "bottom", ...row("357fr 250fr 245fr 237fr") }}>
          <Panel i={9} title="Recent News" sub="(Real-Time Intelligence)" icon={Newspaper} help="Latest headlines from your sources. Untrusted until verified."
            actions={<IconBtn icon={Rss} label="Manage news sources" size="sm" onClick={() => setTab("sources")} />}>
            <div className="ax-rows">{news.slice(0, 5).map((n, i) => (
              <motion.div key={n.id} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}>
                <span className="grow"><span className="t ax-small">{n.title}</span><span className="s">{srcs.find((s) => s.id === n.sourceId)?.name} · <Time iso={n.at} /></span></span><Pill c="var(--ax-accent2)">{n.category}</Pill></motion.div>))}</div>
          </Panel>
          <Panel i={10} title="Cited Findings" sub="& Key Insights" icon={Quote} help="Findings that agents cite, with source and reliability. Unverified findings are marked.">
            <div className="ax-rows">{CITATIONS.map((c, i) => (
              <motion.div key={c.id} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}>
                <span style={{ color: c.verified ? "var(--ax-ok)" : "var(--ax-warn)" }} aria-label={c.verified ? "Verified" : "Unverified"}>{c.verified ? <Check size={14} /> : <Search size={14} />}</span>
                <span className="grow t ax-small" style={{ whiteSpace: "normal" }}>{c.claim}</span></motion.div>))}</div>
          </Panel>
          <Panel i={11} title="Imported Documents" icon={FileText} help="Documents imported by users or agents. Each is scanned and queued for verification before anyone learns it."
            actions={<IconBtn icon={Plus} label="Import a document (sample)" size="sm" onClick={() => toast("Sample mode: no upload backend.")} />}>
            <div className="ax-rows">{IMPORTED_DOCS.map((d, i) => (
              <motion.div key={d.name} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}>
                <Pill c="var(--ax-accent)">{d.type}</Pill><span className="grow"><span className="t ax-small">{d.name}</span><span className="s">{d.size} · <Time iso={d.at} withDate /></span></span></motion.div>))}</div>
          </Panel>
          <Panel i={12} title="Reusable Best Practices" icon={Star} help="Verified practices other missions reuse, with the measured improvement when used.">
            <div className="ax-rows">{BEST_PRACTICES.map((b, i) => (
              <motion.div key={b.name} className="ax-row" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .04 }}>
                <Star size={14} style={{ color: "var(--ax-accent)" }} aria-hidden /><span className="grow"><span className="t ax-small">{b.name}</span><span className="s">Used {b.used} times</span></span>
                <span className="ax-num ax-small" style={{ color: "var(--ax-ok)" }}>+{b.gain}%</span></motion.div>))}</div>
          </Panel>
        </div>
      )}
    </div>
  );
}
