// UI v3 live read models (frontend/react/src/v3/data/live.ts): the hub responses are mapped to the UI types.
// Payload shapes follow what GET /api/control/missions and GET /api/company return (captured from a throwaway instance).
// Run: node --test tests/frontend/*.cjs   (needs frontend/react/node_modules, i.e. `npm ci` there)
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const react = path.join(__dirname, "..", "..", "frontend", "react");
let live;
try {
  const esbuild = require(path.join(react, "node_modules", "esbuild"));
  const out = esbuild.buildSync({ entryPoints: [path.join(react, "src", "v3", "data", "live.ts")], bundle: true, format: "cjs", platform: "node", write: false });
  const mod = { exports: {} };
  new Function("module", "exports", "require", out.outputFiles[0].text)(mod, mod.exports, require);
  live = mod.exports;
} catch (e) { live = null; }

const control = {
  at: 1794800446, mode: "hybrid", primary: "bittensor",
  initiatives: [
    { key: "bittensor", name: "Bittensor", missions: [{ ref: "comp:7", type: "predefined", title: "SN64 · Chutes", status: "active", objective: "Top 10", deadline: "2026-12-01", budget: 500,
      tasks: { fixed_total: 4, fixed_done: 1, proposed: 2 }, gap: { state: "behind" } }] },
    { key: "other", name: "Other initiatives", missions: [{ ref: "mx:3", type: "custom", title: "Customer portal", status: "needs_input", progress: 0.4, budget: 300, spent: 41, updated: 1794800000 }] },
  ],
  tasks: [
    { id: 11, mission: "comp:7", title: "Benchmark miner", status: "running", priority: "high", agent_key: "miner_engineer", created: 1794700000, updated: 1794800000, history: [{ ts: 1794700000, by: "AXoR", what: "added" }], kind: "fixed" },
    { id: 12, mission: "comp:7", title: "Ship v2", status: "proposed", parent_id: 11, created: 1794700100, updated: 1794700100 },
    { id: 13, mission: null, title: "Standalone", status: "todo" },
  ],
};
const company = {
  divisions: [{ id: 1, key: "bittensor", name: "Bittensor Division", projects: 2 }],
  agents: [
    { id: 1, key: "ceo", name: "Ada", title: "CEO Agent", category: "leadership", division_id: null, status: "available", version: 3, skills: { strategy: 5, finance: 3 }, permissions: { read: [] } },
    { id: 2, key: "qa_lead", name: "Quinn", title: "QA Lead", category: "quality", division_id: 1, status: "busy", version: 1, skills: {} },
  ],
  approvals: [{ id: 5, project_id: 2, action_type: "deploy", title: "Deploy v2", reason: "tests green", requested_by: "cto", risk: "high", status: "pending", created: 1794800000, expires_at: 1794900000 }],
  audit: [{ id: 9, ts: 1794800453, actor_type: "user", actor: "boss", action: "company.created", target_type: "company", target_id: 1 }],
};

test("live mapper compiles", { skip: !live && "frontend/react/node_modules missing" }, () => { assert.ok(live.mapControl && live.mapCompany); });

test("control missions and tasks", { skip: !live }, () => {
  const { missions, tasks } = live.mapControl(control);
  assert.deepEqual(missions.map((m) => m.id), ["comp:7", "mx:3"]);
  const comp = missions[0], mx = missions[1];
  assert.equal(comp.progress, 25);                 // fixed_done / fixed_total
  assert.equal(comp.decisionsPending, 2);          // proposed tasks need the owner
  assert.equal(comp.dueKind, "scheduled");
  assert.equal(comp.risk, "high");                 // behind its target
  assert.equal(mx.progress, 40);                   // 0..1 progress scaled
  assert.equal(mx.status, "waiting_user");
  assert.equal(mx.dueKind, "not_scheduled");       // no deadline: never invent one
  assert.equal(tasks.length, 2);                   // standalone tasks (no mission) aren't mission tasks
  assert.deepEqual(tasks.find((t) => t.id === "C-12").deps, ["C-11"]);
  assert.equal(tasks.find((t) => t.id === "C-12").status, "awaiting_approval");
  assert.equal(tasks.find((t) => t.id === "C-11").priority, "High");
});

test("company agents, departments, approvals, audit", { skip: !live }, () => {
  const d = live.mapCompany(company);
  const ceo = d.agents.find((a) => a.id === "ceo"), qa = d.agents.find((a) => a.id === "qa_lead");
  assert.equal(ceo.role, "gm"); assert.equal(ceo.reportsTo, null); assert.equal(ceo.baseline, "v3");
  assert.equal(qa.role, "qa"); assert.equal(qa.reportsTo, "ceo"); assert.equal(qa.dept, "bittensor"); assert.equal(qa.status, "busy");
  assert.equal(ceo.successRate, 0);                // no verified results: the UI shows "no data", not a fake rate
  assert.equal(d.departments[0].id, "bittensor");
  assert.equal(d.approvals[0].status, "pending"); assert.equal(d.approvals[0].priority, "High"); assert.equal(d.approvals[0].risk, "high");
  assert.equal(d.events[0].actor, "user"); assert.equal(d.events[0].action, "company created");
});

test("lifecycle, budgets, deadlines and proposed tasks (GPT review #3)", { skip: !live }, () => {
  const c = { initiatives: [{ key: "other", missions: [
    { ref: "mx:9", type: "custom", title: "Done one", status: "delivered", stage: "learn", budget: 100, spent: 80 },
    { ref: "mx:10", type: "custom", title: "Planning", status: "running", stage: "understand", progress: 0.1 },
  ] }, { key: "bittensor", missions: [{ ref: "comp:7", type: "predefined", title: "SN", status: "active", budget: 200000, used_today: 1500, tasks: {} }] }],
    tasks: [{ id: 21, mission: "mx:10", title: "Propose step", status: "proposed", created: 1794700000 }, { id: 22, mission: "mx:10", title: "Open", status: "todo", created: 1794700000, updated: 1794800000 }] };
  const { missions, tasks } = live.mapControl(c);
  const done = missions.find((m) => m.id === "mx:9"), plan = missions.find((m) => m.id === "mx:10"), comp = missions.find((m) => m.id === "comp:7");
  assert.equal(done.status, "done"); assert.equal(done.progress, 100); assert.equal(done.stage, "deploy");
  assert.equal(plan.stage, "plan"); assert.equal(plan.progress, 10);
  assert.deepEqual(comp.budget, { limit: 0, spent: 0 });             // tokens are not dollars
  assert.deepEqual(comp.tokenBudget, { perDay: 200000, usedToday: 1500 });
  assert.equal(tasks.find((t) => t.id === "C-22").dueUnknown, true);    // update time is not a deadline
  const ap = live.controlApprovals(c);
  assert.equal(ap.length, 1); assert.equal(ap[0].missionId, "mx:10"); assert.equal(ap[0].status, "pending");
  const ag = live.mapCompany({ agents: [{ key: "a", status: "paused" }, { key: "b", status: "archived" }, { key: "c", status: "available", load: 2 }] }).agents;
  assert.deepEqual(ag.map((a) => a.status), ["idle", "offline", "busy"]);
});

test("garbage in does not throw", { skip: !live }, () => {
  assert.deepEqual(live.mapControl({}), { missions: [], tasks: [] });
  const d = live.mapCompany({ agents: "nope", divisions: null });
  assert.deepEqual([d.agents.length, d.departments.length, d.approvals.length, d.events.length], [0, 0, 0, 0]);
});

test("Control's company:<id> agent keys become company agent keys; the lead is marked derived (GPT review #4, #8)", { skip: live ? false : "esbuild missing" }, () => {
  const agents = [{ id: "ceo", role: "gm", hubId: 1, baseline: "v1" }, { id: "cto", role: "architect", hubId: 3, baseline: "v1" }];
  const tasks = live.remapCompanyKeys([
    { id: "C-1", missionId: "mx:3", instanceId: "company:3@mx:3", status: "running" },
    { id: "C-2", missionId: "mx:3", instanceId: "teams:9@mx:3", status: "todo" },
  ], agents);
  assert.equal(tasks[0].instanceId, "cto@mx:3");
  assert.equal(tasks[1].instanceId, "teams:9@mx:3"); // not a company agent: unchanged
  const inst = live.liveInstances([{ id: "mx:3", status: "running", progress: 10, startedAt: "" }], tasks, agents);
  assert.deepEqual(inst.map((i) => [i.agentId, i.tasks, i.derived ?? null]), [["ceo", 0, "company-lead"], ["cto", 1, null]]);
});
