# GPT code review #1 (codex exec, read-only, isolated folder with flattened copies of 10 files)

Prompt:
```
You are the GPT reviewer for AXoR (Claude Code writes the code, you review it). The files in this folder are flattened copies of the new UI v3 code: a React/TS front end (store, component kit, theme engine, router, shell, Mission Control tabs, Add Mission modal) and a FastAPI router (ui_v3.py) with its tests.

Review for real defects only, ranked by severity:
- correctness bugs (state, race conditions, React hooks misuse, stale closures, memory leaks such as object URLs never revoked or timers not cleared);
- security (XSS, SSRF gaps in check_source_url, authorization gaps in ui_v3.py, anything that could leak secrets);
- accessibility (focus management, keyboard traps, ARIA misuse);
- UX logic errors (e.g. decisions double-submittable, idempotency).

For each finding give: file, the line or snippet, why it is wrong, and a concrete fix. Skip style nits. If something is fine, don't mention it. Max 25 findings. End with a one-line verdict.
```

Answer:

1. **P1 — Concurrent requests can overwrite committed changes.** [backend_app_ui_v3.py][backend], lines 190–205, 224–229, 243–257. Settings and sources use separate reads and whole-value writes. Concurrent additions can lose a source; a PATCH can resurrect a deleted source; a notification update can restore stale administrator settings. **Fix:** perform each read/modify/write atomically in a database transaction, with uniqueness enforced inside it.

2. **P1 — Responses carry over to a different decision.** [frontend_react_src_v3_pages_control_Tabs.tsx][tabs], lines 87, 99–111, 262. `DecisionForm` retains its option, text, images, and confirmation state when `a.id` changes. The key on its inner `motion.div` does not reset component hooks. Confirming the next decision can submit the previous decision’s option and response. **Fix:** render `<DecisionForm key={cur.id} ... />` at both call sites and validate the option against the current approval.

3. **P1 — Editing a modal repeatedly resets keyboard focus.** [frontend_react_src_v3_ui_kit.tsx][kit], lines 343–357. The focus effect depends on `onClose`, while Add Mission recreates `close` on every edit. Each keystroke therefore restores old focus and schedules another initial-focus operation, pulling focus out of the field being edited. **Fix:** run focus setup and restoration on open/close transitions; access the latest callback through a ref.

4. **P2 — Alternate loopback addresses bypass URL validation.** [backend_app_ui_v3.py][backend], lines 80–88. `http://127.1/`, `http://2130706433/`, and `http://0x7f000001/` pass because `ipaddress.ip_address()` rejects their spelling, although standard IPv4 parsing resolves them to `127.0.0.1`. This is a validation gap; this router itself does not fetch URLs. **Fix:** reject ambiguous numeric hosts or canonicalize them before checking, and retain resolved-address checks in the fetcher.

5. **P2 — Non-finite font scales crash the sanitizer.** [backend_app_ui_v3.py][backend], lines 61–64. Infinity passes `fs == fs`, then `round(fs)` raises an uncaught `OverflowError`. A numeric JSON value such as `1e309` can reach this path. **Fix:** require `math.isfinite(fs)` and catch `OverflowError`, retaining the default for invalid values.

6. **P2 — The frontend cannot register mission-scoped sources.** [frontend_react_src_v3_data_store.ts][store], lines 208–218. `addNewsSource` has no `missionId` field, but the backend requires it for mission scope. Such requests always fail with 422; members also cannot use organization scope. **Fix:** require and transmit `missionId` for mission-scoped additions, and preserve it in the optimistic row.

7. **P2 — Failed settings writes appear successful.** [frontend_react_src_v3_data_store.ts][store], lines 255–258. Settings change immediately, an audit event is recorded, and every server error is swallowed. A denied or failed self-renewal change therefore remains displayed as applied. **Fix:** reconcile successful responses and expose failures, rolling back the affected optimistic change.

8. **P2 — Rejected source edits and deletions remain applied locally.** [frontend_react_src_v3_data_store.ts][store], lines 230–239. PATCH and DELETE failures only populate `errors`; they never restore the source or its previous values. A 403 can leave a source apparently deleted or disabled until reload. **Fix:** commit after success or implement rollback that preserves any newer changes.

9. **P2 — Actions against a newly added source use its temporary ID.** [frontend_react_src_v3_data_store.ts][store], lines 213–221, 230–239. Before POST completes, editing or deleting the optimistic row sends its browser-generated ID, which the server does not recognize. Deleting it locally also prevents the POST response from replacing it, leaving a persisted source hidden from the UI. **Fix:** disable mutations until creation completes or queue them against the returned server ID.

10. **P2 — Theme state updaters perform side effects.** [frontend_react_src_v3_theme_ThemeContext.tsx][theme], lines 73–81. State updater functions call other setters, write storage, and issue PUT requests. React may replay these functions, including twice under Strict Mode, causing duplicate saves and history entries. **Fix:** keep state transitions pure, preferably in a reducer, and persist committed revisions from an effect.

11. **P2 — Theme requests can overwrite newer choices.** [frontend_react_src_v3_theme_ThemeContext.tsx][theme], lines 55–70. A late initial GET replaces edits made while it was pending. Subsequent PUTs also run concurrently, allowing an older choice to finish last and become the stored preference. **Fix:** discard stale initial responses after local edits and serialize or revision-check saves.

12. **P2 — Website references disappear when a mission starts.** [frontend_react_src_v3_pages_AddMission.tsx][add], lines 26, 48–49. Non-GitHub URLs appear in Resources and Review, but only `ghUrls` reach `addMission`. The resulting mission loses every ordinary reference link. **Fix:** add a web-reference field to the mission input model and pass `webUrls` through.

13. **P2 — The selected autonomy policy is discarded.** [frontend_react_src_v3_data_store.ts][store], lines 84, 102–110. `NewMission.autonomy` is accepted and displayed during review, but never stored on the mission or its policy. L2 and L4 selections produce identical state. **Fix:** persist the selected policy and use it when determining permitted mission actions.

14. **P2 — An oversized due date poisons the draft’s idempotency key.** [frontend_react_src_v3_pages_AddMission.tsx][add], line 42; [frontend_react_src_v3_data_store.ts][store], lines 97–105. Validation accepts any positive day count. A sufficiently large value throws in `toISOString()` after `startKeys.add()`. Retrying the corrected draft then returns an unrelated mission ID instead of creating it. **Fix:** validate finite, bounded inputs before reserving the key, and release the reservation on failure.

15. **P2 — Delayed mission navigation survives closing the modal.** [frontend_react_src_v3_pages_AddMission.tsx][add], lines 31–32, 51. The 500 ms timeout is never cancelled, and closing while busy is allowed. Closing and reopening can let the old callback erase the new draft and navigate unexpectedly. **Fix:** remove the artificial delay or cancel the timer on close/unmount and associate it with the submitted draft.

16. **P2 — Repository decisions do not update repository state.** [frontend_react_src_v3_data_store.ts][store], lines 108, 125–130, 138–147. A proposed repository starts with `created: true`, and selecting “Continue without repository” only records an approval response. The mission still retains that repository. **Fix:** represent proposed repositories as pending and apply the selected outcome, clearing the repository for `none`.

17. **P2 — Candidate rollback leaves the promoted version active.** [frontend_react_src_v3_data_store.ts][store], lines 245–249. Rollback changes only candidate status. The agent baseline remains the promoted version, and version records still mark it as baseline. **Fix:** restore the previous baseline and corresponding version statuses atomically.

18. **P2 — Evaluation completion can undo rejection.** [frontend_react_src_v3_data_store.ts][store], line 252. The timeout unconditionally sets `passed` or `failed`. Rejecting a candidate while evaluation is pending is overwritten when that timer fires. **Fix:** cancel superseded evaluations or require a matching evaluation generation and current `evaluating` status before applying the result.

19. **P2 — “Message agent” cannot create the first user conversation.** [frontend_react_src_v3_pages_control_Tabs.tsx][tabs], lines 178–180, 199. Without an existing user thread, the button selects `"__new"`, but selection immediately falls back to `mine[0]`, the agent-to-agent thread. The composer remains unavailable. **Fix:** handle the new-conversation sentinel explicitly by rendering a composer with `threadId={null}`.

20. **P2 — Decision image previews leak object URLs.** [frontend_react_src_v3_pages_control_Tabs.tsx][tabs], lines 127–129. Every attachment creates a blob URL, but removing images, resolving the decision, and unmounting never revoke it. Large images remain retained for the document’s lifetime. **Fix:** revoke removed URLs immediately and all remaining URLs during cleanup.

21. **P2 — Dialogs without body controls leave focus outside.** [frontend_react_src_v3_ui_kit.tsx][kit], lines 346–352. Initial focus excludes the close button and has no fallback. Help & keyboard therefore opens without moving focus inside. The Tab handler only wraps from known endpoints, so it does not recover focus already outside. **Fix:** focus the first visible enabled control, including Close, or the dialog container; also recover escaped focus.

22. **P2 — Table selections are mouse-only.** [frontend_react_src_v3_pages_control_Tabs.tsx][tabs], lines 299–301, 329. Activity events and report agents are selected exclusively through `<tr onClick>`. Keyboard users cannot open other traces or select another agent’s report. **Fix:** provide a focusable selection button in a cell, with an accessible name and selected state.

23. **P2 — Malformed route encoding throws during rendering.** [frontend_react_src_v3_app_router.ts][router], line 9. A route such as `#/control/%` makes `decodeURIComponent()` throw. Because `parse()` initializes routing hooks, a malformed link can prevent the UI from rendering. **Fix:** catch decoding failures and return a safe invalid-route result.

24. **P2 — New repository approvals are missing from the pending count.** [frontend_react_src_v3_data_store.ts][store], lines 104, 125–131. `decisionsPending: n.createRepo ? 0 : 0` always reports zero, even when creation adds a pending repository approval. Mission summaries consequently hide the outstanding decision. **Fix:** derive the count from the approvals actually created.

Validation used isolated Python and Node probes. The complete test suite could not run because the flattened workspace lacks FastAPI and the full frontend project.

**Verdict: Changes required before release; decision state, modal focus, and concurrent backend writes are the highest-priority fixes.**

