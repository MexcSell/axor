// The /api/stack response (backend/app/stack.py). Fields a member can't see are optional.
export type StackRow = { key: string; spec: string; now: string; live: boolean };
export type Step = { key: string; title: string; done: boolean; detail: string };
export type Database = { engine: "sqlite" | "postgres"; host?: string; port?: number; database?: string; schema?: string };
export type Runtime = {
  enabled: boolean; installed: boolean; ready: boolean; address?: string | null; namespace?: string; queue?: string;
  error?: string | null; since?: number | null; submitted?: number; fallbacks?: number;
};
export type Graph = { enabled: boolean; installed: boolean; max_rounds: number; error?: string | null };
export type Events = { enabled: boolean; installed: boolean; ready: boolean; stream?: string | null; published?: number; in_process?: number; error?: string | null };
export type Monitoring = { prometheus: boolean; tracing: boolean; otlp?: string | null };
export type Stack = {
  version: string; stack: StackRow[]; database: Database; missions_runtime: Runtime; agent_graph: Graph; events: Events;
  monitoring: Monitoring; react: boolean; migration: Step[];
};
