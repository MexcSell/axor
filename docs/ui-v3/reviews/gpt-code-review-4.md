# GPT code review #4: live writes (owner decision 4)

Reviewer: GPT via `codex exec -s read-only --ephemeral` in an empty folder holding only the front-end diff (ed4627c..6932970, frontend/react and tests) and excerpts of the backend endpoints being called. It never saw the repository.

## Findings (verbatim)

1. **[P1] “Request changes” approves and starts a proposal.**  
   File: `frontend/react/src/v3/data/hub.ts:27`  
   `const ok = option !== "skip" && option !== "reject"` maps `"changes"` to `{ok:true}`. The backend approves the proposal and calls `run()`, despite the user requesting revisions. **Fix:** explicitly allow only `"approve"` to produce `true`; refuse `"changes"` for CT approvals and disable that button for them.

2. **[P1] Mission creation continues writing after switching to sample mode.**  
   File: `frontend/react/src/v3/data/store.ts:227`, `startLiveMission()`  
   The function checks neither the mode nor a mode generation before uploads or the final POST. Reproduced: start with an attachment, switch to sample while uploading, resolve the upload; `/api/mos/missions` is then POSTed in sample mode. **Fix:** capture a mode generation and verify it before every upload dispatch and before creating the mission. Invalidate pending creation sequences when switching modes.

3. **[P1] Task actions ignore where the task actually runs.**  
   File: `frontend/react/src/v3/data/hub.ts:48–69`, `planTaskAction()` / `planMoveTask()`  
   Cancellation, retry and acceptance always PATCH `/api/control/tasks/{id}`. That handler updates `ctl_tasks`; it does not cancel, restart or accept the linked board task or mission. Consequently, “Cancel task” can report success while the actual work continues. Additionally, `/mission-tasks/{id}/run` routes every non-agent task through `_to_board()`, so starting a mission-backed task does not resume its mission. **Fix:** retain backend `route` and `ref` in the task model and dispatch according to them; refuse unsupported actions instead of reporting success.

4. **[P1] Approval and board actions can send the same decision twice.**  
   File: `frontend/react/src/v3/data/store.ts:248`, `:366`  
   Approval uses `decide:CT-4`, while moving the same proposal to Running uses `task:C-4`. Both therefore pass `inFlight` and POST `/mission-tasks/4/decide` concurrently. Reproduced with mocked pending responses. The backend decision is a read followed by an unconditional update, so overlapping approvals can both reach `run()`. **Fix:** use one canonical task lock for CT decisions and every action on the corresponding task.

5. **[P2] Write locks expire before stale state is refreshed.**  
   File: `frontend/react/src/v3/data/store.ts:131–133`  
   `inFlight.delete(key)` runs before `loadLive()` completes, and successful reloads are not awaited. During that interval, the UI still exposes the old actionable state. Reproduced: a second Retry sends another PATCH while the first request’s reload remains pending. This can rerun work if the first execution finishes quickly. **Fix:** keep the resource locked until reconciliation completes. If reconciliation fails, require a refresh before another state-dependent action.

6. **[P2] Closing a starting mission discards its duplicate-submission guard.**  
   File: `frontend/react/src/v3/pages/AddMission.tsx`, `close()` / new `startLiveMission(...).then(...)`  
   `close()` explicitly allows closing while `busy`, calls `reset()`, and replaces the draft key. The live request continues. Reopening and submitting creates a second request under a new key; the old completion callback can also reset or close the new draft and navigate away. **Fix:** prevent closing while creation is pending, or retain the pending operation and draft key across reopening and ignore callbacks belonging to obsolete modal sessions.

7. **[P2] Mission chat sends an unscoped company conversation.**  
   File: `frontend/react/src/v3/data/hub.ts`, `planChat()`  
   The request contains only `text` and optionally `conversation_id`; `missionId` never reaches the backend. The UI says the instruction applies “in this mission only,” but the backend creates a conversation with no project context. The agent receives neither the mission objective nor its context. **Fix:** use a verified mission-context mapping and supported request contract. Where no mapping exists, refuse mission-scoped instructions or clearly present the interaction as general company chat.

8. **[P2] Assigned agents disappear because Control and Company IDs are compared directly.**  
   File: `frontend/react/src/v3/data/live.ts:120–127`  
   `byId` uses company keys such as `"ceo"`, while task `instanceId` starts with Control keys such as `"company:1"`. `byId.has(k)` therefore rejects assigned company agents, and their work never contributes to the generated instances. **Fix:** translate Control keys through `company:${agent.hubId}` to the company identity, then use that mapping consistently for membership and task counts.

9. **[P2] Failed decisions can be reported as partially approved without evidence.**  
   File: `frontend/react/src/v3/data/store.ts:248–249`  
   The partial-success predicate uses `find(...)?.status !== "awaiting_approval"`. A missing task satisfies that condition. If the user switches to sample mode while a decision fails, the sample task list lacks that ID, so the toast can claim “Approved … but AXoR couldn’t go further” even when approval never happened. **Fix:** inspect a successfully refreshed live snapshot, require the task to exist, and verify evidence of the requested decision before claiming partial success.

Verdict: **Request changes—wrong-outcome approval, sample-mode writes and duplicate-send paths block enabling live actions.**

## Resolution

Every finding is fixed. Verified with `node --test tests/frontend/*.cjs` (19 pass), `ui-v3-live-writes.mjs`, `ui-v3-live.mjs`, `ui-v3-live-crawl.mjs` (admin and member) and `ui-v3-crawl.mjs`.

| # | Fix |
|---|---|
| 1 | Proposals only send `{ok:true}` for "approve" and `{ok:false}` for skip or reject. "Request changes" on a proposal is refused with the reason, because AXoR has no such state. Unit tested. |
| 2 | Every mode switch bumps a mode generation. `startLiveMission` checks it before each upload and before the create POST, and stops with "You switched to sample data…". `liveWrite` only reports partial success for the same generation. |
| 3 | Live tasks keep the backend's `route` and `ref` (`hubRoute`, `hubRef`), and `whereTask()` decides the action. Agent tasks are PATCHed. A task not yet sent anywhere may be cancelled or queued. A board task is restarted with `mission-tasks/{id}/run`; stopping or accepting it is refused ("stop or accept it there"). A mission's own task is refused ("pause, resume or cancel the mission"). Unknown routes are refused. Unit tested. |
| 4 | A proposal `CT-n` and its task `C-n` share one lock, `task:C-n`, so Approvals and the board can't both send. |
| 5 | The lock is held until the reload after the write has finished (success or failure). |
| 6 | Add Mission can't be closed while a live start is in flight. It says so and keeps the draft key. |
| 7 | AXoR's company chat has no mission field, so the message now carries the mission: `[Mission mx:3: Portal (objective)]` plus the text. Unit tested. |
| 8 | Control task agent keys `company:<id>` are translated to the company agent's key before instances are built, so assigned company agents appear on their missions. |
| 9 | "Approved, but AXoR couldn't go further" needs the decision to be "approve". It also needs the same mode generation, live mode, a successful reload, and the task to exist and no longer be proposed or cancelled. Otherwise the message is "Not done". |
