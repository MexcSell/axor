# Image specs, group G1 (0-1..0-8, 1..12)

Source dir: /home/thomas/subnet-scout/docs/update_2026-11-15/
Duplicate check (md5): 1.png == 2.png (identical bytes, also == a_wide_high_resolution_ui_concept_poster_with_man.png). 6.png == 01_task_flow_flat_light.png, 7.png == 02_agent_lifecycle_luminous_dark.png, 8.png == 03_branch_graph_pretty_pastel.png, 9.png == 04_appearance_studio_fancy_dark.png. All others unique.
Caveat: 1.png and 12.png are AI-generated posters; text in small thumbnails is blurry, partly garbled; values below are best-effort transcriptions (marked "~" when uncertain).

Shared product vocabulary: product "AXoR" (logo wordmark with a stylised "A" mark; the "o" is lowercase: "AXoR"), subtitle "Autonomous Company OS". Left nav items: Overview, Missions, Mission Control, Versions, Organization, Knowledge, Evolution Lab, Finance, Governance, Appearance. Header icon trio on the right of title: "?" help, circle/half-circle (theme/appearance toggle), gear (settings). Four appearance presets: Flat (light, blue), Luminous (dark, cyan), Elegant/Pretty (light, soft rose/violet), Fancy (dark, violet/purple).

---

## 0-1.png
1. Concept diagram "AXoR organizational architecture". Dark page (#0F0F0F) with rounded-rect card border (#2A2A2A, ~12px radius), flat vector diagram with light-blue boxes. 785x678.
2. Layout: centred tree. Top: one blue box "AXoR CORE" (x 36-65%, y 6-19%). Horizontal bus line at y~24% spanning x 20%-81% with 3 vertical drops. Row 1 (y 29-46%): three light boxes. Row 2 (y 52-70%): three boxes, each directly under row 1 and connected by a short vertical line. From row-2 bottoms, 3 vertical lines down to a horizontal bus (y~75%, x 20%-81%), then a single line to bottom green box (x 21-80%, y 78-89%). Caption centered at y~96%.
3. Text exact:
   - Top box: "AXoR CORE" (white bold, on #2556A8 blue, radius ~20px)
   - Row 1: "MISSION INTELLIGENCE" | "AUTONOMOUS WORKFORCE" | "KNOWLEDGE & MEMORY" (two lines each, uppercase, centered, dark-navy #1E2F52 bold on #E8F0F9 fill, 2px border #8FA8CE)
   - Row 2: "SELF-EVOLUTION" (breaks "SELF-" / "EVOLUTION") | "GOVERNANCE & TRUST" | "ECONOMIC INTELLIGENCE"
   - Bottom: "CONTINUOUS VALUE CREATION" (dark green #1F5C3A text on #E1F3E6 fill, border #8DB997)
   - Caption (small, #D8D8D8, centered): "Proposed AXoR organizational architecture. All six systems operate under one company-wide control plane."
4. Icons: none. Connectors: orthogonal lines 3px #6F90BD.
5. Palette: bg #0F0F0F; card border #2A2A2A; core #2556A8; boxes #E8F0F9/#8FA8CE; text navy #1E2F52; value box #E1F3E6; line #6F90BD.
6. Typography: humanist sans (Segoe/Noto-like), bold ~20px uppercase in boxes, no glow/shadow, flat.
7. Requirements: static architecture diagram (can be SVG/HTML); six systems all branch from CORE and merge into "Continuous value creation".

## 0-2.png
1. Dashboard mock: "AXoR Company OS" overview, Overview tab. Dark minimal (shadcn-like), 783x693.
2. Layout: single card (border #262626, radius ~12px). Header row (y 0-9%): left icon (org-tree/network glyph) + "AXoR" bold + "Company OS" muted; right a green pill. Divider. Tab row at y~14%. Section title. 2x2 KPI grid (y 22-42%). "Mission execution" section with 3 progress rows (y 45-68%). Bordered "Executive decisions" card (y 70-93%). Footer caption.
3. Text exact:
   - Pill (green text #22C55E on dark green #0F2A1A, with circle-check icon): "System healthy"
   - Tabs: "Overview" (active, filled dark-grey chip #262626, white bold), "Missions", "Organization", "Evolution", "Finance"
   - "Company overview" (bold)
   - KPIs: "12" / "Active missions"; "38" / "Active agents"; "3" (orange #EA580C) / "Pending decisions"; "96.4%" (green #22C55E) / "Quality pass rate"
   - "Mission execution" (bold, larger) with right muted "Illustrative data"
   - Rows: "AXoR Platform Upgrade" 76%; "Agent Evaluation Framework" 52%; "Research Knowledge Engine" 91% - progress bars 6px tall, blue fill #2F7FD6 on track #2A2A2A, percentage right aligned
   - Card "Executive decisions", right badge "3 pending" (grey pill #262626). Rows (title bold white, sub muted, chevron ">" right):
     - "Approve agent architecture upgrade" / "Evaluation passed · Release approval required" (icon: git-branch/merge)
     - "Review additional compute budget" / "Proposed increase · Awaiting owner decision" (icon: wallet)
   - Caption: "Conceptual dashboard layout, using hypothetical values rather than actual AXoR metrics."
4. Icons: org-tree (logo), check-circle, git-merge, wallet, chevron-right.
5. Palette: bg #0D0D0D; text #F5F5F5; muted #A3A3A3; border #262626; blue #2F7FD6; green #22C55E; orange #EA580C.
6. Typography: Inter-like sans, 11-12px labels, 24px KPI numbers semi-bold; no glow; subtle 1px borders.
7. Requirements: tabs switch Overview/Missions/Organization/Evolution/Finance; KPIs; per-mission progress bars; clickable decision rows; health pill; "illustrative data" label when data is mock.

## 0-3.png
1. Vertical flowchart "Self-evolution process". Dark (#0D0D0D) card, 785x725.
2. Layout: centred vertical stack, down-arrows (small "↓" glyph) between steps; decision node is a bordered wide box (x 8-93%, y 65-82%) split into two coloured halves; last step below.
3. Steps (icon above, bold title, muted subtitle):
   1. magnifier icon - "Detect improvement opportunity" / "Failures, benchmarks, new technology, costs"
   2. lightbulb icon - "Generate improvement proposal" / "Expected benefit, risk, and success criteria"
   3. git-branch icon - "Build in isolated branch / sandbox" / "No impact on production"
   4. shield-check icon - "Independent evaluation" / "Quality, security, regression, performance"
   - Decision box (border #2A2A2A, radius 14px) title "Did the candidate pass all required gates?" Two cells: left "Yes" (green #22C55E title) / "Approve and deploy progressively" on #0E1A14; right "No" (red #F25C5C) / "Reject, learn, and revise" on #1D1414.
   5. chart-trend (bars+line) icon - "Monitor production results" / "Keep or roll back; store verified lessons"
4. Icons: search, lightbulb, git-branch, shield-check, trending-up bars, arrow-down.
5. Palette: bg #0D0D0D; border #262626; text white/#E5E5E5; subtitle #BDBDBD; green #22C55E; red #F25C5C.
6. Typography: sans, titles 15px semibold, subtitles 11px; flat.
7. Requirements: ordered pipeline with gate branching (Yes -> deploy progressively; No -> revise loop); Monitor leads to keep/rollback and verified-lesson storage.

## 0-4.png
1. Accordion list "Roadmap phases". Dark minimal, 782x522.
2. Layout: one rounded card with 4 rows separated by 1px lines (#262626). Row 1 expanded (y 0-51%), rows 2-4 collapsed (~17% each). Right-aligned chevron per row (chevron-up for open, chevron-down for closed).
3. Text exact:
   - "Phase 1 — Reliable autonomous execution" / "Critical priority" (expanded) with check-circle bullets: "Durable mission execution and recovery"; "Company Brain with evidence-backed memory"; "Independent testing and evaluation"; "Fine-grained permissions and approvals"; "Complete execution tracing"
   - "Phase 2 — Intelligent organization" / "High priority"
   - "Phase 3 — Controlled evolution" / "High priority"
   - "Phase 4 — Self-sustaining enterprise" / "Long-term priority"
4. Icons: circle-check (outline) bullets, chevron up/down.
5. Palette: bg #0D0D0D, text #F2F2F2 (title bold 15px), sub #BDBDBD 11px, border #262626.
6. Flat; no gradient.
7. Requirements: expandable accordion (one open at a time or independent), keyboard-accessible; priority label per phase.

## 0-5.png
1. Formula strip, 556x79, black bg, white serif (LaTeX/Times style).
2. Text: "Operating Sustainability Ratio = Recurring Revenue / Recurring Operating Costs" (rendered as a fraction: numerator "Recurring Revenue", fraction bar, denominator "Recurring Operating Costs").
3. Implied: metric = recurring revenue divided by recurring operating costs; show on Finance page; >1 means self-sustaining.
Colors: bg #000, text #FFF. Font: serif, ~20px.

## 0-6.jpg
1. Concept art (photo-like AI render), not a UI: "AI AGENTIC MESH" command-center. Dark teal/cyan neon, ~1024x1024. Glow-heavy sci-fi.
2. Composition: central circular holographic globe/network with floating UI cards and the text "AI AGENTIC MESH" (white/cyan glowing, centered at ~y 49%); round glowing platform table below (y 60-68%); four suited people standing around it holding tablets; curved wall-sized dashboards on left and right (charts, world maps, donuts, tables); vertical cyan light bars as ceiling/wall lines; reflective dark floor with cyan light strips converging; Gemini sparkle watermark bottom-right.
3. Palette: bg #040D14 to #071C2A; neon cyan #3DE0F0/#7FF5FF; panels #0C2E40; white text glow.
4. Use: hero/mood image for landing/login/homepage hero (agentic mesh concept). Not to be reproduced as UI; use as a hero background or inspiration for glow/neon style (Luminous).
7. Requirements: if used, as a background image with dark overlay; glow cyan accent matches "Luminous" preset.

## 0-7.jpg
1. Concept art: futuristic bright white laboratory with a central robot arm inside a holographic cylinder. Light/white + electric blue, ~1024x1024 AI render (DALL-E style).
2. Composition: central holographic glass cylinder with hexagon grid, atom icon, bar-chart hologram panels; humanoid robot with two arms on an octagonal base with blue glowing ring; scientists in white coats at desks with blue-screen monitors in foreground/left/right; second robotic arm in the foreground; shelves of glass cabinets in back.
3. Palette: white/silver #F4F7FA, glass blue #1E90FF/#3AB0FF glow, navy screens #0B3E8A, grey metal.
4. Use: concept art for "Evolution Lab / autonomous workforce" (agents performing experiments); decorative only.
7. Requirements: none functional; use as illustrative hero for Evolution Lab if desired.

## 0-8.jpg
1. Concept art: glowing node-link network "galaxy" (force-directed graph visualisation) on near-black navy, ~1020x786.
2. Composition: spherical cloud of thousands of thin blue-grey edges; bright coloured nodes (pink #F472B6, yellow #F5C518, green #34D399, purple #A78BFA, cyan #38BDF8, orange/red #F87171) with halos; central brightest golden-white node with orbit rings (at ~49%,52%); warm red-orange dense cluster in the upper-middle; faint dots in dark space.
3. Palette: bg #050814; edges #4A6FA5 at ~30% alpha; accent nodes above.
4. Use: reference for Knowledge Graph / Company Brain / agent-network visualisation (large force-directed graph with category-coloured nodes, central hub node, glow). 
7. Requirements: graph view should support large node counts (canvas/WebGL), color by category, zoom/pan, hub node highlighted, glow halos on important nodes.

---

## 1.png (identical to 2.png)
1. "AXoR · Autonomous Company OS — UI Concept" master sheet: 9 numbered screens in a poster. Light theme (flat, white cards, blue #2563EB accent) with dark navy sidebar. 1536x1024.
2. Layout: top banner (h ~4%, navy gradient #1B2B5B->#243A7A) with logo "AXoR" (triangle "A" mark in blue) + "• Autonomous Company OS — UI Concept" (white, ~26px) and right small text "A self-sustaining AI company that plans, executes, verifies, improves, and grows autonomously." Below: row A (y 4-57%): left large panel 1 (x 1-62%), right column x 63-100% with panel 2 (y 4-34%) and panel 3 (y 35-58%). Row B (y 60-79%): three equal thumbnails 4, 5, 6. Row C (y 80-99%): three thumbnails 7, 8, 9. Each has a blue rounded number badge, title in bold, and a one-line description.

### Screen 1 "Company Overview (Homepage)" - "Executive dashboard with company KPIs, missions, decision inbox, performance, and system health."
- Sidebar (navy #14213D, ~12% of panel width): logo "AXoR / Autonomous Company OS"; nav with icons: Overview (house, ACTIVE: blue #2563EB filled pill), Missions (monitor/inbox icon), Organization (org-tree), Knowledge (open book), Evolution Lab (rocket/spark), Finance (database/coins), Governance (shield). Bottom: Settings (gear), Help & Docs (circle-?).
- Top bar: "Workspace" label + dropdown "AXoR Main"; right: green pill "System Healthy" (check-circle), bell icon with red dot, user avatar circle.
- Title "Company Overview" (bold 22px), subtitle "Real-time operating status of the AXoR autonomous company."; right "Jan 26, 2025, 10:24 (UTC)" and blue button "+ Add Mission".
- 5 KPI cards (rounded white, soft shadow, icon in tinted circle left): target icon blue "12" "Active Missions" "↑ +2" (green); people icon blue "38" "Active Agents" "↑ +4"; clipboard icon orange "3" "Pending Approvals"; check-circle icon green "96.4%" "Mission Success" "↑ +2.1%"; database icon blue "$2,840" "This Month Spend" "76% of Budget" with green progress bar.
- "Mission Execution" panel: filter chips "Active (12)" (blue filled), "Completed (24)", "All (36)"; dropdown "All Departments"; search "Search missions...". Table columns: Mission | Progress | Version | Next Edition | Issues. Rows:
  1. star icon (orange) "AXoR Platform Upgrade" / "Enhance core platform and UI (v2.0)" | 76% blue bar | v1.4.0 | "Edition 1.5.0 Feb 2, 2025" | warning triangle orange "1"
  2. "Agent Evaluation Framework" / "Build QA and performance evaluation" | 52% | v0.9.2 | "Edition 1.0.0 Feb 5, 2025" | "–"
  3. "Research Knowledge Engine" / "Organizational memory & knowledge reuse" | 91% | v1.3.1 | "Edition 1.4.0 Jan 30, 2025" | "–"
  4. "Business Opportunity Analysis" / "Identify new product and revenue opportunities" | 34% | v0.3.0 | "Edition 0.4.0 Feb 6, 2025" | warning "2"
  5. "Self-Evolution Engine" / "Continuous improvement and auto-upgrade" | 68% | v0.8.5 | "Edition 0.9.0 Feb 4, 2025" | warning "1"
  (rows 2-5 have a green/grey monitor-icon at left)
- "Decision Inbox" panel with orange pill "3 Pending" and chevron: 
  1. code "</>" icon "Approve agent architecture upgrade" / "Evaluation passed · Release 1.5.0"; red pill "High"; "Due: Jan 28, 2025"; blue button "Review", grey button "Details"
  2. database icon "Review additional compute budget" / "Proposed increase: +$1,200 / month"; orange pill "Medium"; "Due: Jan 29, 2025"; Review/Details
  3. org icon "Approve organizational change" / "Create a "Research Lab" department"; orange "Medium"; "Due: Jan 31, 2025"; Review/Details
- "Company Performance (Last 30 Days)": line/area chart, two series: green "Mission Success Rate" and blue "Autonomous Completion Rate", markers circles; y axis 60%-100% (ticks 60,70,80,90,100%), x labels Dec 26, Dec 30, Jan 3, Jan 7, Jan 11, Jan 15, Jan 19, Jan 23; both lines gently rising ~86-95% (green top) and ~72-88% (blue), area fill light under each.
- "System Health" panel (chevron right): green check rows: "Agents — All operational (38)"; "Tools & Integrations — 5 connected"; "Execution Jobs — 0 failed · 3 running"; "Infrastructure — Healthy (99.9% uptime)".

### Screen 2 "Add Mission" - "Create a new mission with files, GitHub integration, budget, and approval."
Modal "Add New Mission" with X close. Left stepper: 1 "Mission Details" (active, blue circle), 2 "Resources & Files", 3 "Budget & Approval", 4 "Review & Create". Fields: "Mission Title *" placeholder "e.g., Build a customer portal"; "Mission Description *" textarea "Describe the goal, expected outcome, and key requirements..."; "Attachments" dashed-border dropzone with upload icon "Drag & drop files or click to upload" / "Supports PDF, DOCX, TXT, MD, ZIP, PNG, JPG (max 100 MB)"; uploaded file row (red PDF icon) "Requirements.pdf (2.4 MB)" with X; "GitHub Repository (Optional)" input with GitHub icon "https://github.com/owner/repo" + button "Verify". Footer: "Cancel" (outline), "Next: Resources & Files →" (blue).

### Screen 3 "Mission Control" - "Manage mission execution: agent hierarchy, timeline and task flow, with agent conversations and approvals."
Mini dark sidebar + header "Mission Control — AXoR Platform Upgrade", green pill "In Progress (76%)", right "Auto-Run" with green toggle. Three columns: "Agent Hierarchy" (tree: General Manager (GM) > Product Dept. > Development Dept. [Tech Lead Agent, Dev Agent (x3), QA Agent] > Operations Dept. > Research Dept.); tabs "Execution Timeline"(active) | "Task Flow" | "Activity Log" with timeline: Mission Started (Jan 20, 09:00), Requirement Analysis (Completed · Jan 21, 14:20), System Design (Completed · Jan 22, 16:10), Implementation (In Progress (76%) with blue bar), Testing & QA (Pending), Deployment (Pending); right "Conversations"(active)| "Approvals (1)": chat bubbles "Dev Agent Jan 26, 10:02 — Core features are implemented. Ready for the QA test." and "QA Agent Jan 26, 10:07 — I will run the full test suite and report the results."; input "Send a message to agents..." with paperclip + blue send icon.

### Screen 4 "Versions & Preview" - "View editions, release notes, download/run builds, and open a live preview."
Header "Versions & Preview — AXoR Platform Upgrade"; left list "Editions": Edition 1.5.0 Feb 2, 2025 (badge "Next"), Edition 1.4.0 Jan 20, 2025 (selected, badge "Current"), Edition 1.3.0 Jan 5, 2025, Edition 1.2.0 Dec 22, 2024. Tabs: "Release Details"(active) | "Live Preview" | "Download & Run". Content "Edition 1.4.0 (Current)" "Released: Jan 20, 2025"; "Release Notes" bullets: "Enhanced mission dashboard and filters", "Improved agent collaboration", "Bug fixes and performance improvements"; preview screenshot thumbnail and blue button "Open Live Preview ↗".

### Screen 5 "Organization" - "View and manage the agent organization, departments, roles, and performance."
Header "Organization", blue buttons "+ Add Department", "+ Add Agent". Tabs "Org Chart"(active), "Departments", "Agents", "Performance". Org chart: box "General Manager (GM) Coordination & Strategy" with 4 child boxes: "Product Dept. 5 Agents 96%", "Development Dept. 12 Agents 94%", "Operations Dept. 7 Agents 97%", "Research Lab 6 Agents 93%" (green dot + %). Right panel "Department Performance": Development 94%, Operations 97%, Product 96%, Research Lab 93% (green bars).

### Screen 6 "Knowledge & News" - "Manage organizational knowledge, research, and external news with citations."
Header "Knowledge & News", buttons "+ Add Source", "+ Add News URL". Tabs "Knowledge Library"(active), "News & Research". "Sources" list with counts: Project Knowledge (128), Research & Analysis (56), Technical Docs (74), Best Practices (32), Lessons Learned (19). "Recent Knowledge" card "Agent Evaluation Best Practices" with tags Research / Evaluation / Agent, "Updated: Jan 24, 2025", description "A comprehensive guide for evaluating agent performance, including metrics, test sets, and validation methods.", "Citations (3)" collapsible. "Recent News": "New LLM with higher tool-use accuracy techcrunch.com · Jan 25, 2025"; "AI agents for software teams theverge.com · Jan 24, 2025"; "Industry trends: Autonomous companies forbes.com · Jan 23, 2025".

### Screen 7 "Evolution Lab" - "Propose, test, benchmark, and promote agent or system improvements (self-evolution)."
Header "Evolution Lab — Controlled Self-Evolution"; button "+ New Proposal". Tabs "Proposals"(active), "Experiments", "Benchmarks", "History". Table columns Proposal | Target | Baseline → Candidate | Validation | Status | Action. Rows: "Improve task planning accuracy" GM Agent 82.1% → 88.7% Passed (green check) status "Ready to Promote" (green pill) action "Promote" (blue button); "Optimize code generation" Dev Agent 91.4% → 93.9% Passed "In Review" (orange pill) "Review" (outline); "Reduce execution cost" All Agents $0.84 → $0.61 / task Passed "Ready to Promote" "Promote" (outline).

### Screen 8 "Finance" - "Track spending, budgets, resource usage, and cost alerts across missions and departments."
Header "Finance — Spending & Resource Management"; dropdown "This Month (Jan 1 – Jan 31, 2025)". Tabs "Overview"(active), "Budgets", "Usage", "Cost by Mission", "Alerts". Cards: "Total Spend $2,840 ↑ +6.3%"; "Budget $3,750 76% Used" (green bar); "Cost / Mission $237 ↓ -12.4%". Donut chart "Spending by Category" center "$2,840": LLM / API 42%, Compute 24%, Tools & Services 16%, Storage 8%, Other 10% (blue, green, orange-ish, purple, grey). "Alerts (2)": "Compute usage 90% Near budget limit" (orange warning), "Mission "Research Engine" +15% over estimate" (blue info); link "View All Alerts →".

### Screen 9 "Governance & Models" - "Manage autonomy levels, permissions, model routing, self-renewal, and view the audit log."
Header "Governance & Models"; tabs "Autonomy & Policies"(active), "Permissions", "Model Routing", "Self-Renewal", "Audit Log". "Autonomy Levels" radio list: L0 – Observe Only; L1 – Recommend; L2 – Execute Approved Tasks; L3 – Manage Workflows (selected, blue) with detail card "L3 – Manage Workflows: Agents can execute complex workflows within approved scope. High-risk decisions require approval."; L4 – Propose Evolution; L5 – Continuous Optimization. "Model Routing" table Task Type | Assigned Model: Planning GPT-4o (High Accuracy); Implementation Claude 3.5 Sonnet; Review / QA GPT-4o; Research Perplexity / GPT-4o. "Self-Renewal": toggle "Enable Self-Renewal" (green), "Allow AXoR to prepare and apply improvements (with validation and approval)." "Last Renewal: Jan 20, 2025" link "View Audit Log →".

4. Icons overall: all line icons (Lucide-like) 16-18px; star (favorite mission), warning-triangle (issues), check-circle (health), bell with red dot (notifications), avatar circle, paperclip + send arrow, GitHub mark, upload, X close, chevron right.
5. Palette: page bg #EEF2FA; panels #FFFFFF, border #E2E8F0, radius ~10-12px with soft shadow; sidebar #14213D; accent blue #2563EB; green #16A34A; orange #F59E0B/#EA580C; red #DC2626; text #1E293B / muted #64748B; banner gradient #1B2B5B→#2B4A9A.
6. Typography: Inter-like sans; panel titles 600-700; KPI numbers 24px bold; small captions 10-11px; subtle shadows; pill badges fully rounded.
7. Requirements: app shell with sidebar nav (7 + Settings + Help); Overview with 5 KPI cards, mission table with filters/search/progress bars/issues, decision inbox with Review/Details, performance chart, system health; Add Mission 4-step wizard with file drag-drop and GitHub verify; Mission Control with hierarchy, timeline/task flow/activity log, conversations/approvals tabs, Auto-Run toggle; versions/editions with live preview and download; org chart with department performance; knowledge library with citations; evolution proposals with promote/review; finance with donut + alerts; governance autonomy levels L0-L5, model routing, self-renewal toggle.

## 2.png
Identical to 1.png (same bytes, same md5). See 1.png.

## 3.png
1. "AXoR TASK FLOW — FOUR APPEARANCE PRESETS" comparison sheet, same screen (Mission Control / Task Flow) rendered in 4 themes in a 2x2 grid. Page bg #E8ECF7 lavender-grey, heading "AXoR TASK FLOW — FOUR APPEARANCE PRESETS" (navy #172B4D bold ~30px). 1940x1150. Each quadrant ~47% x 45%, labelled "01 TASK FLOW FLAT", "02 TASK FLOW LUMINOUS", "03 TASK FLOW ELEGANT", "04 TASK FLOW FANCY" (bold navy 16px; the labels for 03 and 04 are partly overlapped/cut by the quadrant above - artefact).
2. Common layout per quadrant (app frame ~ 910x520 px at this scale): sidebar left ~16.5% width; main area: top header: title "Mission Control  /  AXoR Upgrade" (bold 20px), subtitle "Visual task DAG · current mission execution · no hidden tabs"; right icon trio "?" "◐" (half-circle theme toggle) "♧"(plug/shield-like glyph) "⚙". Tab row: "Hierarchy", "Task Flow" (active), "Activity Log", "Conversations", "Approvals". Divider. Two columns: left (~52%) card "Execution dependency graph"; right (~42%) two stacked cards "Selected task: Implement Task Flow" and "Execution controls & checkpoints".
3. Sidebar: logo "▲ AXoR" + "AUTONOMOUS COMPANY OS" small caps; nav rows with glyph icons: "◈ Overview", "◎ Missions", "⌘ Mission Control" (active pill), "▯ Versions", "♧ Organization", "▤ Knowledge", "✧ Evolution Lab", "▥ Finance", "◇ Governance", "◐ Appearance".
4. DAG card: nodes (rounded rects 130x55):
   - "01  Intake" status "DONE" (green #1B7F5C text) at row 1 left
   - "02  Architect" "DONE" row 1 right, connected by short horizontal line to 01
   - "03  UI Build" "RUNNING" (accent colour border/text) row 2 left under 01 (vertical line)
   - "04  API Build" "RUNNING" row 2 right under 02
   - "05  QA / Merge" "BLOCKED" row 3 centre; two diagonal accent lines from 03 and 04 converge to 05.
   Done nodes: soft fill, thin border. Running nodes: 1.5px accent border. Blocked: soft fill, grey-blue border, accent-coloured text.
   Selected-task card: "Selected task: Implement Task Flow"; "Owner: UI Builder ◇   Model: Claude Code"; "Dependency: architecture approved"; "Status: running · 7 / 11 checks passed" with progress bar ~64% (accent fill); "Output: branch feature/task-flow"; "? Acceptance: keyboard controls + DAG fidelity".
   Controls card (inner tinted box): "▶ Resume", "Ⅱ Pause", "↻ Retry failed node", each with sub-line "Scoped to selected task, audited and permission-checked".
5. Four themes:
   - 01 FLAT (light): page #F4F6FB, sidebar navy #14233F, active nav/tab/progress blue #2563EB (white text), cards white with #E5E7EB border, node fill #E8EEFC, text #1F2A44.
   - 02 LUMINOUS (dark): page #070F1E, sidebar #060C18, cards #0E1D35/#12294A with #1E3A5F borders, accent cyan #4DC8F5 (active nav/tab with dark text, node borders, progress), done text mint #5EEAD4, inner box #173456.
   - 03 ELEGANT (light, warm): page #FAF6F4, sidebar #3A2B35 (dark plum-brown), accent rose/mauve #BE5F8F (active nav/tab/progress), cards white #FFFDFB, node fill #F6E5EE, tab chips #F5E6EF.
   - 04 FANCY (dark purple): page #130B22, sidebar #120A1F, cards #271A45 with #3A2A63 borders, accent lilac #D8A0FF (active nav pill/tab with dark text, node borders, progress), node fill #3B2260.
6. Typography: DejaVu/Verdana-like sans; headings bold; status labels 8-9px bold uppercase; radii ~6-8px nodes, 12px cards, active nav pill radius 8px.
7. Requirements: theme switch swaps tokens only (layout & functions identical); Task Flow DAG with status nodes (DONE/RUNNING/BLOCKED), selected-task detail, scoped execution controls (Resume, Pause, Retry failed node) that are audited and permission-checked; keyboard accessibility of DAG; help "?" and tabs "no hidden tabs".

## 4.png
1. "AXoR MISSION WORKSPACE — SECONDARY TAB CONTENT" sheet: 4 screens in 2x2, same frame as 3.png (each themed: 05 flat light, 06 luminous dark, 07 elegant light, 08 fancy dark). 1940x1150. Same sidebar/header/tab-row conventions as 3.png.
2. Quadrants:
 - **05 ACTIVITY LOG** (Flat/blue): title "Mission Control / Activity Log", sub "Time-stamped event ledger with filters and trace links"; tabs Hierarchy, Task Flow, Activity Log(active), Conversations, Approvals. Left card "Events  ·  most recent first": rows (bold title + muted sub, right green status):
   - "10:42:16  Task started" / "UI Builder entered execution" - RUNNING
   - "10:41:22  Approval granted" / "Owner approved preview deployment" - APPROVED
   - "10:39:08  QA failed" / "Contrast regression on theme selector" - FAILED
   - "10:36:51  Branch created" / "feature/task-flow at commit 9fd72a" - SUCCESS
   - "10:31:05  Plan accepted" / "GM assigned two workstreams" - SUCCESS
   Right card "Event details & evidence": "Event ID: evt_1092" / "Actor: UI Builder · Mission: AXoR Upgrade" - TRACE; "Related context" / "Task task_321 · Run run_048" - OPEN; "Inputs / outputs" / "Input refs, output hashes, durations" - COPY; "Audit trail" / "Append-only, access controlled" - VERIFIED.
 - **06 CONVERSATIONS** (Luminous): title "Mission Control / Conversations", sub "Agent-scoped conversation sessions and mission isolation"; active tab Conversations. Left "Thread selection": "GM ↔ UI Builder" / "Mission 12 · 14 messages · 10:42" ACTIVE; "UI Builder ↔ QA Agent" / "Mission 12 · 8 messages · 10:39" 8 ITEMS; "GM ↔ Research Agent" / "Mission 03 · 21 messages · 09:53" OPEN; "Human ↔ GM" / "Mission 12 · 6 messages · 09:41" OPEN. Right "Selected conversation": "10:35  General Manager" / "Implement Task Flow and emit validation artifacts" COPY; "10:38  UI Builder" / "Built DAG view on isolated mission branch" COPY; "10:39  QA Agent" / "Found contrast issue; linked test evidence" COPY; "10:42  Human instruction" / "? Please show all dependencies" REPLY.
 - **07 APPROVALS** (Elegant): "Mission Control / Approvals", sub "Decisions require a human rationale and explicit authority"; active tab Approvals. Left "Pending decision queue": "Preview deployment" / "High · Deadline 15:00 · Mission 12" PENDING; "Create new GitHub repo" / "High · Account authorization required" PENDING; "Additional compute budget" / "Medium · Proposed +$150 ceiling" PENDING; "Model route change" / "Low · Gemini → GPT fallback" PENDING. Right "Decision details / choices": "Deploy preview: release 1.4.0" / "Change: staged only · branch preview/task-flow" DETAIL; "Impact and rollback" / "Low risk; revert to release 1.3.1" REVIEW; "Candidates" / "Approve / Request revision / Reject" CHOOSE; "Decision history" / "Prior answers archived and filterable" HISTORY.
 - **08 VERSIONS BRANCHES** (Fancy): title "Versions / Git Graph", sub "Project branches versus isolated agent-version experiments"; tabs Releases, Branches(active), Diff & Merge, Preview, Downloads; sidebar active item = Versions. Left "Repository graph / changes": "main  ● v1.3.1" / "Protected baseline branch" PROTECTED; "feature/task-flow  ● 9fd72a" / "Mission-specific worktree / PR #41" OPEN; "feature/theme-engine  ● 11c782" / "Separate worktree / PR #42" OPEN; "release/v1.4.0  ● 0dbf12" / "Release candidate pending QA" STAGED. Right "Merge review": "PR #41  → main" / "Base main; merge strategy squash" OPEN; "CI & security checks" / "42 / 42 passed · QA approval required" PASS; "Conflicts" / "1 theme-token conflict; manual review" REVIEW; "After merge" / "Preview → signed release → rollback target" PLAN.
3. Status label colours: green #1B7F5C on light themes; mint #5EEAD4/#6EE7B7 on dark themes; label is uppercase 8px bold, right-aligned in the row at ~x 70% of card. Row chips: tinted rounded rects (flat #E8EEFC, luminous #173456, elegant #F6E5EE, fancy #3B2260), 2-line (bold title 10px, muted 8px).
4. Icons: same sidebar glyphs as 3.png; header "? ◐ ♧ ⚙".
5. Palettes: identical to 3.png per theme (flat/luminous/elegant/fancy).
6. Typography: as 3.png.
7. Requirements: Activity log = append-only event ledger, newest first, with detail/evidence pane (Event ID, related context, IO, audit trail with COPY actions); Conversations = per-agent-pair threads with mission isolation, message-level COPY and REPLY; Approvals = decision queue with priority/deadline, details/impact/rollback, candidates Approve/Request revision/Reject, filterable history, human rationale required; Versions = release/branch/diff/preview/download tabs, protected main, PR list, CI checks, conflicts, post-merge plan.

## 5.png
1. "AXoR AGENT EVOLUTION + KNOWLEDGE + APPEARANCE" sheet: 4 screens 2x2 (09 flat light, 10 luminous dark, 11 elegant light, 12 fancy dark), same frame as 3.png/4.png. 1940x1150.
2. Quadrants:
 - **09 AGENT ASSIGNMENTS** (Flat): sidebar active = Organization. Title "Organization / Agent Workspaces", sub "Same agent identity can serve multiple missions independently". Tabs: Org Chart, Departments, Agents, Assignments(active), Performance. Left "Agent: UI Builder ◇": "Canonical agent: ag_ui_01" / "Role: UX engineer · Mission icon: ◇" ACTIVE; "Agent version: 2.4.0" / "Immutable approved artifact" PINNED; "Available skills" / "Layouts · accessibility · components" VERIFIED; "Max parallel missions: 3" / "Currently allocated: 2 / 3" CAPACITY. Right "Concurrent mission instances": "Mission 12 / run 084" / "workspace/mission-12; context isolated" RUNNING; "Mission 03 / run 212" / "workspace/mission-03; context isolated" RUNNING; "Experience candidates" / "Two proposals; not yet merged into agent" REVIEW; "Consolidation" / "Post-run evidence → mentor → QA → promotion" GATED.
 - **10 AGENT BENCHMARKS** (Luminous): active nav Evolution Lab. Title "Evolution Lab / Agent Versions", sub "Compare candidate agents to baseline on held-out tests". Tabs: Proposals, Experiments, Benchmarks(active), History, Mentors. Left "Candidate ag_ui_01 v2.5.0": "Baseline version v2.4.0" / "Pass 87.5% · cost $0.42 · p95 12.4s" CURRENT; "Candidate version v2.5.0" / "Pass 92.8% · cost $0.39 · p95 12.1s" CANDIDATE; "Evaluation set" / "200 held-out cases · fixed rubric" LOCKED; "Safety regression" / "0 critical failures · policy unchanged" PASS. Right "Independent verifier report": "Mentor agent / technical reviewer" / "Identified weak layout recovery" REVIEWED; "Verifier agent / independent QA" / "Run eval_902 using frozen criteria" VERIFIED; "Decision" / "Promote only on next NEW invocation" ELIGIBLE; "Running missions" / "Remain pinned to v2.4.0 until completion" PINNED.
 - **11 KNOWLEDGE SOURCES** (Elegant): active nav Knowledge. Title "Knowledge / Research", sub "Source validity, trust and attribution visible in each record". Tabs: Library, Sources(active), News, Ingestion, Provenance. Left "Connected source registry": "Engineering specifications" / "Approved internal docs; owner assigned" TRUSTED; "GitHub repository" / "Repo issue/PR changes · scoped OAuth" CONNECTED; "Technical publication feed" / "Daily ingestion · citation required" ACTIVE; "Uploaded screenshots & files" / "Per mission; content classification applied" ACTIVE. Right "Selected source settings": "Source URL and permissions" / "Allowed domains / per-agent scopes" EDIT; "Freshness and crawl" / "Polling schedule + last fetched status" STATUS; "Provenance" / "Source link, retrieval date, content hash" TRACE; "Learned knowledge" / "Candidate until validation and approval" PENDING.
 - **12 THEME STUDIO** (Fancy): active nav Appearance. Title "Appearance / Theme Studio", sub "Personalize presentation only; never change permissions or data". Tabs: Themes(active), Colors, Layouts, Accessibility, Presets. Left "Theme chooser": "Flat" / "Light or dark · low visual density" SELECT; "Luminous" / "Dark · glow accents, restrained animation" ACTIVE; "Elegant" / "Light · soft premium surfaces" SELECT; "Fancy" / "Dark/light · gradients & vivid highlights" SELECT; "Custom" / "Accent + radius + density + font scale" EDIT. Right "Live preview / preferences": "Theme: Luminous Dark" / "Accent cyan · compact density" PREVIEW; "? Explain display setting" / "Icon-only help and tooltip on focus" HELP; "Responsive layout" / "Single-viewport target at ≥1440×900" ADAPT; "Save preference" / "Per user/device · shared UI capabilities" SAVE.
3. Palettes/typography: as 3.png.
4. Requirements: one agent identity running concurrent isolated mission instances with immutable pinned versions and capacity limits; candidate promotion only after independent verification, frozen eval set, safety regression; running missions stay pinned, promotion affects only NEW invocations; knowledge sources with trust/provenance (link, date, hash), learned knowledge pending approval, scoped OAuth; theme studio presentation-only, per-user/device saved preferences, single-viewport target >=1440x900, "?" help with tooltip on focus.

## 6.png (identical to 01_task_flow_flat_light.png)
1. Mission Control · Task Flow, flat light theme, 1600x900 (single full-screen mock).
2. Layout: sidebar x 0-15% (#17233F navy), main area bg #F3F6FB. Header (y 0-12%): title "Mission Control · Task Flow" (bold ~30px, #172033) and sub "Mission AX-0142 / AXoR platform modernization / In progress"; top-right three square icon buttons (36px, tinted #E8EFFD, blue glyphs): "?" help, "◉" theme/eye, "⚙" settings. Divider line y~11%. Tab row (y 13-17%): chips "Agent Hierarchy", "Task Flow" (active: tinted blue #E8EFFD with bold blue #2563EB text), "Activity Log", "Conversations", "Reports", "Approvals" (inactive white chips, muted text). Below: left card (x 17-70%, y 19-94%) and right card (x 71-98%, y 19-94%).
3. Sidebar: logo "AXoR" (white bold 36px) + "AUTONOMOUS COMPANY OS"; nav items text-only (no icons): Overview, Missions, Mission Control (ACTIVE: blue #2563EB pill, white bold), Versions, Organization, Knowledge, Evolution Lab, Finance, Governance, Appearance.
4. Left card "Execution dependency graph" (bold 20px) sub "Live workflow, gate states and critical path"; badge top-right "LIVE • 76%" (blue text on #E8EFFD pill). DAG nodes (white cards, 1px #E5E9F2 border, radius 14px, ~268x128, number chip left: blue "01" on #E8EFFD rounded square; title bold + agent sub):
   - 01 "Research & specification" / "Strategy Agent" / pill "Completed" (green #15906A on #E8F5EF)
   - 02 "Architecture review" / "Architect Agent" / "Completed"
   - 03 "Implementation" / "Dev Agent" / "Running" (blue pill) - card clipped at right edge by panel
   - 04 "Independent tests" / "QA Agent" / "Waiting" (amber #D97706 on #FDF3E0)
   - 05 "User acceptance" / "Executive approval" / "Blocked" (amber/orange pill) - clipped
   - 06 "Merge & release" / "Release Agent" / "Not started" (grey pill #EEF1F6 text #5B6578)
   Edges: straight 3px blue #2563EB lines: 01→02 horizontal, 02→03 horizontal, 03↓05 vertical, 04→05 horizontal, 04↓06 vertical. Layout: row1 (01,02,03), row2 (04,05) offset under 02/03, row3 (06) under 04. Right-most nodes overflow card (a layout bug in the mock; real implementation should scroll/zoom).
5. Right card "Selected step" sub "Implementation · TS-0024"; "Owner Dev Agent / instance A-07"; "Status Running • 8 of 11 tasks"; heading "Acceptance criteria" with items: green "✓ Unit tests pass", green "✓ No critical security findings", grey "○ Preview builds successfully", grey "○ Report approved by QA"; heading "Actions" with five square icon buttons (tinted blue): "▶" resume, "Ⅱ" pause, "↻" retry, "↗" open/escalate, "?" help; footer notes small: "Critical path: 01 → 02 → 03 → 04 → 05 → 06" and "Gate: release requires QA + user approval".
6. Palette: sidebar #17233F, active #2563EB, text #172033, muted #64748B/#5B6B86, card border #E5E9F2, bg #F3F6FB, green #15906A, amber #D97706. Font DejaVu Sans-like (Verdana feel), headings 700.
7. Requirements: DAG with 6 steps showing owner agent + status; critical-path text; right inspector with acceptance criteria checklist (done/pending), selected-step actions Resume/Pause/Retry/Open/Help; gate rules shown; live progress badge.

## 7.png (identical to 02_agent_lifecycle_luminous_dark.png)
1. "Agent Evolution · Concurrent Missions" (Evolution Lab, Agent Lifecycle tab), luminous dark theme, 1600x900.
2. Layout same shell as 6.png: sidebar 0-15% (#070E1A), page bg #08111C, header title "Agent Evolution · Concurrent Missions", sub "Agent: Architect A-002 / Stable v3.4 / Proposed v3.5", icons "?", "◉", "⚙" in dark-teal squares (#12384F bg, cyan glyphs). Tabs: Proposals, Experiments, Benchmarks, Agent Lifecycle (active: bg #17384C, cyan #22D3EE bold), History. Left card x 17-67%; right card x 68-98%.
3. Sidebar nav same list; active = "Evolution Lab" (cyan #3AD9F0 filled pill, dark text). Items: Overview, Missions, Mission Control, Versions, Organization, Knowledge, Evolution Lab, Finance, Governance, Appearance.
4. Left card "Agent baseline and isolated mission instances", sub "One registered identity · isolated execution contexts". Diagram:
   - Top node (cyan border, fill #17384C, radius 14): "⌘ Architect Agent" / "Baseline: v3.4 • Read-only while missions run"
   - Two diagonal cyan lines down to:
     - "Instance A" / "Mission AX-0142" / pill "Running" (cyan on #17384C) / "Separate context • tools • workspace"
     - "Instance B" / "Mission AX-0139" / pill "Completed" / "Separate context • tools • workspace"
     (instance cards: fill #0F1E30, border #1E3347)
   - From both instances: orthogonal cyan lines joining a horizontal bus then down to box "Experience consolidation queue" / "Evidence + execution trace + knowledge updates" (cyan border).
   - Footer in green #4ADE80 (mint): "✓ Completed mission learns are deduplicated and reviewed".
   Right card "Candidate promotion" sub "Baseline v3.4 compared with v3.5": rows with divider lines: "Task accuracy" "91.1% → 94.7%"; "Regression pass" "100%"; "Cost per task" "$0.42 → $0.36"; "Security checks" "All passed" (values white bold right aligned). Pill "READY FOR REVIEW" (cyan bold on #17384C). Notes: "Roles: Mentor • Implementer • Evaluator"; "No agent can approve its own candidate."; "Promotion affects NEW instances only.". Action buttons (square dark-teal with cyan glyphs): "✓" approve, "✕" reject, "↻" re-run, "?" help.
5. Palette: bg #08111C; card #0F1E30 border #1E3347; accent cyan #22D3EE; text #F1F5F9; muted #94A3B8; green #4ADE80.
6. Typography: DejaVu Sans; no real glow (flat dark), cyan outlines emphasise.
7. Requirements: baseline agent read-only while missions run; per-mission isolated instances (separate context/tools/workspace); experience consolidation queue with dedup + review; candidate promotion with metrics comparison, independence rule (no self-approval), promotion affects only new instances; approve/reject/rerun actions.

## 8.png (identical to 03_branch_graph_pretty_pastel.png)
1. "Version Management · Branch & Merge" (Versions, Branch Graph tab), pastel "Pretty/Elegant" light theme (lavender), 1600x900.
2. Layout same shell: sidebar #35274A deep purple, page bg #F8F4FA; active nav = "Versions" (violet #9B59B6 pill); header title "Version Management · Branch & Merge" sub "GitHub integration / Protected main / mission-scoped branches"; icon squares tinted #F0E1F5 with violet glyphs ("?", "◉", "⚙"). Tabs: Timeline, Branch Graph (active; violet tint #F2E4F7, bold violet #9B4DB8), Release Notes, Preview, Downloads, Merge Requests. Left card x 17-69% titled "Branch topology" sub "Changes develop separately, pass checks, and merge into main"; right card x 70-98% "Selected merge request".
3. Graph: vertical thick grey-violet trunk line (x 23%) with three violet node dots labelled "main v2.0" (top), "main v2.1" (mid), "main v2.2" (bottom; labels overlap the curves - mock artefact). Purple curve (#9B59B6, 3px) from just below v2.0 sweeping right and returning to main v2.1, with tag chip "feature/agent-evolution" (pale violet chip, bold violet 11px) and label "PR #108 ✓ checks ✓ independent QA". Green curve (#2F9A78) from below v2.1 sweeping right to main v2.2 with chip "mission/AX-0142-preview" and label "PR #112 awaiting approvals".
   Right panel: "Selected merge request" sub "PR #112 · AX-0142"; key/value rows with underline dividers: "Source" / "mission/AX-0142-preview"; "Target" / "main (protected)"; "Commits" / "14"; "Checks" / "12 passed / 1 pending"; "Review" / "QA passed • owner pending". Action icon buttons: "⊞" (diff), "↗" (open PR), "↓" (download), "?" help. Footer: "Merge is disabled until all gates pass."
4. Palette: sidebar #35274A; accent violet #9B59B6; green #2F9A78; text #2E2A44; muted #6B6488; border #ECE4F0.
7. Requirements: git branch topology graph with protected main, mission-scoped branches, PR labels; merge request inspector with source/target/commits/checks/review; merge button disabled until all gates (checks + QA + owner) pass; diff/open/download actions.

## 9.png (identical to 04_appearance_studio_fancy_dark.png)
1. "Appearance Studio · User Personalization" (Appearance, Theme Gallery tab), fancy dark purple theme, 1600x900.
2. Layout same shell: sidebar #120F20 with active nav "Appearance" (lilac #B98BF7 pill, dark bold text). Page bg #0F0D1E. Header title "Appearance Studio · User Personalization" sub "Per-user styles, shared functionality, saved presets, accessibility"; icon squares #2A2347 with lilac glyphs. Tabs: Theme Gallery (active, #3B2A66 bg, lilac bold), Colors, Layout, Density, Icons, Accessibility. Left card (x 17-73%) "Style presets" sub "Choose a visual skin. All tabs and functions remain unchanged."; right card (x 74-98%) "Personal settings".
3. Style presets: 2x2 grid of preview cards (each ~25% x 23% of page, border #2E2750, radius 14px) containing a mini wireframe (rounded square left + one long bar + two small blocks):
   - "Flat" / "Crisp and minimal": white-ish #F3F6FC mini UI, blue #2D6BF4 square
   - "Luminous" / "Glass and neon": dark navy #101B2D mini UI, cyan #2ECBE8 square, slate #384A6B blocks
   - "Pretty" / "Soft and pastel": pink-white #FFF2F8 mini UI, dusty pink #D78FC0 square
   - "Fancy" / "Premium and expressive": dark purple mini UI, lilac #B98BF7 square, slate blocks — SELECTED: 2px lilac outline #B98BF7 (radius 14px).
   Personal settings ("Changes apply immediately"): label left (muted) / value chip right (violet text #B98BF7 bold on #3B2D60 chip): "Mode" Dark; "Accent" Violet; "Density" Compact; "Navigation" Icon + label; "Button labels" Tooltips only; "Help style" "? icon". Footer: "Presets are user-scoped by default."
4. Palette: page #0F0D1E; card #1F1A3A border #2E2750; text #FFFFFF / muted #A99FCB; accent #B98BF7; chips #3B2D60.
7. Requirements: preset gallery (Flat, Luminous, Pretty, Fancy) with live selection ring; personal settings (mode, accent, density, navigation style, button labels, help style) applied immediately; presets per-user by default; accessibility tab; theme affects look only, never function.

## 10.png
1. Flowchart "Agent version lifecycle with isolated mission instances". Dark minimal (#0D0D0D), 787x649.
2. Layout: vertical stack of bordered boxes with down arrows. Row1 (top): icon + title + sub. Row2: two equal side-by-side boxes (x 3-50% and 51-98%). Then full-width boxes ×2 and a final green-tinted box.
3. Text (icon above title):
   - robot-face icon, "Original Agent — Stable Version 3.4" / "Shared identity and approved capabilities"; below it a git-branch icon (fork)
   - Box left: code "</>" icon "Mission A Instance" / "Independent workspace and experience"; Box right: flask icon "Mission B Instance" / "Independent workspace and experience"
   - "↓" then box "Experience Consolidation" / "Verified knowledge, execution traces, skills, and improvement proposals"
   - "↓" then box shield-check icon "Independent Agent Evaluation" / "Mentorship, code review, benchmarks, security and regression testing"
   - "↓" then green box (bg #0F1B14, border #1E3A28) check-circle icon (green) "Promote Version 3.5 if Verified" / "Used by future mission instances; running instances remain pinned"
4. Icons: bot, git-branch, code, flask, shield-check, check-circle, arrow-down.
5. Palette: bg #0D0D0D; box border #2A2A2A radius ~12px; text #F2F2F2; sub #BDBDBD; green #22C55E.
7. Requirements: same behaviours as 7.png: fork per mission, consolidate, independent evaluation, promote only if verified, running instances pinned.

## 11.png
1. Flowchart "Agent version evolution", 786x451, dark minimal like 10.png but simpler (no coloured box).
2. Layout: top title; git-branch icon; row of three equal bordered cards (x 3-34%, 35-66%, 67-98%); arrow; wide bordered box; arrow; unboxed final text.
3. Text:
   - "Original Agent" / "Verified baseline version"
   - Three cards each with small robot icon: "Mission A" / "Isolated agent instance"; "Mission B" / "Isolated agent instance"; "Mission C" / "Isolated agent instance"
   - Wide box: "Experience extraction and independent evaluation" / "Knowledge · Skills · Processes · Agent code"
   - Final (no border): "New verified agent baseline" / "Promoted only after improvement is demonstrated and required approvals pass"
4. Icons: git-branch, bot (x3), arrow-down.
5. Palette: bg #0D0D0D; card border #2A2A2A; text #F2F2F2; sub #BDBDBD.
7. Requirements: N isolated instances (A,B,C...), extraction of knowledge/skills/processes/agent code, independent evaluation, promotion requires proven improvement and approvals.

## 12.png
1. "AXoR Autonomous Company OS — Luxury UI Screen Atlas" poster, 1448x1086. Dark luxury black + gold theme (gold #D4A642 / #F0C85A outlines, glassy black panels, gold gradient glows, serif-gold title). Tagline top-right in laurel wreath: "The Autonomous Company OS for Infinite Execution". Top-left logo "AXoR" (gold triangle mark + serif wordmark). Title (serif gold) "AXoR Autonomous Company OS — Luxury UI Screen Atlas". 12 screens in 3 columns x 4 rows (each ~33% x 24%), each framed with a 1px gold border, radius ~10px, subtle gold glow; caption below each in white: "<n>. <Title> — <description>". AI-rendered, text partly illegible; values best-effort.
Common chrome (screens 1,2): top bar with logo "AXoR", "Autonomous Company OS", search (magnifier), bell, gear, avatar; left sidebar (Home [gold active pill], Agents, Control, Versions, Evolution, Finance, Governance; on screen 2 Missions appears as active). Panel titles end with a gold "(?)" circular help icon. Mission-control screens (4-7) use header "Mission Control (?)", "Mission: M-473  Product v3.2 Release", green pill "Running 78%", and a 4-tab bar with icons: "Task Flow" (list icon), "Agent Graph" (nodes icon), "Conversations" (chat icon), "Approvals & History" (doc/shield icon); active tab = gold-outlined with gold tint.

### 1. Company Overview — Executive Dashboard
"Company Overview (?)" date "Jan 28, 2025 · Tue 14:26". KPI cards: "Revenue (MTD)" "$2.48M" "▲ +12.6%" (green); "Cost (MTD)" "$0.74M" "▲ -8.3%" (green); "Active Missions" "18" "(14 Running)"; "Success Rate" "96.2%" "▲ +2.1 pp". "System Health (?)": gold donut "98%" with checklist "Agents Online 24 / 24", "Task Queue 132 (▲ -18%)", "Model Router OK", "Infra & Tools OK". "Organization Health (?)": radar/pentagon chart (gold) with legend dots: Execution 97%, Quality 96%, Collaboration 95%, Learning 94%, Efficiency 96%. "Active Missions (3) (?)": "M-473 Product v3.2 Release" 78% (green bar), "M-471 Customer Insight Study" 62% (yellow), "M-468 Cost Optimization" 41% (yellow). "Decision Inbox (4) (?)": red dot "Approve: Model Upgrade (Eng)"; orange dot "Select: Design Option (M-471)"; orange "Budget: +$50K (M-468)". "Quick Actions (?)": three round gold-outline icon buttons (play, people/team, document/note). "Recent Activity (?)": green dot "14:20 Finance Agent submitted cost report (M-468)."; green "14:05 QA Agent reported 2 issues (M-471) — awaiting decision."; orange "13:47 Research Agent completed market analysis (M-471)."

### 2. Mission List — Missions, Progress, Issues & Editions
"Mission List (?)"; right controls: dropdown "All Missions", search, filter (funnel), list-view icon, gold "+" button. Table columns: ID | Mission Title & Summary | Progress | Issues | Pending | Output (Ver.) | Completion | Next Edition | Status. Rows:
- M-473 "Product v3.2 Release" / "Release v3.2 with new features & fixes." 78% (gold bar) issues 2 (red) pending 1 (orange chip) v0.9.3 "Jan 30, 17:00" "Feb 06, 10:00" Running (green pill)
- M-471 "Customer Insight Study" / "Market & user analysis for Q1 strategy." 62% issues 0 pending 2 v0.4.1 "Feb 02, 12:00" "Feb 09, 12:00" Running
- M-468 "Cost Optimization" / "Reduce infra & tool cost by 215%." 41% issues 1 pending 1 v0.3.0 "Feb 01, 18:00" "Feb 08, 18:00" Running
- M-465 "AI Model Routing Upgrade" / "Improve model selection & cost." 100% (green) 0 0 v1.0.0 "Jan 26, 14:00" "–" Completed (blue pill)
- M-460 "Agent Evolution v2" / "Self-renewal & performance boost." 100% 0 0 v2.0.0 "Jan 20, 16:00" "–" Completed
- M-457 "New Market Exploration" / "Explore EU market & entry plan." 12% (red-ish bar) 0 0 v0.1.0 "Feb 10, 10:00" "Feb 17, 10:00" Planned (grey pill)
Footer legend chips: "All (18)", "Running (14)" green, "Pending User (4)" orange, "Completed (3)" blue, "Planned (1)" grey, "Issue (3)" red.

### 3. Add Mission Modal — Create a New Mission
Dimmed screen behind; modal "+ Add Mission (?)" with close X. Fields: "Mission Title *" value "Launch AI Marketing Campaign"; "Mission Summary *" textarea "Plan, create, and launch an AI-driven marketing campaign for the new product, including strategy, assets, A/B tests, and performance analysis."; "Attachments (?)": 4 square type buttons "Text" (T), "Docs", "Images", "GitHub" (selected/gold outline); URL input "https://github.com/axor-ai/marketing-campaign"; gold checkbox (checked) "No repository? (?)" + "AXoR can create a new GitHub repo automatically (e.g., axor-ai/marketing-campaign) upon start."; row of selects: "Budget (?)" "$ 100,000", "Duration (Target) (?)" "14 days" (calendar icon), "Priority (?)" "High" (bars icon), "Team/Scope (?)" "Marketing (Auto)" (people icon); "Advanced Options ˅"; buttons "Cancel" (dark outlined) and "▶ Start Mission" (gold filled, dark text).

### 4. Mission Control / Task Flow — Task Flow, Dependencies & Blockers
Tab Task Flow active. "Overall Progress" gold bar "78%"; stat cells: "Tasks 24 / 31", "Issues 2" (red), "Blockers 1" (red), "Pending User 1" (gold). Phase pipeline with gold arrows between 5 phase cards: "1 Planning ✓ 100%" (children: green check "Requirements", "Scope & Plan"); "2 Design ✓ 100%" ("UX/UI Design", "Design Review"); "3 Development 76%" (mini bars "Feature Impl. 86%", "Integration 70%"); "4 QA 60%" (bar "Test & QA 80%", red chip "Fix Issues 2"); "5 Release 0%" (unchecked checkboxes "Packaging", "Deploy", "Announce"). Bottom 3 panels: "Dependencies (?)": "QA depends on Development (In Progress)", "Release depends on QA (Blocked: 1 issue)"; "Current Blockers (1) (?)": red dot "Critical: Test failure on payment flow (Assigned: QA Agent)"; "Issue Summary (?)": Total 2 / Open 2 (orange) / Resolved 0 (green).

### 5. Mission Control / Agent Graph — Hierarchy, Relations & Agent Details
Tab Agent Graph active. Tree: top node (gold border) "General Manager (GM)" "● Online | Orchestrating" (golden helmet-robot avatar); connectors to 6 agent cards with distinct robot-helmet avatars: "Product Agent ● Running" (blue, cube icon), "Engineering Agent ● Running" (blue, </> icon; highlighted/selected with gold border), "Design Agent ● Running" (purple, pencil icon), "QA Agent ● Busy" (orange, shield icon), "Finance Agent ● Online" (green, coins icon), "Operations Agent ● Running" (gold, gear icon). Sub-nodes under Engineering: "Dev-1 (Feature) ● Run", "Dev-2 (Integration) ● Run", "Dev-3 (Tooling) ● Run". Right panel "Selected Agent": avatar, "Engineering Agent (ID: ENG-01)", rows: Status "● Running"; Role "Lead development & integration"; Current Task "Implement v3.2 features"; Progress "76%" (gold bar); Load "6 / 8 tasks"; Model "Claude 3.5 Sonnet"; four small icon buttons at bottom (chat, settings gear, branch/network, people).

### 6. Mission Control / Conversations — Multi-Level Agent Communications
Tab Conversations active. Left list with dropdown "All Conversations", search, list icons; threads (avatar, title, hashtag sub, time): "GM ⇌ All Agents" "# orchestration, status" 14:20 (selected gold); "Me ⇌ Engineering" "# feature, progress" 14:05; "QA ⇌ Engineering" "# test, issue" 13:58 (red unread badge); "Me ⇌ GM" "# approval, budget" 13:47; "Design ⇌ Product" "# UI, iteration" 13:33; "Finance ⇌ GM" "# cost, forecast" 13:10. Right chat: header "GM ⇌ All Agents" "Mission: M-473 | Scope: Product v3.2 Release" with copy and list icons; message "GM 14:20": "Team, here is the latest status for M-473: • Overall progress: 78% (▲ +6 pp) • 2 open issues (QA) • 1 item awaiting user approval (design option) Please prioritize the QA fixes and prepare the v0.9.4 output."; message "QA Agent 14:20": "Acknowledged. We are fixing the 2 issues now. ETA: within 3 hours."; copy icon on each message; composer: "+" button, input "Message to GM / All Agents...", gold send arrow button.

### 7. Mission Control / Approvals & History — Decisions, Options & Audit Trail
Tab Approvals & History active. Left "User Decision Queue (3) (?)": "Select Design Option" / "M-471 | Design Agent" / "Today 14:05" red "(High)" (selected, gold, pencil icon); "Approve Model Upgrade" / "M-471 | GM" / "Today 13:50" (briefcase icon); "Budget Increase (+$50K)" / "M-468 | Finance Agent" / "Today 13:32" (coins icon). Centre "Decision: Select Design Option (?)": 3 option cards with letter badges: "A Minimal — Clean & efficient" (dark screenshot), "B Modern (Rec.) — Rich & engaging" (selected gold, light screenshot), "C Bold — Brand focused" (purple screenshot). "Your Input / Comment (?)": textarea "Go with Option B. It best aligns with our brand and v3.2 goals."; attachment chip "mockup_b.png (1.2 MB)" with X; red X (reject) and gold check (approve) square buttons. Right "History (?)": green ✓ "Approved: v0.9.3 Jan 27, 16:20"; green ✓ "Approved: Scope Update Jan 26, 11:08"; red ✗ "Rejected: Design (v1) Jan 25, 15:44"; green ✓ "Approved: Budget +$20K Jan 24, 10:13".

### 8. Versions & Preview — Versions, Release Notes & Branch/Merge
Header "Versions & Preview (?)  Mission: M-473 Product v3.2 Release". Left "Versions / Branches (?)": tree: "main (Baseline)" [badge Baseline] > "v1.0.0"; "M-473 (Mission Branch)" > "v0.9.4" [green badge "Latest", selected gold], "v0.9.3", "v0.9.2", "v0.9.1"; "M-471 (Branch)" > "v0.4.1"; "M-468 (Branch)" > "v0.3.0". Centre: "Version: v0.9.4 [Latest] (?)", chips "Branch: M-473", "From main@v1.0.0", "Feb 06, 10:00 (Next)"; "Release Notes (?)": "• Implemented feature: smart onboarding. • Fixed 2 issues (auth, page loading). • Improved performance (~18%). • Updated UI based on user feedback."; "Output & Actions (?)": buttons "Download Output (ZIP, 48.3 MB)" (download icon) and "▶ Run Preview" (gold play). Right "Branch & Merge Graph (?)": node "main (v1.0.0)" gold, three child nodes "M-473 (v0.9.4)" (blue highlighted), "M-471 (v0.4.1)", "M-468 (v0.3.0)", merging into bottom gold node "Merge (→ main v1.1.0)".

### 9. Agent Profile & Multi-Mission Branches — Parallel Instances & Experience Merge
Header "Agent Profile (?)  Agent: Engineering Agent (ENG-01)". Tabs with icons: "Profile", "Multi-Mission Branches" (active), "Skills & Knowledge", "Mentoring", "Verifier". Left card: blue robot avatar, "Engineering Agent (ENG-01)", "● Active"; rows: Role "Engineering (Development)"; Model "Claude 3.5 Sonnet"; Perf. (30d) "96.8% ▲ +2.4 pp"; Experience "1,240 exp"; Mentor "Senior Engineer (Ver. AG-01)"; Verifier "QA Agent (QA-01)". Centre "Multi-Mission Branches (Parallel & Isolated) (?)": base agent node "ENG-01 (Base Agent) v2.3" with gold arrows to three instance cards: "M-473 (Instance) Feature Dev [Running 76%]" (blue border), "M-471 (Instance) Integration [Running 62%]" (purple border), "M-468 (Instance) Tooling [Running 41%]" (green border); arrows loop to right box "Experience Merge (?)": "On completion, learnings from all instances are merged back to the base agent (ENG-01)." with gold merge-icon button. Footer green checks: "Parallel execution (isolated)", "No cross-contamination", "Auto-merge after completion".

### 10. Evolution Lab — Self-Renewal, Benchmark & Promotion
Header "Evolution Lab (?)". Tabs: "Self-Renewal" (active), "Benchmark", "Updates (Code/Prompt/Tool)", "Verifier", "Promotion". Left "Self-Renewal Proposal (?)": "Proposal: ENG-01 → v2.4", "Goal: Improve coding quality and task completion speed."; green-check rows: "Code Update — Refactor task planner", "Prompt Update — Better decomposition", "Tool Update — Add code-search tool", "Verifier Agents — QA-01, PERF-01". Centre "Benchmark: Old vs New (?)": table Metric | v2.3 (Current) | v2.4 (Candidate) | Δ: "Task Success Rate 96.1% 97.8% +1.7 pp"; "Avg. Completion Time 42.5 min 36.1 min -15.1%"; "Output Quality (Score) 92.6 95.4 +2.8"; "Tool Usage Efficiency 88.3% 93.7% +5.4 pp" (deltas green). Right "Promotion Decision (?)": green box "✓ Performance improves (All key metrics ↑)"; "Promote to v2.4?"; gold button "✓ Promote"; dark button "✕ Keep v2.3". Bottom banner (laurel icon): "Verifier Result: PASS" (green) "The new version (v2.4) shows a clear performance improvement. Promotion is recommended."

### 11. Appearance Studio — Agent Avatar Customization & Styling
Header "Appearance Studio (?)  Agent: Engineering Agent (ENG-01)". Left "Preview (Live) (?)": large golden-lit robot avatar in gold circle, name "Engineering Agent (ENG-01)", three small buttons (reset/undo/target). Tabs: Face (active), Color, Style, Expression, Frame, Glow. "Face Format (?)": 4 tiles "Human-like", "Robot (Rec.)" (selected gold), "Mascot", "Abstract". "Color (Primary) (?)": 6 swatches (gold with check [selected], blue, purple, pink, green, cyan). "Mode (?)": segmented "Bright", "Luminous (Rec.)" (selected), "Fancy". "Style (?)": 5 round face icons "Friendly/Serious-like..." labels ~"Professional, Playful?, Confident (Rec.) (selected), Focused, Friendly". Right "Frame": 3 ring options (middle selected); "Glow Level (?)" slider gold at "80%"; "Expression (?)": 4 smiley tiles "Neutral", "Confident (Rec.)" (selected), "Focused", "Friendly"; gold button "✓ Apply".

### 12. Finance, Governance & Model Routing — Budgets, Policies, Model Assignment & Audit
Header "Finance, Governance & Model Routing (?)". Tabs: "Budget & Cost" (active), "Governance", "Model Routing", "Audit Log". "Budget & Cost Overview (?)": cards "Total Budget (Q1)" "$5.00M"; "Spent" "$1.86M"; "Remaining" "$3.14M" (green "(62.8%)"). "Cost by Department (MTD) (?)": gold bars: Engineering $281K, Design $98K~, QA $87K~, Operations $78K~, Research $79K~, Finance $51K. "Policy & Autonomy (?)": gold toggles "Agent Autonomy (Execute w/o approval)" ON, "Self-Renewal (Evolution)" ON; dropdown "Budget Limit per Mission" "$250,000"; dropdown "Approval Policy" "High-Risk Only". "Model Loader / Router (?)": table Agent / Role | Assigned Model: "GM (Orchestration) GPT-4o", "Engineering (Coding) Claude 3.5 Sonnet", "Research (Analysis) Gemini 2.0 Pro", "Design (Creative) GPT-4o", "QA (Testing) Claude 3.5 Haiku", "Finance (Calculation) GPT-4o-mini" (dropdown chevrons). "Audit Log (Recent) (?)" with button "View All": "14:18 Model route updated: Engineering → Claude 3.5 Sonnet"; "13:55 Policy change: Approval Policy → High-Risk Only"; "13:40 Self-Renewal enabled (global)".

4. Icons: gold-outline line icons; "(?)" circular help; avatars are 3D-rendered helmet robots in per-agent colours (GM gold, Engineering blue, Product blue, Design purple, QA orange, Finance green, Operations gold); status dots green/orange/red.
5. Palette: page #070707 near-black with warm gradient #1A140A edges; panel #0E0E10 -> #141211 with gold border #B8892B (1px) and glow #F0C85A at ~25%; gold accent #E6B84A / gradient #F4D27A→#C58F25; text white #F5F0E6 / muted #A89F8D; green #3CCB6C; red #E5484D; orange #F08C2B; blue #3B82F6; purple #8B5CF6.
6. Typography: serif luxury display (Cinzel/Trajan style) for title/logo in gold gradient; UI text clean sans (Inter), 10-13px; subtle inner shadows, thin gold rules, rounded 10px, glassy gradient panels, gold-tinted active states, cards with soft gold shadow.
7. Requirements: luxury gold dark theme across 12 screens listed above; Home dashboard with revenue/cost/missions/success KPIs, health donut, org-health radar, decision inbox, quick actions, activity feed; mission list table with legend filter chips; add-mission modal with attachment types (Text/Docs/Images/GitHub), auto-create GitHub repo, budget/duration/priority/team; Mission Control tabs (Task Flow, Agent Graph, Conversations, Approvals & History); Versions & Preview with branch tree, release notes, ZIP download, run preview, branch/merge graph; Agent Profile multi-mission isolated instances with experience merge; Evolution Lab self-renewal, benchmark old vs new, verifier result, promote/keep; Appearance Studio avatar customisation (face, colour, mode, style, expression, frame, glow slider, live preview, Apply); Finance/Governance/Model Routing with budgets, autonomy toggles, per-agent model assignment, audit log; every panel has "?" help icon.
