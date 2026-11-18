# GPT code review #5: confirmation pass on the review #4 fixes

Reviewer: GPT via `codex exec -s read-only --ephemeral` in an empty folder holding only the fix diff (6932970..45e8679), its own review #4 findings and the backend endpoint excerpts.

## Findings (verbatim)

| # | Status | Evidence from `fixes.diff` |
|---|---|---|
| 1 | **FIXED** | `hub.ts`: `const ok = option === "approve"`; `"changes"` explicitly returns a refusal before sending. |
| 2 | **FIXED** | `store.ts`: `switched()` checks both `modeGen` and live mode before every upload and the mission POST. |
| 3 | **FIXED** | `hub.ts`: task actions consult `whereTask(t)`; board retries use `/run`, while unsupported board/mission actions refuse. |
| 4 | **FIXED** | `store.ts`: CT decisions now use the corresponding task’s lock: `` `task:C-${a.id.slice(3)}` ``. |
| 5 | **PARTIAL** | `store.ts`: `await loadLive(); inFlight.delete(key)` waits for refresh, but still unlocks without verifying refresh succeeded; retain a refresh-required block after failure. |
| 6 | **FIXED** | `AddMission.tsx`: `if (busy) { toast(...); return; }` prevents closing and resetting the pending draft. |
| 7 | **FIXED** | `Tabs.tsx` explicitly describes “AXoR’s company chat, with the mission named at the top”; `hub.ts` adds that prefix—the permitted general-chat fallback. |
| 8 | **FIXED** | `live.ts`: `ctl.tasks = remapCompanyKeys(ctl.tasks, company.agents)` runs before constructing instances and counting their tasks. |
| 9 | **FIXED** | `store.ts`: partial approval requires unchanged mode generation, live/OK state, `option === "approve"`, an existing task, and neither awaiting-approval nor cancelled status. |

One confirmed new defect:

- **[P2] Mission chat silently removes the end of accepted instructions.**  
  **File:** `frontend/react/src/v3/data/hub.ts:134`  
  **Snippet:** `const body = (ctx + t).slice(0, 8000);`  
  **Why:** Validation accepts an 8,000-character user message before adding context. The prefix then displaces the message’s ending. Reproduced with a valid message ending `DO NOT PUBLISH`: that instruction disappeared from the request, while the plan still reported `Sent to Ada`.  
  **Fix:** Validate the combined length and refuse overlong messages with the available limit, or shorten only the generated context. Preserve the user’s entire instruction.

**Verdict: Request changes—finish the refresh-failure guard and remove silent chat truncation.**

## Resolution

| Item | Fix |
|---|---|
| #5 partial (refresh failure) | If the reload after a write fails, the target goes into `needsRefresh`. Further writes to it are refused, and a reload is started, until a reload succeeds. A successful reload clears the set. |
| New: chat truncation | User text is capped at 7,600 characters and refused above that, never cut. Only the generated `[Mission …]` context is shortened to fit 8,000. Unit tested with a message ending "DO NOT PUBLISH". |

Verified: `node --test` (20 pass), `ui-v3-live-writes.mjs`, `ui-v3-live.mjs` and `ui-v3-live-crawl.mjs`.
