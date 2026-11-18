// SAMPLE data for the Finance page (no billing integration is connected).
export const MODEL_USAGE: Record<string, { share: number; calls: number; tokensM: number }> = {
  "claude-opus-5-5": { share: .31, calls: 5120, tokensM: 74 }, "claude-sonnet-5-5": { share: .27, calls: 18400, tokensM: 190 }, "claude-haiku-5-5": { share: .08, calls: 41200, tokensM: 310 },
  "gpt-6.1": { share: .30, calls: 6050, tokensM: 66 }, "text-embedding-4": { share: .04, calls: 92000, tokensM: 520 }, "open-mixture-200b": { share: 0, calls: 0, tokensM: 0 },
};
export const OPTIMISATIONS = [
  { id: "rightsize", label: "Auto right-size compute", saving: 120 }, { id: "routing", label: "Model cost routing", saving: 210 }, { id: "cache", label: "Cache and reuse results", saving: 85 },
  { id: "idle", label: "Idle resource shutdown", saving: 14 }, { id: "lifecycle", label: "Data lifecycle management", saving: 40 },
];
export const FORECAST_ASSUMPTIONS = [
  ["Method", "Damped trend: level = mean of the last 7 days; slope = least-squares slope over 30 days, damped by 0.9 per day so growth levels off. Not a machine-learning model."],
  ["Band", "90% band = 1.64 x residual standard deviation x sqrt(1 + days/10). The 30-day range adds up the daily bands, which assumes errors move together, so it is conservative. Real errors are usually larger around launches and price changes."],
  ["Prices", "Provider prices held at today's list prices. Announced batch-price cuts are not included."],
  ["Mission load", "No new missions beyond those already running. A new mission raises spend; completing one lowers it."],
  ["Revenue", "Recurring revenue grows 2% per month (sample assumption); one-off revenue is excluded."],
  ["Not modelled", "Provider outages, fallback to costlier models, and human review costs that are not quantified."],
];
export const THRESHOLDS = [
  { id: "t1", scope: "Company monthly budget", pct: 80, on: true }, { id: "t2", scope: "Any department", pct: 85, on: true }, { id: "t3", scope: "Any mission", pct: 90, on: true },
  { id: "t4", scope: "LLM / API category", pct: 95, on: true }, { id: "t5", scope: "Daily spend vs daily budget", pct: 110, on: false },
];
