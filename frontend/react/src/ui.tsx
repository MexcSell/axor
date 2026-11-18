import type { ReactNode } from "react";
import type { Load } from "./useLoad";

export function Badge({ on, label }: { on: boolean; label?: string }) {
  return <span className={`badge ${on ? "on" : "off"}`}>{label ?? (on ? "live" : "off")}</span>;
}

export function Head({ kicker, title, lede, actions }: { kicker: string; title: string; lede: string; actions?: ReactNode }) {
  return (
    <header className="head">
      <p className="kicker">{kicker}</p>
      <div className="head-row"><h1>{title}</h1>{actions}</div>
      <p className="lede">{lede}</p>
    </header>
  );
}

// Loading / error / content for a Load; errors keep a way forward (sign in, try again)
export function Loaded<T>({ load, retry, children }: { load: Load<T>; retry: () => void; children: (data: T, at: Date) => ReactNode }) {
  if (load.state === "loading") return <p className="muted">Loading…</p>;
  if (load.state === "error") {
    return (
      <div className="notice">
        <strong>{load.kind === "signed-out" ? "Signed out" : load.kind === "forbidden" ? "Not for this account" : "Couldn't load this"}</strong>
        <span>{load.message}</span>
        {load.kind === "signed-out" ? <a href="/">Sign in</a> : load.kind === "error" ? <button onClick={retry}>Try again</button> : null}
      </div>
    );
  }
  return <>{children(load.data, load.at)}</>;
}

export function Panel({ title, note, children, className = "" }: { title: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head"><h2>{title}</h2>{note && <span className="muted small">{note}</span>}</div>
      {children}
    </section>
  );
}

export const tok = (n: number | null | undefined) =>
  n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k` : String(Math.round(n));
