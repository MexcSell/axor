// One typed client store (GPT architecture review #1): immutable snapshots, narrow subscriptions via useSyncExternalStore.
// Every resource carries its source ("sample" | "live"); live data from /api/ui/* replaces a resource only when the server
// actually answers. A live failure never silently falls back to sample: it is recorded in `errors`.
import { useRef, useSyncExternalStore } from "react";
import * as S from "./sample";
import * as H from "./hub";
import type {
  AgentIdentity, AgentInstance, AgentVersion, Approval, Branch, Candidate, Department, Event, Experience, KnowledgeItem, MergeRequest, Mentoring,
  Message, Mission, ModelReg, NewsItem, NewsSource, Notice, Release, Settings, Source, Task, Thread,
} from "../domain/types";

export interface State {
  missions: Mission[]; tasks: Task[]; agents: AgentIdentity[]; instances: AgentInstance[]; agentVersions: AgentVersion[]; experiences: Experience[];
  threads: Thread[]; messages: Message[]; approvals: Approval[]; events: Event[]; releases: Release[]; branches: Branch[]; mergeRequests: MergeRequest[];
  candidates: Candidate[]; mentoring: Mentoring[]; departments: Department[]; knowledge: KnowledgeItem[]; newsSources: NewsSource[]; news: NewsItem[];
  models: ModelReg[]; notices: Notice[]; settings: Settings; gmThoughts: { at: string; text: string }[];
  sources: Partial<Record<keyof Omit<State, "sources" | "errors" | "me">, Source>>; errors: Record<string, string>;
  me: { name: string; role: "admin" | "member" | "guest"; email?: string } | null;
  dataMode: "sample" | "live"; liveAvailable: boolean; liveStatus: "off" | "loading" | "ok" | "error" | "unavailable";
  flash: { n: number; text: string; tone: "ok" | "info" | "warn" | "bad" } | null;
}

function initial(): State {
  return {
    missions: S.MISSIONS, tasks: S.TASKS, agents: S.AGENTS, instances: S.INSTANCES, agentVersions: S.AGENT_VERSIONS, experiences: S.EXPERIENCES,
    threads: S.THREADS, messages: S.MESSAGES, approvals: S.APPROVALS, events: S.EVENTS, releases: S.RELEASES, branches: S.BRANCHES,
    mergeRequests: S.MERGE_REQUESTS, candidates: S.CANDIDATES, mentoring: S.MENTORING, departments: S.DEPARTMENTS, knowledge: S.KNOWLEDGE,
    newsSources: S.NEWS_SOURCES, news: S.NEWS, models: S.MODELS, notices: S.NOTICES, settings: S.SETTINGS, gmThoughts: S.GM_THOUGHTS,
    sources: {}, errors: {}, me: null, dataMode: "sample", liveAvailable: false, liveStatus: "off", flash: null,
  };
}

let state: State = initial();
const subs = new Set<() => void>();
function set(fn: (s: State) => Partial<State>) { state = { ...state, ...fn(state) }; subs.forEach((f) => f()); }
export function getState() { return state; }
export function subscribe(f: () => void) { subs.add(f); return () => { subs.delete(f); }; }
// Selectors may build new arrays (e.g. filter by mission). useSyncExternalStore needs a stable snapshot, so the
// result is cached per (state, selector) and arrays that are element-wise equal keep their previous identity.
export function useStore<T>(sel: (s: State) => T): T {
  const ref = useRef<{ s: State | null; sel: unknown; v: T }>({ s: null, sel: null, v: undefined as T });
  const get = () => {
    const c = ref.current;
    if (c.s === state && c.sel === sel) return c.v;
    const v = sel(state);
    const same = Array.isArray(v) && Array.isArray(c.v) && v.length === c.v.length && v.every((x, i) => x === (c.v as unknown[])[i]);
    ref.current = { s: state, sel, v: same ? c.v : v };
    return ref.current.v;
  };
  return useSyncExternalStore(subscribe, get, get);
}
export function sourceOf(s: State, k: keyof State["sources"]): Source { return s.sources[k] ?? "sample"; }

const nowIso = () => new Date().toISOString();
let refusals = 0;
let seq = 1000;
const nid = (p: string) => `${p}-${Date.now().toString(36)}${(++seq).toString(36)}`;
function log(e: Omit<Event, "id" | "at" | "trace">) {
  if (getState().sources.events === "live") return; // live audit comes from the server only (review #3, #12)
  const id = nid("E");
  set((s) => ({ events: [{ ...e, id, at: nowIso(), trace: `tr-${id.slice(2)}` }, ...s.events] }));
}

/* ---------------- live data (/api/ui) ---------------- */
async function j<T>(url: string, init?: RequestInit): Promise<T> {
  // AXoR's CSRF guard (backend/app/main.py) only accepts writes carrying X-Requested-With: scout from the same origin.
  const r = await fetch(url, { credentials: "same-origin", ...init, headers: { "Content-Type": "application/json", "X-Requested-With": "scout", ...(init?.headers ?? {}) } });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json() as Promise<T>;
}
/* ---------------- live read models (data/live.ts) ---------------- */
// GPT review #3: Sample mode must not write real configuration (settings and news sources swap too), a late load must
// not override the user's choice, switching modes keeps each mode's edits, and a failed load is visible.
type SwapKey = "missions" | "tasks" | "agents" | "instances" | "departments" | "approvals" | "events" | "settings" | "newsSources";
const SWAP_KEYS: SwapKey[] = ["missions", "tasks", "agents", "instances", "departments", "approvals", "events", "settings", "newsSources"];
const snaps: Record<"sample" | "live", Partial<Pick<State, SwapKey>> | null> = { sample: null, live: null };
let liveGen = 0, userChoseMode = false;
export async function loadLive() {
  const g = ++liveGen;
  set(() => ({ liveStatus: "loading" }));
  const { fetchLive } = await import("./live");
  const d = await fetchLive();
  if (g !== liveGen) return; // a newer load is in flight
  if (d === "forbidden") { set(() => ({ liveStatus: "unavailable" })); return; } // members: hub data is admin-only; quietly stay on sample
  if (!d) { set((s) => ({ liveStatus: "error", errors: { ...s.errors, live: "Couldn't load live missions and agents from AXoR, so these pages show sample data. Settings and news sources you change are still saved." } })); return; }
  const cur = getState();
  const live = { missions: d.missions, tasks: d.tasks, agents: d.agents, instances: d.instances, departments: d.departments, approvals: d.approvals, events: d.events,
    settings: cur.sources.settings === "live" ? cur.settings : S.SETTINGS, newsSources: cur.sources.newsSources === "live" ? cur.newsSources : S.NEWS_SOURCES };
  if (!snaps.sample) snaps.sample = { missions: S.MISSIONS, tasks: S.TASKS, agents: S.AGENTS, instances: S.INSTANCES, departments: S.DEPARTMENTS, approvals: S.APPROVALS, events: S.EVENTS, settings: S.SETTINGS, newsSources: S.NEWS_SOURCES };
  set(() => ({ liveStatus: "ok", liveAvailable: true }));
  needsRefresh.clear();
  if (!userChoseMode || cur.dataMode === "live") { snaps.live = live; set((s) => ({ ...live, dataMode: "live", sources: { ...s.sources, ...Object.fromEntries(SWAP_KEYS.map((k) => [k, "live"])) } })); }
  else snaps.live = live; // the user is looking at sample data: keep it, the live copy waits
}
let modeGen = 0;
function applyMode(mode: "sample" | "live") {
  const s0 = getState(); if (mode === s0.dataMode || !snaps[mode]) return;
  modeGen++;
  snaps[s0.dataMode] = Object.fromEntries(SWAP_KEYS.map((k) => [k, s0[k]])) as Partial<Pick<State, SwapKey>>; // keep this mode's edits
  set((s) => ({ ...snaps[mode], dataMode: mode, sources: { ...s.sources, ...Object.fromEntries(SWAP_KEYS.map((k) => [k, mode === "live" ? "live" : "sample"])) } }));
}
// Called by pages that show hub data (missions, agents, approvals, audit). Loads once per session.
export function ensureLive() {
  const s = getState(); if (!s.me || s.liveStatus !== "off") return;
  // GET /api/control/missions and GET /api/company are administrator-only in AXoR today: members don't call them (no
  // 403 noise, no side effects) and see sample data. Remove this guard if those hubs open to members.
  if (s.me.role !== "admin") { set(() => ({ liveStatus: "unavailable" })); return; }
  loadLive();
}
// User choice from the header switch.
export function setDataMode(mode: "sample" | "live") { userChoseMode = true; applyMode(mode); }
// Live writes (owner decision 4): in live mode an action is sent to AXoR's own endpoint (data/hub.ts) and the hub data is
// reloaded afterwards, so the screen shows what the server holds. Nothing is simulated in live mode. While live data
// is still loading for the first time, nothing is sent or simulated.
let flashN = 0;
export function flash(text: string, tone: "ok" | "info" | "warn" | "bad" = "ok") { set(() => ({ flash: { n: ++flashN, text, tone } })); }
const isLive = (key: keyof State["sources"]) => getState().sources[key] === "live";
// Sample-mode success toasts at call sites; in live mode the server's answer is the toast.
export const liveMode = () => getState().dataMode === "live";
function stillLoading(): string | null {
  const s0 = getState();
  return s0.liveStatus === "loading" && s0.dataMode !== "live" && !userChoseMode ? "Still loading live data; try again in a moment." : null;
}
const inFlight = new Set<string>();
// targets whose post-write reload failed: no further write until a reload succeeds (GPT review #5)
const needsRefresh = new Set<string>();
// Sends a planned request once per key. Returns a refusal (sync) or null when sent; the outcome arrives as a flash.
// `partly`: after a refusal and the reload, true when the server kept part of it (AXoR's proposal decide saves the
// approval, then 409s if it can't start the task): the toast says so instead of "Not done".
function liveWrite(key: string, plan: H.Plan, after?: (data: unknown) => void, partly?: () => boolean): string | null {
  if (H.refused(plan)) return plan.refuse;
  if (inFlight.has(key)) return "Already sending that: wait for AXoR's answer.";
  if (needsRefresh.has(key)) { loadLive(); return "AXoR's state couldn't be reloaded after the last change here: wait a moment for the reload, then try again."; }
  inFlight.add(key);
  flash(`${plan.label.split(":")[0]}: sending to AXoR…`, "info");
  const gen = modeGen;
  H.send(plan).then(async (r) => {
    // the target stays locked until the reload shows the server's state (no second send against stale buttons)
    if (r.ok) { flash(plan.label, "ok"); after?.(r.data); }
    await loadLive();
    if (getState().liveStatus !== "ok") needsRefresh.add(key);
    inFlight.delete(key);
    if (r.ok) return;
    const sure = gen === modeGen && getState().dataMode === "live" && getState().liveStatus === "ok";
    if (sure && partly?.()) flash(`${plan.label}, but AXoR couldn't go further: ${r.error}`, "warn"); else flash(`Not done: ${r.error}`, "bad");
  });
  return null;
}

// Sample mode = no AXoR server answered /api/ui/bootstrap (static preview / signed out). While bootstrap is still
// loading, nobody is treated as admin (fail closed; GPT review #2, #4).
export const isSampleMode = (s: State) => !!s.errors.bootstrap && !/: 40[13]$/.test(s.errors.bootstrap) && !s.me; // signed out / forbidden is not sample mode
export const identityLoading = (s: State) => !s.me && !s.errors.bootstrap;
export const isAdmin = (s: State) => s.me?.role === "admin" || isSampleMode(s);

// Pulls what the server has. Resources the server doesn't serve stay "sample".
export async function bootstrap() {
  try {
    const b = await j<{ me?: State["me"]; resources?: Partial<Record<keyof State["sources"], unknown[]>>; settings?: Partial<Settings> }>("/api/ui/bootstrap");
    set((s) => {
      const next: Partial<State> = { me: b.me ?? s.me, sources: { ...s.sources } };
      for (const [k, v] of Object.entries(b.resources ?? {})) {
        if (Array.isArray(v)) { (next as Record<string, unknown>)[k] = v; next.sources![k as keyof State["sources"]] = "live"; }
      }
      if (b.settings) { next.settings = { ...s.settings, ...b.settings }; next.sources!.settings = "live"; }
      return next;
    });
    // Hub data is loaded only when a page that shows it opens (ensureLive): the hub GETs have side effects (the
    // company is created on first read, recurring tasks reopen), so visiting e.g. Appearance must not trigger them.
  } catch (e) {
    set((s) => ({ errors: { ...s.errors, bootstrap: (e as Error).message } }));
  }
}

/* ---------------- actions ---------------- */
const startKeys = new Set<string>();
export interface NewMission { key: string; text: string; title?: string; files: string[]; images: string[]; githubUrls: string[]; webUrls?: string[]; priority: Mission["priority"]; budget: number; dueDays: number; autonomy: string; createRepo: boolean; repoName?: string; repoPrivate?: boolean }
// The GM names the mission from its content (CREATE-04). Idempotent per key (MIS-005).
export function suggestTitle(text: string): string {
  const t = text.replace(/https?:\/\/\S+/g, "").replace(/\s+/g, " ").trim();
  if (!t) return "New mission";
  const verbs = /^(build|create|make|design|develop|add|improve|research|analy[sz]e|automate|launch|write|fix|migrate|set up)\b/i;
  const first = t.split(/[.!?\n]/)[0].slice(0, 80);
  const words = first.split(" ").filter(Boolean).slice(0, 7).join(" ");
  const titled = words.replace(/\b\w/g, (c) => c.toUpperCase());
  return verbs.test(first) ? titled : `Mission: ${titled}`;
}
export function addMission(n: NewMission): string {
  const blocked = stillLoading(); if (blocked) throw new Error(blocked);
  if (isLive("missions")) throw new Error("Live mode: missions are started with startLiveMission."); // AddMission routes live starts there
  const existing = getState().missions.find((m) => m.inputs && (m as Mission & { key?: string }).key === n.key);
  if (existing) return existing.id;
  // validate before reserving the idempotency key (GPT review #1, #14)
  if (!Number.isFinite(n.dueDays) || n.dueDays < 1 || n.dueDays > 3650) throw new Error("Target completion must be 1–3650 days.");
  if (!Number.isFinite(n.budget) || n.budget <= 0 || n.budget > 1e7) throw new Error("Budget must be a positive amount.");
  if (startKeys.has(n.key)) throw new Error("This mission is already being started.");
  startKeys.add(n.key);
  const ix = getState().missions.length + 1; const id = `M-${String(ix).padStart(3, "0")}`;
  const title = n.title?.trim() || suggestTitle(n.text);
  const slug = (n.repoName || title).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
  const mission: Mission & { key: string } = {
    key: n.key, id, title, summary: n.text.split("\n")[0].slice(0, 90) || title, status: "running", stage: "plan", progress: 0, progressBasis: "calculating",
    issuesOpen: 0, decisionsPending: n.createRepo && !n.githubUrls[0] ? 1 : 0, autonomy: n.autonomy, version: "v0.1.0", dueAt: new Date(Date.now() + n.dueDays * 864e5).toISOString(), dueKind: "estimated",
    nextEditionAt: new Date(Date.now() + Math.max(1, Math.round(n.dueDays / 3)) * 864e5).toISOString(), nextEditionKind: "estimated",
    startedAt: nowIso(), lastActivityAt: nowIso(), owner: getState().me?.name ?? "you", workstream: "development", icon: "sparkles", color: "#f2b53a", risk: "low",
    budget: { limit: n.budget, spent: 0 }, priority: n.priority,
    repo: n.githubUrls[0] ? { url: n.githubUrls[0], branch: `mission/${id}/main`, created: false } : n.createRepo ? { url: `https://github.com/<your-account>/${slug}`, branch: "main", created: false, pending: true } : null,
    inputs: { text: n.text, files: n.files, images: n.images, githubUrls: n.githubUrls, webUrls: n.webUrls ?? [] },
  };
  const gm: Task = { id: `${id}-T1`, missionId: id, title: "GM: plan & charter", phase: "1. Planning", status: "running", progress: 5, instanceId: `GM@${id}`, deps: [],
    start: nowIso(), end: new Date(Date.now() + 864e5).toISOString(), acceptance: ["Plan with milestones accepted", "Agents assigned"], evidence: [], retries: 0, priority: n.priority,
    history: [{ at: nowIso(), text: "Mission started; GM is drafting the plan" }], critical: true };
  const research: Task = { ...gm, id: `${id}-T2`, title: "Research internal & external sources", phase: "2. Research", status: "queued", progress: 0, instanceId: `RCH-01@${id}`, deps: [gm.id], critical: false, history: [] };
  set((s) => ({
    missions: [mission, ...s.missions], tasks: [...s.tasks, gm, research],
    instances: [...s.instances,
      { id: `GM@${id}`, agentId: "GM", missionId: id, pinnedVersion: "v3.2.0", branch: `agent/GM/mission/${id}`, status: "running", progress: 5, tasks: 1, supervisor: null, startedAt: nowIso(), errors: 0, spend: 0 },
      { id: `RCH-01@${id}`, agentId: "RCH-01", missionId: id, pinnedVersion: "v2.1.4", branch: `agent/RCH-01/mission/${id}`, status: "queued", progress: 0, tasks: 1, supervisor: `GM@${id}`, startedAt: nowIso(), errors: 0, spend: 0 }],
    threads: [{ id: `TH-${id}`, missionId: id, a: "user", b: "GM", kind: "user", unread: 1, lastAt: nowIso(), status: "running" }, ...s.threads],
    messages: [...s.messages,
      { id: nid("MSG"), threadId: `TH-${id}`, missionId: id, from: "user", to: "GM", at: nowIso(), kind: "instruction", text: n.text || title, condensed: true, state: "done", attachments: [...n.files, ...n.images] },
      { id: nid("MSG"), threadId: `TH-${id}`, missionId: id, from: "GM", to: "user", at: nowIso(), kind: "report",
        text: `Mission "${title}" created. Workspace ${id} is ready${mission.repo ? `, repository ${mission.repo.pending ? "will be created after your approval" : "linked"} (${mission.repo.url})` : ", no repository"}. I'm drafting the plan now.`, condensed: true, state: "running" }],
    approvals: n.createRepo && !n.githubUrls[0] ? [{
      id: `A-${id}`, missionId: id, ref: `GH-${id}`, title: `Create GitHub repository "${slug}"`, area: "GitHub", priority: "Medium" as const,
      question: `Create a ${n.repoPrivate === false ? "public" : "private"} repository "${slug}" under your authorized GitHub account?`, context: "No GitHub address was provided. AXoR uses your connected GitHub authorization (never just an e-mail address).",
      impact: "Creates one repository; the mission's work is pushed there on branches.", requestedBy: "GM", at: nowIso(), dueAt: new Date(Date.now() + 864e5).toISOString(), risk: "medium" as const,
      options: [{ id: "create", label: "Create repository", detail: `${n.repoPrivate === false ? "Public" : "Private"} · ${slug}`, recommended: true }, { id: "none", label: "Continue without repository", detail: "Artifacts stay in AXoR storage" }],
      evidence: ["GitHub authorization: connected account"], status: "pending" as const,
    }, ...s.approvals] : s.approvals,
  }));
  log({ missionId: id, actor: "GM", action: "mission started", target: `${id} ${title}`, result: "success", severity: "info", icon: "play" });
  // Sample mode only: live missions are started in AXoR by startLiveMission (POST /api/mos/missions).
  return id;
}

// Live: stage the files (POST /api/mos/uploads), then POST /api/mos/missions. Resolves to the new mission's ref (mx:<id>).
export async function startLiveMission(n: NewMission, files: File[]): Promise<{ id: string } | { error: string }> {
  const dry = H.planCreateMission({ ...n, uploads: [] }); if (H.refused(dry)) return { error: dry.refuse };
  if (startKeys.has(n.key)) return { error: "This mission is already being started." };
  startKeys.add(n.key);
  const gen = modeGen;
  const switched = () => gen !== modeGen || getState().dataMode !== "live";
  const uploads: number[] = [];
  for (const f of files) {
    if (switched()) { startKeys.delete(n.key); return { error: "You switched to sample data, so the mission wasn't started." }; }
    const u = await H.upload(f);
    if (!u.ok) { startKeys.delete(n.key); return { error: u.error }; }
    uploads.push(u.id);
  }
  if (switched()) { startKeys.delete(n.key); return { error: "You switched to sample data, so the mission wasn't started." }; }
  const plan = H.planCreateMission({ ...n, uploads }) as H.Req;
  const r = await H.send<{ mission?: { id?: number } }>(plan);
  if (!r.ok) { startKeys.delete(n.key); return { error: r.error }; }
  const mid = r.data?.mission?.id;
  await loadLive();
  return { id: typeof mid === "number" ? `mx:${mid}` : "" };
}

export function decide(approvalId: string, option: string | undefined, text: string, images: string[]): string | null {
  const blocked = stillLoading(); if (blocked) return blocked;
  const a = getState().approvals.find((x) => x.id === approvalId); if (!a || a.status !== "pending") return "This decision was already answered."; // double-submit guard
  // a proposal (CT-n) and its task (C-n) share one lock: approving from Approvals and dragging to Running can't both send
  if (isLive("approvals")) return liveWrite(a.id.startsWith("CT-") ? `task:C-${a.id.slice(3)}` : `decide:${a.id}`, H.planDecide(a, option, text, images), undefined,
    () => { const t = getState().tasks.find((x) => x.id === `C-${a.id.slice(3)}`); return a.id.startsWith("CT-") && option === "approve" && !!t && t.status !== "awaiting_approval" && t.status !== "cancelled"; });
  const status: Approval["status"] = option === "reject" ? "rejected" : option === "changes" ? "changes" : "approved";
  set((s) => ({
    approvals: s.approvals.map((x) => x.id === approvalId ? { ...x, status, response: { option, text, images, at: nowIso(), by: s.me?.name ?? "you" } } : x),
    tasks: s.tasks.map((t) => t.blocker?.approvalId === approvalId ? { ...t, status: status === "approved" ? "running" : "blocked", blocker: status === "approved" ? undefined : t.blocker,
      history: [...t.history, { at: nowIso(), text: `Decision ${approvalId}: ${status}` }] } : t),
    missions: s.missions.map((m) => {
      if (m.id !== a.missionId) return m;
      const next = { ...m, decisionsPending: Math.max(0, m.decisionsPending - 1) };
      // repository-creation decision: apply the outcome (GPT review #1, #16)
      if (a.ref.startsWith("GH-") && m.repo?.pending) next.repo = status === "approved" && option !== "none" ? { ...m.repo, pending: false, created: true } : null;
      return next;
    }),
    notices: s.notices.map((n) => n.detail.includes(approvalId) ? { ...n, read: true } : n),
  }));
  log({ missionId: a.missionId, actor: "user", action: `decision ${status}`, target: `${a.id} ${a.title}`, result: "success", severity: a.risk === "high" ? "high" : "info", icon: "check" });
  // Sample-mode decision: recorded in this browser session only (live decisions go to the hubs above).
  return null;
}

export function sendMessage(missionId: string, threadId: string | null, to: string, text: string, attachments: string[]) {
  const blocked = stillLoading(); if (blocked) { flash(blocked, "warn"); return threadId ?? ""; }
  const s0 = getState();
  if (isLive("agents")) {
    const ag = s0.agents.find((a) => a.id === to);
    const conv = threadId ? liveConv.get(threadId) ?? null : null;
    const mi = s0.missions.find((m) => m.id === missionId);
    const plan = H.planChat(ag, text, attachments, conv, mi ? { id: mi.id, title: mi.title, summary: mi.summary } : undefined);
    if (H.refused(plan)) { flash(plan.refuse, "warn"); return threadId ?? ""; }
    return liveChat(missionId, threadId, ag!, plan, text);
  }
  let tid = threadId;
  if (!tid) {
    const ex = s0.threads.find((t) => t.missionId === missionId && ((t.a === "user" && t.b === to) || (t.b === "user" && t.a === to)));
    tid = ex?.id ?? `TH-${missionId}-${to}`;
    if (!ex) set((s) => ({ threads: [{ id: tid!, missionId, a: "user", b: to, kind: "user", unread: 0, lastAt: nowIso(), status: "queued" }, ...s.threads] }));
  }
  const id = nid("MSG");
  set((s) => ({
    messages: [...s.messages, { id, threadId: tid!, missionId, from: "user", to, at: nowIso(), kind: "instruction", text, condensed: true, state: "queued", attachments }],
    threads: s.threads.map((t) => t.id === tid ? { ...t, lastAt: nowIso(), status: "running" } : t),
  }));
  // Execution state progression shown on the message (CTRL-003/004). Sample mode simulates the agent acknowledging.
  const step = (state: Message["state"], ms: number) => window.setTimeout(() => set((s) => ({ messages: s.messages.map((m) => m.id === id ? { ...m, state } : m) })), ms);
  step("running", 700);
  window.setTimeout(() => {
    const ag = getState().agents.find((a) => a.id === to);
    set((s) => ({
      messages: s.messages.map((m): Message => m.id === id ? { ...m, state: "done" } : m).concat({
        id: nid("MSG"), threadId: tid!, missionId, from: to, to: "user", at: nowIso(), kind: "report", condensed: true, state: "running",
        text: `${ag?.name ?? to}: received. I'll fold this into my current task and report back with evidence.${s.sources.messages === "live" ? "" : " (sample mode: simulated reply)"}`,
      }),
    }));
  }, 1800);
  log({ missionId, actor: "user", action: "sent instruction", target: to, result: "info", severity: "info", icon: "message" });
  // Sample mode: messages stay in this session (live messages go to AXoR's company chat via liveChat).
  return tid!;
}

// Live chat: the user's message and a running reply appear at once; the reply is polled from the agent's workspace.
const liveConv = new Map<string, number>();
function liveChat(missionId: string, threadId: string | null, ag: AgentIdentity, plan: H.Req, text: string): string {
  const key = `chat:${ag.hubId}`;
  if (inFlight.has(key)) { flash(`${ag.name} is still answering: wait for it.`, "warn"); return threadId ?? ""; }
  const s0 = getState();
  const ex = threadId ? s0.threads.find((t) => t.id === threadId) : s0.threads.find((t) => t.missionId === missionId && ((t.a === "user" && t.b === ag.id) || (t.b === "user" && t.a === ag.id)));
  const tid = ex?.id ?? `TH-${missionId}-${ag.id}`;
  const mine = nid("MSG"), reply = nid("MSG");
  set((s) => ({
    threads: ex ? s.threads.map((t) => t.id === tid ? { ...t, lastAt: nowIso(), status: "running" } : t)
      : [{ id: tid, missionId, a: "user", b: ag.id, kind: "user", unread: 0, lastAt: nowIso(), status: "running" }, ...s.threads],
    messages: [...s.messages, { id: mine, threadId: tid, missionId, from: "user", to: ag.id, at: nowIso(), kind: "instruction", text, condensed: true, state: "queued", attachments: [] }],
  }));
  const patchMsg = (id: string, p: Partial<Message>) => set((s) => ({ messages: s.messages.map((m) => m.id === id ? { ...m, ...p } : m) }));
  inFlight.add(key);
  type WS = { conversation_id?: number; messages?: { id: number; role: string; body: string; status: string }[] };
  H.send<WS>(plan).then(async (r) => {
    if (!r.ok) { inFlight.delete(key); patchMsg(mine, { state: "failed" }); flash(`Not sent: ${r.error}`, "bad"); return; }
    const cid = r.data?.conversation_id; if (typeof cid === "number") liveConv.set(tid, cid);
    patchMsg(mine, { state: "done" });
    const last = (w?: WS) => (w?.messages ?? []).filter((m) => m.role === "agent").sort((a, b) => b.id - a.id)[0];
    const rid = last(r.data)?.id;
    set((s) => ({ messages: [...s.messages, { id: reply, threadId: tid, missionId, from: ag.id, to: "user", at: nowIso(), kind: "report", text: `${ag.name} is answering…`, condensed: true, state: "running" }] }));
    // the reply is written in the background (company_agents.AgentDesk._reply): poll the workspace, up to ~5 minutes
    for (let i = 0; i < 120; i++) {
      await new Promise((ok) => window.setTimeout(ok, 2500));
      const w = await fetch(`/api/company/agents/${ag.hubId}/workspace${typeof cid === "number" ? `?conversation=${cid}` : ""}`, { credentials: "same-origin" })
        .then((x) => (x.ok ? (x.json() as Promise<WS>) : null)).catch(() => null);
      const m = (w?.messages ?? []).find((x) => x.id === rid) ?? last(w ?? undefined);
      if (m && m.status !== "running") {
        patchMsg(reply, { text: m.body || "(no answer)", state: m.status === "done" ? "done" : "failed", at: nowIso() });
        set((s) => ({ threads: s.threads.map((t) => t.id === tid ? { ...t, lastAt: nowIso(), status: "done" } : t) }));
        inFlight.delete(key); return;
      }
    }
    patchMsg(reply, { text: `${ag.name} is still working on it: open the agent's workspace on the classic Company page to follow it.`, state: "running" });
    inFlight.delete(key);
  });
  return tid;
}

export function taskAction(taskId: string, action: "pause" | "resume" | "retry" | "cancel"): string | null {
  const blocked = stillLoading(); if (blocked) return blocked;
  if (isLive("tasks")) {
    const t = getState().tasks.find((x) => x.id === taskId); if (!t) return "Unknown task";
    return liveWrite(`task:${taskId}`, H.planTaskAction(t, action));
  }
  const map = { pause: "paused", resume: "running", retry: "running", cancel: "cancelled" } as const;
  set((s) => ({ tasks: s.tasks.map((t) => t.id === taskId ? { ...t, status: map[action], retries: action === "retry" ? t.retries + 1 : t.retries, history: [...t.history, { at: nowIso(), text: `${action} by you` }] } : t) }));
  const t = getState().tasks.find((x) => x.id === taskId);
  log({ missionId: t?.missionId ?? null, actor: "user", action: `task ${action}`, target: taskId, result: "info", severity: "low", icon: action });
  return null;
}
// Board moves (MC-FLOW): cannot mark complete without acceptance evidence; dependencies must be done before work starts.
export function moveTask(taskId: string, to: Task["status"]): string | null {
  const blocked = stillLoading(); if (blocked) return blocked;
  const s0 = getState(); const t = s0.tasks.find((x) => x.id === taskId); if (!t) return "Unknown task";
  if (t.status === to) return null;
  if (isLive("tasks")) return liveWrite(`task:${taskId}`, H.planMoveTask(t, to));
  if ((to === "done" || to === "passed") && !t.evidence.length) return `${t.id} can't be marked done without acceptance evidence. Send it to Review so QA can verify it.`;
  const open = t.deps.filter((d) => s0.tasks.find((x) => x.id === d)?.status !== "done");
  if ((to === "running" || to === "review") && open.length) return `${t.id} depends on ${open.join(", ")}, which ${open.length > 1 ? "are" : "is"} not done yet.`;
  set((s) => ({ tasks: s.tasks.map((x) => x.id === taskId ? { ...x, status: to, history: [...x.history, { at: nowIso(), text: `Moved to ${to} by you` }] } : x) }));
  log({ missionId: t.missionId, actor: "user", action: `moved task to ${to}`, target: taskId, result: "info", severity: "low", icon: "list" });
  return null;
}
export function reassignTask(taskId: string, instanceId: string) {
  set((s) => ({ tasks: s.tasks.map((x) => x.id === taskId ? { ...x, instanceId, history: [...x.history, { at: nowIso(), text: `Reassigned to ${instanceId}` }] } : x) }));
}
export function missionAction(missionId: string, action: "pause" | "resume" | "cancel" | "archive"): string | null {
  const blocked = stillLoading(); if (blocked) return blocked;
  if (isLive("missions")) {
    const m = getState().missions.find((x) => x.id === missionId); if (!m) return "Unknown mission";
    return liveWrite(`mission:${missionId}`, H.planMissionAction(m, action));
  }
  const st = { pause: "paused", resume: "running", cancel: "cancelled", archive: undefined } as const;
  set((s) => ({ missions: s.missions.map((m) => m.id === missionId ? { ...m, status: st[action] ?? m.status, archived: action === "archive" ? true : m.archived } : m) }));
  log({ missionId, actor: "user", action: `mission ${action}`, target: missionId, result: "info", severity: "low" });
  return null;
}

export function addNewsSource(src: { name: string; url: string; cadence: string; scope: NewsSource["scope"]; topics: string[]; missionId?: string }): string | null {
  if (src.scope === "mission" && !src.missionId) return "Choose the mission this source belongs to.";
  let u: URL; try { u = new URL(src.url); } catch { return "That isn't a valid URL."; }
  if (!/^https?:$/.test(u.protocol)) return "Only http(s) sources are allowed.";
  if (/^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|0\.|\[)/.test(u.hostname) || /\.(internal|local|localhost)$/.test(u.hostname) || /^(\d+|0x[0-9a-f]+)$/i.test(u.hostname.split(".").pop() ?? "") && !/^\d+\.\d+\.\d+\.\d+$/.test(u.hostname)) return "Private and internal addresses are blocked (SSRF protection).";
  if (getState().newsSources.some((x) => x.url === u.toString())) return "This source is already registered.";
  const id = nid("S");
  set((s) => ({ newsSources: [...s.newsSources, { id, name: src.name || u.hostname, url: u.toString(), cadence: src.cadence, trust: 50, lastFetched: null, status: "pending", scope: src.scope, missionId: src.scope === "mission" ? src.missionId : undefined, topics: src.topics, items: 0, addedBy: s.me?.name ?? "you" }] }));
  log({ missionId: null, actor: "user", action: "added news source", target: u.hostname, result: "success", severity: "info", icon: "rss" });
  if (getState().sources.newsSources === "live") {
    // Live: the server validates (SSRF, scope permissions) and owns the id; a refusal reverts the optimistic row.
    fetch("/api/ui/news-sources", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Requested-With": "scout" }, body: JSON.stringify(src) })
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (r.ok) set((s) => ({ newsSources: s.newsSources.some((x) => x.id === id) ? s.newsSources.map((x) => x.id === id ? { ...x, ...d } : x) : [...s.newsSources, d] }));
        else set((s) => ({ newsSources: s.newsSources.filter((x) => x.id !== id), errors: { ...s.errors, newsSource: d.detail ?? `Server refused the source (${r.status})` } }));
      })
      .catch(() => set((s) => ({ newsSources: s.newsSources.filter((x) => x.id !== id), errors: { ...s.errors, newsSource: "Couldn't reach the server" } })));
  } else {
    // sample fetch completes only if the source is still pending (a disable meanwhile wins; #10)
    window.setTimeout(() => set((s) => ({ newsSources: s.newsSources.map((x) => x.id === id && x.status === "pending" ? { ...x, status: "ok", lastFetched: nowIso() } : x) })), 2200);
  }
  return null;
}
// Live edits are optimistic and roll back on refusal; a row still being created can't be edited yet (review #1, #8/#9).
const pendingNew = (id: string) => getState().sources.newsSources === "live" && getState().newsSources.find((x) => x.id === id)?.status === "pending" && id.startsWith("S-");
export function updateNewsSource(id: string, patch: Partial<NewsSource>): string | null {
  if (pendingNew(id)) return "Still saving this source; try again in a moment.";
  const live = getState().sources.newsSources === "live";
  // The server stores name, cadence and enabled only: trust and fetch results can't be set from the UI (#11, #12).
  if (live && ("trust" in patch || "lastFetched" in patch || patch.status === "ok" || patch.status === "error")) return "Trust and fetch results come from the fetcher; they can't be set here.";
  const before = getState().newsSources.find((x) => x.id === id); if (!before) return "Unknown source";
  set((s) => ({ newsSources: s.newsSources.map((x) => x.id === id ? { ...x, ...patch } : x) }));
  if (live) {
    const body: Record<string, unknown> = {}; if (patch.name) body.name = patch.name; if (patch.cadence) body.cadence = patch.cadence; if (patch.status) body.enabled = patch.status !== "disabled";
    j(`/api/ui/news-sources/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) })
      // roll back only the fields this request changed, and only if nothing newer replaced them (#8)
      .catch((e) => set((s) => ({ newsSources: s.newsSources.map((x) => {
        if (x.id !== id) return x; const y = { ...x } as Record<string, unknown>;
        for (const k of Object.keys(patch)) if (y[k] === (patch as Record<string, unknown>)[k]) y[k] = (before as unknown as Record<string, unknown>)[k];
        return y as unknown as NewsSource;
      }), errors: { ...s.errors, newsSource: (e as Error).message } })));
  }
  return null;
}
export function removeNewsSource(id: string): string | null {
  if (pendingNew(id)) return "Still saving this source; try again in a moment.";
  const before = getState().newsSources; const ix = before.findIndex((x) => x.id === id);
  set((s) => ({ newsSources: s.newsSources.filter((x) => x.id !== id) }));
  if (getState().sources.newsSources === "live" && ix >= 0) j(`/api/ui/news-sources/${encodeURIComponent(id)}`, { method: "DELETE" })
    .catch((e) => set((s) => ({ newsSources: s.newsSources.some((x) => x.id === id) ? s.newsSources : [...s.newsSources.slice(0, ix), before[ix], ...s.newsSources.slice(ix)], errors: { ...s.errors, newsSource: (e as Error).message } })));
  return null;
}

// Promotion gates, enforced in the action itself rather than only by the page (GPT review #2, #1):
// verified by an independent evaluator, no security regression, a rollback point exists, and non-low risk needs the
// owner's permission-gate approval.
export function promotionBlockers(s: State, c: Candidate): string[] {
  const out: string[] = [];
  if (c.status !== "passed") out.push("not verified by an independent evaluator");
  const sec = c.metrics.find((m) => /security/i.test(m.name)); if (sec && sec.cand > sec.base) out.push("security regression");
  if (!s.agentVersions.some((v) => v.agentId === c.agentId && v.version === c.from) && !s.agents.some((a) => a.id === c.agentId && a.baseline === c.from)) out.push("no rollback point");
  if (c.risk !== "low" && !c.permissionApproved) out.push(`${c.risk}-risk change needs your permission-gate approval`);
  if (!isAdmin(s)) out.push("only an administrator can promote");
  return out;
}
export function approveCandidateGate(id: string, approved: boolean) {
  if (!isAdmin(getState())) return "Only an administrator can approve the permission gate.";
  set((s) => ({ candidates: s.candidates.map((x) => x.id === id ? { ...x, permissionApproved: approved } : x) }));
  log({ missionId: null, actor: "user", action: approved ? "approved permission gate" : "withdrew permission gate", target: id, result: "info", severity: "medium", icon: "check" });
  return null;
}
export function candidateAction(id: string, action: "evaluate" | "promote" | "reject" | "rollback"): string | null {
  const s0 = getState(); const c = s0.candidates.find((x) => x.id === id); if (!c) return "Unknown candidate";
  if (action === "promote") { const b = promotionBlockers(s0, c); if (b.length) return `Can't promote: ${b.join("; ")}.`; }
  if (action === "rollback") {
    if (c.status !== "promoted") return "Only a promoted candidate can be rolled back.";
    if (!s0.agents.some((a) => a.id === c.agentId && a.baseline === c.to)) return `${c.agentId} is no longer on ${c.to}; roll back the newer version instead.`; // obsolete rollback (#7)
  }
  const status = { evaluate: "evaluating", promote: "promoted", reject: "rejected", rollback: "rolled_back" }[action] as Candidate["status"];
  set((s) => ({
    candidates: s.candidates.map((x) => x.id === id ? { ...x, status, canary: action === "promote" ? 10 : x.canary } : x),
    agents: action === "promote" ? s.agents.map((a) => a.id === c.agentId ? { ...a, baseline: c.to, candidate: undefined } : a)
      : action === "rollback" && c.status === "promoted" ? s.agents.map((a) => a.id === c.agentId && a.baseline === c.to ? { ...a, baseline: c.from } : a) : s.agents,
    agentVersions: action === "promote" ? s.agentVersions.map((v) => v.agentId === c.agentId ? { ...v, status: v.version === c.to ? "baseline" : v.status === "baseline" ? "retired" : v.status } : v)
      : action === "rollback" && c.status === "promoted" ? s.agentVersions.map((v) => v.agentId === c.agentId ? { ...v, status: v.version === c.to ? "rolled_back" : v.version === c.from ? "baseline" : v.status } : v) : s.agentVersions,
  }));
  log({ missionId: null, actor: "user", action: `candidate ${action}`, target: `${c.agentId} ${c.to}`, result: action === "reject" ? "warning" : "success", severity: "medium", icon: "dna" });
  // Sample data only: simulate the independent verdict. Live candidates get their verdict from a real evaluation (#2).
  // Only an evaluation that is still running may set it (a rejection meanwhile wins; review #1, #18).
  if (action === "evaluate" && getState().sources.candidates !== "live") window.setTimeout(() => set((s) => ({ candidates: s.candidates.map((x) => x.id === id && x.status === "evaluating" ? { ...x, status: x.delta > 5 ? "passed" : "failed" } : x) })), 2500);
  return null;
}
// Shows an action's refusal as a warning toast; returns true when there was one (so callers skip their success toast).
export function toastIfErr(err: string | null, toast: (t: string, k?: "ok" | "info" | "warn" | "bad") => void): boolean { if (err) toast(err, "warn"); return !!err; }
// Agent audit rollback: the target version becomes the baseline, the departed one is marked rolled back (#18).
export function rollbackAgentVersion(agentId: string, version: string): string | null {
  const s0 = getState(); const a = s0.agents.find((x) => x.id === agentId); if (!a) return "Unknown agent";
  if (!isAdmin(s0)) return "Only an administrator can roll back an agent.";
  if (a.baseline === version) return `${version} is already the baseline.`;
  const from = a.baseline;
  set((s) => ({
    agents: s.agents.map((x) => x.id === agentId ? { ...x, baseline: version } : x),
    agentVersions: s.agentVersions.map((v) => v.agentId !== agentId ? v : v.version === version ? { ...v, status: "baseline" } : v.version === from ? { ...v, status: "rolled_back" } : v),
  }));
  log({ missionId: null, actor: "user", action: `rolled back ${agentId}`, target: `${from} → ${version}`, result: "warning", severity: "medium", icon: "retry" });
  return null;
}

export function setSettings(patch: Partial<Settings>): string | null {
  const s0 = getState();
  if (["selfRenewal", "aiRoles", "autonomy", "verificationProvider"].some((k) => k in patch) && !isAdmin(s0)) {
    const msg = identityLoading(s0) ? "Still checking who you are; try again in a moment." : "Only administrators change self-renewal, autonomy levels, verification and AI roles.";
    // also recorded so the global error toaster shows it even where the caller ignores the return value
    set((s) => ({ errors: { ...s.errors, settings: `${msg} (${++refusals})` } }));
    return msg;
  }
  const before = s0.settings;
  set((s) => ({ settings: { ...s.settings, ...patch } }));
  log({ missionId: null, actor: "user", action: "changed settings", target: Object.keys(patch).join(", "), result: "info", severity: "low", icon: "settings" });
  // Live: a refused change (e.g. self-renewal by a non-admin) is rolled back and reported (review #1, #7).
  if (getState().sources.settings === "live") j("/api/ui/settings", { method: "PUT", body: JSON.stringify(patch) })
    // restore only fields still holding this request's value (a newer edit wins; #8)
    .catch((e) => set((s) => ({ settings: { ...s.settings, ...Object.fromEntries(Object.keys(patch).filter((k) => s.settings[k as keyof Settings] === patch[k as keyof Settings]).map((k) => [k, before[k as keyof Settings]])) }, errors: { ...s.errors, settings: (e as Error).message } })));
  return null;
}
// Roles that would have no enabled model if these models were switched (#15).
export function rolesLosingCoverage(s: State, ids: string[], enabled: boolean): string[] {
  if (enabled) return [];
  const after = s.models.map((m) => (ids.includes(m.id) ? { ...m, enabled: false } : m));
  const roles = new Set(s.models.flatMap((m) => m.roles));
  return [...roles].filter((r) => s.models.some((m) => m.enabled && m.roles.includes(r)) && !after.some((m) => m.enabled && m.roles.includes(r)));
}
export function updateModel(id: string, patch: Partial<ModelReg>) { set((s) => ({ models: s.models.map((m) => m.id === id ? { ...m, ...patch } : m) })); }
export function markNotice(id: string | "all") { set((s) => ({ notices: s.notices.map((n) => (id === "all" || n.id === id) ? { ...n, read: true } : n) })); }
export function readThread(id: string) { set((s) => ({ threads: s.threads.map((t) => t.id === id ? { ...t, unread: 0 } : t) })); }

// Mission-scoped selectors (AG-AT-01: nothing crosses missions).
export const byMission = <T extends { missionId: string | null }>(list: T[], missionId: string) => list.filter((x) => x.missionId === missionId);
export const agentById = (s: State, id: string) => s.agents.find((a) => a.id === id);
export const nameOf = (s: State, p: string) => (p === "user" ? s.me?.name ?? "You" : p);
