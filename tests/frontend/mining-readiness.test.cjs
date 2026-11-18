const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Exercise the shipped renderer with a frozen clock and the browser helpers.
const source = fs.readFileSync(path.join(__dirname, '../../frontend/mining.js'), 'utf8');
const ctx = vm.createContext({
  Date: class extends Date { static now() { return 1000000; } },
  $: () => null,
  icon: () => '',
  esc: s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  clock: () => '12:00', when: () => '12:00', ago: () => 'now',
  fmtNum: n => String(n),
  MiningWork: { count: () => 0 },
});
vm.runInContext(source.replace('return { open, stop, init, compsCard, camp, nav };', `return {
  renderTest(state) { d = state; cid = 1; return { ticker: ticker(), readiness: readiness(), actions: actions(), alerts: alertsBlock() }; }
};`) + '\nthis.health = MiningReadiness; this.renderTest = Mining.renderTest;', ctx);

const state = overrides => ({
  campaign: { keys: ['public-key'], status: 'live', settings: { target: 1, autonomy: 'ask' } },
  field: { block: 123, top1: 4, miners: 242, earners: 40, reg_cost: 0.001 },
  schedule: { last_sample: 990, interval: 60, next_sample: 1050, next_cycle: 1200 },
  mine: [], missing: ['public-key'], actions: [], alerts: [], running: null,
  brief: { standing: 'green', ts: 500, stats: { rank: 1, uid: 15, em: 4, gap: 0 } },
  ...overrides,
});

test('manually completed registration never overrides missing on-chain UID', () => {
  const s = state({ actions: [{ status: 'done', title: 'Register hotkey' }] });
  assert.equal(ctx.health(s).title, 'No registered miner found');
  assert.equal(ctx.health(s).tone, 'bad');
  const html = ctx.renderTest(s);
  assert.match(html.readiness, /No registered miner found/);
  assert.doesNotMatch(html.ticker, /#1|UID 15/);
  assert.doesNotMatch(html.alerts, /all clear|Registration was found/);
});

test('missing and stale snapshots cannot verify registration', () => {
  assert.equal(ctx.health(state({ field: null })).title, 'Registration not checked');
  const s = state({ mine: [{ uid: 7, rank: 3 }], missing: [], schedule: { last_sample: 1, interval: 60 } });
  assert.equal(ctx.health(s).title, 'Chain data is out of date');
  assert.notEqual(ctx.health(s).tone, 'ok');
});

test('no tracked keys offers setup, rather than a registration failure', () => {
  const h = ctx.health(state({ campaign: { keys: [] } }));
  assert.equal(h.title, 'Add your miner keys');
  assert.equal(h.go, 'settings');
});

test('a fresh matching UID verifies only chain readiness and uses current rank', () => {
  const s = state({ mine: [{ uid: 7, rank: 3, of: 242, em: 0.5, gap_target: 3.5 }], missing: [] });
  assert.equal(ctx.health(s).title, 'Registration verified');
  const html = ctx.renderTest(s);
  assert.match(html.ticker, /#3/);
  assert.match(html.ticker, /UID 7/);
  assert.doesNotMatch(html.ticker, /#1|running on their own/);
  assert.match(html.readiness, /Benchmark and submission readiness are checked separately/);
});

test('partial matches and critical alerts remain actionable', () => {
  const mine = [{ uid: 7, rank: 3 }];
  assert.equal(ctx.health(state({ mine })).title, 'Some tracked keys have no miner');
  const h = ctx.health(state({ mine, missing: [], alerts: [{ level: 'critical' }] }));
  assert.equal(h.title, 'Critical alerts need attention');
  assert.equal(h.tone, 'bad');
});

test('scheduled monitoring is distinct from an executing cycle and pause', () => {
  assert.match(ctx.renderTest(state()).actions, /Monitoring scheduled/);
  assert.doesNotMatch(ctx.renderTest(state()).actions, />Working</);
  assert.match(ctx.renderTest(state({ running: { step: 'analysis' } })).actions, /Analysis cycle running/);
  assert.match(ctx.renderTest(state({ campaign: { keys: ['k'], status: 'paused', settings: { autonomy: 'ask' } } })).actions, /Paused/);
});

