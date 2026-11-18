# GPT code review #2 (codex exec, read-only, isolated folder: 14 flattened files from the agent-built pages, store and theme provider)

Prompt:
```
You are the GPT reviewer for AXoR. This folder has flattened copies of React/TS pages built by parallel agents (Knowledge sources, Governance self-renewal and model loader, Versions merge requests, preview and releases, Evolution promotion queue, Appearance, Settings, Agent profile, Organization) plus the shared store and theme provider, which were already fixed after your first review.

Review for real defects only, ranked by severity:
- broken governance logic (anything that lets an unverified candidate be promoted, a merge happen without the gate, self-renewal changed by a non-admin, or stop controls bypass their confirmation);
- correctness and React bugs (stale state, leaks, timers not cleared, keys);
- XSS or unsafe URL handling (javascript: links, window.open of user input);
- accessibility of interactive controls;
- honesty problems (UI claiming something live or done that is only sample/local).

For each finding give: file, snippet, why, and the fix. Max 20. End with a one-line verdict.
```

Answer:

1. **P1 — Promotion does not enforce all gates.** `data_store.ts:265`
   
   Snippet: `if (action === "promote" && c.status !== "passed") return;`
   
   **Why:** The mutation checks only status. It accepts a passed candidate without permission approval, security clearance, or a rollback point. An isolated fixture promoted a high-risk candidate with no version records.
   
   **Fix:** Enforce every promotion gate atomically in the shared action and server, using recorded approvals rather than component-local state.

2. **P1 — Simulated evaluation can verify live candidates.** `data_store.ts:276`
   
   Snippet: `status: x.delta > 5 ? "passed" : "failed"`
   
   **Why:** A timer manufactures verification from estimated improvement, including when `sources.candidates === "live"`. That fabricated status unlocks promotion. Reproduced with a live candidate.
   
   **Fix:** Restrict simulation to explicit sample data. Live verdicts must come from independent evaluation results.

3. **P1 — Merge confirmation bypasses current gates.** `pages_versions_MergeRequests.tsx:60`
   
   Snippet: `setMerged({ ...merged, [pr.id]: true })`
   
   **Why:** Confirmation never rechecks `can`. If checks fail while the modal is open, confirmation still marks the PR merged. Because `ask` stores only a boolean, changed props can also make confirmation operate on a different PR.
   
   **Fix:** Store the requested PR ID and revision; revalidate its current gates inside confirmation and reject changed or blocked requests.

4. **P1 — Pending identity grants admin access; confirmation does not reauthorize.** `pages_governance_renewal.tsx:14,66`; `pages_settings_tabs.tsx:185,206`; `data_store.ts:279`
   
   Snippets: `sampleMode = !me`, `admin = !me || me.role === "admin"`, `setSettings({ selfRenewal: !!ask })`
   
   **Why:** `me` starts null during bootstrap, so a member can open confirmation before identity loads and confirm afterward. The shared mutation has no role check. Server rejection may protect persistence, but the client still changes governance state and reports success.
   
   **Fix:** Distinguish explicit sample mode from authentication loading, fail closed while loading, and check the current role in both confirmation and the mutation.

5. **P1 — Releasing a stop bypasses confirmation.** `pages_governance_renewal.tsx:61`
   
   Snippet: `onClick={() => { setActive({ ...active, [st.id]: false }); ... }}`
   
   **Why:** Activation requires confirmation; Release immediately removes the stop, despite the stated confirmation policy. Releasing a kill/freeze control permits work to resume.
   
   **Fix:** Confirm releases through the same action flow as activations, identifying the control and requested transition.

6. **P1 — News links accept unsafe schemes.** `pages_knowledge_Tabs.tsx:100`
   
   Snippet: `window.open(n.url, "_blank", "noopener,noreferrer")`
   
   **Why:** External article URLs reach `window.open` without protocol validation. Checking only for `"#"` permits `javascript:`, `data:`, and other unwanted schemes. `noopener` does not validate the destination.
   
   **Fix:** Parse the URL and allow only `http:` and `https:` before opening it.

7. **P2 — Rolling back an older promotion creates inconsistent baselines.** `data_store.ts:270–272`
   
   Snippets: `a.baseline === c.to` versus `v.version === c.from ? "baseline" : v.status`
   
   **Why:** The agent update checks that the candidate is still current; version updates do not. After a newer promotion, rolling back the older candidate leaves the agent unchanged but creates a second baseline version. Reproduced.
   
   **Fix:** Reject obsolete rollbacks or apply an explicit current-baseline transition atomically across candidates, agents, and versions.

8. **P2 — Failed requests overwrite newer successful edits.** `data_store.ts:250,285`
   
   Snippets: `x.id === id ? before : x`, `before[k as keyof Settings]`
   
   **Why:** Rollbacks restore stale snapshots without checking subsequent edits. Reproduced: a newer provider/cadence save succeeded, then an older failure restored the original value.
   
   **Fix:** Serialize conflicting mutations or use revision-aware rollback and reconcile with authoritative server state. Avoid restoring whole source rows for individual field failures.

9. **P2 — Mission-scoped sources lose their mission association.** `data_store.ts:225`
   
   Snippet: `{ ..., scope: src.scope, topics: src.topics, ... }`
   
   **Why:** `src.missionId` is validated and sent to the server but omitted from the local source record. Sample records permanently lose the selected mission; optimistic records also lack it.
   
   **Fix:** Preserve `missionId` in the source type and record, and enforce that association wherever sources are consumed.

10. **P2 — A pending sample fetch re-enables disabled sources.** `data_store.ts:237`
    
    Snippet: `x.id === id ? { ...x, status: "ok", lastFetched: nowIso() } : x`
    
    **Why:** Disable a newly added source before its 2.2-second timer fires, and the timer changes it back to enabled/OK. Reproduced.
    
    **Fix:** Cancel the pending fetch on disable or require the matching pending operation and enabled state before applying completion.

11. **P2 — Live trust edits are never persisted.** `pages_knowledge_Tabs.tsx:140`; `data_store.ts:248`
    
    Snippets: `updateNewsSource(s.id, { trust: +e.target.value })`; request body includes only `name`, `cadence`, and `enabled`.
    
    **Why:** The slider changes trust locally while sending `{}` to the server. It appears accepted but disappears on reload.
    
    **Fix:** Persist trust through a supported API field, or disable and clearly label the control for live sources.

12. **P2 — “Fetch now” fabricates live fetch success.** `pages_knowledge_Tabs.tsx:147`; `data_store.ts:248`
    
    Snippet: `updateNewsSource(s.id, { status: "ok", lastFetched: new Date().toISOString() })`
    
    **Why:** This runs for live sources too. It invents a successful fetch and timestamp; the actual request only patches `enabled: true`. The sample toast does not isolate the operation from live configuration.
    
    **Fix:** Use a real fetch endpoint and its result for live sources; keep simulation confined to sample records.

13. **P2 — Server refusals still produce success notifications.** `pages_governance_renewal.tsx:18`; `pages_knowledge_Tabs.tsx:120`; `data_store.ts:233–235,285`
    
    Snippet: `setSettings({ selfRenewal: v }); toast(...)`
    
    **Why:** Actions return before their requests finish. Failures roll back and populate `errors`, but none of these supplied pages renders those errors. Users receive success messages for rejected changes.
    
    **Fix:** Return asynchronous results, show pending state, and emit success only after acceptance. Surface rejection details visibly.

14. **P2 — Model configuration edits claim completion but remain local.** `data_store.ts:287`; `pages_governance_loader.tsx:39,57`
    
    Snippet: `export function updateModel(...) { set(...) }`
    
    **Why:** Enablement, fallback, and role changes never reach a server, even for live model records. The loader reports “enabled,” “disabled,” and “updated” without identifying these as local simulations.
    
    **Fix:** Persist supported live changes and reconcile responses; otherwise label the editor as a local simulation and prevent it from appearing to configure live routing.

15. **P2 — Appearance bypasses the last-model confirmation.** `pages_appearance_ThemeTab.tsx:154`
    
    Snippet: `ms.forEach((m) => updateModel(m.id, { enabled: v }))`
    
    **Why:** Governance checks for roles losing their last enabled model before disabling. The provider toggle disables every model directly, removing role coverage without that confirmation.
    
    **Fix:** Centralize coverage checking and confirmation for individual and batch model changes.

16. **P2 — Merge-request selection is inaccessible by keyboard.** `pages_versions_MergeRequests.tsx:30`
    
    Snippet: `<motion.tr ... onClick={() => setSel(p.id)}>`
    
    **Why:** Rows are the selection mechanism but have no focusable control or keyboard handler. Keyboard users cannot select another PR to inspect or approve.
    
    **Fix:** Put a native selection button in each row, with an accessible name and selection state.

17. **P2 — Quiet-hours times are discarded.** `pages_settings_tabs.tsx:123,137–139`
    
    Snippets: `useState({ from: "22:00", to: "07:00" })`; `setSettings({ quietHours: v })`
    
    **Why:** Only enablement is saved. The displayed From/To controls update component state and reset on remount, so the apparent configured schedule is never applied.
    
    **Fix:** Store and hydrate both times with the quiet-hours setting, or explicitly present the time controls as non-operative samples.

18. **P2 — Audit rollback marks the restored version as rolled back.** `pages_agents_Profile.tsx:225,242–243`
    
    Snippet: `setRolled((r) => ({ ...r, [ask!]: true }))`
    
    **Why:** “Roll back to v1” labels v1 `rolled_back`, leaves the existing baseline intact, and adds no audit event. Even as a local simulation, this contradicts the modal’s promised baseline and audit changes.
    
    **Fix:** Simulate the coherent shared transition: make the target baseline, update the departed version appropriately, and append a local audit event.

19. **P3 — Appearance can claim device persistence after storage fails.** `theme_ThemeContext.tsx:73,77–78`; `pages_appearance_tabs.tsx:29`
    
    Snippets: `catch { /* private mode */ }`; `setSaved("local")`
    
    **Why:** If localStorage fails and server saving also fails, the UI still says “Saved on this device,” although the change exists only in memory.
    
    **Fix:** Track successful persistence separately and use the existing `error` state when neither destination saved the change.

Verdict: Changes required—governance bypasses, unsafe URL handling, and confirmed state-consistency defects remain.
## Resolution (Claude Code)

All 19 findings fixed. Promotion gates (verified, no security regression, rollback point, permission approval for non-low risk, admin) are enforced in `candidateAction` itself via `promotionBlockers`; the simulated verdict runs only for sample candidates; merge confirmation re-checks the gates of the PR it was opened for; identity fails closed while loading (`isAdmin`, `isSampleMode`, `identityLoading`), and a 401/403 is not sample mode; stop releases are confirmed; article links open only for http(s); obsolete rollbacks are refused; optimistic rollbacks restore only untouched fields; mission-scoped sources keep their mission; a disabled pending source is not re-enabled; live trust and fetch results can't be set from the UI; refusals surface through a global error toaster and actions return errors instead of success toasts; model edits are labelled local and provider toggles check role coverage; merge rows are keyboard-selectable; quiet-hours times are stored in settings; agent rollback is a coherent store transition with an audit event; Appearance shows 'Not saved' when neither storage worked.

Found while verifying (not in the review): the page transition rendered the new page inside the exiting wrapper and then mounted it again, dropping clicks made during the 0.22 s transition; fixed in Shell.tsx (enter-only transition).
