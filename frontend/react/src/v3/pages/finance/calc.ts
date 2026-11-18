// Finance calculations over the store's sample series. All figures are SAMPLE data in US dollars.
import { FINANCE, SPEND_SERIES, SPEND_BREAKDOWN } from "../../data/sample";

export const usd = (n: number, d = 0) => "$" + n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
/** Operating Sustainability Ratio = Recurring Revenue / Recurring Operating Costs (reference 0-5). >= 1.0 means self-sustaining. */
export const sustainability = (revenue = FINANCE.revenue, cost = FINANCE.opCost) => revenue / cost;

export type Scenario = "optimistic" | "base" | "pessimistic";
export const SCENARIO: Record<Scenario, { label: string; slope: number; why: string }> = {
  optimistic: { label: "Optimistic", slope: 0.3, why: "Cost routing and caching remove most of the recent daily growth in spend." },
  base: { label: "Base", slope: 1, why: "The 30-day trend continues, flattening out over the next weeks." },
  pessimistic: { label: "Pessimistic", slope: 2.2, why: "Mission volume grows faster than the recent trend and cheaper routes are not adopted." },
};
export interface Pt { day: string; actual?: number; fc?: number; lo?: number; hi?: number; band?: number; budget?: number }
export const LAST30 = SPEND_SERIES.reduce((a, p) => a + p.spend, 0);
/** Damped-trend projection: level = mean of the last 7 days, slope = least-squares slope over all 30 days (damped by 0.9 per day so growth levels off),
 *  band = 1.64 x residual std x sqrt(1 + days/10). A simple statistical extrapolation, not a model of missions or prices. */
export function projection(days: number, sc: Scenario) {
  const n = SPEND_SERIES.length, ys = SPEND_SERIES.map((p) => p.spend), xs = ys.map((_, i) => i);
  const mx = (n - 1) / 2, my = ys.reduce((a, b) => a + b) / n;
  const slope = xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / xs.reduce((a, x) => a + (x - mx) ** 2, 0);
  const icpt = my - slope * mx;
  const sigma = Math.sqrt(ys.reduce((a, y, i) => a + (y - (icpt + slope * xs[i])) ** 2, 0) / (n - 2));
  const level = ys.slice(-7).reduce((a, b) => a + b) / 7, last = SPEND_SERIES[n - 1], phi = 0.9;
  const out: Pt[] = SPEND_SERIES.map((p, i) => ({ day: p.day, actual: p.spend, budget: p.budget, ...(i === n - 1 ? { fc: p.spend, lo: p.spend, hi: p.spend, band: 0 } : {}) }));
  let total = 0, lo = 0, hi = 0, damp = 0;
  for (let j = 1; j <= days; j++) {
    damp += Math.pow(phi, j);
    const v = Math.max(0, level + slope * SCENARIO[sc].slope * damp), w = 1.64 * sigma * Math.sqrt(1 + j / 10);
    const d = new Date(Date.UTC(2026, 10, 16) + j * 864e5);
    out.push({ day: String(d.getUTCMonth() + 1).padStart(2, "0") + "-" + String(d.getUTCDate()).padStart(2, "0"), fc: Math.round(v), lo: Math.round(Math.max(0, v - w)), hi: Math.round(v + w), band: Math.round(v + w) - Math.round(Math.max(0, v - w)), budget: last.budget });
    total += v; lo += Math.max(0, v - w); hi += v + w;
  }
  return { points: out, total: Math.round(total), lo: Math.round(lo), hi: Math.round(hi), slope: +slope.toFixed(2), sigma: +sigma.toFixed(1), level: Math.round(level) };
}

/** Category figures derived from SPEND_BREAKDOWN (percent of this month's spend). Budget shares and month-on-month changes are SAMPLE assumptions. */
const BUDGET_SHARE = [0.40, 0.23, 0.17, 0.10, 0.10];
const MOM = [5.6, -2.1, -4.8, -6.5, -3.2];
export const CATEGORIES = SPEND_BREAKDOWN.map((c, i) => {
  const spend = Math.round(FINANCE.month * c.value / 100), budget = Math.round(FINANCE.budget * BUDGET_SHARE[i]);
  return { ...c, spend, budget, usage: spend / budget * 100, mom: MOM[i] };
});
export const SAVINGS_YTD = 412;
