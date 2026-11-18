# GPT code review #3 (codex exec, read-only, isolated folder: live.ts, store.ts, App.tsx, Shell.tsx, ui_v3.py and tests)

Prompt:
```
You are the GPT reviewer for AXoR. New since your review #2 (flattened copies here):
- live.ts maps GET /api/control/missions and GET /api/company to UI types.
- store.ts adds live/sample data modes and refuses un-wired writes in live mode. Note that AXoR's CSRF guard requires the header X-Requested-With: scout on writes.
- App.tsx adds a page error boundary and an error toaster.
- Shell.tsx adds the Live/Sample switch and a health pill from /api/health.
- ui_v3.py now also persists autonomy, verification provider and quiet hours. Notifications and quiet hours are per user; the rest is organisation-wide.

Review for real defects only, ranked by severity: authorization/privacy (per-user vs org data leaks, admin gates), correctness of the live mapping (wrong status semantics, crashes on real payloads), honesty (UI claiming live/done when not), races between bootstrap/loadLive/setDataMode, and anything that would break when signed in on the real server. Give file, snippet, why, and fix. Max 15. One-line verdict at the end.
```

Answer:

1. **P1 — “Design sample” still writes real configuration.** `store.ts:80–85,385`
   
   **Snippet:** `return { ...src, dataMode: mode, sources: { ...s.sources, ... } }`
   
   **Why:** Switching to Sample replaces only six resources. Settings and news sources remain live, so experimenting with autonomy, self-renewal, or sources still persists real changes. Reproduced a settings PUT while `dataMode === "sample"`.
   
   **Fix:** Make Sample isolate all editable resources, or explicitly identify and confirm live configuration changes within that mode.

2. **P2 — Legacy notification preferences still cross user boundaries.** `ui_v3.py:124–136,263–267`
   
   **Snippet:** `d = {**d, **{k: p[k] for k in PERSONAL if k in p}}`
   
   **Why:** Personal overrides are layered over organization settings without first removing personal fields. Existing `ui_settings.notifications` values therefore become another user’s preferences when their personal record is absent. Organization writes preserve those legacy fields.
   
   **Fix:** Exclude `PERSONAL` fields from organization reads and storage. Start personal settings from defaults; migrate legacy values only when ownership is known.

3. **P2 — Finished missions appear running; every mission appears in development.** `live.ts:17–19,53`
   
   **Snippets:** `...[s] ?? "running"`; `stage: "develop"`
   
   **Why:** The real mission engine finishes with `status="delivered"`, which falls through to running. It also supplies stages such as `understand`, `plan`, `verify`, and `learn`; these are discarded. Reproduced a delivered mission appearing running, developing, and 0% complete.
   
   **Fix:** Explicitly translate the server lifecycle, preserving terminal outcome and verification distinctions. Represent unavailable stages/progress as unknown.

4. **P2 — Real agent IDs crash the agent graph.** `live.ts:72`; existing `pages/agents/Graph.tsx:32–33`
   
   **Snippets:** `id: str(a.key || a.id)` versus `agents.find((x) => x.id === "GM")!`
   
   **Why:** The actual company roster uses keys such as `ceo`. After live replacement, the graph dereferences `gm.id` on `undefined`. The error boundary merely offers sample data.
   
   **Fix:** Build the graph from actual identities and reporting relationships; remove hardcoded sample IDs and handle missing roots.

5. **P2 — A legitimate empty account crashes Mission Control.** `store.ts:75`; existing `pages/MissionControl.tsx:19`
   
   **Snippet:** `... ? route.param : missions[0].id`
   
   **Why:** A signed-in account with no missions correctly maps to `[]`. Loading that result makes Mission Control throw instead of showing an empty state; the boundary incorrectly describes this as unconnected data.
   
   **Fix:** Handle an empty mission collection before selecting or rendering a mission.

6. **P2 — Approval links cannot reach their records.** `live.ts:55,82`
   
   **Snippet:** `missionId: a.project_id ? \`project:${str(a.project_id)}\` : "company"`
   
   **Why:** Mapped missions use `comp:*` and `mx:*`; no mission matches these approval IDs. Existing approval links open Mission Control, which selects another mission and filters the approval away. Meanwhile, proposed control tasks increment mission decision counts without becoming approval records.
   
   **Fix:** Keep company/project approvals and control-task proposals distinct, with valid inboxes and routes. Link unsupported actions to their classic pages.

7. **P2 — Token budgets are displayed as dollars, with invented zero spending.** `live.ts:58`
   
   **Snippet:** `budget: { limit: num(m.budget), spent: num(m.spent) }`
   
   **Why:** Predefined missions expose a daily **token** budget and `used_today`; custom missions use monetary budgets. The shared UI renders `$spent / $limit`. Predefined missions consequently show token amounts as dollars and spending as zero.
   
   **Fix:** Preserve budget unit and accounting period, map the corresponding usage, and render unavailable monetary values explicitly.

8. **P2 — Live loading failures silently enable simulated operations.** `live.ts:102`; `store.ts:74,90–91,115`
   
   **Snippets:** `catch { return null; }`; `if (getState().sources[key] !== "live") return null`
   
   **Why:** After identity succeeds, either hub failing leaves sample resources active without recording a live error. During loading—and indefinitely after failure—mission creation and messaging can report simulated success because their guards inspect resource provenance.
   
   **Fix:** Track loading/error/explicit-sample states separately. Require explicit sample selection before simulations; otherwise reject unsupported actions and surface the load failure.

9. **P2 — A delayed load overrides an explicit Sample selection.** `store.ts:72–77`
   
   **Snippet:** `setDataMode("live");`
   
   **Why:** Every successful request forces Live mode. With overlapping loads, switching to Sample after the first completes is undone when the second completes. Reproduced; older responses can also replace newer snapshots.
   
   **Fix:** Use request generations and a separate user-selected mode. Apply only current responses without overriding a subsequent selection.

10. **P2 — Mission sources reject every real mission reference.** `ui_v3.py:283`
    
    **Snippet:** `re.match(r"^[A-Za-z0-9_\-]{1,40}$", body.missionId)`
    
    **Why:** Both actual reference formats, `comp:7` and `mx:3`, contain a colon and receive HTTP 422. The test covers only the obsolete sample format `M-001`.
    
    **Fix:** Validate supported mission-reference formats and verify that the referenced mission belongs to the requesting user.

11. **P2 — Paused and archived agents appear active.** `live.ts:75`
    
    **Snippet:** `... === "disabled" ? "offline" : "active"`
    
    **Why:** The server supports `paused` and `archived`, but both fall through to active. Real workload is exposed through `load`, so checking only `busy`/`working` also misses working agents.
    
    **Fix:** Translate actual status values and load explicitly; preserve paused/archived distinctions.

12. **P2 — Local activity contaminates the “live audit” resource.** `store.ts:56–58,383`
    
    **Snippet:** `events: [{ ...e, id, at: nowIso(), ... }, ...s.events]`
    
    **Why:** Once events are live, settings and source actions still prepend browser-generated events to that same collection. A subsequently rejected request leaves its local event present, while `sources.events` continues claiming live provenance.
    
    **Fix:** Separate local activity from server audit records. Reconcile persisted actions with authoritative audit results.

13. **P2 — Task update/completion timestamps become fake deadlines.** `live.ts:39`
    
    **Snippet:** `end: iso(t.done_at || t.updated)`
    
    **Why:** Existing consumers label `Task.end` as “Due” and use it in scheduling views. An open task’s last update therefore becomes its deadline; completed tasks use completion time as deadline. The API’s actual recurrence field, `due`, is ignored.
    
    **Fix:** Model deadline, completion, and last-update times separately. Render missing deadlines as unscheduled.

14. **P2 — Switching modes loses sample edits.** `store.ts:83–84`
    
    **Snippet:** `if (!sampleSnap) sampleSnap = ...`
    
    **Why:** The sample snapshot is captured once. After editing sample data, switching Live → Sample restores that original snapshot and discards subsequent edits. Reproduced a paused sample task reverting to queued.
    
    **Fix:** Save the outgoing mode’s current resources before switching, or maintain independent mutable state for each mode.

The store writes include the required `X-Requested-With: scout` header. Reproductions used in-memory mapper/store harnesses and the extracted settings loader; the full application suite was not run.

Verdict: Changes required—Sample mode can alter real configuration, and live lifecycle, routing, and loading behavior remain incorrect.
## Resolution (Claude Code)

- #4 and #5 were already fixed before this review in files it didn't receive (Graph.tsx builds the hierarchy from the data; Mission Control and Overview have empty states). Both are verified by the live crawl.
- #1, #9, #14: settings and news sources swap with the data mode, so Sample never writes real configuration (a live check asserts that no PUT is sent). A later load can't override the user's choice (generation counter + explicit choice). Switching modes saves the outgoing mode's edits.
- #8: liveStatus is loading, ok or error. Un-wired writes are refused while loading, and a failed load is shown.
- #12: local UI actions don't go into the live audit list.
- #3, #7, #11, #13: delivered and other lifecycle states, real stages, token budgets kept apart from money, paused/archived/load agent states, and tasks without a deadline shown as 'Not scheduled' (tests added).
- #6: proposed Control tasks become approvals on their own mission. Approvals without a matching mission link to Notifications → Pending.
- #2: personal fields never come from the organisation record, and the organisation record no longer stores them (test added).
- #10: mission refs comp:<id> and mx:<id> are accepted (test added). Ownership of the ref is not checked by this router; this is documented.
