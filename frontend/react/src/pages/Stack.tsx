import type { ReactNode } from "react";
import { getJSON } from "../http";
import { useLoad } from "../useLoad";
import { Badge, Head, Loaded, Panel } from "../ui";
import type { Database, Events, Graph, Monitoring, Runtime, Stack as StackT } from "./stackApi";

export default function Stack() {
  const { load, reload } = useLoad((s) => getJSON<StackT>("/api/stack", s), 15000, []);
  return (
    <>
      <Head kicker={`AXoR ${load.state === "ok" ? load.data.version : "5.1"} · React + TypeScript`} title="Stack & migration"
        lede="The stack the AXoR 5.0 spec recommends, what this server runs today, and how far the move has come. Each part switches on by itself, so the app keeps working while the rest moves." />
      <Loaded load={load} retry={() => reload()}>{(data, at) => <Body data={data} at={at} />}</Loaded>
    </>
  );
}

function Body({ data, at }: { data: StackT; at: Date }) {
  const done = data.migration.filter((s) => s.done).length;
  return (
    <>
      <section className="cards">
        <DatabaseCard db={data.database} />
        <RuntimeCard rt={data.missions_runtime} />
        <GraphCard g={data.agent_graph} />
        <EventsCard ev={data.events} />
        <MonitoringCard m={data.monitoring} />
      </section>
      <Panel title="Migration" note={`${done} of ${data.migration.length} steps`}>
        <div className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={data.migration.length} aria-valuenow={done}>
          <span style={{ width: `${(done / data.migration.length) * 100}%` }} />
        </div>
        <ol className="steps">
          {data.migration.map((s) => (
            <li key={s.key} className={s.done ? "done" : ""}>
              <span className="tick" aria-hidden>{s.done ? "✓" : ""}</span>
              <div><strong>{s.title}</strong><p>{s.detail}</p></div>
            </li>
          ))}
        </ol>
      </Panel>
      <Panel title="Spec vs. this server" note={`updated ${at.toLocaleTimeString()}`}>
        <div className="tablewrap">
          <table>
            <thead><tr><th>Part</th><th>Spec</th><th>Here</th><th>Live</th></tr></thead>
            <tbody>
              {data.stack.map((r) => (
                <tr key={r.key}>
                  <td className="part">{r.key.replace(/_/g, " ")}</td><td>{r.spec}</td><td className="muted hide-narrow">{r.now}</td><td><Badge on={r.live} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

function Card({ title, state, children }: { title: string; state: { on: boolean; label: string }; children: ReactNode }) {
  return (
    <article className="card">
      <div className="card-head"><h3>{title}</h3><Badge on={state.on} label={state.label} /></div>
      <dl>{children}</dl>
    </article>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  if (v === undefined || v === null || v === "") return null;
  return (<><dt>{k}</dt><dd>{v}</dd></>);
}

function DatabaseCard({ db }: { db: Database }) {
  const pg = db.engine === "postgres";
  return (
    <Card title="Database" state={{ on: pg, label: pg ? "PostgreSQL" : "SQLite" }}>
      <Row k="Engine" v={pg ? "PostgreSQL (db_pg.py)" : "SQLite file (auth.db)"} />
      <Row k="Host" v={db.host ? `${db.host}:${db.port}` : undefined} />
      <Row k="Database" v={db.database} />
      <Row k="Schema" v={db.schema} />
      {!pg && <Row k="Switch" v={<code>k8s/stack.sh migrate</code>} />}
    </Card>
  );
}

function RuntimeCard({ rt }: { rt: Runtime }) {
  const label = rt.ready ? "Temporal" : rt.enabled ? (rt.installed ? "unreachable" : "not installed") : "in-process";
  return (
    <Card title="Mission runtime" state={{ on: rt.ready, label }}>
      <Row k="Runs on" v={rt.ready ? "Temporal workflows" : "the server's own worker pool"} />
      <Row k="Server" v={rt.address ?? undefined} />
      <Row k="Queue" v={rt.queue} />
      <Row k="Handed over" v={rt.submitted !== undefined ? `${rt.submitted} · ${rt.fallbacks ?? 0} fell back` : undefined} />
      <Row k="Problem" v={rt.error ?? undefined} />
    </Card>
  );
}

function GraphCard({ g }: { g: Graph }) {
  const on = g.enabled && g.installed;
  return (
    <Card title="Agent reasoning" state={{ on, label: on ? "LangGraph" : g.enabled ? "not installed" : "single call" }}>
      <Row k="Direct engine" v={on ? `draft → review → revise, up to ${g.max_rounds} revisions` : "one model call"} />
      <Row k="Switch" v={on ? undefined : <code>AGENT_GRAPH=langgraph</code>} />
      <Row k="Problem" v={g.error ?? undefined} />
    </Card>
  );
}

function EventsCard({ ev }: { ev: Events }) {
  const label = ev.ready ? "Redis" : ev.enabled ? (ev.installed ? "unreachable" : "not installed") : "in-process";
  return (
    <Card title="Events & limits" state={{ on: ev.ready, label }}>
      <Row k="Event stream" v={ev.ready ? `Redis Streams (${ev.stream})` : "this server's memory"} />
      <Row k="Sign-in limits" v={ev.ready ? "shared through Redis" : "per server"} />
      <Row k="Published" v={ev.published !== undefined ? `${ev.published} to Redis · ${ev.in_process ?? 0} kept in-process` : undefined} />
      <Row k="Feed" v={<a href="#/activity">Activity</a>} />
      <Row k="Problem" v={ev.error ?? undefined} />
    </Card>
  );
}

function MonitoringCard({ m }: { m: Monitoring }) {
  const on = m.prometheus || m.tracing;
  return (
    <Card title="Monitoring" state={{ on, label: on ? "on" : "off" }}>
      <Row k="Prometheus" v={m.prometheus ? "/metrics (bearer token)" : <code>METRICS_TOKEN</code>} />
      <Row k="Traces" v={m.tracing ? `OTLP → ${m.otlp ?? "collector"}` : <code>OTEL_EXPORTER_OTLP_ENDPOINT</code>} />
      <Row k="Dashboards" v={on ? "Grafana (k8s/stack.sh monitoring)" : undefined} />
    </Card>
  );
}
