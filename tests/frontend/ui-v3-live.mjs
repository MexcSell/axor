// UI v3 live check against a THROWAWAY AXoR instance (never production). Signed in as an admin ("boss") and a member
// ("ann"): bootstrap identity, theme round trip, self-renewal admin gate (UI + API), CSRF guard, news-source permissions
// and SSRF refusal, console/CSP errors on every route.
//
// Throwaway instance (internal docker network, read-only tree, tmpfs data, test users only):
//   docker network create --internal axor-ui-test
//   docker run -d --name axor-ui-test --network axor-ui-test --tmpfs /tmp/axdata:uid=1000,mode=1777 \
//     -v "$PWD/backend/app:/app/backend/app:ro" -v "$PWD/frontend:/app/frontend:ro" \
//     -e DATA_DIR=/tmp/axdata -e AUTH_METHOD=basic -e HIBP_CHECK=0 axor/web:<tag>
//   seed users boss (admin) / ann (member) with AuthDB inside the container (see docs/ui-v3/EVIDENCE.md)
//   LIVE=http://<container-ip>:8000 CHROME=<chromium> node tests/frontend/ui-v3-live.mjs
// Live check of UI v3 against a throwaway AXoR instance (signed in), see docs/ui-v3/EVIDENCE.md
// Live check of UI v3 against a throwaway AXoR instance (signed in), see docs/ui-v3/EVIDENCE.md
// Live check of UI v3 against a throwaway AXoR instance (signed in), see docs/ui-v3/EVIDENCE.md
import { chromium } from 'playwright-core';
const BASE = process.env.LIVE;            // e.g. http://172.27.0.2:8000
const out = []; let fails = 0; const ok = (c, m) => { out.push(`${c ? "ok  " : "FAIL"} ${m}`); if (!c) fails++; };
const b = await chromium.launch({ executablePath: process.env.CHROME, args: ['--no-sandbox'] });
async function session(user) {
  const ctx = await b.newContext({ viewport: { width: 1672, height: 941 }, reducedMotion: "reduce" });
  const p = await ctx.newPage(); const errs = [], writes = [];
  p.on('console', (m) => { if (m.type() === 'error' && !/Cross-Origin-Opener-Policy header has been ignored/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  p.on('response', (r) => { if (r.status() >= 400) errs.push(`HTTP ${r.status()} ${new URL(r.url()).pathname}`); });
  p.on('pageerror', (e) => errs.push('pageerror ' + e.message));
  p.on('response', (r) => { const m = r.request().method(); if (m !== 'GET' && r.url().includes('/api/ui/')) writes.push(`${m} ${new URL(r.url()).pathname} ${r.status()}`); });
  const lr = await p.request.post(BASE + '/api/auth/login', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { login: user, password: 'Correct-Horse-Battery-77' } });
  ok(lr.ok(), `${user}: login ${lr.status()}`);
  return { ctx, p, errs, writes };
}
// --- admin
{
  const { ctx, p, errs, writes } = await session('boss');
  await p.goto(BASE + '/app#/overview'); await p.waitForTimeout(2500);
  const boot = await p.request.get(BASE + '/api/ui/bootstrap'); const bj = await boot.json();
  ok(boot.ok() && bj.me?.role === 'admin', `boss: bootstrap me=${JSON.stringify(bj.me)}`);
  ok(await p.locator('.ax-sample').count() > 0, 'boss: sample badge still visible (most data is sample)');
  // theme round trip via the UI
  await p.goto(BASE + '/app#/appearance?tab=gallery'); await p.waitForTimeout(1500);
  const tile = p.getByRole('button', { name: /Pretty Pastel/ }).first();
  if (await tile.count()) { await tile.click(); await p.waitForTimeout(1500); }
  await p.reload(); await p.waitForTimeout(2500);
  ok(await p.evaluate(() => document.documentElement.dataset.axStyle) === 'pretty', `boss: theme persisted after reload (style=${await p.evaluate(() => document.documentElement.dataset.axStyle)})`);
  ok(writes.some((w) => w.startsWith('PUT /api/ui/preferences 200')), `boss: preferences PUT ${writes.filter((w) => w.includes('preferences')).join(', ') || 'none'}`);
  // self-renewal as admin (Settings → Admin)
  const before = (await (await p.request.get(BASE + '/api/ui/settings')).json()).self_renewal;
  await p.goto(BASE + '/app#/settings?tab=admin'); await p.waitForTimeout(1800);
  await p.getByRole('switch', { name: /Self-renewal/ }).first().click(); await p.waitForTimeout(600);
  const confirm = p.getByRole('button', { name: /^Confirm$/ }); if (await confirm.count()) { await confirm.first().click(); }
  await p.waitForTimeout(1500);
  const after = (await (await p.request.get(BASE + '/api/ui/settings')).json()).self_renewal;
  ok(after === !before, `boss: self-renewal ${before} -> ${after} persisted on the server`);
  // Sample mode must not write real configuration (GPT review #3, #1)
  const nWrites = writes.filter((w) => w.startsWith('PUT /api/ui/settings')).length;
  await p.goto(BASE + '/app#/overview'); await p.waitForTimeout(2500); // hub data (and the switch) load on pages that show it
  ok(await p.getByRole('button', { name: 'Design sample data' }).count() > 0, 'boss: Live/Sample switch available after opening Overview');
  await p.getByRole('button', { name: 'Design sample data' }).first().click(); await p.waitForTimeout(800);
  await p.goto(BASE + '/app#/settings?tab=admin'); await p.waitForTimeout(1500);
  await p.getByRole('switch', { name: /Self-renewal/ }).first().click(); await p.waitForTimeout(600);
  const c2 = p.getByRole('button', { name: /^Confirm$/ }); if (await c2.count()) await c2.first().click();
  await p.waitForTimeout(1200);
  ok(writes.filter((w) => w.startsWith('PUT /api/ui/settings')).length === nWrites, 'boss: in Sample mode a settings change sends nothing to the server');
  ok((await (await p.request.get(BASE + '/api/ui/settings')).json()).self_renewal === after, 'boss: server self-renewal unchanged by Sample-mode edits');
  await p.getByRole('button', { name: /^Live AXoR data/ }).first().click(); await p.waitForTimeout(800);
  // CSRF: a write without the header is refused
  const csrf = await p.request.put(BASE + '/api/ui/settings', { data: { selfRenewal: before } });
  ok(csrf.status() === 403, `CSRF guard refuses a write without X-Requested-With (${csrf.status()})`);
  // every route: no console errors (CSP etc.)
  for (const r of ['overview','missions','control/M-001','agents','organization','versions','evolution','knowledge','finance','governance','appearance','settings','notifications']) { await p.goto(BASE + '/app#/' + r); await p.waitForTimeout(1200); }
  ok(!errs.length, `boss: console errors on all routes: ${errs.length ? [...new Set(errs)].join(' | ') : 'none'}`);
  out.push('     writes: ' + [...new Set(writes)].join('; '));
  await ctx.close();
}
// --- member
{
  const { ctx, p, errs, writes } = await session('ann');
  await p.goto(BASE + '/app#/settings?tab=admin'); await p.waitForTimeout(2500);
  const sw = p.getByRole('switch', { name: /Self-renewal/ }).first();
  ok(await sw.isDisabled(), 'ann (member): self-renewal switch disabled');
  const api = await p.request.put(BASE + '/api/ui/settings', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { selfRenewal: true } });
  ok(api.status() === 403, `ann: API refuses self-renewal (${api.status()})`);
  const org = await p.request.post(BASE + '/api/ui/news-sources', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { url: 'https://example.org/feed', scope: 'organization' } });
  ok(org.status() === 403, `ann: organisation source refused (${org.status()})`);
  const mis = await p.request.post(BASE + '/api/ui/news-sources', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { url: 'https://example.org/feed-' + Date.now(), scope: 'mission', missionId: 'M-001', cadence: 'Daily' } });
  ok(mis.status() === 200, `ann: mission source accepted (${mis.status()})`);
  await p.goto(BASE + '/app#/knowledge?tab=sources'); await p.reload(); await p.waitForTimeout(2500);
  ok(await p.getByText('example.org').count() > 0, 'ann: live source list shows the new source');
  const ssrf = await p.request.post(BASE + '/api/ui/news-sources', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { url: 'http://169.254.169.254/latest', scope: 'mission', missionId: 'M-001' } });
  ok(ssrf.status() === 422, `ann: metadata address refused (${ssrf.status()})`);
  await p.goto(BASE + '/app#/overview'); await p.waitForTimeout(2500);
  ok(await p.getByRole('button', { name: 'Design sample data' }).count() === 0, 'ann (member): no Live switch (hub data is admin-only), sample shown');
  ok(!errs.filter((e) => !/40[13]/.test(e)).length, `ann: console errors: ${errs.length ? [...new Set(errs)].join(' | ') : 'none'}`);
  await ctx.close();
}
await b.close();
console.log(out.join('\n')); console.log(fails ? `\n${fails} failure(s)` : '\nall live checks passed'); process.exit(fails ? 1 : 0);
