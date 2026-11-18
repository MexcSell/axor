import { useState } from "react";
import { getJSON } from "../http";
import { useLoad } from "../useLoad";
import { Head, Loaded, Panel } from "../ui";

// New in 5.1: the event stream (bus.py; Redis Streams when REDIS_URL is set). GET /api/events, administrators only.
type Ev = { id?: string; kind: string; ts: number; run?: number; system?: string; status?: string; model?: string; tokens?: number;
  mission?: number; stage?: string; type?: string; text?: string; error?: string; agent?: string; ref?: string };
type Feed = { source: "redis" | "in-process"; events: Ev[] };

const KINDS = [["", "All"], ["run.started,run.finished", "Agent runs"], ["mission.event", "Missions"]] as const;

function line(e: Ev) {
  if (e.kind === "run.started") return `${e.system ?? "?"} run #${e.run} started${e.agent ? ` · ${e.agent}` : ""}${e.model ? ` on ${e.model}` : ""}`;
  if (e.kind === "run.finished") return `run #${e.run} ${e.status}${e.tokens ? ` · ${e.tokens.toLocaleString()} tokens` : ""}${e.error ? ` · ${e.error}` : ""}`;
  if (e.kind === "mission.event") return `mission #${e.mission} · ${e.stage}: ${e.text ?? ""}`;
  return e.kind;
}

export default function Activity() {
  const [kind, setKind] = useState("");
  const { load, reload } = useLoad((s) => getJSON<Feed>(`/api/events?limit=150${kind ? `&kind=${encodeURIComponent(kind)}` : ""}`, s), 5000, [kind]);
  return (
    <>
      <Head kicker="Activity · new in 5.1" title="Activity"
        lede="What every agent system is doing right now: runs starting and finishing, and each mission's steps, newest first. It comes from AXoR's event stream, which other services can read too."
        actions={<div className="chips" role="group" aria-label="Show">{KINDS.map(([k, l]) => (
          <button key={l} type="button" className="chip" aria-pressed={kind === k} onClick={() => setKind(k)}>{l}</button>))}</div>} />
      <Loaded load={load} retry={() => reload()}>{(f, at) => (
        <Panel title="Events" note={`${f.source === "redis" ? "Redis Streams" : "this server's memory (no Redis)"} · ${at.toLocaleTimeString()}`}>
          {!f.events.length ? <p className="muted">Nothing yet. Events appear as agents run and missions move.</p> : (
            <ol className="feed">
              {f.events.map((e, i) => (
                <li key={e.id ?? `${e.ts}-${i}`} className={e.status && !["done", "running"].includes(e.status) ? "bad" : ""}>
                  <time className="num muted">{new Date(e.ts * 1000).toLocaleTimeString()}</time>
                  <span className="kind">{e.kind}</span>
                  <span className="what">{line(e)}</span>
                </li>
              ))}
            </ol>)}
        </Panel>)}
      </Loaded>
    </>
  );
}
