# UI v3: evidence report (coordination protocol §8)

```text
Task / issue: #22 AXoR UI v3 update from docs/update_2026-11-15
Executor: Claude Code (implementation; 5 parallel page sub-agents, each integrated and reviewed by the lead session)
          + GPT via `codex exec` (architecture review, agent-function document, 5 code reviews: 24 + 19 + 14 + 9 findings, all resolved; #5 confirmed the #4 fixes, its 2 follow-ups resolved)
VPS host / checkout identity: AXoR VPS, separate clone /home/thomas/axor-ui-v3 (shared checkout /home/thomas/subnet-scout untouched)
Starting commit: e8790a9 (preservation/prod-d429a13-20261115 = production d429a13 + the 4 overlay files, byte-identical with the VPS working tree)
Task branch: feat/ui-v3
Final commit: see the PR head (this report refreshed at 31f8986, after owner decisions 3 and 4)
Changed files: 193 files, +16,486 / -79 (vs e8790a9). Excluding generated build output, reference catalogs and screenshots:
  backend/app/ui_v3.py (new), backend/app/main.py (+2 lines: router wiring)
  frontend/app.js (BUG-01: toast removed), frontend/app/* (rebuilt React bundle served at /app)
  frontend/react/** (UI v3: theme, shell, kit, avatars, store, live read models, 14 pages)
  tests/unit/test_ui_v3.py, tests/frontend/*.test.cjs, tests/frontend/ui-v3-crawl.mjs, ui-v3-live.mjs, ui-v3-live-crawl.mjs
  docs/ui-v3/** (ROADMAP, PROGRESS, AGENT_FUNCTIONS, EVIDENCE, reviews, reference catalogs, screenshots)
Commands executed (final state):
  tests/run-unit.sh                          -> exit 0; Ran 954 tests, OK (skipped=7); ~67 s; axor/web:d429a13 image, --network none
  tests/run-unit.sh -- -k test_ui_v3         -> exit 0; Ran 19 tests, OK
  node --test tests/frontend/*.cjs           -> exit 0; 20 pass, 0 fail (BUG-01 guard, mining readiness, live read-model mapping,
                                                live-write request planning: approvals, tasks, missions, create, chat, error text)
  cd frontend/react && npx tsc --noEmit      -> exit 0
  cd frontend/react && npx vite build        -> exit 0; a fresh clone builds output identical to the committed frontend/app
  node tests/frontend/ui-v3-crawl.mjs        -> "all checks passed" (repeated). 14 v3 routes + 3 legacy pages; every tab is non-empty
                                                and changes the content; no page scroll at 1672x941 and 1600x900; no unnamed icon
                                                buttons; ? help on every page; console clean except /api/ui 404 in the static preview
  --shots --themes                           -> 140 screenshots (14 pages x 10 presets); selection in docs/ui-v3/screenshots/
  Throwaway AXoR instance (axor/web image, internal docker network, read-only tree, tmpfs data, test users boss=admin, ann=member):
  node tests/frontend/ui-v3-live.mjs         -> "all live checks passed": login and bootstrap; theme persisted across reload;
                                                self-renewal: admin round trip OK, member UI disabled and API 403; Sample mode sends no
                                                settings write; CSRF guard 403 without the header; organisation source 403 for a
                                                member, mission source 200, metadata URL 422; no console errors on all routes
  node tests/frontend/ui-v3-live-writes.mjs  -> "all live write checks passed" (owner decision 4), as the admin on the seeded instance,
                                                driving the real buttons: proposal decide -> POST mission-tasks/4/decide {ok:true}
                                                (AXoR saved the approval, then 409 "Only a Competition team has a board" because
                                                the seed has no team: the UI says "approved, but AXoR couldn't go further"); failed
                                                board task retry -> POST mission-tasks/5/run (same 409, shown as "Not done");
                                                success paths (seed_data2): agent-run task cancel -> PATCH /api/control/tasks/7
                                                {status:cancelled} 200, server cancelled; proposal skip -> POST
                                                mission-tasks/8/decide {ok:false} 200, server cancelled; company approval rejected
                                                from the Notifications inbox button -> 200, server rejected; Add Mission with a
                                                .txt attachment -> POST /api/mos/uploads 200, its id carried in attachments;
                                                mission resume -> POST /api/mos/missions/1/resume 200; agent chat -> POST
                                                /api/company/agents/1/chat 409 "No model is connected" shown; Add Mission -> POST
                                                /api/mos/missions with the MissionIn body, 503 "No model is available yet" shown in
                                                the dialog; Sample mode sends no hub writes; no page errors.
  node tests/frontend/ui-v3-first-visit.mjs  -> "first visit ok" on a BARE instance (no seed): admin one-time password, forced password
                                                change, then /app on live data with no missions: every page renders, admin lands on
                                                live data, /app console clean (the classic sign-in page's own 401/403 before login
                                                are not counted) Not provable here: a successful chat reply and mission creation need
                                                a model provider, which the throwaway instance doesn't have (no production
                                                credentials were copied into it).
  node tests/frontend/ui-v3-live-crawl.mjs   -> as admin and as member, on an instance seeded with real-shaped missions (running and
                                                delivered), tasks in six statuses incl. proposed, and a pending company approval: every
                                                route and tab renders, no error boundary, no page scroll, console clean
Build / artifact hashes:
  frontend/app/index.html sha256 bc19485a89d8678ab95a069839bbacd5f21aa56fd6a2107157ba46a8e73a98e9
  frontend/app/** (sorted file list, sha256 of sha256s) 4e9e51fc94a2311bf196f1375368368688fa10df06f6df877d7a476421472330
  No container image built or published. The throwaway instance used the existing local axor/web:d429a13 image unchanged.
Security and migration notes:
  - No migration: /api/ui stores JSON in app_settings (AuthDB.setting). Keys: ui_prefs:<user>, ui_user_settings:<user>
    (personal notifications and quiet hours), ui_settings (organisation: self-renewal, AI roles, autonomy, verification
    provider), ui_news_sources. A process lock serialises read-modify-write; several replicas would need a DB-level CAS.
  - /api/ui: signed-in users only. Self-renewal, AI roles, autonomy and the verification provider are admin-only.
    Organisation news sources are admin-only, mission sources need a mission ref, edits are owner-or-admin, and every
    write is audited. Writes carry X-Requested-With: scout (AXoR's CSRF guard) and work under the existing CSP
    (no blob: images; previews use data: URLs).
  - News-source URLs: http(s) only. Credentials, odd ports, private/loopback/link-local/metadata hosts and ambiguous numeric
    hosts are refused. Sources are stored only; the eventual fetcher must re-check the resolved address. Mission-ref
    ownership is not checked by this router.
  - BEHAVIOUR CHANGE: live data comes from GET /api/control/missions and GET /api/company, the same calls the classic
    pages make. These GETs are not side-effect free: the company is created on first read and recurring tasks reopen.
    UI v3 calls them only when an administrator opens a page that shows hub data (Overview, Missions, Mission Control,
    Agents, Organization, Notifications, Analytics), and never for members (both hubs are administrator-only, so members
    see sample data). Owner decision 3: admins land on live data (unchanged).
  - BEHAVIOUR CHANGE (owner decision 4, 2026-11-16: "wiring the real actions: enable"): in live mode UI v3 writes to the
    hubs through the endpoints the classic pages use (frontend/react/src/v3/data/hub.ts), and reloads the hub data after
    every write:
      decide a proposal       POST /api/control/mission-tasks/{id}/decide {ok}            (approve / skip)
      decide a company item   POST /api/company/approvals/{id}/decide {decision, reason}  (decide only; Execute stays on
                                                                                           the classic Company page)
      retry / cancel a task   by where it runs (GPT review #4): agent tasks PATCH /api/control/tasks/{id} {todo | cancelled};
                              board tasks restart with POST mission-tasks/{id}/run, are stopped/accepted on the board;
                              a mission's own tasks follow the mission
      board moves             the same rules (done needs an agent task with a result)
      pause/resume/cancel     POST /api/mos/missions/{id}/pause|resume|cancel              (custom mx: missions only)
      Add Mission             POST /api/mos/uploads per file, then POST /api/mos/missions
      message an agent        POST /api/company/agents/{id}/chat with "[Mission <ref>: <title>]" leading the text (the
                              company chat has no mission field), reply polled from GET .../workspace
    Refused in the UI with the reason (AXoR has no such action): task pause, competition-mission pause, archive (never
    mapped to DELETE), creating a GitHub repository from a new mission, pictures on a decision, attachments in chat.
    Server refusals show FastAPI's own text. One request per target (a proposal and its task share one) is in flight until
    the reload after it has finished. A mode switch stops a mission start that is still uploading. Sample mode sends nothing.
  - GPT only ever saw docs and diffs copied into an empty folder (codex exec -s read-only --ephemeral), never the repo
    tree. The tree tracks .env.before-stack, which holds a real 108-character CLAUDE_CODE_OAUTH_TOKEN (see below).
  - Previews never proxied to a real service: a static http.server on 127.0.0.1:5199, and the throwaway container on
    an internal network.
Known limitations:
  - Live for missions, tasks, agents, departments, approvals and audit (read and write, owner decision 4) and for messages
    you send to agents, plus preferences, settings and news sources (read/write via /api/ui). Versions, evolution,
    knowledge, finance, models, past conversations and the KPI and health figures are SAMPLE in every mode. They are
    badged: header switch, a banner in live mode, and Sample pills.
  - Hub writes are live (above). Actions on the still-sample areas (versions: merge, deploy, run preview; evolution;
    knowledge; finance) and creating a GitHub repository record locally in sample mode only; nothing real happens.
  - Fidelity: layouts, panels, tab sets, texts and icons follow the canonical images (30-1 .. 30-10, 40-13, 40-14).
    Raster art (hero city, guardian mascot, robot avatars) is redrawn as animated SVG; numbers come from data.
  - SECURITY (pre-existing, not changed): .env.before-stack is tracked in git since 3acfe1a (2026-11-10) and contains a
    CLAUDE_CODE_OAUTH_TOKEN. Recommend rotating that token and removing the file (history purge optional). Owner action.
Rollback: don't merge. Or revert the branch. The classic UI is unchanged except BUG-01 (one line). /app serves whatever
  frontend/app build is deployed.
Server (2026-11-16): a separate instance of this branch, NOT production: container axor-ui-v3 on 127.0.0.1:8840 (image
  axor/web:d429a13 unchanged, branch tree mounted read-only, own volume axor-ui-v3-data, no production env or credentials).
PR: #23 (draft)
Deployment: NOT DEPLOYED (D-OWNER-003 HOLD). No restart, migration, image publish or k8s change on production.
```
