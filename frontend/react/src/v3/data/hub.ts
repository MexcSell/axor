// Live writes to AXoR's hubs (owner decision 4, 2026-11-16: "wiring the real actions: enable").
//
// Each UI action maps to the endpoint the classic pages already use, or is refused with the reason. Nothing is faked:
// after a write the store reloads the hub data, so the screen shows what the server holds. The plan* functions are pure
// (tests/frontend/ui-v3-hub-writes.test.cjs); send() does the request and returns the server's own error text.
import type { AgentIdentity, Approval, Mission, Task } from "../domain/types";

export interface Req { method: "POST" | "PATCH"; url: string; body?: unknown; label: string }
export type Plan = Req | { refuse: string };
export const refused = (p: Plan): p is { refuse: string } => "refuse" in p;

const int = (s: string, prefix: string): number | null => {
  if (!s.startsWith(prefix)) return null;
  const n = Number(s.slice(prefix.length));
  return Number.isInteger(n) && n > 0 ? n : null;
};
const ctlTask = (t: Task) => int(t.id, "C-");

/* ---------- approvals ---------- */
// CT-<task id>: a Mission Intelligence proposal (POST /api/control/mission-tasks/{id}/decide {ok}).
// CO-<approval id>: a company approval (POST /api/company/approvals/{id}/decide {decision, reason}). Like the classic
// Company page, deciding doesn't execute: the approved action is run from the classic page's Execute button.
export function planDecide(a: Approval, option: string | undefined, text: string, images: string[]): Plan {
  if (images.length) return { refuse: "AXoR decisions don't take pictures yet: remove them, or describe them in the note." };
  const ct = int(a.id, "CT-");
  if (ct) {
    // AXoR proposals are approved (and started) or declined; there is no "request changes" (review #4, #1)
    if (option === "changes") return { refuse: "AXoR proposals are approved or declined: decline it and say what to do instead, or message the agent." };
    const ok = option === "approve";
    if (!ok && option !== "skip" && option !== "reject") return { refuse: "Choose approve or skip." };
    return { method: "POST", url: `/api/control/mission-tasks/${ct}/decide`, body: { ok }, label: ok ? `Approved: ${a.title}` : `Declined: ${a.title}` };
  }
  const co = int(a.id, "CO-");
  if (co) {
    const decision = option === "reject" ? "reject" : option === "changes" ? "changes" : "approve";
    const reason = text.trim().slice(0, 1000);
    if (decision !== "approve" && !reason) return { refuse: "Say why, so the team can act on it." };
    return { method: "POST", url: `/api/company/approvals/${co}/decide`, body: { decision, reason },
      label: decision === "approve" ? `Approved: ${a.title} (run it from Company → Approvals → Execute)` : decision === "reject" ? `Rejected: ${a.title}` : `Changes asked: ${a.title}` };
  }
  return { refuse: "This decision isn't an AXoR approval, so it can't be sent." };
}

/* ---------- tasks ---------- */
// Where the work runs decides what the UI may do (review #4, #3). PATCH /api/control/tasks/{id} (done | cancelled | todo)
// only changes the Control task, so it is used for agent-run tasks and for tasks not yet sent anywhere. A task on a team
// board is (re)started with POST mission-tasks/{id}/run; stopping or accepting it happens on the board. A task that is a
// mission's own work follows its mission (pause / resume / cancel the mission). AXoR has no task pause.
type Where = "agent" | "board" | "mission" | "unsent" | "unknown";
export function whereTask(t: Task): Where {
  if (t.hubRoute === "agent") return "agent";
  if (t.hubRoute === "mission" || (t.hubRef ?? "").startsWith("mx:")) return "mission";
  if (t.hubRoute === "board") return t.hubRef ? "board" : "unsent";
  return t.hubRef ? "unknown" : t.hubRoute ? "unsent" : "unknown";
}
const elsewhere = (t: Task, w: Where) => w === "board" ? `${t.id} runs on its team's board: stop or accept it there (Competition page).`
  : w === "mission" ? `${t.id} is its mission's own work: pause, resume or cancel the mission instead.` : `${t.id}: AXoR didn't say where it runs, so it isn't changed from here.`;
export function planTaskAction(t: Task, action: "pause" | "resume" | "retry" | "cancel"): Plan {
  const id = ctlTask(t); if (!id) return { refuse: `${t.id} isn't an AXoR task.` };
  if (action === "pause" || action === "resume") return { refuse: "AXoR tasks can't be paused: cancel the task, or pause the whole mission." };
  const w = whereTask(t);
  if (action === "cancel") {
    if (["done", "cancelled"].includes(t.status)) return { refuse: `${t.id} is finished already.` };
    if (w !== "agent" && w !== "unsent") return { refuse: elsewhere(t, w) };
    return { method: "PATCH", url: `/api/control/tasks/${id}`, body: { status: "cancelled" }, label: `${t.id} cancelled` };
  }
  if (t.status === "running" || t.status === "review") return { refuse: `${t.id} is under way: wait for it, or cancel it.` };
  if (t.status === "awaiting_approval") return { refuse: `${t.id} is a proposal: approve it first (Approvals).` };
  if (w === "agent") return { method: "PATCH", url: `/api/control/tasks/${id}`, body: { status: "todo", feedback: "Retried from Mission Control (UI v3)." }, label: `${t.id} sent back to run again` };
  if (w === "board" || w === "unsent") return { method: "POST", url: `/api/control/mission-tasks/${id}/run`, label: `${t.id} sent to the team's board again` };
  return { refuse: elsewhere(t, w) };
}
// Board moves: only the moves AXoR has. The other columns are states AXoR sets itself.
export function planMoveTask(t: Task, to: Task["status"]): Plan {
  const id = ctlTask(t); if (!id) return { refuse: `${t.id} isn't an AXoR task.` };
  const w = whereTask(t);
  if (to === "cancelled") return planTaskAction(t, "cancel");
  if (t.status === "running") return { refuse: `${t.id} is running: wait for it, or cancel it.` };
  if (to === "done" || to === "passed") {
    if (w !== "agent") return { refuse: w === "unsent" ? `${t.id} hasn't run yet.` : elsewhere(t, w) };
    if (!t.evidence.length) return { refuse: `${t.id} can't be marked done without a result. Let the agent finish it, or send it back.` };
    return { method: "PATCH", url: `/api/control/tasks/${id}`, body: { status: "done" }, label: `${t.id} accepted` };
  }
  if (to === "queued") {
    if (t.status === "awaiting_approval") return { refuse: `${t.id} is a proposal: approve it (Approvals) to queue it.` };
    if (w !== "agent" && w !== "unsent") return { refuse: elsewhere(t, w) };
    return { method: "PATCH", url: `/api/control/tasks/${id}`, body: { status: "todo" }, label: `${t.id} back in the queue` };
  }
  if (to === "running") {
    if (t.status === "awaiting_approval") return { method: "POST", url: `/api/control/mission-tasks/${id}/decide`, body: { ok: true }, label: `${t.id} approved and started` };
    if (w === "mission" || w === "unknown") return { refuse: elsewhere(t, w) };
    if (t.status === "review") return { refuse: `${t.id} is waiting for review: accept it or send it back.` };
    return { method: "POST", url: `/api/control/mission-tasks/${id}/run`, label: `${t.id} started` };
  }
  return { refuse: `AXoR sets "${to}" itself: move the task to Queued, Running, Done or Cancelled.` };
}

/* ---------- missions ---------- */
// Custom missions (mx:<id>) are AXoR missions (/api/mos). Predefined competition missions (comp:<id>) run while their
// competition is active and have no pause; they are changed on the Competition page.
export function planMissionAction(m: Mission, action: "pause" | "resume" | "cancel" | "archive"): Plan {
  if (action === "archive") return { refuse: "Live missions aren't archived: AXoR keeps the recent finished ones and prunes older ones itself." };
  const mx = int(m.id, "mx:");
  if (!mx) return { refuse: `${m.title} is a competition mission: it runs while the competition is active. Change it on the Competition page.` };
  return { method: "POST", url: `/api/mos/missions/${mx}/${action}`, label: `${m.title}: ${action === "pause" ? "paused" : action === "resume" ? "resumed" : "cancelled"}` };
}

export interface CreateIn { text: string; title?: string; githubUrls: string[]; webUrls?: string[]; budget: number; dueDays: number; autonomy: string; createRepo: boolean; uploads: number[] }
// POST /api/mos/missions. AXoR names the mission from the goal (the title, if given, leads it). Budget in dollars
// (0.05..10000), deadline in epoch seconds, autonomy {level: L0..L4}, attachments = staged upload ids.
export function planCreateMission(n: CreateIn, now = Date.now()): Plan {
  const goal = [n.title?.trim(), n.text.trim()].filter(Boolean).join("\n\n");
  if (goal.length < 12) return { refuse: "Describe the mission in at least 12 characters." };
  if (goal.length > 4000) return { refuse: "Keep the description under 4,000 characters (attach longer material as a document)." };
  if (n.createRepo) return { refuse: "AXoR can't create a GitHub repository from a new mission yet: link an existing repository, or choose “Continue without repository”." };
  if (!Number.isFinite(n.budget) || n.budget < 0.05 || n.budget > 10000) return { refuse: "AXoR mission budgets are $0.05 to $10,000." };
  if (!Number.isFinite(n.dueDays) || n.dueDays < 1 || n.dueDays > 3650) return { refuse: "Target completion must be 1–3650 days." };
  if (!/^L[0-4]$/.test(n.autonomy)) return { refuse: "Unknown autonomy level." };
  const links = [...n.githubUrls, ...(n.webUrls ?? [])];
  return { method: "POST", url: "/api/mos/missions", label: "Mission started in AXoR",
    body: { goal, budget: Math.round(n.budget * 100) / 100, deadline: Math.round(now / 1000) + Math.round(n.dueDays * 86400), autonomy: { level: n.autonomy },
      resources: links.length ? `Links:\n${links.join("\n")}` : "", attachments: n.uploads } };
}

/* ---------- agents ---------- */
// POST /api/company/agents/{id}/chat: the reply is written in the background; poll the workspace for it.
export function planChat(agent: AgentIdentity | undefined, text: string, attachments: string[], conversation: number | null, mission?: { id: string; title: string; summary?: string }): Plan {
  if (!agent || agent.hubId == null) return { refuse: "This conversation isn't with a live AXoR agent, so it can't be sent." };
  if (agent.hubStatus && agent.hubStatus !== "available") return { refuse: `${agent.name} is ${agent.hubStatus}: resume it to talk to it.` };
  if (attachments.length) return { refuse: "Attachments can't be sent to a live agent from here yet: paste the text, or use the agent's workspace." };
  const t = text.trim(); if (!t) return { refuse: "Type a message first." };
  if (t.length > 7600) return { refuse: "Messages up to 7,600 characters here (the mission's name is added at the top)." };
  // only the generated context is ever shortened, never the user's text (GPT review #5)
  const full = mission ? `[Mission ${mission.id}: ${mission.title}${mission.summary && mission.summary !== mission.title ? ` (${mission.summary.slice(0, 200)})` : ""}]\n` : "";
  const ctx = full.length + t.length <= 8000 ? full : full.slice(0, Math.max(0, 8000 - t.length - 2)) + "]\n";
  const body = ctx + t;
  return { method: "POST", url: `/api/company/agents/${agent.hubId}/chat`, body: conversation ? { text: body, conversation_id: conversation } : { text: body }, label: `Sent to ${agent.name}` };
}

/* ---------- transport ---------- */
// FastAPI puts the reason in `detail` (a string, or a list of validation errors).
export function errorText(status: number, body: unknown): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string" && d) return d;
  if (Array.isArray(d) && d.length) return d.map((x) => (x as { msg?: string }).msg ?? "").filter(Boolean).join("; ") || `AXoR refused it (${status}).`;
  if (status === 401) return "You're signed out: sign in again.";
  if (status === 403) return "Only an administrator can do that.";
  if (status === 429) return "AXoR is at its limit right now: wait for a running mission or agent to finish.";
  return `AXoR refused it (${status}).`;
}
export async function send<T = unknown>(r: Req): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  try {
    const res = await fetch(r.url, { method: r.method, credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Requested-With": "scout" },
      body: r.body === undefined ? undefined : JSON.stringify(r.body) });
    const data = await res.json().catch(() => null);
    return res.ok ? { ok: true, data: data as T } : { ok: false, error: errorText(res.status, data) };
  } catch { return { ok: false, error: "AXoR didn't answer: check the connection and try again." }; }
}
// Stages one file for the next mission (POST /api/mos/uploads); returns its id.
export async function upload(file: File): Promise<{ ok: true; id: number } | { ok: false; error: string }> {
  const data = await new Promise<string>((res, rej) => { const fr = new FileReader(); fr.onerror = () => rej(fr.error); fr.onload = () => res(String(fr.result).split(",", 2)[1] ?? ""); fr.readAsDataURL(file); })
    .catch(() => null);
  if (data == null) return { ok: false, error: `${file.name} couldn't be read.` };
  const r = await send<{ id?: number }>({ method: "POST", url: "/api/mos/uploads", body: { filename: file.name, data }, label: file.name });
  if (!r.ok) return { ok: false, error: `${file.name}: ${r.error}` };
  return typeof r.data?.id === "number" ? { ok: true, id: r.data.id } : { ok: false, error: `${file.name}: AXoR didn't return an upload id.` };
}
