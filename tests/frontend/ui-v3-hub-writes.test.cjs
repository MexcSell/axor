// UI v3 live writes (frontend/react/src/v3/data/hub.ts): each UI action maps to the AXoR endpoint the classic pages use,
// with the body the backend's pydantic model accepts, or is refused with the reason. Owner decision 4 (2026-11-16).
// Run: node --test tests/frontend/*.cjs   (needs frontend/react/node_modules, i.e. `npm ci` there)
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const react = path.join(__dirname, "..", "..", "frontend", "react");
let hub;
try {
  const esbuild = require(path.join(react, "node_modules", "esbuild"));
  const out = esbuild.buildSync({ entryPoints: [path.join(react, "src", "v3", "data", "hub.ts")], bundle: true, format: "cjs", platform: "node", write: false });
  const mod = { exports: {} };
  new Function("module", "exports", "require", out.outputFiles[0].text)(mod, mod.exports, require);
  hub = mod.exports;
} catch (e) { hub = null; }
const skip = hub ? false : "esbuild not installed (run npm ci in frontend/react)";

const task = (o) => ({ id: "C-41", missionId: "mx:3", title: "T", phase: "task", status: "queued", progress: 0, instanceId: "a@mx:3", deps: [], start: "", end: "",
  acceptance: [], evidence: [], retries: 0, priority: "Medium", history: [], hubRoute: "agent", hubRef: null, ...o });
const appr = (id, o = {}) => ({ id, missionId: "mx:3", ref: "", title: "Do it", area: "", priority: "Medium", question: "", context: "", impact: "", options: [],
  evidence: [], requestedBy: "GM", at: "", dueAt: "", risk: "low", status: "pending", ...o });

test("approvals: proposals go to mission-tasks decide with ok, company approvals to company decide", { skip }, () => {
  assert.deepEqual(pick(hub.planDecide(appr("CT-12"), "approve", "", [])), { method: "POST", url: "/api/control/mission-tasks/12/decide", body: { ok: true } });
  assert.deepEqual(pick(hub.planDecide(appr("CT-12"), "skip", "", [])).body, { ok: false });
  assert.deepEqual(pick(hub.planDecide(appr("CT-12"), "reject", "", [])).body, { ok: false });
  assert.match(hub.planDecide(appr("CT-12"), "changes", "redo it", []).refuse, /approved or declined/); // never {ok:true} (review #4, #1)
  assert.deepEqual(pick(hub.planDecide(appr("CO-5"), "approve", "fine", [])), { method: "POST", url: "/api/company/approvals/5/decide", body: { decision: "approve", reason: "fine" } });
  assert.deepEqual(pick(hub.planDecide(appr("CO-5"), "changes", "split it", [])).body, { decision: "changes", reason: "split it" });
  assert.match(hub.planDecide(appr("CO-5"), "reject", "  ", []).refuse, /Say why/); // the backend 400s without a reason
  assert.match(hub.planDecide(appr("CO-5"), "approve", "", ["a.png"]).refuse, /pictures/);
  assert.ok(hub.planDecide(appr("A-M-001"), "approve", "", []).refuse); // sample-only approval ids are never sent
});

test("tasks: only the moves AXoR has (done | cancelled | todo, run, approve)", { skip }, () => {
  assert.deepEqual(pick(hub.planTaskAction(task({ status: "failed" }), "retry")), { method: "PATCH", url: "/api/control/tasks/41", body: { status: "todo", feedback: "Retried from Mission Control (UI v3)." } });
  assert.deepEqual(pick(hub.planTaskAction(task({ status: "running" }), "cancel")).body, { status: "cancelled" });
  assert.match(hub.planTaskAction(task({ status: "running" }), "retry").refuse, /under way/);
  assert.match(hub.planTaskAction(task(), "pause").refuse, /can't be paused/);
  assert.ok(hub.planTaskAction(task({ id: "M-001-T1" }), "cancel").refuse);
  assert.match(hub.planMoveTask(task({ status: "review" }), "done").refuse, /without a result/);
  assert.deepEqual(pick(hub.planMoveTask(task({ status: "review", evidence: ["r"] }), "done")).body, { status: "done" });
  assert.deepEqual(pick(hub.planMoveTask(task({ status: "awaiting_approval" }), "running")), { method: "POST", url: "/api/control/mission-tasks/41/decide", body: { ok: true } });
  assert.deepEqual(pick(hub.planMoveTask(task(), "running")), { method: "POST", url: "/api/control/mission-tasks/41/run", body: undefined });
  assert.deepEqual(pick(hub.planMoveTask(task({ status: "failed" }), "queued")).body, { status: "todo" });
  assert.match(hub.planMoveTask(task({ status: "running" }), "queued").refuse, /running/);
  assert.match(hub.planMoveTask(task(), "review").refuse, /sets "review" itself/);
});

test("tasks: actions follow where AXoR runs the task (review #4, #3)", { skip }, () => {
  const board = task({ hubRoute: "board", hubRef: "mw_task:9", status: "failed" });
  assert.deepEqual(pick(hub.planTaskAction(board, "retry")), { method: "POST", url: "/api/control/mission-tasks/41/run", body: undefined });
  assert.match(hub.planTaskAction(task({ hubRoute: "board", hubRef: "mw_task:9", status: "queued" }), "cancel").refuse, /team's board/);
  assert.deepEqual(pick(hub.planTaskAction(task({ hubRoute: "board", hubRef: null }), "cancel")).body, { status: "cancelled" }); // not sent anywhere yet
  assert.match(hub.planMoveTask(task({ hubRoute: "board", hubRef: "mw_task:9", status: "review", evidence: ["r"] }), "done").refuse, /board/);
  const mx = task({ hubRoute: "mission", hubRef: "mx:3" });
  for (const a of ["retry", "cancel"]) assert.match(hub.planTaskAction(mx, a).refuse, /mission's own work/);
  assert.match(hub.planMoveTask(mx, "running").refuse, /mission's own work/);
  assert.match(hub.planTaskAction(task({ hubRoute: undefined, hubRef: "x:1" }), "cancel").refuse, /didn't say where/);
});

test("missions: mx: missions pause/resume/cancel in /api/mos; competition missions and archive are refused", { skip }, () => {
  const m = { id: "mx:9", title: "Portal" };
  assert.deepEqual(pick(hub.planMissionAction(m, "pause")), { method: "POST", url: "/api/mos/missions/9/pause", body: undefined });
  assert.equal(pick(hub.planMissionAction(m, "cancel")).url, "/api/mos/missions/9/cancel");
  assert.match(hub.planMissionAction({ id: "comp:7", title: "SN64" }, "pause").refuse, /competition/);
  assert.match(hub.planMissionAction(m, "archive").refuse, /archived/); // never mapped to DELETE
});

test("create: the MissionIn body (goal, budget, deadline in epoch s, autonomy level, links, staged uploads)", { skip }, () => {
  const now = Date.UTC(2026, 10, 16);
  const p = hub.planCreateMission({ text: "Build a customer portal", title: "Portal", githubUrls: ["https://github.com/o/r"], webUrls: [], budget: 25, dueDays: 2, autonomy: "L3", createRepo: false, uploads: [4] }, now);
  assert.deepEqual(pick(p), { method: "POST", url: "/api/mos/missions", body: { goal: "Portal\n\nBuild a customer portal", budget: 25, deadline: now / 1000 + 172800,
    autonomy: { level: "L3" }, resources: "Links:\nhttps://github.com/o/r", attachments: [4] } });
  assert.match(hub.planCreateMission({ text: "short", githubUrls: [], budget: 5, dueDays: 1, autonomy: "L3", createRepo: false, uploads: [] }).refuse, /12 characters/);
  assert.match(hub.planCreateMission({ text: "A long enough goal", githubUrls: [], budget: 5, dueDays: 1, autonomy: "L3", createRepo: true, uploads: [] }).refuse, /repository/);
  assert.match(hub.planCreateMission({ text: "A long enough goal", githubUrls: [], budget: 20000, dueDays: 1, autonomy: "L3", createRepo: false, uploads: [] }).refuse, /\$0\.05/);
});

test("chat: company agents by numeric id; non-live agents, paused agents and attachments refused", { skip }, () => {
  const ag = { id: "ceo", name: "Ada", hubId: 3, hubStatus: "available" };
  assert.deepEqual(pick(hub.planChat(ag, " hi ", [], null)), { method: "POST", url: "/api/company/agents/3/chat", body: { text: "hi" } });
  assert.deepEqual(pick(hub.planChat(ag, "hi", [], 17)).body, { text: "hi", conversation_id: 17 });
  assert.equal(pick(hub.planChat(ag, "hi", [], null, { id: "mx:3", title: "Portal", summary: "Build it" })).body.text, "[Mission mx:3: Portal (Build it)]\nhi"); // review #4, #7
  assert.match(hub.planChat({ id: "GM", name: "GM" }, "hi", [], null).refuse, /live AXoR agent/);
  assert.match(hub.planChat({ ...ag, hubStatus: "paused" }, "hi", [], null).refuse, /paused/);
  assert.match(hub.planChat(ag, "hi", ["a.pdf"], null).refuse, /Attachments/);
  // GPT review #5: the user's text is never cut; only the generated mission context is shortened
  const long = "x".repeat(7590) + "DO NOT PUBLISH";
  assert.match(hub.planChat(ag, long, [], null).refuse, /7,600/);
  const ok7600 = "y".repeat(7586) + "DO NOT PUBLISH";
  const b = pick(hub.planChat(ag, ok7600, [], null, { id: "mx:3", title: "T".repeat(300), summary: "S".repeat(200) })).body.text;
  assert.ok(b.endsWith("DO NOT PUBLISH") && b.length <= 8000 && b.startsWith("[Mission mx:3"));
});

test("errors: FastAPI detail is shown as the server wrote it", { skip }, () => {
  assert.equal(hub.errorText(409, { detail: "It's running already." }), "It's running already.");
  assert.equal(hub.errorText(422, { detail: [{ msg: "field required" }, { msg: "too short" }] }), "field required; too short");
  assert.match(hub.errorText(403, null), /administrator/);
});

function pick(p) { assert.ok(!p.refuse, p.refuse); return { method: p.method, url: p.url, body: p.body }; }
