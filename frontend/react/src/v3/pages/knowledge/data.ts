// SAMPLE data for the Knowledge & News page (no live research backend is connected). Everything here is illustrative.
import { at } from "../../data/sample";

export const ORG_MEMORY = [
  { name: "Company Knowledge", sub: "Strategy, policies, architecture", n: 12540, pct: 100, c: "#22d3ee" },
  { name: "Mission Knowledge", sub: "Plans, results, learnings", n: 8392, pct: 91, c: "#a77bff" },
  { name: "Agent Knowledge", sub: "Agent configs, skills, behaviors", n: 4106, pct: 87, c: "#3b8cff" },
  { name: "Product & R&D", sub: "Designs, code, evaluations", n: 6935, pct: 82, c: "#2fd27a" },
  { name: "Operations & Process", sub: "Workflows, runbooks, metrics", n: 3421, pct: 77, c: "#f2b53a" },
  { name: "Lessons Learned", sub: "Retros, failures, optimizations", n: 1086, pct: 69, c: "#ff7a59" },
];

export interface ResearchJob { id: string; title: string; mission: string; agent: string; status: "running" | "done" | "review" | "queued"; progress: number; sources: number; quality: number; started: string }
export const RESEARCH_JOBS: ResearchJob[] = [
  { id: "R-41", title: "Agentic coding benchmarks 2026", mission: "M-002", agent: "RCH-01", status: "running", progress: 64, sources: 18, quality: 88, started: at(0, -3) },
  { id: "R-40", title: "Competitor pricing Q4", mission: "M-004", agent: "RCH-02", status: "review", progress: 100, sources: 11, quality: 74, started: at(-1, -2) },
  { id: "R-39", title: "Prompt-injection defences in README ingestion", mission: "M-008", agent: "RCH-01", status: "done", progress: 100, sources: 22, quality: 93, started: at(-2) },
  { id: "R-38", title: "Batch API pricing changes", mission: "M-001", agent: "RCH-03", status: "queued", progress: 0, sources: 0, quality: 0, started: at(0, -.2) },
];
export const CONCLUSIONS = [
  { id: "C-1", job: "R-39", text: "Treat README and issue text as untrusted input; strip tool-call syntax before summarising.", conf: 93, supports: 7, against: 0 },
  { id: "C-2", job: "R-41", text: "Agentic coding benchmarks overweight single-file tasks; use repo-level suites for our decisions.", conf: 78, supports: 5, against: 2 },
  { id: "C-3", job: "R-40", text: "Competitor X lowered entry pricing about 15% in Q4.", conf: 61, supports: 2, against: 2 },
];
export const CONTRADICTIONS = [
  { id: "X-1", claim: "LLM cost per task fell 30% YoY", a: "Provider blog (self-reported)", b: "Independent benchmark: 18% decrease", job: "R-40", state: "open" },
  { id: "X-2", claim: "Competitor X pricing is $49/seat", a: "Cached pricing page (Oct)", b: "Live pricing page: $42/seat", job: "R-40", state: "open" },
  { id: "X-3", claim: "Framework Y is production-ready", a: "Vendor docs", b: "Two independent bug reports on stability", job: "R-41", state: "resolved" },
];

export interface Citation { id: string; claim: string; source: string; url: string; retrieved: string; license: string; reliability: number; usedBy: string[]; verified: boolean }
export const CITATIONS: Citation[] = [
  { id: "CT-1", claim: "Agent collaboration improves task success rate by 12.9% (n=3,240)", source: "arXiv cs.AI", url: "https://arxiv.org/abs/2501.12345", retrieved: at(-1), license: "CC BY 4.0", reliability: 90, usedBy: ["M-002", "M-005"], verified: true },
  { id: "CT-2", claim: "Self-evolution with feedback loops yields +18.6%", source: "Nature Machine Intelligence", url: "https://www.nature.com/articles/s41586-025-12345-6", retrieved: at(-2), license: "Publisher (quote only)", reliability: 94, usedBy: ["M-001"], verified: true },
  { id: "CT-3", claim: "Structured evaluation reduces regression rate by 24.1%", source: "Google Research", url: "https://research.google/blog/operational-llm-systems", retrieved: at(-3), license: "CC BY 4.0", reliability: 86, usedBy: ["M-006"], verified: true },
  { id: "CT-4", claim: "Cost-aware inference can cut spend by 30-42%", source: "OpenAI Research", url: "https://openai.com/research/self-improvement", retrieved: at(-3, -4), license: "Publisher (quote only)", reliability: 82, usedBy: ["M-001", "M-009"], verified: false },
  { id: "CT-5", claim: "Governance and guardrails reduce risk incidents by 76%", source: "Competitor changelog", url: "https://example.com/changelog", retrieved: at(-4), license: "Unknown", reliability: 40, usedBy: ["M-004"], verified: false },
];

export const IMPORTED_DOCS = [
  { name: "AXoR_Platform_v1.4.0_Spec.pdf", size: "12.6 MB", at: at(-1, -2), type: "PDF" },
  { name: "Agent_Eval_Report_Q4.pdf", size: "8.4 MB", at: at(-1, -1), type: "PDF" },
  { name: "R&D_Roadmap_2025.pptx", size: "24.1 MB", at: at(-2, -3), type: "PPT" },
  { name: "Governance_Policy_Update.docx", size: "3.2 MB", at: at(-2, -5), type: "DOC" },
  { name: "Best_Practices_Agent_Dev.pdf", size: "5.9 MB", at: at(-3), type: "PDF" },
];
export const BEST_PRACTICES = [
  { name: "Agent Development Workflow", used: 48, gain: 18.2 }, { name: "Evaluation & Testing Playbook", used: 36, gain: 12.9 },
  { name: "Cost Optimization Guidelines", used: 31, gain: 24.1 }, { name: "Deployment & Rollout Checklist", used: 28, gain: 16.7 }, { name: "Incident Response (Agents)", used: 19, gain: 20.5 },
];

// Learning Queue candidates that came from external research (the internal ones come from the store's pending / conflict / outdated items).
export interface QItem { id: string; title: string; origin: "internal" | "external"; source: string; summary: string; confidence: number; flags: string[]; license: string; missions: string[]; base?: "pending" | "conflict" | "outdated" }
export const QUEUE_EXTRA: QItem[] = [
  { id: "LQ-1", title: "Batch API prices cut by 40% (provider announcement)", origin: "external", source: "https://openai.com/blog", summary: "Provider states batch endpoints are 40% cheaper from next month.", confidence: 77, flags: ["Single source", "Self-reported"], license: "Publisher (quote only)", missions: ["M-001"] },
  { id: "LQ-2", title: "Fine-grained token expiry on GitHub", origin: "external", source: "https://github.blog/feed/", summary: "GitHub adds expiry policies for fine-grained tokens; affects deploy credentials.", confidence: 90, flags: [], license: "CC BY 4.0", missions: ["M-012"] },
  { id: "LQ-3", title: "README-based prompt injection pattern", origin: "external", source: "https://news.ycombinator.com/rss", summary: "Hidden instructions in README files can steer coding agents. Content contained instruction-like text; quarantined and summarised only.", confidence: 71, flags: ["Injection scan: instruction-like text found", "Needs human verification"], license: "Unknown", missions: ["M-008"] },
];
export const RECIPIENTS = [
  { id: "all", label: "Entire company (all agents)" }, { id: "research", label: "Research" }, { id: "development", label: "Development" }, { id: "operations", label: "Operations" },
  { id: "qa", label: "QA / Verifier" }, { id: "knowledge", label: "Knowledge" }, { id: "finance", label: "Finance" }, { id: "deployment", label: "Deployment" },
];
export const RECENT_RESEARCH_SOURCES = [
  { name: "Agentic AI: Architectures & Evaluation (2025)", url: "arxiv.org/abs/2501.12345", cites: 12 },
  { name: "Multi-Agent Collaboration at Scale", url: "nature.com/articles/s41586-025", cites: 8 },
  { name: "Operational LLM Systems Best Practices", url: "research.google/blog/operational-llm", cites: 11 },
  { name: "AI Company Automation & Governance", url: "microsoft.com/research", cites: 6 },
];

export const EXTERNAL_SOURCES = [
  { name: "Agentic AI: Architectures & Evaluation (2025)", url: "https://arxiv.org/abs/2501.12345", cites: 12, mark: "x", c: "#b31b1b" },
  { name: "Multi-Agent Collaboration at Scale", url: "https://www.nature.com/articles/s41586-025-1234", cites: 8, mark: "N", c: "#222" },
  { name: "Operational LLM Systems Best Practices", url: "https://research.google/blog/operational-llm-systems/", cites: 11, mark: "G", c: "#3b8cff" },
  { name: "AI Company Automation & Governance", url: "https://www.microsoft.com/research/ai-company-governance", cites: 6, mark: "M", c: "#f25022" },
  { name: "Continuous Self-Improvement for Agents", url: "https://openai.com/research/self-improvement-agents", cites: 9, mark: "O", c: "#10a37f" },
];
