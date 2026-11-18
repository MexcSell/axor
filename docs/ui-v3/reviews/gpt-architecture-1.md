# GPT architecture review #1 (codex exec, model gpt-6.1-sol, read-only, isolated folder with ROADMAP.md only)

Prompt:
```
You are the GPT architect for AXoR (an autonomous multi-agent "company OS" web app). Claude Code writes the code; you own architecture and design review. The file ROADMAP.md in the current folder is the update plan. Context you need:
- Frontend: existing React 18 + TypeScript + Vite sub-app (hash routes, served at /app by FastAPI). New libs: framer-motion 11, lucide-react, @xyflow/react 12, recharts 2. No router/state library yet.
- Backend: FastAPI, ~77k lines, existing hubs /api/control (missions, mission-tasks run/decide), /api/company (agents, approvals decide/execute), /api/evolution, /api/knowledge. AuthDB for users; require_user(req) for auth.
- Target: 13 pages, each with 5-7 tabs, all populated; one-screen (1600x900) dense dashboards; 10 theme presets via CSS variables; every element animated (respect reduced motion); icon-only buttons with tooltips and "?" help popovers; role-specific robot agent avatars.
- Data: where no backend exists yet, a clearly badged Sample dataset; later a /api/ui/* router.

Deliver, concisely (<= 900 words), as numbered sections:
1. Frontend module architecture (folders, the data layer: a single typed client store vs per-page hooks; how to swap Sample -> live per resource; how to keep mission isolation in the store; routing incl. per-page tab in URL).
2. The domain types you'd define (names + key fields) for Mission, Task, AgentIdentity, AgentInstance, AgentVersion, Thread/Message, Approval, Event, Version/Release, Branch, EvolutionCandidate, Evaluation, MentoringRecord, NewsSource, ModelRoute, Budget. Keep it compact.
3. The /api/ui/* backend contract you'd implement first (max 10 endpoints) and storage choice given an existing AuthDB (sqlite/postgres) layer.
4. Top 8 risks/pitfalls for this plan (fidelity, perf with many animated panels, a11y, theme tokens, honesty of sample data) with a mitigation each.
5. Anything in ROADMAP.md you'd change.
```

Answer:

1. **Frontend architecture**

Use `src/{app,domain,data,features,ui,themes,test-support}`:

- `app/`: shell, route/tab registry, authentication boundary, lazy page loading.
- `domain/`: entities, status unions, DTO validation and adapters.
- `data/`: HTTP client, resource providers, normalized store, subscriptions.
- `features/<page>/`: panels, selectors and actions.
- `ui/`: accessible primitives, charts, graph wrappers, avatars.
- `themes/`: semantic tokens, presets and motion policy.

Choose **one typed resource store**, exposed through resource hooks such as `useMissionTasks(missionId)`. Keep temporary form state local. Use narrowly subscribed, immutable snapshots through [`useSyncExternalStore`](https://react.dev/reference/react/useSyncExternalStore).

Each resource provider implements the same interface, with explicit Sample/live selection. Results carry `{source, observedAt, status, capabilities}`. Never silently substitute fixtures after a live failure; badge each Sample panel, including mixed dashboards.

Cache keys include authenticated principal/company, source, mission, resource and query. Share stable agent identities; partition tasks, instances, threads and approvals by mission. Abort superseded requests, reject stale responses, and clear caches on logout.

Use `/app/#/control/<missionId>?tab=conversations&thread=<id>`; profile sub-tabs get another explicit parameter. A validated route registry handles defaults, unknown routes, reload and Back/Forward.

2. **Domain types**

Common fields: `id`, ownership scope, timestamps and revision; use typed IDs, explicit status unions, UTC timestamps and decimal money with currency.

| Type | Key fields |
|---|---|
| Mission | title, goal, status, progress, ownerId, budgetId, releaseId, nextEditionAt, scheduleKind |
| Task | missionId, parentId, dependencyIds, assigneeInstanceId, status, attempt, outputs |
| AgentIdentity | name, role, avatarKey, capabilities, currentVersionId |
| AgentInstance | identityId, missionId, agentVersionId, supervisorInstanceId, branchId, status |
| AgentVersion | identityId, parentVersionId, configurationHash, artifactRef, evaluationIds |
| Thread / Message | missionId, participantRefs, kind; threadId, senderRef, body, attachments, sequence |
| Approval | missionId, actionType, payloadHash, candidates, status, decidedBy, executionStatus |
| Event | missionId?, actorRef, type, subjectRef, payloadVersion, occurredAt, sequence |
| Version / Release | missionId, commitSha, artifactRef; versionId, environment, status, gates, publishedAt |
| Branch | repositoryId, missionId?, name, baseSha, headSha, status |
| EvolutionCandidate | identityId, baselineVersionId, proposedVersionId, evidenceRefs, status |
| Evaluation | candidateId, evaluatorRef, independenceEvidence, benchmarkVersion, scores, verdict |
| MentoringRecord | mentorRef, menteeRef, missionId?, objectives, evidenceRefs, outcomes |
| NewsSource | ownerId, url, trust, cadence, enabled, validationStatus, lastFetchedAt |
| ModelRoute | scope, taskClass, provider, modelId, fallbackIds, constraints, revision |
| Budget | scope, period, currency, limit, spent, reserved, thresholds |

Keep approval decision and execution separate; preserve immutable agent-version provenance.

3. **First `/api/ui/*` contract**

Implement these ten method/path combinations:

1. `GET /bootstrap` — preferences, capabilities, company overview.
2. `GET /missions` — filtered, cursor-paginated summaries.
3. `GET /missions/{id}` — mission details.
4. `GET /missions/{id}/{resource}` — strictly enumerated `tasks|instances|threads|approvals|events`, each with a typed, paginated response.
5. `GET /missions/{id}/threads/{threadId}/messages`.
6. `GET /agents/{id}` — identity, version summaries, authorized instance references.
7. `PUT /preferences` — versioned schema and revision precondition.
8. `GET /news-sources`.
9. `POST /news-sources`.
10. `PATCH /news-sources/{id}` — edit or disable.

Return provenance, freshness, cursors and structured errors. Apply `require_user(req)` plus company/mission authorization on every lookup; authentication alone is insufficient.

Aggregate existing hubs through shared application services. Retain existing command routes for mission creation, task execution and approval actions; require server authorization, idempotency and conflict handling.

Reuse AuthDB’s configured SQLite/Postgres engine and repository conventions. Add dedicated preferences/news-source tables and migration files; keep operational records authoritative in existing stores. Respect the deployment/migration HOLD.

4. **Top eight risks**

1. **Reference fidelity:** alternate compositions can conflict. Assign one canonical reference per page and approve geometry screenshots before populating everything.
2. **Animation performance:** bound concurrent animations, virtualize lists, lazy-mount tabs, memoize graph nodes and handlers. [React Flow guidance](https://reactflow.dev/learn/advanced-use/performance).
3. **Accessibility:** keyboard-operable tabs, named icon buttons, focus management, text status cues and focus-triggered tooltips/help. Follow the [WAI tabs pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/).
4. **Viewport rigidity:** allow internal panel scrolling; support reflow and zoom beyond the reference viewport.
5. **Theme drift:** use semantic surface/text/status/chart tokens; validate contrast across every preset.
6. **Sample dishonesty:** deterministic coherent fixtures, panel-level badges, explicit simulated actions and visible live errors.
7. **Mission leakage/races:** scoped cache keys, request cancellation, revision checks and backend ownership checks.
8. **Unsafe actions:** server-enforced permissions, approval/execution separation, idempotency and audit; URL ingestion needs SSRF protection, previews need isolation.

5. **Changes to ROADMAP.md**

- Resolve **14 listed routes versus 13 target pages**; Analytics lacks a tab inventory.
- Define exactly **10 presets**; reconcile that with “nine styles × light/dark” and Sakura/Sakura Night.
- Move contract definitions and one live mission vertical slice into foundation work; waiting until step 7 invites rework.
- Start U14’s identity/instance/lifecycle definitions before U7/U10.
- Replace literal “every element animates” with a shared motion policy honoring reduced motion.
- Define density acceptance at both 1600×900 and 1672×941, with accessible overflow.
- Run verification incrementally: interactions, mission isolation, failure states and canonical screenshots—not merely non-empty tabs.
