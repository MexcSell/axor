// SAMPLE data for the Versions & GitHub page (not live telemetry): benchmarks, build stages, logs and provenance are illustrative.
import type { Release } from "../../domain/types";
import { sha } from "../../data/sample";

/** Display hashes (sample): stable, hex, any length. The shared sample hashes are placeholders. */
export function fakeSha(seed: string, len = 7): string {
  let out = ""; let h = 2166136261;
  while (out.length < len) { for (const ch of seed + out.length) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; } out += h.toString(16).padStart(8, "0"); }
  return out.slice(0, len);
}

export const REPO = "AXoR/ai-company-os";

/** Deterministic pseudo-benchmarks per version, so Compare is stable between renders. */
export function benchOf(version: string): { name: string; value: number; unit: string; higherBetter: boolean }[] {
  const n = [...version].reduce((a, c) => a * 31 + c.charCodeAt(0), 7) % 1000;
  const k = (version.match(/\d+/g) ?? ["1"]).map(Number); const rank = k[0] * 10 + (k[1] ?? 0) + (k[2] ?? 0) / 10;
  return [
    { name: "Task success rate", value: +(70 + rank * 1.6 + (n % 7) / 10).toFixed(1), unit: "%", higherBetter: true },
    { name: "Build time", value: +(260 - rank * 4.2 + (n % 9)).toFixed(0), unit: "s", higherBetter: false },
    { name: "Resource efficiency", value: +(90 + rank * 0.9 + (n % 5) / 10).toFixed(1), unit: "%", higherBetter: true },
    { name: "Knowledge coverage", value: +(80 + rank * 0.8 + (n % 4) / 10).toFixed(1), unit: "%", higherBetter: true },
    { name: "p95 API latency", value: +(310 - rank * 3 + (n % 11)).toFixed(0), unit: "ms", higherBetter: false },
  ];
}

export const BUILD_STAGES = [
  { id: "checkout", label: "Checkout", ms: 700, log: "git fetch origin && git checkout {commit}" },
  { id: "install", label: "Install", ms: 900, log: "npm ci (cached 412 packages)" },
  { id: "build", label: "Build", ms: 1300, log: "vite build: 118 modules transformed" },
  { id: "test", label: "Test", ms: 1100, log: "vitest: {tests} tests" },
  { id: "deploy", label: "Deploy preview", ms: 800, log: "preview service machine restarted (isolated sandbox)" },
  { id: "health", label: "Health", ms: 600, log: "GET /healthz -> 200 (sample)" },
] as const;

export function provenance(r: Release) {
  return {
    builder: "axor-ci (sample)", builtBy: r.author, commit: r.commit, branch: r.branch, workflow: ".github/workflows/release.yml",
    run: `run-${sha(r.version + "run", 5)}`, signed: false, slsa: "L2 (sample, not attested)",
  };
}

/** A release manifest generated in the browser (no server round trip). Honest: it lists sample artifacts. */
export function manifestOf(r: Release, only?: string) {
  return {
    schema: "axor.release-manifest/1", sample: true, repository: REPO, version: r.version, status: r.status, branch: r.branch, commit: r.commit, releasedAt: r.at,
    tests: r.tests, security: r.security, notes: r.notes, fixes: r.fixes, knownIssues: r.known, mergedFrom: r.mergedFrom, provenance: provenance(r),
    artifacts: r.artifacts.filter((a) => !only || a.name === only),
    generatedAt: new Date().toISOString(), generatedBy: "AXoR UI (client-side)",
  };
}
export function saveJson(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export const COMMITS = [
  ["a7f9d2e", "Integrate Knowledge Engine v1.3.1", "RCH-01", "10:12"], ["b3e8c4f", "Optimize build pipeline (-24%)", "DEV-01", "09:59"],
  ["c9d1e27", "Add QA auto-verification", "QA-01", "09:47"], ["e2f6a90", "Self-evolution auto-opt (v2.4.0)", "GM", "09:21"],
  ["f4b8c11", "Update deployment & rollback", "DEP-01", "08:58"], ["d1a7b30", "Theme engine tokens", "DEV-02", "08:31"],
] as const;
