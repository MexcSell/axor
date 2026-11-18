import { useCallback, useEffect, useState } from "react";
import { Forbidden, SignedOut } from "./http";

export type Load<T> =
  | { state: "loading" }
  | { state: "ok"; data: T; at: Date }
  | { state: "error"; message: string; kind: "signed-out" | "forbidden" | "error" };

// Loads with `fetcher`, again every `everyMs` (0: once) and whenever `deps` change; keeps the last data while reloading.
export function useLoad<T>(fetcher: (signal: AbortSignal) => Promise<T>, everyMs: number, deps: unknown[]) {
  const [load, setLoad] = useState<Load<T>>({ state: "loading" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fetcher, deps);
  const reload = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await run(signal ?? new AbortController().signal);
      setLoad({ state: "ok", data, at: new Date() });
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      const kind = e instanceof SignedOut ? "signed-out" : e instanceof Forbidden ? "forbidden" : "error";
      setLoad({ state: "error", message: (e as Error).message, kind });
    }
  }, [run]);
  useEffect(() => {
    const ctl = new AbortController();
    reload(ctl.signal);
    const t = everyMs ? window.setInterval(() => reload(), everyMs) : 0;
    return () => { ctl.abort(); if (t) window.clearInterval(t); };
  }, [reload, everyMs]);
  return { load, reload };
}
