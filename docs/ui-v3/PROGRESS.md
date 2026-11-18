# UI v3: progress log

Newest entries go at the top. Each entry: time (UTC+9), commit, what was done and verified, what comes next.

## 2026-11-16 (later)
- **Advisor review before "done":** run the UI against the real backend, fix whatever that finds, wire live data, and close the fidelity gaps.
  - **Throwaway AXoR instance** (internal network, test users): found that writes needed AXoR's CSRF header and that the CSP blocks `blob:` images. Both fixed. Settings were persisted only partly; now complete, with personal and organisation settings kept apart.
  - **Live read models** from `/api/control` and `/api/company`, with a Live/Sample switch, a banner saying what is live, real `/api/health`, and empty states.
  - **Analytics** (40-13) and the **Notifications** inbox (40-14) built. Header hero and mascot redrawn closer to the reference.
  - **GPT code reviews #2 and #3:** 19 and 14 findings, all resolved.
  - Everything is verified by `EVIDENCE.md` (954 backend tests, 12 node tests, crawls, live checks).

## 2026-11-16
- **All 13 pages are built.** Agents (30-4), Organization (30-5), Versions (30-6), Evolution (30-7), Knowledge (30-8), Finance and Governance (30-9), Appearance & Settings (30-10) and Notifications (40-14). Four parallel page agents built them from one shared brief; each was integrated and reviewed here. Agents B (Versions/Evolution) and C (Knowledge/Finance/Governance) are on a second fidelity pass against their reference images.
- **Acceptance crawl** (`tests/frontend/ui-v3-crawl.mjs`): 13 pages, 125 tabs. Every tab changes the content and none is empty. No page scroll at 1672×941 or 1600×900, no unnamed icon buttons, "?" help on every page, console clean (apart from `/api/ui` 404s in the static preview).
- **GPT code review #1:** 24 findings (3 P1), all fixed. The review is in `reviews/gpt-code-review-1.md`.
- **Backend `/api/ui`:** preferences, settings and news sources, with 17 unit tests. The full suite passes: 949 tests OK on the axor/web:d429a13 image, offline.
- **Theme engine additions from 30-10:** glow level, icon set, avatar face style and avatar colour scheme. The Deputy GM ("associate governor") was added to the sample organisation.
- **U4 + U5 (Missions, Mission Control).** Missions follows 30-2: KPIs, filter chips (including Waiting on you and Archived), search, sort, column chooser, CSV export, bulk pause/archive, analytics donut, workload bars, quick add with "Generate with AI", and a detail column (resources, goals, related agents, milestones). Mission Control has 7 populated tabs:
  - Overview: hierarchy graph, plan, GM notes & reports, decisions waiting for you with history.
  - Task Flow (30-3): Kanban with drag guards (no Done without evidence, no start before dependencies), a dependency Gantt with zoom and fullscreen, a DAG view, a table, and the critical path, blockers and release checklist.
  - Agents: hierarchy with command/report/peer arrows; click an agent to chat on the right, filtered by user, seniors, juniors and peers.
  - Conversations: full or summary view, type filters, copy, execution status.
  - Approvals: pending only by default, a dossier, candidate choice, text and image answers, Confirm or reject or request changes, and a confirmation step for high-risk items.
  - Activity: filters, trace inspector, JSON/CSV export.
  - Reports: per agent, assigned / received / process / results, with Markdown export.
- Fixed the store snapshot cache (React #185 loop when selectors build arrays).
- U3 Overview (30-1) with every mini-tab populated; the shell, theme system and kit are in place (commit d3cb8f8). Issue #22 and draft PR #23 are open.
- Plan committed (`ROADMAP.md`), plus reference catalogs of all 76 images and the ChatGPT transcript.
- U0 done: the "Updated to block N" toast was removed (BUG-01) and a regression test added (`node --test tests/frontend/*.cjs`: 7 passed).
- Added `framer-motion`, `lucide-react`, `@xyflow/react` and `recharts` (exact pins) to `frontend/react`. The existing build still reproduces the committed asset hashes.
- Next: U1/U2 foundation (theme tokens, shell, primitives, avatars).
