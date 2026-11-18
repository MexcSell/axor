// UI v3: the owner's first visit on a BARE throwaway instance (no seed): admin one-time password -> forced change ->
// /app on live data with no missions. Errors on the classic sign-in page before login (401/403) are AXoR's own and not counted.
//   docker exec <container> python -m app.create_admin admin   (prints the one-time password)
//   LIVE=http://<ip>:8000 OTP=<one-time password> CHROME=<chromium> node tests/frontend/ui-v3-first-visit.mjs
import { chromium } from 'playwright-core';
const BASE = process.env.LIVE, PW = process.env.OTP, NEWPW = 'Brand-New-Owner-Pass-2026!';
const out = []; let fails = 0; const ok = (c, m) => { out.push(`${c ? "ok  " : "FAIL"} ${m}`); if (!c) fails++; };
const b = await chromium.launch({ executablePath: process.env.CHROME, args: ['--no-sandbox'] });
const p = await (await b.newContext({ viewport: { width: 1672, height: 941 }, reducedMotion: "reduce" })).newPage();
const errs = []; p.on('pageerror', (e) => { if (p.url().includes('/app')) errs.push(`${p.url()}: ${e.message}`); });
p.on('console', (m) => { if (m.type() === 'error' && p.url().includes('/app') && !/Cross-Origin-Opener-Policy/.test(m.text())) errs.push(`${p.url()}: ${m.text().slice(0, 160)}`); });
await p.goto(BASE + '/'); await p.waitForSelector('#f-login input[name=login]');
await p.fill('#f-login input[name=login]', 'admin'); await p.fill('#f-login input[name=password]', PW);
await p.click('#f-login button[type=submit]'); await p.waitForTimeout(2500);
const cur = p.locator('input[name=current]:visible').first();
ok(await cur.count() > 0, 'forced password change shown after the one-time login');
await cur.fill(PW); await p.locator('input[name=password][autocomplete=new-password]:visible').first().fill(NEWPW);
const conf = p.locator('input[name=confirm]:visible'); if (await conf.count()) await conf.first().fill(NEWPW);
await cur.press('Enter'); await p.waitForTimeout(2500);
const me = await (await p.request.get(BASE + '/api/auth/me')).json().catch(() => ({}));
ok(me && !me.must_change, `password changed (must_change=${me?.must_change})`);
for (const r of ['overview', 'missions', 'control', 'agents', 'notifications']) {
  await p.goto(BASE + `/app#/${r}`); await p.waitForTimeout(3000);
  const boundary = await p.getByText(/This view needs data|Something went wrong/i).count();
  ok(!boundary, `/app#/${r} renders (no error boundary)`);
}
await p.goto(BASE + '/app#/missions'); await p.waitForTimeout(2500);
ok(await p.getByText('Live AXoR', { exact: false }).count() > 0, 'admin lands on live data (decision 3)');
await p.screenshot({ path: process.env.SHOT || 'firstvisit.png' });
ok(!errs.length, `/app console clean: ${errs.join(' | ')}`);
console.log(out.join('\n')); console.log(fails ? `${fails} FAILED` : 'first visit ok'); await b.close();
