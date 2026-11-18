# AXoR UI v3 — update plan (from `docs/update_2026-11-15`)

Status: in progress on branch `feat/ui-v3` · Executor: Claude Code (code) with GPT via `codex exec` (architecture review, design critique, code review) · Started 2026-11-16

## Status (2026-11-16)

U0–U12, U14 and U15 are done on `feat/ui-v3`. Evidence is in `EVIDENCE.md`, screenshots are in `screenshots/`, and the GPT reviews are in `reviews/`.

U13 (backend) is partly done:
- **Live through `/api/ui`:** appearance preferences, settings, news sources.
- **Read-only from the existing hubs:** missions and tasks (`/api/control/missions`); agents, departments, approvals and audit (`/api/company`). When signed in, a header switch toggles Live and Sample.
- **Not wired yet (needs an owner decision):** writes (start mission, decide, message, task moves). In live mode they refuse with a clear message.
- **Still sample in every mode:** versions, evolution, knowledge, finance, models and conversations.

Verification so far:
- Run against a throwaway AXoR instance as an admin and a member: `tests/frontend/ui-v3-live*.mjs`.
- Run in sample mode: `ui-v3-crawl.mjs`.

Owner decisions of 2026-11-16:
- **3. Default view:** keep the current behaviour (admins land on live data).
- **4. Writes:** enabled. Live-mode actions call the hubs (`data/hub.ts`). They are tested in `tests/frontend/ui-v3-hub-writes.test.cjs` and `ui-v3-live-writes.mjs`.

Not deployed (D-OWNER-003). This branch runs as its own server for the owner: container `axor-ui-v3` on `127.0.0.1:8840`, separate from production. It has its own data volume and no production credentials.

## 0. Ground rules (what this branch may and may not do)

| | |
|---|---|
| Base | `preservation/prod-d429a13-20261115` @ `e8790a9`. This is production `d429a13` plus the four uncommitted overlay files. Their SHA-256 values were checked against `/home/thomas/subnet-scout`'s working tree on 2026-11-16 and are byte-identical. These are the "current modifications" the owner asked to branch from. |
| Workspace | Separate clone `/home/thomas/axor-ui-v3`. The shared checkout `/home/thomas/subnet-scout` is not touched (D-OWNER-001, owner-decisions §Safety). |
| Divergence | The base is 3 commits ahead of / 157 behind `origin/main` (merge-base `5862bed`). This branch does **not** reconcile that. Reconciliation is owner decision step 4. |
| Git | Only `feat/ui-v3` is pushed. One draft PR, no merge. "Merge at the end" means a PR ready for the Owner. |
| Deploy | **HOLD (D-OWNER-003).** No deploy, restart, migration, image publish or k8s change on production. Previews run on a local dev server or a throwaway process. On 2026-11-16 the owner asked to "start server", so a separate branch server runs as container `axor-ui-v3` on `127.0.0.1:8840` (`--restart unless-stopped`). It has its own volume and no production env, and production is untouched. Stop it with `docker rm -f axor-ui-v3`; delete its data with `docker volume rm axor-ui-v3-data`. |
| Login sharing | D-OWNER-002 is untouched. No change to Claude/Codex login-sharing behaviour. |
| Data honesty | Screens without a backend yet show **Sample** data with a visible badge. Fixtures are never reported as live features. |

## 1. Sources read

* `readme.txt`, the owner's notes (copied to `reference/owner-readme-2026-11-15.txt`).
* Seven .docx files, six of them distinct: *Complete Autonomous Company Upgrade v2.0*, *Homepage & Platform Update v1.0*, *UI & Agent Function v3*, *Detailed UI & Agent Function v3*, *UI v3 Detailed Pages & Agent Function*, *UI Design & Page Function*.
* 76 images, catalogued in `reference/image-catalog-G1..G4.md`. Some are byte-identical: 1 = 2, 6 = 01, 7 = 02, 8 = 03, 9 = 04. SHA-256 values are in `reference/SOURCE_SHA256SUMS`. The images themselves are **not** committed (the owner excludes that folder from git); they live in `/home/thomas/subnet-scout/docs/update_2026-11-15/`.
* The ChatGPT share link, read with headless Chromium (`reference/chatgpt-share-transcript.txt`). It shows the image series are deliberate *alternative compositions*. The owner asked GPT for "each screen with a different aspect", then a light-mode set.

## 2. Overall look → design decision

The images are not one design. They are one product drawn in several looks, and the owner asked that the user can change "the face" (flat, luminous, pretty, fancy, bright and dark). So:

* **Default look = "Dark Luxury"**: navy/black, gold hairlines and glow, robot agent avatars. This is the 30-x series plus 13.png and 12.png. Layout, panels, tabs and texts follow the **30-x per-page images** exactly.
* Every other series becomes a selectable **Appearance Studio preset** using the same layout and functions:

| Preset | Reference |
|---|---|
| Classic Light | 1.png / poster |
| Midnight Dark | 0-2 |
| Flat Minimal | 01 / 6 |
| Luminous Neon | 16, 19, 02, 40-x |
| Pretty Pastel | 03, 14, 50-x |
| Fancy Glass | 04 |
| Sakura / Sakura Night | 15, 18 |
| Renaissance | 17 |

  Each style has a light and a dark palette, plus accent, density, font, icon-shape, contrast and motion settings.
* Library additions (exact pins): `framer-motion 11.11.17` (every element animates, and the reduced-motion setting is honoured), `lucide-react 0.460.0` (icons with a clear meaning; every icon-only button has a tooltip and an `aria-label`), `@xyflow/react 12.3.5` (agent graph, task DAG, branch graph), `recharts 2.13.3` (charts).
* Where it is built: the existing React + Vite app (`frontend/react`, served at `/app`). The classic UI at `/` stays as it is. The only change there is the BUG-01 toast removal.

### Page → reference image (canonical first)

| Page (route) | Canonical | Also |
|---|---|---|
| Shell (header, sidebar, mascot) | 30-1 | 13, 12 |
| Company Overview `#/overview` | 30-1 | 13#1, 0-2, 50-1, 40-5 |
| Missions `#/missions` + Add Mission modal | 30-2 | 13#2–3, 40-1, 40-3, 50-2 |
| Mission Control `#/control` (Overview, Task Flow, Agents, Conversations, Approvals, Activity, Reports) | 30-3 | 13#4–5/#8, 01, 3/4/5 (Activity Log, Conversations, Approvals), 50-3 |
| Agents / Agent Profile `#/agents` | 30-4 | 13#6–7, 40-4, 40-6, 50-4, 10, 11 |
| Organization `#/organization` | 30-5 | 40-7, 40-8, 40-9, 50-5 |
| Versions & GitHub `#/versions` | 30-6 | 13#9, 03, 50-6 |
| Evolution Lab `#/evolution` | 30-7 | 13#10, 02, 0-3, 10, 11, 50-7 |
| Knowledge & News `#/knowledge` | 30-8 | 13#11, 50-8 |
| Finance `#/finance` / Governance `#/governance` | 30-9 | 0-5 (sustainability ratio), 50-9 |
| Appearance Studio `#/appearance` + Settings `#/settings` | 30-10 | 13#12, 04, 50-10, 40-10..12 |
| Notifications `#/notifications` | 40-14 | |
| Analytics `#/analytics` (existing page, restyled) | 40-13 | |

### Tab inventory (all tabs must have real content: UI-AT-01)

The tab inventory is the union of the documents and the images.

* **Overview:** Summary · Missions · Decisions · Performance · System Health
* **Missions:** All · In Progress · Review · Waiting · Completed · Archived. The Add Mission modal has four steps: Details · Resources · Budget & Policy · Review.
* **Mission Control:** Overview · Task Flow · Agents · Conversations · Approvals · Activity · Reports. Task Flow has Board / Flow (DAG) / Timeline (Gantt) / Table views.
* **Agents:** Directory · Agent Graph · Profile. The profile tabs are Capabilities · Mission Instances · Experience · Evolution · Mentoring · Performance · Audit.
* **Organization:** Org Chart · Departments · Agents · Assignments · Performance · Reorganization
* **Versions:** Releases · Branch Graph · Compare · Merge Requests · Preview · Downloads
* **Evolution Lab:** Proposals · Experiments · Benchmarks · Agent Lifecycle · Promotion Queue · Mentoring · History
* **Knowledge & News:** Library · Research · News Feed · Sources · Citations · Learning Queue
* **Finance:** Overview · Budgets · Usage · Cost by Mission · Alerts · Forecast
* **Governance:** Autonomy · Permissions · Model Routing (model loader) · Self-Renewal · Policies · Audit
* **Appearance Studio:** Themes · Colors · Typography · Layout · Icons & Avatars · Accessibility · Presets
* **Settings:** General · Integrations · Approvals · Notifications · Security · Admin (Self-Renewal, Model Loader, Verification, AI roles)
* **Notifications:** Inbox · Pending · Resolved · Rules

## 3. What has to be updated, item by item

| # | Item (source) | What changes | Done when |
|---|---|---|---|
| U0 | Stray white board "updateable to block 9365236" (readme, BUG-01, NFR-008) | Remove the `toast("Updated to block N")` in `frontend/app.js` and add a node regression test | ✅ commit `fix(ui): remove the 'Updated to block N' toast` |
| U1 | Global design system (UX-001..006, THEME-001..003) | Tokens, nine styles × light/dark, accent, density, font, icon shape, high contrast, reduced motion. Shell: header, sidebar, status pill, clock, help, notifications, avatar. Primitives: Panel with "?" help, Tabs, IconButton with tooltip, StatusPill (icon + text + colour), Progress, KPI, Gauge, Donut, Avatar, Modal, Toast, Skeleton, Empty/Error | All presets apply to every screen and survive a reload |
| U2 | Agent avatars (readme, UX-006, AT-11) | Role-specific animated robot avatars: GM crown, research magnifier, developer code, QA shield, ops gear, finance ledger, knowledge book, deploy rocket, architect blueprint, mentor cap. Each has text alt and a "glyph" pack alternative | Every agent shows a role-specific avatar |
| U3 | Company Overview (HOME-001..008) | 30-1 layout: KPIs, Company Health, Quick Actions, Missions, Org snapshot, Mission Control mini, Decision Inbox, Agent Conversation, Recent Activity, Versions, Evolution, Knowledge, Finance, Governance | Matches 30-1 at 1672×941 |
| U4 | Missions + Add Mission (readme §1–2, MIS-001..006, CREATE-01..06) | List with progress colours, issues and needs-your-decision count (distinct colour), version, completion and next edition (marked estimated or scheduled). The four-step modal takes text, documents, images and GitHub URLs. The GM generates the title. GitHub repo creation needs explicit approval | Start creates exactly one mission and opens Mission Control |
| U5 | Mission Control (readme §3, CTRL-*, MC-FLOW-*) | Agent hierarchy with arrows. Click an agent to open the chat on the right. Thread list by counterpart (user, senior, junior, peer). Full / condensed views, timestamps, icon-only copy. GM thoughts and reports window. Decisions with candidates, history, image input and Confirm; answered items hidden. Execution state colours. Task Flow DAG, board, timeline and table | UI-AT-02..05 |
| U6 | Versions & Preview (readme §4–5, VER-*, PREV-*) | Version list with right-side detail, download, Run preview, branch graph (main ↔ feature ↔ merge), compare, merge requests with gates, live preview iframe with commit and environment | Selecting a version shows details, and Run/Download work or explain why not |
| U7 | Agents & Agent Profile (v3 §4.10, §5) | Stable identity, concurrent mission instances (branch/merge model), experience, evolution diff, mentoring, performance, audit | AG-AT-01..05 visible in the UI |
| U8 | Organization (v3 §4.9, ADMIN-02) | Org chart, departments, assignments, performance, GM reorganization proposals with before/after | |
| U9 | Knowledge & News (readme §6, NEWS-*, KNOW-*) | Library, research, news feed. Users add their own source URLs (validation, cadence, trust). Learning queue, citations | A user can add a news source |
| U10 | Evolution Lab (v3 §4.12, §6, EVO-*) | Proposals, experiments, paired benchmarks, lifecycle (baseline → mission instances → consolidation → independent eval → promote), mentoring, history and rollback | |
| U11 | Finance & Governance (v3 §4.13, FIN-*, GOV-*) | Spend and budgets, sustainability ratio (0-5), autonomy levels L0–L5, permissions, **Model Loader / routing**, **Self-Renewal toggle** (admin), policies, audit | |
| U12 | Appearance Studio + Settings (v3 §3.2, §4.14) | Theme gallery with live preview, colours with contrast check, typography, layout, icons and avatars, accessibility, presets import/export. Admin settings: self-renewal, model loader, verification, AI roles (GPT = architecture/creative, Claude Code = code, joint research) | UI-AT-06 |
| U13 | Backend contracts (v3 §7, HOME §9) | `/api/ui/*`: per-user appearance preferences (server-side, versioned), news sources, mission/approval/thread/agent-instance read models. They aggregate existing hubs where they exist (`/api/control`, `/api/company`, `/api/evolution`, `/api/knowledge`), with unit tests | Prefs persist server-side; tests pass |
| U14 | Agent function document (readme: "documentation about the agent function is missing") | `docs/ui-v3/AGENT_FUNCTIONS.md`: roles, avatars, identity vs instance, multi-mission branch/merge, experience → candidate → independent verification → promotion, mentoring, self-renewal, model loader, GPT/Claude division of work | ✅ drafted by GPT, reviewed by Claude Code |
| U15 | Verification | Playwright script: every route × every tab has distinct non-empty content, no console errors, no page scroll at 1600×900, screenshots for every preset, side by side with the references | Script green; screenshots in the PR |

## 4. Step order (each step = commit + push; GPT review at each phase)

1. Plan, progress log and U0 ✅
2. U1 + U2 foundation (theme, shell, primitives, avatars, sample data store), then GPT design review
3. U3 Overview, U4 Missions, U5 Mission Control: the core user loop, checked against 30-1/30-2/30-3 by screenshot
4. U6 Versions, U7 Agents, U8 Organization
5. U9 Knowledge, U10 Evolution, U11 Finance & Governance, U12 Appearance/Settings, Notifications
6. U15 verification script and visual pass on every preset
7. U13 backend `/api/ui` with tests; wire live data where existing hubs have it
8. U14 agent function document, final GPT review, draft PR with evidence (§8 format)

## 5. Open items for the Owner (not decided by this branch)

* Merge into which base: the 157-commit divergence from `origin/main` must be reconciled first (owner decision sequence step 4).
* Whether `/app` (React) should replace `/` as the default signed-in page. This branch only links between them.
* Real GitHub repository creation, preview-service restart and production promotion stay gated by D-OWNER-003. The UI shows the approval flow but this branch does not wire production side effects.
