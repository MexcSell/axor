// Live read models from AXoR's existing hubs (GPT/advisor review: U13): GET /api/control/missions and GET /api/company,
// the same calls the classic Mission Control and Company pages make. Writes go through data/hub.ts (owner decision 4).
import type { AgentIdentity, AgentInstance, Approval, Department, Event, Mission, Task } from "../domain/types";
import type { Role } from "../ui/Avatar";
import type { Status } from "../ui/kit";

type J = Record<string, unknown>;
const str = (v: unknown, d = "") => (typeof v === "string" ? v : v == null ? d : String(v));
const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const iso = (ts: unknown) => { const n = num(ts, 0); return n > 0 ? new Date(n * 1000).toISOString() : new Date().toISOString(); };

export function taskStatus(s: string): Status {
  return ({ todo: "queued", queued: "queued", proposed: "awaiting_approval", running: "running", review: "review", verifying: "verifying", done: "done",
    failed: "failed", cancelled: "cancelled", skipped: "cancelled", blocked: "blocked", paused: "paused", needs_input: "waiting_user" } as Record<string, Status>)[s] ?? "queued";
}
export function missionStatus(s: string): Status {
  return ({ active: "running", running: "running", queued: "queued", needs_input: "waiting_user", paused: "paused", done: "done", completed: "done",
    delivered: "done", closed: "done", failed: "failed", cancelled: "cancelled", blocked: "blocked", review: "review", verifying: "verifying" } as Record<string, Status>)[s] ?? "queued";
}
// The mission engine's stages (understand, plan, research, build, verify, deliver, learn) -> the UI's six stages.
export function missionStage(stage: string, progress: number): Mission["stage"] {
  const m: Record<string, Mission["stage"]> = { understand: "plan", plan: "plan", research: "research", build: "develop", develop: "develop", execute: "develop",
    test: "test", verify: "verify", review: "verify", deliver: "deploy", delivered: "deploy", learn: "deploy", done: "deploy" };
  if (m[stage]) return m[stage];
  return progress >= 99 ? "deploy" : progress >= 85 ? "verify" : progress >= 70 ? "test" : progress >= 40 ? "develop" : progress >= 20 ? "research" : "plan";
}
export function roleFor(a: { key?: unknown; title?: unknown; category?: unknown }): Role {
  const t = `${str(a.key)} ${str(a.title)} ${str(a.category)}`.toLowerCase();
  const rules: [RegExp, Role][] = [[/\b(ceo|coo|chief|general manager|leadership|director)\b/, "gm"], [/architect|cto/, "architect"], [/secur/, "security"],
    [/\b(qa|test|verif|quality)/, "qa"], [/research|analyst|intelligence/, "research"], [/financ|cfo|budget/, "finance"], [/deploy|release|devops/, "deploy"],
    [/knowledge|doc|librar/, "knowledge"], [/design|ux|ui\b/, "designer"], [/strateg|product|market/, "strategist"], [/mentor|coach|train/, "mentor"],
    [/ops|operation|infra|sre/, "ops"], [/engineer|develop|code|miner|protocol/, "developer"]];
  return rules.find(([re]) => re.test(t))?.[1] ?? "developer";
}

export function mapControl(d: J): { missions: Mission[]; tasks: Task[] } {
  const tasksRaw = (Array.isArray(d.tasks) ? d.tasks : []) as J[];
  const ms = ((Array.isArray(d.initiatives) ? d.initiatives : []) as J[]).flatMap((ini) => ((Array.isArray(ini.missions) ? ini.missions : []) as J[]).map((m) => ({ ini, m })));
  const tasks: Task[] = tasksRaw.filter((t) => t.mission).map((t) => {
    const st = taskStatus(str(t.status));
    const hist = (Array.isArray(t.history) ? t.history : []) as J[];
    return {
      id: `C-${str(t.id)}`, missionId: str(t.mission), title: str(t.title, "Task"), phase: str(t.kind, "task"), desc: str(t.detail || t.summary),
      status: st, progress: st === "done" ? 100 : st === "running" || st === "review" ? 50 : 0, instanceId: `${str(t.agent_key || "GM")}@${str(t.mission)}`,
      // no deadline in the API except a recurrence "due": never turn update/completion times into deadlines (review #3, #13)
      deps: t.parent_id ? [`C-${str(t.parent_id)}`] : [], start: iso(t.created), end: t.due ? iso(t.due) : iso(t.created), dueUnknown: !t.due, acceptance: [],
      evidence: t.has_result ? [`result of task ${str(t.id)}`] : [], retries: 0, priority: str(t.priority) === "high" ? "High" : str(t.priority) === "low" ? "Low" : "Medium",
      history: hist.slice(-20).map((h) => ({ at: iso(h.ts), text: `${str(h.by)}: ${str(h.what)}` })),
      hubRoute: str(t.route) || undefined, hubRef: t.ref == null ? null : str(t.ref),
    };
  });
  const missions: Mission[] = ms.map(({ ini, m }) => {
    const ref = str(m.ref); const mine = tasks.filter((t) => t.missionId === ref);
    const tk = (m.tasks ?? {}) as J;
    const fixedTotal = num(tk.fixed_total), fixedDone = num(tk.fixed_done);
    const st = missionStatus(str(m.status));
    const progress = typeof m.progress === "number" ? Math.round(m.progress <= 1 ? m.progress * 100 : m.progress)
      : st === "done" ? 100 : fixedTotal ? Math.round((fixedDone / fixedTotal) * 100) : mine.length ? Math.round(mine.filter((t) => t.status === "done").length / mine.length * 100) : 0;
    const deadline = str(m.deadline); const due = deadline && !Number.isNaN(Date.parse(deadline)) ? new Date(deadline).toISOString() : null;
    const proposed = num(tk.proposed) || mine.filter((t) => t.status === "awaiting_approval").length;
    return {
      id: ref, title: str(m.title, ref), summary: str(m.objective || m.parent_title || ini.name), status: st, stage: missionStage(str(m.stage), progress),
      progress, progressBasis: fixedTotal || mine.length ? "tasks" : "calculating", issuesOpen: mine.filter((t) => t.status === "failed" || t.status === "blocked").length,
      decisionsPending: proposed, version: "—", dueAt: due ?? new Date().toISOString(), dueKind: due ? "scheduled" : "not_scheduled", nextEditionAt: null, nextEditionKind: "not_scheduled",
      startedAt: mine.length ? mine.map((t) => t.start).sort()[0] : iso(m.updated), lastActivityAt: iso(m.updated), owner: "you", workstream: str(ini.key, "other"),
      icon: str(m.type) === "predefined" ? "chart" : "star", color: str(m.type) === "predefined" ? "#22d3ee" : "#f2b53a", risk: str(m.gap && (m.gap as J).state) === "behind" ? "high" : "low",
      // predefined (competition) missions have a daily TOKEN budget, custom missions a money budget (review #3, #7)
      budget: str(m.type) === "predefined" ? { limit: 0, spent: 0 } : { limit: num(m.budget), spent: num(m.spent) },
      tokenBudget: str(m.type) === "predefined" ? { perDay: num(m.budget), usedToday: num(m.used_today) } : undefined, repo: null, priority: "Medium",
    };
  });
  return { missions, tasks };
}
// Proposed Control tasks wait for the owner: show them as approvals on their own mission (review #3, #6).
export function controlApprovals(d: J): Approval[] {
  return ((Array.isArray(d.tasks) ? d.tasks : []) as J[]).filter((t) => str(t.status) === "proposed" && t.mission).map((t) => ({
    id: `CT-${str(t.id)}`, missionId: str(t.mission), ref: `task ${str(t.id)}`, title: `Proposed task: ${str(t.title)}`, area: "Mission task",
    priority: str(t.priority) === "high" ? "High" : "Medium", question: `Run the proposed task "${str(t.title)}"?`, context: str(t.detail || t.summary),
    impact: "Adds work to the mission's team board.", options: [{ id: "approve", label: "Approve the task", detail: "" }, { id: "skip", label: "Skip it", detail: "" }],
    evidence: [], requestedBy: str(t.agent_key || "GM"), at: iso(t.created), dueAt: iso(t.created), risk: "low", status: "pending",
  }));
}

export function mapCompany(d: J): { agents: AgentIdentity[]; departments: Department[]; approvals: Approval[]; events: Event[] } {
  const divs = ((Array.isArray(d.divisions) ? d.divisions : []) as J[]);
  const divKey = (id: unknown) => str(divs.find((x) => x.id === id)?.key, "executive");
  const agentsRaw = (Array.isArray(d.agents) ? d.agents : []) as J[];
  const lead = agentsRaw.find((a) => roleFor(a) === "gm");
  const agents: AgentIdentity[] = agentsRaw.map((a) => {
    const role = roleFor(a); const skills = (a.skills && typeof a.skills === "object" ? a.skills : {}) as Record<string, number>;
    return {
      id: str(a.key || a.id), name: str(a.name), role, title: str(a.title), dept: a.division_id == null ? "executive" : divKey(a.division_id),
      reportsTo: a === lead ? null : str(lead?.key || "") || null, baseline: `v${num(a.version, 1)}`, models: [str(a.model || "auto")], tools: [],
      skills: Object.entries(skills).map(([name, lv]) => ({ name, level: Math.min(100, num(lv) * 20) })), permissions: Object.keys((a.permissions ?? {}) as J),
      status: ["disabled", "archived"].includes(str(a.status)) ? "offline" : str(a.status) === "paused" ? "idle" : ["busy", "working"].includes(str(a.status)) || num(a.load) > 0 ? "busy" : "active",
      successRate: 0, tasksDone: 0, costPerTask: 0, latencyS: 0, qualified: Object.keys(skills).slice(0, 3), created: iso(a.created),
      hubId: typeof a.id === "number" ? a.id : undefined, hubStatus: str(a.status),
    };
  });
  const departments: Department[] = divs.map((v) => ({ id: str(v.key), name: str(v.name), role: roleFor({ key: v.key, title: v.name }), head: str(agents.find((a) => a.dept === str(v.key))?.id || ""),
    budget: 0, spent: 0, performance: 0, backlog: num(v.projects) }));
  const approvals: Approval[] = ((Array.isArray(d.approvals) ? d.approvals : []) as J[]).map((a) => ({
    id: `CO-${str(a.id)}`, missionId: a.project_id ? `project:${str(a.project_id)}` : "company", ref: `#${str(a.id)}`, title: str(a.title, str(a.action_type)), area: str(a.action_type, "Company"),
    priority: str(a.risk) === "high" ? "High" : str(a.risk) === "low" ? "Low" : "Medium", question: str(a.title), context: str(a.reason), impact: str(a.expected || a.rollback),
    options: [{ id: "approve", label: "Approve", detail: str(a.rollback) ? `Rollback: ${str(a.rollback)}` : "" }], evidence: Object.keys((a.evidence ?? {}) as J),
    requestedBy: str(a.requested_by, "GM"), at: iso(a.created), dueAt: iso(a.expires_at), risk: (["low", "medium", "high"].includes(str(a.risk)) ? str(a.risk) : "medium") as Approval["risk"],
    status: str(a.status) === "pending" ? "pending" : str(a.status) === "approved" ? "approved" : str(a.status) === "rejected" ? "rejected" : "answered",
    response: a.decided_at ? { option: str(a.status), text: str(a.decision_reason), images: [], at: iso(a.decided_at), by: str(a.decided_by) } : undefined,
  }));
  const events: Event[] = ((Array.isArray(d.audit) ? d.audit : []) as J[]).map((e) => ({
    id: `CA-${str(e.id)}`, missionId: null, at: iso(e.ts), actor: str(e.actor_type) === "user" ? "user" : str(e.actor, "system"), action: str(e.action).replace(/[._]/g, " "),
    target: `${str(e.target_type)} ${str(e.target_id)}`.trim(), result: /fail|error|denied/.test(str(e.action)) ? "failure" : "success", trace: `co-${str(e.id)}`, severity: "info", icon: "check",
  }));
  return { agents, departments, approvals, events };
}

// Control names company agents "company:<id>"; the UI uses the company agent's key (GPT review #4, #8).
export function remapCompanyKeys(tasks: Task[], agents: AgentIdentity[]): Task[] {
  const byHub = new Map(agents.filter((a) => a.hubId != null).map((a) => [`company:${a.hubId}`, a.id]));
  return tasks.map((t) => { const at = t.instanceId.indexOf("@"); const id = byHub.get(t.instanceId.slice(0, at)); return id ? { ...t, instanceId: id + t.instanceId.slice(at) } : t; });
}
// Who works on each live mission, for the hierarchy and chat: the company's lead (it answers for every mission) and any
// live agent a task of the mission is assigned to.
export function liveInstances(missions: Mission[], tasks: Task[], agents: AgentIdentity[]): AgentInstance[] {
  const lead = agents.find((a) => a.role === "gm" && a.hubId != null) ?? agents.find((a) => a.hubId != null);
  const byId = new Map(agents.map((a) => [a.id, a]));
  const out: AgentInstance[] = [];
  for (const m of missions) {
    const mine = tasks.filter((t) => t.missionId === m.id);
    const ids = new Set<string>(lead ? [lead.id] : []);
    for (const t of mine) { const k = t.instanceId.split("@")[0]; if (byId.has(k)) ids.add(k); }
    for (const id of ids) {
      const work = mine.filter((t) => t.instanceId.split("@")[0] === id);
      const running = work.some((t) => t.status === "running");
      out.push({ id: `${id}@${m.id}`, agentId: id, missionId: m.id, pinnedVersion: byId.get(id)?.baseline ?? "v1", branch: "", status: running ? "running" : m.status === "done" ? "done" : "queued",
        progress: work.length ? Math.round(work.filter((t) => t.status === "done").length / work.length * 100) : m.progress, tasks: work.length,
        supervisor: lead && id !== lead.id ? `${lead.id}@${m.id}` : null, startedAt: m.startedAt, errors: work.filter((t) => t.status === "failed").length, spend: 0,
        ...(lead && id === lead.id && !work.length ? { derived: "company-lead" as const } : {}) });
    }
  }
  return out;
}

// Fetches both hubs. "forbidden" when this account may not read them (both hubs are administrator-only in AXoR today);
// null on any other failure. Either way the UI stays on sample data.
export async function fetchLive(): Promise<null | "forbidden" | ReturnType<typeof mapControl> & ReturnType<typeof mapCompany> & { instances: AgentInstance[] }> {
  const get = async (u: string) => {
    const r = await fetch(u, { credentials: "same-origin" });
    if (r.status === 401 || r.status === 403) throw new Error("forbidden");
    if (!r.ok) throw new Error(`${u}: ${r.status}`); return (await r.json()) as J;
  };
  try {
    const [c, co] = await Promise.all([get("/api/control/missions"), get("/api/company")]);
    const company = mapCompany(co);
    const ctl = mapControl(c);
    ctl.tasks = remapCompanyKeys(ctl.tasks, company.agents);
    return { ...ctl, ...company, approvals: [...controlApprovals(c), ...company.approvals], instances: liveInstances(ctl.missions, ctl.tasks, company.agents) };
  } catch (e) { return (e as Error).message === "forbidden" ? "forbidden" : null; }
}
