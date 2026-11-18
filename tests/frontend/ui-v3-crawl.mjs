// UI v3 acceptance crawl (docs/ui-v3/ROADMAP.md U15; UI-AT-01/06/07/08).
// Visits every route, clicks every tab, and checks that each tab shows non-empty content that differs from the previous
// state, that there are no console errors, that icon-only buttons have accessible names, and that the page itself does
// not scroll at the reference viewports. Optionally screenshots every route in every theme preset.
//
// Needs a built /app served statically (no API needed: the UI falls back to sample data) and playwright-core:
//   npm i --no-save playwright-core@1.48.2          (or reuse an existing install)
//   (cd <dir containing static/app> && python3 -m http.server 5199 --bind 127.0.0.1) &
//   CHROME=~/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome node tests/frontend/ui-v3-crawl.mjs [--shots DIR] [--themes]
import { chromium } from "playwright-core";
import fs from "node:fs";

const BASE = process.env.BASE || "http://127.0.0.1:5199/static/app/";
const args = process.argv.slice(2);
const shotDir = args.includes("--shots") ? args[args.indexOf("--shots") + 1] : null;
const themes = args.includes("--themes");
const ROUTES = process.env.ROUTES ? process.env.ROUTES.split(",") : ["overview", "missions", "control/M-001", "agents", "organization", "versions", "evolution", "knowledge", "finance", "governance", "appearance", "settings", "notifications", "analytics"];
// Earlier React pages kept inside the v3 shell: only page-scroll and crash checks (they predate the ? help and tab rules
// and call admin APIs that answer 401/404 on a static preview).
const LEGACY = ["system", "activity", "analytics-classic"];
const PRESETS = [["dark-luxury", "luxury", "dark"], ["classic-light", "classic", "light"], ["midnight-dark", "classic", "dark"], ["flat-minimal", "flat", "light"], ["luminous-neon", "luminous", "dark"],
  ["pretty-pastel", "pretty", "light"], ["fancy-glass", "fancy", "dark"], ["sakura", "sakura", "light"], ["sakura-night", "sakura", "dark"], ["renaissance", "renaissance", "light"]];
const IGNORE = [/\/api\/ui\//, /Failed to load resource: the server responded with a status of 404/];

const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ["--no-sandbox"] });
const results = []; let failures = 0;
const fail = (route, msg) => { failures++; results.push(`FAIL ${route}: ${msg}`); };

async function page(viewport) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: "reduce" });
  const p = await ctx.newPage(); const errors = [];
  p.on("console", (m) => { if (m.type() === "error" && !IGNORE.some((r) => r.test(m.text()))) errors.push(m.text().slice(0, 200)); });
  p.on("pageerror", (e) => errors.push("pageerror: " + e.message.slice(0, 200)));
  return { p, ctx, errors };
}
const mainText = (p) => p.evaluate(() => (document.querySelector("#main")?.innerText || "").replace(/\d{1,2}:\d{2}/g, "").replace(/\s+/g, " ").trim());

for (const vp of [{ width: 1672, height: 941 }, { width: 1600, height: 900 }]) {
  const { p, ctx, errors } = await page(vp);
  for (const r of ROUTES) {
    await p.goto(BASE + "#/" + r); await p.waitForTimeout(1600); // let entrance animations settle before clicking
    const sc = await p.evaluate(() => ({ h: document.documentElement.scrollHeight - document.documentElement.clientHeight, w: document.documentElement.scrollWidth - document.documentElement.clientWidth }));
    if (sc.h > 2) fail(`${r} @${vp.width}x${vp.height}`, `page scrolls vertically by ${sc.h}px`);
    if (sc.w > 2) fail(`${r} @${vp.width}x${vp.height}`, `page scrolls horizontally by ${sc.w}px`);
    if (vp.width !== 1672) continue; // tab crawl once
    // icon-only buttons need an accessible name (UI-AT-07)
    const unnamed = await p.evaluate(() => [...document.querySelectorAll("button")].filter((b) => !b.innerText.trim() && !b.getAttribute("aria-label") && !b.getAttribute("title")).length);
    if (unnamed) fail(r, `${unnamed} icon-only button(s) without an accessible name`);
    const helps = await p.locator("button.ax-help").count();
    if (!helps) fail(r, "no ? help buttons");
    // every tab (UI-AT-01)
    const tabs = p.locator("#main [role=tab]");
    const n = await tabs.count(); let prev = await mainText(p); let empty = 0, same = 0;
    for (let i = 0; i < n; i++) {
      const t = tabs.nth(i); if (!(await t.isVisible().catch(() => false))) continue;
      const label = ((await t.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim();
      const wasSelected = (await t.getAttribute("aria-selected")) === "true";
      let clicked = await t.click({ timeout: 2000 }).then(() => true, () => false);
      if (!clicked) { await p.waitForTimeout(500); clicked = await t.click({ timeout: 3000 }).then(() => true, () => false); }
      if (!clicked) { fail(r, `tab "${label}" could not be clicked`); continue; }
      // tab bodies animate out before the new one mounts: poll until the text settles on a new value (max 2.5 s)
      let txt = await mainText(p);
      for (let k = 0; k < 25 && !wasSelected && txt === prev; k++) { await p.waitForTimeout(100); txt = await mainText(p); }
      if (!wasSelected && txt === prev) { // one retry: a click can land mid-transition and be dropped
        await t.click({ timeout: 2000 }).catch(() => {});
        for (let k = 0; k < 25 && txt === prev; k++) { await p.waitForTimeout(100); txt = await mainText(p); }
      }
      await p.waitForTimeout(150); txt = await mainText(p);
      if (txt.length < 200) { empty++; fail(r, `tab "${label}" looks empty (${txt.length} chars)`); }
      if (!wasSelected && txt === prev) { same++; fail(r, `tab "${label}" did not change the content (selected after click: ${await t.getAttribute("aria-selected")})`); }
      prev = txt;
    }
    results.push(`ok   ${r}: ${n} tabs, ${helps} help buttons${empty || same ? `, ${empty} empty, ${same} unchanged` : ""}`);
  }
  if (vp.width === 1672) for (const r of LEGACY) {
    await p.goto(BASE + "#/" + r); await p.waitForTimeout(1200);
    const crashed = await p.evaluate(() => !document.querySelector("#main")?.children.length);
    const sc = await p.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight);
    if (crashed) fail(r, "legacy page did not render");
    results.push(`ok   ${r} (legacy page, scroll ${sc > 2 ? sc + "px" : "none"})`);
  }
  const unexpected = [...new Set(errors.filter((e) => !/status of 40[134]/.test(e)))];
  if (unexpected.length) fail(`console @${vp.width}`, unexpected.join(" | "));
  await ctx.close();
}

if (shotDir) {
  fs.mkdirSync(shotDir, { recursive: true });
  for (const [id, style, mode] of themes ? PRESETS : PRESETS.slice(0, 1)) {
    const { p, ctx } = await page({ width: 1672, height: 941 });
    await p.goto(BASE + "#/overview");
    await p.evaluate(([s, m]) => localStorage.setItem("axor.v3.appearance", JSON.stringify({ version: 1, style: s, mode: m })), [style, mode]);
    for (const r of ROUTES) { await p.goto(BASE + "#/" + r); await p.reload(); await p.waitForTimeout(1500); await p.screenshot({ path: `${shotDir}/${id}__${r.replace(/\W+/g, "_")}.png` }); }
    await ctx.close();
  }
  results.push(`screenshots in ${shotDir}`);
}
await browser.close();
console.log(results.join("\n"));
console.log(failures ? `\n${failures} failure(s)` : "\nall checks passed");
process.exit(failures ? 1 : 0);
