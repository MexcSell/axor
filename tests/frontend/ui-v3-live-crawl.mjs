// UI v3 live crawl: signed in (as the admin test user) against a THROWAWAY AXoR instance, visits every route and tab in live
// data mode and reports pages that fall into the 'needs data that isn't connected' boundary, page scroll and console errors.
// Setup: see tests/frontend/ui-v3-live.mjs. Run: LIVE=http://<ip>:8000 OUT=<dir> CHROME=<chromium> node tests/frontend/ui-v3-live-crawl.mjs
import { chromium } from 'playwright-core';
const BASE = process.env.LIVE;
const b = await chromium.launch({ executablePath: process.env.CHROME, args: ['--no-sandbox'] });
const ctx = await b.newContext({ viewport: { width: 1672, height: 941 }, reducedMotion: "reduce" });
const p = await ctx.newPage(); const errs = [];
p.on('console', (m) => { if (m.type() === 'error' && !/Cross-Origin-Opener-Policy/.test(m.text())) errs.push(m.text().slice(0, 220)); });
p.on('pageerror', (e) => errs.push('pageerror ' + e.message.slice(0, 200)));
await p.request.post(BASE + '/api/auth/login', { headers: { 'X-Requested-With': 'scout', Origin: BASE }, data: { login: process.env.USER_LOGIN || 'boss', password: 'Correct-Horse-Battery-77' } });
await p.goto(BASE + '/app#/overview'); await p.waitForTimeout(3000);
console.log('mode', await p.evaluate(() => document.querySelector('[aria-label="Data source"] [aria-pressed="true"]')?.getAttribute('aria-label')));
for (const r of ['overview','missions','control','agents','organization','versions','evolution','knowledge','finance','governance','appearance','settings','notifications','analytics']) {
  await p.goto(BASE + '/app#/' + r); await p.waitForTimeout(1500);
  const boundary = await p.getByText("This view needs data that isn't connected yet").count();
  const tabs = p.locator('#main [role=tab]'); const n = await tabs.count(); let tb = 0;
  for (let i = 0; i < Math.min(n, 14); i++) { await tabs.nth(i).click({ timeout: 1500 }).catch(() => {}); await p.waitForTimeout(250); if (await p.getByText("This view needs data that isn't connected yet").count()) { tb++; console.log('  boundary after tab', i, (await tabs.nth(i).innerText().catch(() => '?')).trim()); await p.goto(BASE + '/app#/' + r); await p.waitForTimeout(800); } }
  await p.goto(BASE + '/app#/' + r); await p.waitForTimeout(1200);
  await p.screenshot({ path: `${process.env.OUT}/${r}.png` });
  const sc = await p.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight); console.log(r, boundary ? 'BOUNDARY' : 'ok', `tabs ${n}`, tb ? `tab-boundaries ${tb}` : '', sc > 2 ? 'PAGE-SCROLL ' + sc : '');
}
console.log(errs.length ? 'ERRORS:\n' + [...new Set(errs)].join('\n') : 'console clean');
await b.close();
