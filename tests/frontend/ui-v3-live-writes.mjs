// UI v3 live writes against a THROWAWAY AXoR instance (never production): owner decision 4. Signed in as the admin "boss"
// on an instance seeded like docs/ui-v3/EVIDENCE.md (custom mission mx:1 with six tasks incl. a proposal and a failed task,
// one pending company approval; plus seed_data2: an agent-run task "Draft the FAQ" (company:2) and a proposal "Ship docs site").
// Drives the real buttons and checks the hub's state through its own GET endpoints.
//   LIVE=http://<container-ip>:8000 CHROME=<chromium> node tests/frontend/ui-v3-live-writes.mjs
import { chromium } from 'playwright-core';
const BASE = process.env.LIVE;
const out = []; let fails = 0; const ok = (c, m) => { out.push(`${c ? "ok  " : "FAIL"} ${m}`); if (!c) fails++; };
const b = await chromium.launch({ executablePath: process.env.CHROME, args: ['--no-sandbox'] });
const ctx = await b.newContext({ viewport: { width: 1672, height: 941 }, reducedMotion: "reduce" });
const p = await ctx.newPage();
const errs = [], writes = [], toasts = [];
p.on('pageerror', (e) => errs.push(`pageerror at ${p.url()}: ${e.message}`));
p.on('console', (m) => { if (m.type() === 'error' && !/Cross-Origin-Opener-Policy|status of 4\d\d|status of 503/.test(m.text())) errs.push(m.text().slice(0, 200)); });
p.on('response', async (r) => {
  const m = r.request().method(); const u = new URL(r.url()).pathname;
  if (m !== 'GET' && /^\/api\/(control|company|mos)\//.test(u)) writes.push({ m, u, s: r.status(), body: r.request().postData() });
});
const lr = await p.request.post(BASE + '/api/auth/login', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { login: 'boss', password: 'Correct-Horse-Battery-77' } });
ok(lr.ok(), `login ${lr.status()}`);
const hub = async () => (await p.request.get(BASE + '/api/control/missions')).json();
const task = async (id) => (await hub()).tasks.find((t) => t.id === id);
const grabToasts = async () => { for (const t of await p.locator('[role="status"], .ax-toast').allInnerTexts().catch(() => [])) if (t && !toasts.includes(t)) toasts.push(t); };
const settle = async (ms = 2500) => { for (let i = 0; i < ms / 250; i++) { await p.waitForTimeout(250); await grabToasts(); } };
const last = (re) => writes.filter((w) => re.test(w.u)).at(-1);

// 1. Approve the proposal "Ship portal v1" (task 4) from Mission Control → Approvals
await p.goto(BASE + '/app#/control/mx%3A1?tab=approvals'); await settle(3500);
ok(await p.getByText('Live AXoR', { exact: false }).count() > 0, 'live banner shown (admin lands on live data)');
await p.getByRole('button', { name: 'Confirm', exact: true }).click(); await settle();
let w = last(/mission-tasks\/4\/decide$/);
ok(w && JSON.parse(w.body).ok === true, `proposal decision sent: POST ${w?.u} ${w?.s} ${w?.body}`);
ok(w && (w.s === 200 || toasts.some((t) => /Not done:|couldn't go further/.test(t))), `outcome shown: ${w?.s === 200 ? 'approved' : toasts.filter((t) => /Not done|couldn't go further/.test(t)).at(-1)}`);
ok((await task(4)).status !== 'proposed', `task 4 is no longer proposed on the server: ${(await task(4)).status}`);

// 2. Retry the failed task "Fix upload timeout" (task 5) from the mission header
await p.goto(BASE + '/app#/control/mx%3A1?tab=overview'); await settle(2500);
await p.getByRole('button', { name: /Retry 1 failed task/ }).click(); await settle();
w = last(/\/api\/control\/(tasks\/5|mission-tasks\/5\/run)$/);
// task 5 is a board task not sent anywhere yet: retry sends it to the team's board (POST mission-tasks/5/run)
ok(w && /mission-tasks\/5\/run$/.test(w.u), `failed board task retried through run: ${w?.m} ${w?.u} ${w?.s}`);
ok(w && (w.s === 200 ? (await task(5)).status !== 'failed' : toasts.some((t) => /Not done:/.test(t))), `outcome shown / server state: ${w?.s === 200 ? (await task(5)).status : toasts.filter((t) => /Not done/.test(t)).at(-1)}`);

// 3. Resume / pause the mission (mx:1): whatever AXoR answers is what the UI shows
const mos = async () => (await (await p.request.get(BASE + '/api/mos/missions/1')).json()).mission?.status;
const before = await mos();
await p.getByRole('button', { name: /^(Resume|Pause) mission$/ }).first().click(); await settle();
w = last(/\/api\/mos\/missions\/1\/(pause|resume)$/);
const after = await mos();
ok(w && (w.s === 200 ? toasts.some((t) => /: (paused|resumed)$/.test(t)) : toasts.some((t) => /Not done:/.test(t))), `mission ${before} → ${w?.u.split('/').pop()} ${w?.s} → now ${after} (AXoR's mission clock may pause it again without a model)`);

// 4. Message the mission's lead agent (company agent 1): sent to the company chat; AXoR's answer (or refusal) is shown
await p.goto(BASE + '/app#/control/mx%3A1?tab=agents'); await settle(2500);
const box = p.getByRole('textbox', { name: /Message to .* in mission mx:1/ }).first();
ok(await box.count() > 0, 'composer for a live agent on the live mission');
if (await box.count()) { await box.fill('Status update, please.'); await box.press('Enter'); await settle(3500); }
w = last(/\/api\/company\/agents\/\d+\/chat$/);
ok(w && (w.s === 200 || toasts.some((t) => /Not sent:/.test(t))), `chat: POST ${w?.u} ${w?.s}; ${w?.s === 200 ? 'accepted' : 'refusal shown: ' + toasts.filter((t) => /Not sent/.test(t)).join(' | ')}`);

// 4b. Cancel the agent-run task (route agent): PATCH 200 and cancelled on the server
const faq = (await hub()).tasks.find((t) => t.title === 'Draft the FAQ');
await p.goto(BASE + `/app#/control/mx%3A1?tab=flow&task=C-${faq.id}`); await settle(2500);
const accept = (d) => d.accept(); p.on('dialog', accept);
await p.getByRole('button', { name: 'Cancel task', exact: true }).first().click(); await settle();
p.off('dialog', accept);
w = last(new RegExp(`/api/control/tasks/${faq.id}$`));
ok(w && w.m === 'PATCH' && w.s === 200 && JSON.parse(w.body).status === 'cancelled', `agent task cancelled: ${w?.m} ${w?.u} ${w?.s} ${w?.body}`);
ok((await task(faq.id)).status === 'cancelled', `server shows it cancelled: ${(await task(faq.id)).status}`);

// 4c. Skip the proposal "Ship docs site": {ok:false} 200 and cancelled on the server
const docs = (await hub()).tasks.find((t) => t.title === 'Ship docs site');
await p.goto(BASE + '/app#/control/mx%3A1?tab=approvals'); await settle(2500);
await p.getByText('Proposed task: Ship docs site').first().click(); await settle(800);
await p.getByLabel('Skip it').check(); await p.getByRole('button', { name: 'Confirm', exact: true }).click(); await settle();
w = last(new RegExp(`/mission-tasks/${docs.id}/decide$`));
ok(w && w.s === 200 && JSON.parse(w.body).ok === false, `proposal skipped: POST ${w?.u} ${w?.s} ${w?.body}`);
ok((await task(docs.id)).status === 'cancelled', `server shows it declined: ${(await task(docs.id)).status}`);

// 4d. Company approval from the Notifications inbox (the real button): reject with the inbox's reason
await p.goto(BASE + '/app#/notifications?tab=pending'); await settle(2500);
await p.getByRole('button', { name: 'Reject: Publish the portal preview' }).first().click(); await settle(600);
await p.getByRole('button', { name: 'Reject', exact: true }).last().click(); await settle();
w = last(/\/api\/company\/approvals\/1\/decide$/);
ok(w && w.s === 200 && JSON.parse(w.body).decision === 'reject', `company approval rejected from the inbox: ${w?.s} ${w?.body}`);
const coAppr = (await (await p.request.get(BASE + '/api/company')).json()).approvals.find((a) => a.id === 1);
ok(coAppr?.status === 'rejected', `server shows the approval rejected: ${coAppr?.status}`);

// 5. Start a mission from Add Mission (AXoR may refuse here: no model provider on a throwaway instance)
await p.goto(BASE + '/app#/missions'); await settle(2000);
await p.getByRole('button', { name: 'Add mission' }).first().click(); await settle(800);
await p.locator('#am-desc').fill('Build a small changelog page that lists every release with its notes.');
await p.getByLabel('GitHub or web address').fill('https://github.com/example/changelog');
await p.getByLabel('GitHub or web address').press('Enter');
await p.locator('input[type=file][accept*=".pdf"]').first().setInputFiles({ name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('Changelog brief: list releases with notes.') });
await settle(400);
await p.getByRole('button', { name: 'Start Mission' }).click(); await settle(600);
await p.getByRole('button', { name: 'Start Mission' }).click(); await settle(3000);
w = last(/\/api\/mos\/missions$/);
const alert = await p.locator('[role="alert"]').allInnerTexts().catch(() => []);
ok(w && w.m === 'POST' && JSON.parse(w.body).goal.includes('changelog') && JSON.parse(w.body).autonomy.level === 'L3', `create: POST /api/mos/missions ${w?.s} ${w?.body?.slice(0, 160)}`);
const up = last(/\/api\/mos\/uploads$/);
ok(up && up.s === 200, `attachment staged: POST /api/mos/uploads ${up?.s}`);
ok(w && Array.isArray(JSON.parse(w.body).attachments) && JSON.parse(w.body).attachments.length === 1 && Number.isInteger(JSON.parse(w.body).attachments[0]), `create carries the staged upload id: ${JSON.stringify(JSON.parse(w?.body ?? '{}').attachments)}`);
ok(w && (w.s === 200 || alert.some((t) => t.length > 5)), `create outcome shown: ${w?.s === 200 ? 'mission created' : 'modal says: ' + alert.join(' | ')}`);
await p.keyboard.press('Escape');

// 6. Sample mode sends nothing to the hubs
const n0 = writes.length;
await p.goto(BASE + '/app#/control/M-001?tab=overview'); await settle(1500);
await p.getByRole('radio', { name: /Design sample data/ }).or(p.getByRole('button', { name: /Design sample data/ })).first().click().catch(() => {});
await settle(1000);
await p.getByRole('button', { name: /^(Resume|Pause) mission$/ }).first().click().catch(() => {}); await settle(1500);
ok(writes.length === n0, `sample mode: no hub writes (${writes.length - n0})`);

ok(!errs.length, `no page errors: ${errs.join(' | ')}`);
console.log(out.join('\n'));
console.log('writes:', writes.map((x) => `${x.m} ${x.u} ${x.s}`).join(', '));
console.log('toasts:', toasts.slice(-12).join(' || '));
console.log(fails ? `${fails} FAILED` : 'all live write checks passed');
await b.close(); process.exit(fails ? 1 : 0);
