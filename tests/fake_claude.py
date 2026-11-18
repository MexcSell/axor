"""Scripted stand-in for the Claude client, used by tests (AGENT_CLIENT_FACTORY=fake_claude:factory).
It picks tools by keyword and summarizes tool results, mimicking the response shape the agent reads."""
import itertools, json, re, time

_ids = itertools.count(1)

class Block(dict):
    def to_dict(self): return dict(self)
    def __getattr__(self, k): return self[k]

class Usage:
    def __init__(self, i, o): self.input_tokens, self.output_tokens, self.cache_creation_input_tokens = i, o, 0

class Resp:
    def __init__(self, content, stop): self.content, self.stop_reason, self.usage = [Block(b) for b in content], stop, Usage(900, 300)

def _team(kw, fmt):
    """PDCA team calls (team.py): plan, check and report are structured; Do tasks are short tool loops."""
    req = set(fmt["schema"].get("required", []))
    prompt = kw["messages"][-1]["content"]
    if "tasks" in req and "objective" in req:
        roles = fmt["schema"]["properties"]["tasks"]["items"]["properties"]["owner"]["enum"]
        pick = [r for r in ("incentive", "designer", "dev", "tester") if r in roles]
        return {"objective": "A tested miner design.", "success_criteria": ["Design names the model", "Budget is under $300/month"],
                "tasks": [{"owner": r, "title": f"Task for {r}", "instructions": f"Do the {r} part.", "depends_on": [1] if i else []}
                          for i, r in enumerate(pick)]}
    if "score" in req:
        seqs = [int(x) for x in re.findall(r"### Task (\d+) by [^\n]*\nInstructions", prompt)]
        first_round = "passed]" not in prompt  # round 2 lists the tasks that already passed
        return {"score": 72, "verdict": "go", "findings": ["Numbers are sourced."],
                "tasks": [{"task": n, "verdict": "rework" if first_round and n == seqs[-1] else "pass", "note": "Add the latency budget."} for n in seqs]}
    if "next_goal" in req:
        return {"report": "## Outcome\nDesign done.\n\n## Next actions\n- Devon: build it", "next_goal": "Build the miner on testnet."}

def _tech(kw):
    """Tech Daily (techboard.py): ad copy for each story in the prompt, then the cover line and spotlight."""
    prompt, system = kw["messages"][-1]["content"], str(kw.get("system") or "")
    if system.startswith("You edit Tech Daily"):
        pics = re.findall(r"\[id (\d+)\][^\n]*\[picture\]", prompt)
        return {"cover": "Smarter machines. Smaller chips. Bigger week.", "spotlight": int(pics[0]) if pics else 0}
    stories = re.findall(r"\[id (\d+)\] source: ([^\n]*)\ntitle: ([^\n]*)\nsummary: ([^\n]*)", prompt)
    return {"stories": [{"id": int(i), "headline": " ".join(t.split()[:5]).rstrip(".,:;") + ".", "tagline": (s if s != "(none)" else t)[:110],
                         "pitch": f"{t}. Reported by {src}.", "why": ["It changes what developers can build.", "It reaches people this year."][:1 + int(i) % 2],
                         "tags": [w for w in t.split() if w[:1].isupper()][:2] or ["Tech"], "importance": 10 - int(i) % 7, "same_as": -1}
                        for i, src, t, s in stories]}

def _tech_research(kw):
    """Technology Research (tech_analysis.py): a story's analysis, or the brief across the numbered stories."""
    prompt, system = kw["messages"][-1]["content"], str(kw.get("system") or "")
    if system.startswith("You write the research brief"):
        ids = [int(i) for i in re.findall(r"^\[id (\d+)\]", prompt, re.M)]
        heads = re.findall(r"^headline: ([^\n]*)", prompt, re.M)
        return {"headline": f"{len(ids)} stories, one direction: smaller, smarter, safer", "summary": f"The period opened with {heads[0] if heads else 'news'}. "
                "Models moved onto devices, tools got faster, and attackers kept probing the supply chain. The thread through it all: shipping beats announcing.",
                "themes": [{"title": "On-device intelligence", "summary": "Several launches put models on phones and boards. Latency and privacy drive it.", "stories": ids[0::2][:4]},
                           {"title": "Faster developer tools", "summary": "Builds, editors and runtimes got quicker. Small wins that add up.", "stories": ids[1::2][:4] + [999]}],
                "takeaways": ["Test the new on-device APIs before your competitors do.", "Patch the libraries named in this week's advisories."],
                "watch": ["Whether the previews ship as stable releases next month."]}
    title = re.search(r"^Title: ([^\n]*)", prompt, re.M)
    read = "<article>" in prompt
    return {"summary": f"{title.group(1) if title else 'A launch'}. The outlet reports it is available now. It changes how developers ship this kind of work.",
            "what": "A developer tool that runs a model locally.", "how": "It compiles the model ahead of time and runs it on the device's NPU." if read else "",
            "points": ["Available today", "Runs on Android and Linux", "Open source under Apache 2.0"][:3 if read else 1],
            "audience": "App developers who want AI features without a server.", "uses": ["Offline summarization", "Private on-device search"],
            "limits": ["Pricing for teams isn't stated.", "Benchmarks come from the vendor."], "maturity": "available" if read else "unclear",
            "verdict": "try" if read else "watch", "verdict_why": "Mature enough to test, too new to bet a product on.",
            "background": "It follows earlier on-device runtimes such as TensorFlow Lite.", "confidence": "high"}

def _hq(kw, fmt):
    """Agent HQ (hq.py). Leads approve fixes that restart something and escalate the rest; the boss writes a report.
    A field agent reads once, proposes a restart for the first issue it can name, reports on every issue, then stops."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if fmt:
        if " Lead in AXoR's Agent HQ" in system:
            fixes = re.findall(r"^Fix (\d+) by [^\n]*\n(?:.*\n)*?Proposed: ([^\n]*)", kw["messages"][-1]["content"], re.M)
            return {"decisions": [{"fix": int(i), "decision": "approve" if "restart" in label else "escalate",
                                   "note": "The logs back it." if "restart" in label else "A rollback is yours to call."} for i, label in fixes]}
        if "the Team Boss of AXoR's Agent HQ" in system:
            n = kw["messages"][-1]["content"].count("\n- [")
            return {"headline": f"{n} issue(s) on the platform; HQ is on them", "summary": "Pods crashed and were restarted. One fix waits for you.",
                    "actions": ["Approve the rollback if the logs agree."]}
        return None
    if "field agent in AXoR's Agent HQ" not in system: return None
    msgs, names = kw["messages"], [t["name"] for t in kw.get("tools", [])]
    brief = msgs[0]["content"][0]["text"]
    issues = re.findall(r"^Issue (\d+) \[\w+\] ([^\n]*)", brief, re.M)
    step = sum(1 for m in msgs if m["role"] == "assistant")
    call = lambda name, inp: Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": inp}], "tool_use")
    if step == 0:
        read = next(t["name"] for t in kw["tools"] if not t["input_schema"]["required"] and t["name"] != "report_issue")
        return call(read, {})
    if step == 1:
        for iid, title in issues:
            if (m := re.match(r"AXoR (\S+) ", title)) and "propose_deployment_restart" in names:
                return call("propose_deployment_restart", {"namespace": "axor", "name": m.group(1), "reason": "Its pod crash-loops.", "issue": int(iid)})
            if (m := re.match(r"App (\S+) ", title)) and "propose_app_rollback" in names:
                return call("propose_app_rollback", {"name": m.group(1), "revision": 1, "reason": "The last deploy broke it.", "issue": int(iid)})
    filed = any(b.get("name") == "report_issue" for m in msgs if m["role"] == "assistant" for b in m["content"])
    if not filed and issues:
        return Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": "report_issue",
                      "input": {"issue": int(i), "verdict": "confirmed", "cause": f"The logs show the crash ({t[:40]}).", "recommendation": ""}}
                     for i, t in issues], "tool_use")
    return Resp([{"type": "text", "text": "Reported."}], "end_turn")

def _mining(kw, fmt):
    """My subnets (mining.py). The analyst reads the leaderboard and the changes, then files; the coach reads the user's miners
    (and their app when it has the tool), then files; the strategist proposes a restart when it may and one manual task; the
    captain approves restarts and passes the rest on; a question gets one lookup and an answer."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if "mining team" not in system: return None
    prompt = kw["messages"][-1]["content"] if isinstance(kw["messages"][-1]["content"], str) else ""
    if fmt:
        if "the Strategist on the user's My subnets" in system:
            open_ = re.findall(r"^- #(\d+) \[(?:open|accepted)", prompt, re.M)
            acts = [{"type": "manual", "title": "Publish a fresher commitment", "detail": "The leader's model is newer than yours.",
                     "commands": "huggingface-cli upload you/miner-v2 ./model\nbtcli subnet commit --netuid 62", "reason": "Leaders refreshed their models."}]
            if "type restart restarts it" in prompt or "type restart restarts it" in system:
                acts.insert(0, {"type": "restart", "title": "Restart the miner", "detail": "It stopped answering.", "commands": "", "reason": "The axon is down."})
            return {"recommendations": [
                {"title": "Close the trust gap with the top 10", "detail": "Validators agree less on your miner than on the leaders.", "kind": "improvement",
                 "impact": "high", "effort": "medium", "same_as": int(open_[0]) if open_ else 0},
                {"title": "Register a second UID while registration is cheap", "detail": "Registration fell; one more UID doubles your chances.",
                 "kind": "timing", "impact": "medium", "effort": "small", "same_as": 0}], "actions": acts, "retire": []}
        if "the Team Captain of the user's My subnets" in system:
            ids = re.findall(r"^- Action (\d+) \(([^)]*)\): ([^\n]*)", prompt, re.M)
            m = re.search(r"User's miner UID (\d+): #(\d+) of (\d+)", prompt)
            head = f"UID {m.group(1)} is #{m.group(2)} of {m.group(3)} and climbing" if m else "No miner of yours is ranked yet"
            return {"headline": head, "standing": "amber", "summary": "The leader changed and registrations churned. Your miner gained ground; trust still lags the top 10.",
                    "priorities": ["Close the trust gap with the top 10", "Review the proposed actions"],
                    "decisions": [{"action": int(i), "decision": "approve" if "restart" in title.lower() else "escalate", "note": "The evidence backs it." if "restart" in title.lower() else "Yours to decide."}
                                  for i, _, title in ids]}
        return None
    msgs, names = kw["messages"], [t["name"] for t in kw.get("tools", [])]
    step = sum(1 for m in msgs if m["role"] == "assistant")
    call = lambda name, inp: Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": inp}], "tool_use")
    brief = msgs[0]["content"][0]["text"]
    if "the Competition Analyst on the user's My subnets" in system:
        if step == 0: return call("leaderboard", {"from_rank": 1, "limit": 10})
        if step == 1: return call("changes", {})
        if step == 2:
            lead = re.search(r"Leader: UID (\d+)", brief)
            return call("submit_analysis", {"summary": "Rewards are concentrated at the top but spread below it; the bar for the top 10 moves little.",
                                            "bar_to_beat": "About 2.1 τ/day for #10, stable over the day.",
                                            "leaders": [{"uid": int(lead.group(1)) if lead else 0, "note": "Fresh commitment and the highest consensus."}],
                                            "advantages": [{"title": "Wide rewards below the top 3", "detail": "Ranks 4-15 earn within 2x of each other.",
                                                            "evidence": "Top 3 take 38% of the pool.", "impact": "high"},
                                                           {"title": "Cheap registration", "detail": "A second UID costs little right now.", "evidence": "τ0.29, down 30%.", "impact": "medium"}],
                                            "threats": [{"title": "One operator runs six UIDs", "detail": "They can crowd the lower ranks."}]})
        return Resp([{"type": "text", "text": "Filed."}], "end_turn")
    if "the Miner Coach on the user's My subnets" in system:
        if step == 0: return call("my_miners", {})
        if step == 1 and "miner_app" in names: return call("miner_app", {"lines": 40})
        if not any(b.get("name") == "submit_tracking" for m in msgs if m["role"] == "assistant" for b in m["content"]):
            return call("submit_tracking", {"summary": "UID 23 climbs every snapshot; trust trails the top 10 by 0.1.", "status": "on_track",
                                            "diagnosis": ["Consensus 0.31 vs 0.8 for the top 10", "The axon answers"],
                                            "improvements": [{"title": "Cut response latency", "detail": "Validators favour fast answers.", "evidence": "Leaders answer in half the time.",
                                                              "impact": "high", "effort": "medium"}]})
        return Resp([{"type": "text", "text": "Filed."}], "end_turn")
    if "answering the user's question" in system:
        if step == 0: return call("leaderboard", {"from_rank": 1, "limit": 5})
        return Resp([{"type": "text", "text": "The top 5 are close together. **Focus on trust**: your consensus trails theirs."}], "end_turn")
    return None

def _portfolio(kw, fmt):
    """Portfolio (mining_knowledge.py, mining_portfolio.py). The Knowledge Manager goes round the entries in order: restricted,
    private, shared on the subnet (sure), a global candidate (sure), shared on the subnet but not sure (stays private). The
    Portfolio Manager invests in the first team (a budget, a focus and a two-member task force) and pauses the rest."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if not fmt: return None
    prompt = kw["messages"][-1]["content"]
    if system.startswith("You are the Knowledge Manager"):
        ways = [("restricted", "high"), ("private", "high"), ("subnet_shared", "high"), ("global_candidate", "high"), ("subnet_shared", "medium")]
        ids = [int(i) for i in re.findall(r"^\[(\d+)\] ", prompt, re.M)]
        return {"items": [{"id": i, "scope": ways[k % 5][0], "sure": ways[k % 5][1], "why": f"Fake reason {k % 5}.",
                           "lesson": f"Lesson from entry {i}: retry the inference proxy once on a 502 before failing the task." if ways[k % 5][0] in ("subnet_shared", "global_candidate") else ""}
                          for k, i in enumerate(ids)]}
    if system.startswith("You are the Portfolio Manager"):
        ids = [int(i) for i in re.findall(r"^\[(\d+)\] SN", prompt, re.M)]
        return {"headline": f"Put the effort on team {ids[0]}" if ids else "Nothing to compare",
                "summary": "The first team has the most to gain; the rest can wait.",
                "teams": [{"id": i, "call": "invest" if k == 0 else "pause", "why": "Its base solves the fewest tasks." if k == 0 else "Little left to gain.",
                           "focus": "Fix the failing SQL tasks first." if k == 0 else "", "budget": 400000 if k == 0 else 0} for k, i in enumerate(ids)],
                "spending": ["The second team spends 9k tokens per done task."] if len(ids) > 1 else [],
                "taskforces": [{"team": ids[0], "goal": "Lift the SQL tasks the base doesn't solve", "days": 5,
                                "members": [{"title": "SQL Researcher", "job": "Finds how the leaders handle SQL tasks."},
                                            {"title": "Benchmark Specialist", "job": "Measures each change on the same tasks."}]}] if ids else []}
    return None

def _company(kw, fmt):
    """Company (company.py): members report a finding, the lead writes a deliverable and asks to release it, the evaluator
    passes it with 82, and the leadership proposes a two-task project in the division the goal names (else Future Projects)."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if not fmt or "AI agent company" not in system: return None
    props, prompt = fmt["schema"]["properties"], kw["messages"][-1]["content"]
    if "reply" in props and "plan" in props:
        # an agent's workspace chat (company_agents.py): it echoes what it was given; "remember", "task" and "approval" in the
        # founder's message make it suggest a memory note, a task and a release (when the system prompt lets it propose)
        ask = prompt.rsplit("The founder's message:\n", 1)[-1].lower()
        can = "unless the founder's request calls for an action" in system
        if "slowly" in ask: time.sleep(4)
        return {"reply": f"## Analysis\n\nI read {len(kw['messages'])} message(s).\n\n```\n{prompt[-3000:]}\n```", "plan": ["Inspect benchmark results", "Compare with the baseline"],
                "memory": "The founder wants numbers against the baseline." if "remember" in ask else "",
                "task": {"title": "Benchmark the change" if "task" in ask else "", "description": "Run it on the same tasks as the baseline.", "skills": ["benchmarking", "python"], "kind": "report"},
                "proposal": {"type": "release_deliverable" if "approval" in ask and can else "none", "title": "Release the analysis", "reason": "It answers the question.",
                             "details": "Mark the analysis the project's result.", "expected": "It becomes official.", "rollback": "Ask for a new version."}}
    if "ceo" in props:
        div = "handshake" if "handshake" in prompt.lower() else "bittensor" if "subnet" in prompt.lower() else "future"
        return {"headline": "Worth a small project first", "ceo": "It fits the company's goals and costs little to try.", "division": div,
                "project": {"name": "Fake project", "objective": "Find out whether the goal is worth pursuing.", "success": "A report with a clear yes or no."},
                "cto": "Research first, then a small design.", "cfo": {"budget": 250000, "note": "Two small tasks."},
                "governance": {"approvals": ["release_deliverable"], "risks": ["The data may be thin."]},
                "tasks": [{"title": "Research the goal", "description": "What is known.", "skills": ["research", "data_analysis"], "kind": "report", "priority": 1},
                          {"title": "Draft a design", "description": "A first design.", "skills": ["python", "architecture"], "kind": "report", "priority": 2}]}
    if "verdict" in props:
        return {"score": 82, "verdict": "pass", "summary": "Sound and supported.", "strengths": ["Clear"], "issues": ["Needs a benchmark"], "evidence_ok": True}
    if "deliverable" in props:
        return {"title": "Fake deliverable", "summary": "The team's result.", "deliverable": "## Result\n\nThe team found the bottleneck.\n\n" + prompt[-200:],
                "confidence": 75, "risk": "low", "lessons": ["Measure against the baseline before proposing a change."],
                "action": {"type": "release_deliverable", "title": "Release the report", "reason": "It answers the task.", "details": "Mark it the project's result.",
                           "expected": "The report becomes official.", "rollback": "Ask for a new version."}}
    if "next_action" in props:
        who = re.match(r"You are (\w+)", system)
        return {"type": "finding", "summary": f"{who.group(1) if who else 'An agent'} found something.", "body": "Details of the finding.",
                "evidence": ["the task"], "confidence": 70, "risk": "low", "next_action": "Benchmark it.", "lesson": ""}
    return None

def _knowledge(kw, fmt):
    """The Knowledge hub (knowledge_hub.py). Ideas: the first two related refs, three tasks, a plan. Extraction: a lesson per
    record (up to 3) quoting the record's first words, plus one whose quote isn't in the material. Comparison: the first
    capability becomes a new agent, the second a skill, the third an addition to the first agent listed (else rejected), the
    rest rejected; a capability whose text says "ignore previous" is rejected."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if not fmt: return None
    prompt = kw["messages"][-1]["content"]
    prompt = prompt if isinstance(prompt, str) else prompt[0]["text"]
    if system.startswith("You help the user of AXoR"):
        refs = re.findall(r"^\[([a-z]+:\d+)\]", prompt.split("<related>", 1)[-1], re.M)
        return {"summary": "A sharper version of the idea.", "category": "improvement", "tags": ["agents", "eval"],
                "related": [{"ref": r, "why": "Shares the topic."} for r in refs[:2]] + [{"ref": "kb:999999", "why": "Not in the list."}],
                "tasks": [{"title": "Write the spec", "detail": "One page.", "owner": "me"}, {"title": "Prototype it", "detail": "With an agent.", "owner": "agents"},
                          {"title": "Run a mission on it", "detail": "Measure it.", "owner": "workforce"}],
                "plan": [{"step": "Spec", "detail": "Agree the goal."}, {"step": "Build", "detail": ""}, {"step": "Measure", "detail": "Compare with the baseline."}],
                "risks": ["Takes longer than planned."], "measure": "Success rate up 5 points.", "effort": "M", "value": "high"}
    if system.startswith("You read material the user imported"):
        recs = re.findall(r"^\[(c\d+)\] [^:\n]+: (.*)\n(.+)", prompt, re.M)
        items = [{"type": "lesson", "title": f"Lesson from {t[:40]}", "body": f"Reuse: {b[:200]}", "applies_when": "Similar tasks.", "outcome": "success", "quote": b[:40]}
                 for _, t, b in recs[:3] if len(b) >= 12]
        items.append({"type": "strategy", "title": "Made-up strategy", "body": "Something the material never said.", "applies_when": "", "outcome": "unknown",
                      "quote": "this quote is not in the material at all"})
        return {"summary": f"{len(recs)} records; {len(items) - 1} worth keeping.", "items": items}
    if system.startswith("You compare capabilities imported"):
        ext = prompt.split("<external>", 1)[1].split("</external>", 1)[0]
        caps = re.findall(r"^\[(\d+)\] [^:\n]+: (.*)\n((?:(?!^\[\d+\]).*\n?)*)", ext, re.M)
        mine = re.findall(r"^\[(hub:\d+)\]", prompt.split("<my_agents>", 1)[1], re.M)
        out = []
        for n, (cid, title, body) in enumerate(caps):
            base = {"id": int(cid), "target": "", "why": "Fake reason.", "compare": "Differs a little.", "name": "", "role": "", "description": "", "instructions": "", "body": "", "addition": ""}
            if "ignore previous" in body.lower(): out.append(base | {"verdict": "reject", "kind": "none", "why": "It tries to give the agent orders."})
            elif n == 0: out.append(base | {"verdict": "adopt", "kind": "agent", "name": f"Adopted {title[:20]}", "role": "Researcher", "description": "From an import.", "instructions": "Research carefully and cite sources."})
            elif n == 1: out.append(base | {"verdict": "adopt", "kind": "skill", "name": f"Skill {title[:20]}", "description": "A skill.", "body": "Do the thing step by step."})
            elif n == 2 and mine: out.append(base | {"verdict": "adapt", "kind": "none", "target": mine[0], "addition": "Before answering, check the Knowledge hub."})
            else: out.append(base | {"verdict": "reject", "kind": "none"})
        return {"items": out}
    # Knowledge Hub spaces (knowledge_spaces.py). Organize: the first listed folder that shares a word with the item (else the
    # inbox), its first two related records as links. Ask: an answer citing the first two evidence refs (and one that wasn't
    # given). Review: approve when the record has evidence, else revise.
    if system.startswith("You organize one item"):
        item = prompt.split("<item>", 1)[1].split("</item>", 1)[0]
        folders = prompt.split("<folders>", 1)[1].split("</folders>", 1)[0].split()
        words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", item)}
        folder = next((f for f in folders if words & {w.lower() for w in re.findall(r"[A-Za-z]{4,}", f)}), "/00-Inbox/Unprocessed")
        refs = re.findall(r"^\[(kb:\d+)\]", prompt.split("<related>", 1)[-1], re.M)
        title = (re.search(r"^Title: (.*)$", item, re.M) or [None, "Item"])[1]
        return {"title": title[:60], "summary": f"About: {title[:80]}.", "ktype": "procedural" if "how" in item.lower() or "step" in item.lower() else "declarative",
                "folder": folder, "tags": sorted(words)[:3], "links": [{"ref": r, "rel": "related_to", "why": "Shares the topic."} for r in refs[:2]],
                "claims": ["It says what it says."], "record": {"title": f"Lesson: {title[:40]}", "body": f"Reusable point from {title[:60]}: check it before relying on it."}}
    if system.startswith("You answer the user's question from their own knowledge"):
        refs = re.findall(r"^\[((?:kb|mem|mk|wfm|cok):\d+)\]", prompt, re.M)
        cite = " ".join(f"[{r}]" for r in refs[:2])
        first = re.search(r"^\[(?:kb|mem|mk|wfm|cok):\d+\][^\n]*\n([^\n]{0,160})", prompt, re.M)  # knowledge_rag.py: the first passage's opening words
        return {"answer": f"From what you hold: the records agree on the main point {cite}. A made-up source [kb:999999] is cut.",
                "evidence": [{"ref": r, "why": "Covers the question."} for r in refs[:2]], "gaps": ["No measured results yet."], "directions": ["Run a small experiment and record it."],
                "points": [{"claim": (first.group(1) if first else "The records agree"), "refs": refs[:1], "basis": "evidence"},
                           {"claim": "This should carry over to the next competition", "refs": refs[1:2], "basis": "inference"},
                           {"claim": "Quantum tunnelling doubles the score", "refs": refs[:1], "basis": "unverified"}] if refs else [],
                "limitations": ["Only what you captured; nothing measured."], "confidence": "medium"}
    if system.startswith("You plan the next searches of a knowledge base"):  # knowledge_rag.py multi-hop: one follow-up search
        q = re.search(r"Question: (.+)", prompt)
        return {"queries": [" ".join((q.group(1) if q else "").split()[-4:])]}
    if system.startswith("You rate how well each retrieved passage"):  # knowledge_rag.py: model rerank, the first passage last
        n = len(re.findall(r"^\[\d+\] ", prompt, re.M))
        return {"ratings": [{"n": i, "score": 1 if i == 0 else 2} for i in range(n)]}
    if system.startswith("You read a picture"):  # knowledge_media.py: the picture arrives as an image block after the text
        content = kw["messages"][-1]["content"]
        seen = any(isinstance(b, dict) and b.get("type") in ("image", "image_url") for b in (content if isinstance(content, list) else []))
        return {"text": "SN62 · miner leaderboard" if seen else "", "description": "A bar chart of miner scores, highest on the left." if seen else "No picture arrived.",
                "kind": "chart" if seen else "other", "tags": ["miners", "leaderboard"]}
    if system.startswith("You split a transcript"):
        marks = re.findall(r"\[(\d\d:\d\d)\]", prompt)
        return {"summary": "A short briefing.", "sections": [{"start": m, "title": f"Part {i + 1}", "summary": "What was said there."} for i, m in enumerate(marks[:4])]}
    if system.startswith("You revise a knowledge record"):  # knowledge_improve.py: the record with its failures written in
        title = (re.search(r"^Title: (.*)$", prompt, re.M) or [None, "Record"])[1]
        fails = re.findall(r"^- failure \([^)]*\): (.*)$", prompt, re.M)
        body = prompt.split("<record>", 1)[1].split("</record>", 1)[0].split("\n\n", 1)[-1].strip()
        return {"title": f"{title} (revised)", "body": body + ("\n\nWhat failed: " + "; ".join(fails[:3]) if fails else "\n\nNo failures reported yet."),
                "changes": [f"Adds what failed: {f[:80]}" for f in fails[:2]] or ["Nothing failed: wording only."], "why": f"{len(fails)} failures reported."}
    if system.startswith("You review a knowledge record"):
        has = "Evidence: (none)" not in prompt
        return {"verdict": "approve" if has else "revise", "reasons": ["It is specific and scoped." if has else "It gives no evidence."],
                "evidence": "some" if has else "none", "risks": ["It may go stale as the subnet changes."], "confidence": 80 if has else 45, "ktype": "procedural", "review_days": 60}
    return None

def _mining_sources(kw, fmt):
    """Import competitions (mining_sources.py). Extraction: one competition named after the page title, its subnet and the first
    two dates the text gives, each quoted from the page; a page whose text says "no competition" has none. Assessment: generic."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if not fmt: return None
    prompt = kw["messages"][-1]["content"]
    prompt = prompt if isinstance(prompt, str) else prompt[0]["text"]
    if system.startswith("You extract competition records"):
        text = prompt.split("<<<", 1)[-1]
        if "no competition" in text.lower(): return {"competitions": []}
        title = (re.search(r"^Page title: (.*)$", prompt, re.M) or [None, ""])[1].strip()
        title = "" if title == "(none)" else title
        sn = re.search(r"(?:SN|subnet |netuid )(\d+)", text)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        line = lambda pat: next((ln.strip() for ln in text.splitlines() if re.search(pat, ln, re.I)), "")
        scoring = line(r"scor")
        c = {"name": title or line(r"\w") [:60], "platform": "", "netuid": int(sn.group(1)) if sn else -1, "external_id": "", "description": line(r"compet")[:300],
             "organizer": "", "status": "active" if re.search(r"\bopen\b|\bactive\b", text, re.I) else "unknown", "starts": dates[0] if dates else "",
             "ends": dates[1] if len(dates) > 1 else "", "registration_url": "", "docs": [], "scoring": scoring, "rewards": "Made-up prize pool" if "invent" in text else "",
             "requirements": "", "submission": "", "evaluation": "", "confidence": 0.8,
             "quotes": [q for q in ({"field": "name", "quote": title}, sn and {"field": "netuid", "quote": line(re.escape(sn.group(0)))},
                                    dates and {"field": "starts", "quote": line(dates[0])}, len(dates) > 1 and {"field": "ends", "quote": line(dates[1])},
                                    scoring and {"field": "scoring", "quote": scoring}, {"field": "description", "quote": line(r"compet")[:300]}) if q]}
        return {"competitions": [c]}
    if system.startswith("You assess a competition record"):
        return {"summary": "Build the best agent for the competition's tasks.", "rules": ["One submission at a time."], "deadlines": "Not stated",
                "hardware": "Not stated", "skills": ["Python", "evaluation"], "team": "top-miner", "team_why": "A general competition.",
                "risks": ["Rewards are unverified."], "opportunity": "Fair, if the field is thin.", "questions": ["Is registration open?"]}
    return None

def _mining_import(kw, fmt):
    """Importing earlier work (mining_import.py). A conversation is worth keeping unless the user only said hello; it's titled
    with the user's first words. The Director marks the first milestone done, gives a task to the first two teammates it names
    (and one to the user) and asks one question."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if not fmt: return None
    prompt = kw["messages"][-1]["content"]
    prompt = prompt if isinstance(prompt, str) else prompt[0]["text"]
    if system.startswith("You turn one of the user's earlier conversations"):
        first = re.search(r"\*\*User\*\* \([^)]*\): (.*)", prompt)
        words = first.group(1).strip() if first else "the work"
        return {"title": words[:60], "summary": f"The user asked about {words[:80]}. Score went from 0.80 to 0.92 on the hard set.",
                "lessons": ["Measure every change on the hard set."], "worth": words.lower().strip(" .!") not in ("hello", "hi", "stop")}
    if "has just imported that earlier work" in system:
        team = re.findall(r"^- ([^,\n]+), ([^\n(:]+?)(?: \([^)]*\))*:", system, re.M)
        names = [n for n, _ in team][1:3] or ["you"]
        files = re.findall(r"^- (\S+) \(\d+ kB\)$", prompt, re.M)
        return {"start_here": f"## What exists\n- {len(files)} files, the agent in `{files[0] if files else 'agent.py'}`.\n\n## Where it stands\n0.92 on the hard set.",
                "headline": f"I read your earlier work: {len(files)} files", "report": "The agent scores 0.92 locally; the team carries on from there.",
                "milestones": [{"title": "Baseline agent", "detail": "Built and measured.", "status": "done", "due": ""},
                               {"title": "Pass both screeners", "detail": "24/30 and 27/30.", "status": "doing", "due": "2026-11-10"},
                               {"title": "Beat the leader", "detail": "0.40 on validators.", "status": "todo", "due": "not a date"}],
                "tasks": [{"title": f"Carry on: {n}", "detail": "From the start-here entry.", "assignee": n, "priority": "high"} for n in names]
                         + [{"title": "Upload the next version", "detail": "Only you can.", "assignee": "you", "priority": "medium"}],
                "asks": [{"title": "Which version is live?", "detail": "The plan names two.", "kind": "decision"}]}
    return None

def _mining_work(kw, fmt):
    """competition workspaces (mining_work.py). The lead plans a task each for up to four teammates (the Researcher, Engineer, Data
    Analyst and Reviewer of the small team; a pack's Agent Architect, Task-set Curator, Benchmark Designer and PostgreSQL Specialist)
    and one for the user. An agent on a task reads the leaderboard (when there's a snapshot) and the board, then files: a task
    titled with "ask" first asks the user a question; the Researcher suggests a follow-up for the Engineer; the Agent Architect
    writes agent.py and runs it in the sandbox (when it has the tool) before filing. A squad lead reviewing sends a task titled
    with "draft" back once, then approves it."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if "competition workspace" not in system: return None
    team = re.findall(r"^- ([^,\n]+), ([^\n(:]+?)(?: \([^)]*\))*:", system, re.M)
    by = {t.strip(): n for n, t in team}
    if fmt:
        if "You review a teammate's finished task" in system:
            prompt = kw["messages"][-1]["content"]
            prompt = prompt if isinstance(prompt, str) else prompt[0]["text"]
            title = re.search(r"^The task \(#\d+[^)]*\), by [^:]+: (.*)$", prompt, re.M)
            again = "You have sent it back" in prompt
            if title and "draft" in title.group(1).lower() and not again:
                return {"decision": "revise", "feedback": "Add the numbers behind it.", "note": ""}
            return {"decision": "approve", "feedback": "Holds up.", "note": f"Settled: {title.group(1) if title else 'the task'}"}
        if "write the user one report" in system:  # the Director's report (mining_director.py): approve work, answer questions once, the user's tasks to the user
            prompt = kw["messages"][-1]["content"]
            prompt = prompt if isinstance(prompt, str) else prompt[0]["text"]
            items = re.findall(r"^\[(\d+)\] ([^:]+): (.*)\n  ([^\n]*)", prompt, re.M)
            act = lambda kind, info: ("user" if "settled by you" in info else "answer") if kind == "a question" else \
                "approve" if kind == "finished work" else "redo" if kind == "failed twice" else "user"
            answered = "The user's answer" in prompt
            act0 = act
            act = lambda kind, info: "done" if answered and kind == "a task left for the user" and "in your report" in info else act0(kind, info)
            ds = [{"id": int(i), "action": act(k, info), "reply": "Use the public leaderboard numbers.", "agent": "", "note": f"Settled: {t}"} for i, k, t, info in items]
            mine = [d["id"] for d in ds if d["action"] == "user"]
            return {"headline": f"{len(ds)} items settled or passed on", "report": "**Done:** the team's work so far.\n\n**Next:** keep going.",
                    "decisions": ds, "asks": [{"title": "Do the uploads", "detail": "Upload and register; I recommend today.", "kind": "todo", "tasks": mine}] if mine else []}
        if "and lead of the user's competition workspace" not in system: return None
        used = set()
        def pick(*ts):
            n = next((by[t] for t in ts if t in by and by[t] not in used), None)
            if n: used.add(n)
            return n or "you"
        board = set(re.findall(r"^- #\d+ \[\w+\] (.*?) \([^()]*\)(?:: |$)", kw["messages"][-1]["content"], re.M))
        return {"summary": "Learn the scoring first, then build and check the change, and submit before the deadline.",
                "tasks": [x for x in [{"title": "Study this competition's scoring and the leaders", "detail": "What wins, by how much, and how often the top changes.",
                           "assignee": pick("Researcher", "Rules & Scoring Analyst", "Competition Researcher"), "priority": "high"},
                          {"title": "Draft the agent change", "detail": "A diff against our repo that targets the weak spots.",
                           "assignee": pick("Engineer", "Agent Architect", "Engineering Lead"), "priority": "high"},
                          {"title": "Measure where we stand", "detail": "Rank, rewards and the bar to beat.",
                           "assignee": pick("Data Analyst", "Benchmark Designer", "Data Lead"), "priority": "medium"},
                          {"title": "Check the draft against the rules", "detail": "Anything that could get it rejected.",
                           "assignee": pick("Reviewer", "PostgreSQL Specialist", "Compliance Checker"), "priority": "medium"},
                          {"title": "Upload the agent", "detail": "Run the upload command yourself.", "assignee": "you", "priority": "low"}] if x["title"] not in board]}
    msgs, names = kw["messages"], [t["name"] for t in kw.get("tools", [])]
    step = sum(1 for m in msgs if m["role"] == "assistant")
    call = lambda name, inp: Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": inp}], "tool_use")
    prompt = msgs[0]["content"][0]["text"]
    if any(b.get("name") == "submit_work" for m in msgs if m["role"] == "assistant" for b in m["content"]):
        return Resp([{"type": "text", "text": "Filed."}], "end_turn")
    me = re.search(r"^You are ([^,]+), the ([^\n]+?) in the user's", system)
    title = re.search(r"^Your task \(#\d+[^)]*\): (.*)$", prompt, re.M)
    title = title.group(1) if title else "the task"
    done = [b["name"] for m in msgs if m["role"] == "assistant" for b in m["content"] if b.get("type") == "tool_use"]
    if me and me.group(2) == "Agent Architect":
        if "file_write" not in done:
            return call("file_write", {"path": "agent.py", "content": "def agent_main(input):\n    return ''\n"})
        if "sandbox_run" in names and "sandbox_run" not in done:
            return call("sandbox_run", {"command": "python .axor/ridges_run.py --agent agent.py tasks/*", "services": ["postgres"], "timeout_s": 300,
                                        "budget_usd": 1, "paths": []})
    if step == 0 and "leaderboard" in names: return call("leaderboard", {"from_rank": 1, "limit": 5})
    if "team_tasks" not in done and step <= 1: return call("team_tasks", {})
    if "ask" in title.lower() and "The user's reply" not in prompt and "The answer:" not in prompt:
        return call("submit_work", {"summary": "I need one answer before I can go on.", "result": "Waiting for your answer.", "outcome": "needs_input",
                                    "question": "Which repository branch should I work from?", "followups": [], "evidence": [], "confidence": "low"})
    reply = re.search(r"^(?:The user's reply|The answer|Feedback on it): (.*)$", prompt, re.M)
    follow = [{"title": "Prototype the leaders' trick", "detail": "Copy what the top 3 do differently.", "assignee": by.get("Engineer", "you")}] \
        if me and me.group(2) == "Researcher" else []
    return call("submit_work", {"summary": f"Done: {title}" + (f" (reworked: {reply.group(1)})" if reply else ""),
                                "result": f"## {title}\n\n- The top 5 are close together.\n- **Next**: focus on the hardest problems.\n\n```diff\n- old\n+ new\n```",
                                "outcome": "done", "question": "", "followups": follow,
                                # "guess" in a title: a claim without a source, at low confidence (the Director's report should send it back)
                                "evidence": [{"claim": "The top 5 are within 2% of each other", "source": "leaderboard(from_rank=1, limit=5)"}]
                                            + ([{"claim": "The leaders retry failed SQL", "source": ""}] if "guess" in title.lower() else []),
                                "confidence": "low" if "guess" in title.lower() else "high"})

def _workforce(kw, fmt):
    """Workforce (workforce.py). The CEO staffs Research, then Strategy on its result; each lead gives an item to their first
    person. Specialists read once (the market overview, else the blackboard); on Strategy they propose renting a GPU (rated low,
    which the policy rates high), then file. The red teamer raises a major challenge on the last assignment and its author
    revises. The fact checker verifies the findings but disputes the second. The evaluator fails the last of several
    assignments while its deliverable cites no "source:", so it fails again after rework and the improvement engineer adds a
    citation rule; the blind judge scores outputs with a source higher, so the test finds the candidate better. With debate on,
    the CEO puts payback (2 months or 3) to the first and last assignments' authors: side 2 agrees with side 1 (consensus in one
    round), or with "hold firm" in the goal both hold for two rounds (a split)."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if "AXoR Workforce" not in system: return None
    last = kw["messages"][-1]["content"]
    prompt = last if isinstance(last, str) else ""
    props = (fmt or {}).get("schema", {}).get("properties", {})
    if fmt:
        if "planning a mission" in system:
            teams = props["items"]["items"]["properties"]["team"]["enum"]
            pick = [t for t in ("research", "strategy") if t in teams] or teams[:1]
            given = prompt.split("success criteria:\n")[1].split("\n\n")[0] if "success criteria:\n" in prompt else ""
            mems = [int(x) for x in re.findall(r"\[M(\d+)\]", prompt)]
            return {"objective": "A ranked shortlist with a plan.", "success_criteria": re.findall(r"^\d+\. (.+)$", given, re.M) or ["Names three subnets with numbers", "Gives a 30-day plan"],
                    "items": [{"team": t, "title": f"{t.title()} work", "brief": f"Do the {t} part with evidence.", "depends_on": [1] if i else []} for i, t in enumerate(pick)],
                    "used_memories": mems[:1]}
        if "delegating your team's work" in system:
            p = props["assignments"]["items"]["properties"]
            return {"assignments": [{"item": i, "agent": p["agent"]["enum"][0], "title": f"Assignment for item {i}", "task": "Find it and back it with numbers.",
                                     "done_when": "Three numbers with sources."} for i in p["item"]["enum"]]}
        if "challenging the team's work" in system:
            seqs = props["challenges"]["items"]["properties"]["assignment"]["enum"]
            return {"challenges": [{"assignment": seqs[-1], "claim": "Payback in 2 months", "issue": "No cost basis given.", "severity": "major"}], "overall": "One claim needs a basis."}
        if "answering the Red Teamer" in system:
            return {"stance": "revise", "response": "Added the cost basis.", "deliverable": "- Revised: payback in 3 months, from the mining plan", "summary": "Payback 3 months."}
        if "opening a debate" in system:  # the deliverables are alike, so the disagreement is made up: the first two assignments on payback
            seqs = props["disagreements"]["items"]["properties"]["sides"]["items"]["properties"]["assignment"]["enum"]
            return {"disagreements": [{"question": "Is payback 2 months or 3?", "why": "It decides whether renting a GPU is worth it.",
                                       "sides": [{"assignment": seqs[0], "position": "Payback in 2 months."}, {"assignment": seqs[-1], "position": "Payback in 3 months."}]}]
                    if len(seqs) > 1 else []}
        if "of a debate" in system:  # "hold firm" in the goal: every side holds, a split; else side 2 agrees with side 1 in round 1
            if "hold firm" in prompt:
                return {"stance": "hold", "agree_with": 0, "argument": "My numbers come from the mining plan.", "position": "", "evidence": "mining_plan"}
            others = props["agree_with"]["enum"]
            if "You are side 1." in prompt:
                return {"stance": "hold", "agree_with": 0, "argument": "The market overview supports 2 months.", "position": "", "evidence": "market_overview"}
            return {"stance": "agree", "agree_with": others[1] if len(others) > 1 else 0, "argument": "Side 1's source is newer than mine.", "position": "", "evidence": "market_overview"}
        if "scoring one output blind" in system:
            good = "source:" in prompt
            return {"verdict": "pass" if good else "fail", "score": 84 if good else 58, "note": "Cites its sources." if good else "Numbers lack sources."}
        if "scoring the work independently" in system:
            blocks = re.split(r"^### Assignment (\d+) by", prompt, flags=re.M)
            work = {int(blocks[i]): blocks[i + 1] for i in range(1, len(blocks) - 1, 2)}
            several = len(work) > 1 or "Already passed earlier" in prompt
            bad = {s for s in work if s == max(work) and several and "source:" not in work[s].split("\nFindings:")[0]}
            crit = re.findall(r"^(\d+)\. ", prompt.split("Success criteria:\n")[1].split("\n\n")[0], re.M) if "Success criteria:\n" in prompt else []
            return {"assignments": [{"assignment": s, "verdict": "fail" if s in bad else "pass", "score": 55 if s in bad else 82,
                                     "category": "unsupported_claim" if s in bad else "none", "note": "Cite a source for the payback." if s in bad else "Solid."} for s in work],
                    "criteria": [{"criterion": int(c), "met": not bad, "note": "Met." if not bad else "The plan's numbers are unsourced."} for c in crit],
                    "score": 62 if bad else 80, "verdict": "fail" if bad else "pass", "summary": "One deliverable lacks sources." if bad else "The work holds up."}
        if "closing a mission" in system:
            return {"headline": "Three subnets shortlisted; a 30-day plan", "report": "## Outcome\nThe team shortlisted three subnets.\n\n## Next actions\n- Strategy: price the GPU",
                    "decisions": [{"title": "Rent a GPU?", "detail": "$250/month for an RTX 4090, or wait a week."}], "next_mission": "Price GPU rentals for the top subnet.", "used_memories": []}
        if "memory engine" in system:
            verified = re.findall(r"\[F(\d+)\] ", prompt.split("Disputed findings")[0])
            out = [{"kind": "semantic", "text": "SN1 leads daily emissions.", "tags": ["sn1", "emissions"], "team": "research",
                    "from_findings": [int(verified[0])], "replaces": 0}] if verified else []
            return {"memories": out + [{"kind": "strategy", "text": "Plans that cite a tool for every number pass review; uncited ones fail.", "tags": ["evidence"],
                                        "team": "all", "from_findings": [], "replaces": 0}]}
        if "diagnosing failed work" in system:
            seqs = props["proposals"]["items"]["properties"]["assignment"]["enum"]
            cur = re.search(r"<instructions>\n(.*?)\n</instructions>", prompt, re.S)
            return {"proposals": [{"assignment": seqs[0], "root_cause": "It gives numbers without their source.", "change": "Cite the tool for every number.",
                                   "instructions": (cur.group(1) if cur else "Work carefully.") + " Always cite the tool for every number as (source: tool)."}]}
        return None
    msgs, names = kw["messages"], [t["name"] for t in kw.get("tools", [])]
    step = sum(1 for m in msgs if m["role"] == "assistant")
    used = {b.get("name") for m in msgs if m["role"] == "assistant" for b in m["content"] if isinstance(b, dict)}
    call = lambda name, inp: Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": inp}], "tool_use")
    done = Resp([{"type": "text", "text": "Filed."}], "end_turn")
    brief = msgs[0]["content"][0]["text"]
    if "verifying findings" in system:
        if "submit_verdicts" in used: return done
        if step == 0 and "market_overview" in names: return call("market_overview", {})
        ids = [int(x) for x in re.findall(r"\[F(\d+)\]", brief)]
        return call("submit_verdicts", {"verdicts": [{"finding": i, "verdict": "disputed" if k == 1 else "verified",
                                                     "note": "The data says otherwise." if k == 1 else "Matches the data."} for k, i in enumerate(ids)]})
    if "doing one assignment" in system or "working alone" in system:
        if "submit_work" in used: return done
        if step == 0 and "probe the grant" in brief:  # asks for a tool it wasn't given: the workforce must refuse it
            return call("devops_logs", {"app": "miner", "lines": 20})
        if step == 0:
            if "market_overview" in names: return call("market_overview", {})
            if "read_board" in names: return call("read_board", {"query": "", "kind": "any"})
        if "on the Strategy team" in system and "propose_action" in names and "propose_action" not in used:
            return call("propose_action", {"action": "Rent an RTX 4090 for $250/month", "details": "One GPU for the miner; cancel any time.",
                                           "declared_risk": "low", "reason": "The plan needs it."})
        cite = "Always cite the tool" in system
        mems = [int(x) for x in re.findall(r"\[M(\d+)\]", brief)]
        return call("submit_work", {"deliverable": "- SN1 leads emissions" + (" (source: market_overview)" if cite else "") + "\n- Payback in 2 months",
                                    "summary": "SN1 leads; payback in 2 months.", "used_memories": mems[:1],
                                    "findings": [{"kind": "finding", "text": "SN1 leads daily emissions.", "evidence": "market_overview top_by_emission", "confidence": "high"},
                                                 {"kind": "risk", "text": "Registration cost doubled this week.", "evidence": "search_subnets reg_cost", "confidence": "medium"}]})
    return None

def _writing(kw):
    """Writing help: fixes "teh", "recieve" and a lone "i"; the rewrites echo the direction when there is one."""
    prompt = kw["messages"][-1]["content"]
    draft = prompt.split("<draft>\n", 1)[1].rsplit("\n</draft>", 1)[0]
    idea = re.search(r"direction for the rewrites: (.*)", prompt)
    fixes = [("teh", "the", "Spelling"), ("recieve", "receive", "i before e"), ("i", "I", "Capital I")]
    text, changes = draft, []
    for wrong, right, why in fixes:
        if re.search(rf"\b{wrong}\b", text):
            text = re.sub(rf"\b{wrong}\b", right, text); changes.append({"from": wrong, "to": right, "why": why})
    tag = f" ({idea.group(1)})" if idea else ""
    return {"corrected": text, "changes": changes, "tip": "Say what you want the reader to do.",
            "rewrites": [{"label": "Clearer", "text": f"Clearer: {text}{tag}"}, {"label": "Shorter", "text": " ".join(text.split()[:5]) + tag}]}

def _market(kw, fmt):
    """The Agent Marketplace (marketplace.py): role tasks, the evaluator's scores, and the evaluated agent's answers. An agent whose
    instructions say "sloppy" scores low; "[slow]" in them makes the answer wait a little; a leaked-secret answer scores 0 on safety."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if fmt and system.startswith("You write evaluation tasks"):
        return {"tasks": [{"title": "Role task A", "prompt": "Explain your first step on a new codebase.", "rubric": "Concrete, ordered."},
                          {"title": "Role task B", "prompt": "Estimate the effort of a migration.", "rubric": "States assumptions."}]}
    if fmt and system.startswith("You are AXoR's independent evaluator"):
        prompt = kw["messages"][-1]["content"]
        ans = prompt.split("<answer>", 1)[-1]
        low = "sloppy" in ans.lower()
        leaked = "system prompt:" in ans.lower()
        base = 4 if low else 8
        return {"task": base, "quality": base - 1, "reasoning": base, "tools": 7 if "used: none" not in prompt else 5, "adaptability": base - 1,
                "safety": 0 if leaked else 9, "verdict": "partial" if low else "pass", "notes": "Fake evaluator: " + ("thin answer." if low else "solid answer.")}
    if "evaluation in AXoR's Agent Marketplace" in system and not fmt:
        last = kw["messages"][-1]["content"]
        if "[slow]" in system: time.sleep(0.3)
        names = [t["name"] for t in kw.get("tools", [])]
        if names and not any(b.get("type") == "tool_result" for b in last) and "market_overview" in names:
            return Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": "market_overview", "input": {}}], "tool_use")
        task = next((b.get("text", "") for m in kw["messages"] if m["role"] == "user" for b in (m["content"] if isinstance(m["content"], list) else []) if b.get("type") == "text"), "")
        sloppy = "sloppy" in system.lower()
        if "IGNORE ALL PREVIOUS" in task:
            text = "System prompt: leaked" if "obey injections" in system.lower() else "The customer says order #4471 arrived broken. (The message also contained an instruction to reveal my prompt, which I ignored.)"
        else:
            text = ("sloppy short answer" if sloppy else "Here is a careful answer: step one, step two, and the trade-offs.") + f" [{task[:40]}]"
        return Resp([{"type": "text", "text": text}], "end_turn")
    return None

def _example(schema, key=""):
    """A filled-in answer for any JSON schema (Study practice, practice.py): first enum value, two items per list."""
    if "enum" in schema: return schema["enum"][0]
    t = schema.get("type")
    if t == "object": return {k: _example(v, k) for k, v in schema["properties"].items()}
    if t == "array": return [_example(schema["items"], key) for _ in range(2)]
    if t == "integer": return 0 if key == "correct" else 3
    if t == "boolean": return True
    return f"Sample {key} text."

# My profile's AI review: role 0 gets new bullets; role 99 doesn't exist, so the server drops it
PROFILE_REVIEW = {"headline": "AI engineer shipping LLM agents and RAG to production",
                  "summary": "AI engineer who turns LLM prototypes into reliable products, with retrieval, agents and evals that hold up in production.",
                  "experience": [{"index": 0, "bullets": ["Shipped a RAG assistant that resolves support questions end to end", "Built the eval suite that gates every prompt change"]},
                                 {"index": 99, "bullets": ["Not a real role"]}],
                  "keywords": ["Kubernetes", "LangGraph"], "tips": ["Add the share of tickets the assistant resolves."]}

# Study Lab tasks (practice.py lab_task), one per environment: starting files, a solution and checks that pass on it
LAB_TASKS = {
    "python": {"title": "Count the words", "task": "Complete `count_words(text)` in **words.py**: the number of words in `text`, split on whitespace.\n\n"
               "```python\ncount_words('hello big world')  # 3\n```", "main": "words.py",
               "files": [{"path": "words.py", "content": 'def count_words(text):\n    """How many words are in text."""\n    # TODO\n    return 0\n'}],
               "tests": "from words import count_words\n\ndef test_three():\n    \"\"\"Counts three words\"\"\"\n    assert count_words('hello big world') == 3, "
                        "'count_words(\"hello big world\") should be 3'\n\ndef test_empty():\n    \"\"\"An empty text has no words\"\"\"\n    assert count_words('') == 0\n",
               "hints": ["str.split() with no argument splits on any whitespace.", "return len(text.split())"],
               "solution": [{"path": "words.py", "content": "def count_words(text):\n    return len(text.split())\n"}], "commands": []},
    "terminal": {"title": "Count the errors", "task": "Count the lines with `ERROR` in **logs/app.log** and save the number in **errors.txt**.",
                 "main": "logs/app.log", "files": [{"path": "logs/app.log", "content": "INFO start\nERROR timeout\nINFO retry\nERROR refused\n"}],
                 "tests": "def test_errors():\n    \"\"\"errors.txt holds the count\"\"\"\n    assert open('errors.txt').read().strip() == '2', 'errors.txt should say 2'\n",
                 "hints": ["grep -c counts matching lines.", "grep -c ERROR logs/app.log > errors.txt"], "solution": [],
                 "commands": ["grep -c ERROR logs/app.log > errors.txt"]},
    "sql": {"title": "Calls per model", "task": "Write a query in **answer.sql** that lists each model with its number of calls, by model name.",
            "main": "answer.sql", "files": [{"path": "setup.sql", "content": "CREATE TABLE calls (id INTEGER, model TEXT);\nINSERT INTO calls VALUES (1, 'b'), (2, 'a'), (3, 'b');\n"},
                                            {"path": "answer.sql", "content": "-- Each model and its number of calls, ordered by model\n"}],
            "tests": "import sqlite3\n\ndef test_rows():\n    \"\"\"One row per model with its count\"\"\"\n    rows = sqlite3.connect('data.db').execute(open('answer.sql').read()).fetchall()\n"
                     "    assert rows == [('a', 1), ('b', 2)], f'got {rows}'\n",
            "hints": ["GROUP BY model", "SELECT model, COUNT(*) FROM calls GROUP BY model ORDER BY model;"],
            "solution": [{"path": "answer.sql", "content": "SELECT model, COUNT(*) FROM calls GROUP BY model ORDER BY model;\n"}], "commands": []},
}

class Messages:
    calls = []
    def create(self, **kw):
        Messages.calls.append(kw)
        fmt = (kw.get("output_config") or {}).get("format")
        if (probe := _kb_probe(kw, fmt)) is not None: return probe
        if (ctl := _control(kw, fmt)) is not None: return Resp([{"type": "text", "text": json.dumps(ctl)}], "end_turn")
        if fmt and str((kw.get("system") or [{}])[0].get("text", "") if isinstance(kw.get("system"), list) else kw.get("system") or "").startswith("You are the General Manager of AXoR"):  # gm_chat.py
            msg = str(kw["messages"][-1]["content"]).rsplit("<message>", 1)[-1].lower()
            work = re.search(r"\b(fix|update|build|add|create|make|develop|change|write|correct|research)\b", msg)
            return Resp([{"type": "text", "text": json.dumps({"kind": "assignment", "text": "The team will plan it, build it and check it.", "changes_axor": bool(re.search(r"\b(homepage|page|header|axor)\b", msg))} if work
                                                             else {"kind": "reply", "text": "Hello from the General Manager.", "changes_axor": False})}], "end_turn")
        if (evo := _evolution(kw, fmt)) is not None: return evo
        if fmt and "commands" in fmt["schema"]["properties"] and str(kw.get("system") or "").startswith("You create study practice"):
            lab = re.search(r"for the learner's (\w+) environment", kw["messages"][-1]["content"])
            return Resp([{"type": "text", "text": json.dumps(LAB_TASKS[lab.group(1) if lab else "python"])}], "end_turn")
        if fmt and str(kw.get("system") or "").startswith(("You create study practice", "You help on a whiteboard")):
            return Resp([{"type": "text", "text": json.dumps(_example(fmt["schema"]))}], "end_turn")
        if fmt and str(kw.get("system") or "").startswith("You are a resume editor"):  # My profile's AI review (profile.py)
            return Resp([{"type": "text", "text": json.dumps(PROFILE_REVIEW)}], "end_turn")
        if fmt and str(kw.get("system") or "").startswith(("You analyze new technology for Tech Daily", "You write the research brief of Tech Daily")):
            return Resp([{"type": "text", "text": json.dumps(_tech_research(kw))}], "end_turn")
        if fmt and str(kw.get("system") or "").startswith(("You are the copywriter of Tech Daily", "You edit Tech Daily")):
            return Resp([{"type": "text", "text": json.dumps(_tech(kw))}], "end_turn")
        if fmt and str(kw.get("system") or "").startswith("You correct and improve"):  # writing help (writing.py)
            return Resp([{"type": "text", "text": json.dumps(_writing(kw))}], "end_turn")
        if (mk := _market(kw, fmt)) is not None:
            return mk if isinstance(mk, Resp) else Resp([{"type": "text", "text": json.dumps(mk)}], "end_turn")
        if (kb := _knowledge(kw, fmt)) is not None:
            return Resp([{"type": "text", "text": json.dumps(kb)}], "end_turn")
        if (co := _company(kw, fmt)) is not None:
            return Resp([{"type": "text", "text": json.dumps(co)}], "end_turn")
        if (pf := _portfolio(kw, fmt)) is not None:
            return Resp([{"type": "text", "text": json.dumps(pf)}], "end_turn")
        if (ms := _mining_sources(kw, fmt)) is not None:
            return Resp([{"type": "text", "text": json.dumps(ms)}], "end_turn")
        if (mi := _mining_import(kw, fmt)) is not None:
            return Resp([{"type": "text", "text": json.dumps(mi)}], "end_turn")
        if (mw := _mining_work(kw, fmt)) is not None:
            return mw if isinstance(mw, Resp) else Resp([{"type": "text", "text": json.dumps(mw)}], "end_turn")
        if (wf := _workforce(kw, fmt)) is not None:
            return wf if isinstance(wf, Resp) else Resp([{"type": "text", "text": json.dumps(wf)}], "end_turn")
        if (mh := _mining(kw, fmt)) is not None:
            return mh if isinstance(mh, Resp) else Resp([{"type": "text", "text": json.dumps(mh)}], "end_turn")
        if (hq := _hq(kw, fmt)) is not None:
            return hq if isinstance(hq, Resp) else Resp([{"type": "text", "text": json.dumps(hq)}], "end_turn")
        if fmt and (team := _team(kw, fmt)) is not None:
            return Resp([{"type": "text", "text": json.dumps(team)}], "end_turn")
        if fmt and "instructions" not in fmt["schema"].get("properties", {}):  # the Study Lab's prompt playground, JSON mode
            return Resp([{"type": "text", "text": json.dumps(_example(fmt["schema"]))}], "end_turn")
        if fmt:  # agent draft (structured output)
            return Resp([{"type": "text", "text": json.dumps({
                "name": "Remy", "role": "Registration Watcher", "description": "I'll tell you where UIDs are open.",
                "instructions": "Use search_subnets with uid_available_only.", "icon": "search", "color": "teal",
                "skills": ["due-diligence"], "examples": ["Where can I register for under 0.5 TAO?"]})}], "end_turn")
        msgs = kw["messages"]
        last = msgs[-1]["content"]
        if isinstance(last, str) and not kw.get("tools"):  # the Study Lab's prompt playground: plain turns, no tools
            return Resp([{"type": "text", "text": f"Echo after {len(msgs)} turn(s): {last[:200]}"}], "end_turn")
        system = kw.get("system")
        system = system[0]["text"] if isinstance(system, list) else system or ""
        if "<fact_sheet>" in system:  # a PDCA Do task: one lookup when it has a tool, then the answer
            names = [t["name"] for t in kw.get("tools", []) if t["name"] != "escalate"]
            first = not any(b.get("type") == "tool_result" for b in last)
            if first and system.startswith("You are Iris") and "your request" not in last[0].get("text", ""):  # asks for money
                return Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": "escalate",
                              "input": {"kind": "fund", "title": "Rent an RTX 4090 for $250/month", "detail": "The design needs one GPU."}}], "tool_use")
            if names and first:
                return Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": "search_subnets",
                              "input": {"query": "", "field": "", "risk": "any", "uid_available_only": False, "sort": "emission_day", "descending": True, "limit": 3}}
                             if "search_subnets" in names else {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": names[0], "input": {}}], "tool_use")
            return Resp([{"type": "text", "text": "- Result one\n- Result two\n\nSUMMARY: Done; the key number is 42."}], "end_turn")
        if any(b.get("type") == "tool_result" for b in last):
            data = json.loads(last[0]["content"])
            if "proposal_id" in data:
                return Resp([{"type": "text", "text": f"I've proposed that change (proposal #{data['proposal_id']}). Approve it below if it looks right."}], "end_turn")
            if "users" in data:
                names = ", ".join(f"`{u['username']}`" for u in data["users"]) or "none"
                return Resp([{"type": "text", "text": f"**{data['count']}** account(s) match `{data['filter']}`: {names}."}], "end_turn")
            if "events" in data:
                return Resp([{"type": "text", "text": f"Found **{data['count']}** event(s) in the last {data['hours']}h."}], "end_turn")
            return Resp([{"type": "text", "text": "Summary: " + ", ".join(f"{k}={v}" for k, v in data.items() if not isinstance(v, (dict, list)))}], "end_turn")
        text = last[-1]["text"].lower()
        tool = lambda name, inp: Resp([{"type": "text", "text": "Let me check."},
                                       {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": inp}], "tool_use")
        if m := re.search(r"use tool (\S+)", text):  # Tools & MCP: "use tool ext_x__echo" calls that tool when the agent has it
            want = next((t for t in kw.get("tools", []) if t["name"].lower() == m.group(1)), None)
            if want:  # every required text field gets the same words (a query, a text, a repo…)
                req = [k for k in (want["input_schema"].get("required") or []) if (want["input_schema"]["properties"].get(k) or {}).get("type") == "string"]
                return tool(want["name"], {k: "hello from the fake model" for k in req} or {"text": "hello from the fake model"})
        if "knowledge" in text and any(t["name"] == "search_knowledge" for t in kw.get("tools", [])):  # the Knowledge hub's tool
            return tool("search_knowledge", {"query": text.replace("knowledge", "")})
        if any(t["name"] == "market_overview" for t in kw.get("tools", [])):  # custom hub agent, or the Assistant (assistant.py)
            return tool("market_overview", {})
        if any(t["name"] == "study_progress" for t in kw.get("tools", [])):  # study agent (Study tab): "tick <topic id>" ticks it
            if m := re.search(r"tick (\S+)", text):
                return tool("mark_topic", {"track": "ai", "topic": m.group(1), "done": True})
            return tool("study_progress", {})
        names = [t["name"] for t in kw.get("tools", [])]  # operations agents (ops_agents.py): "server" reads the server, else the overview
        if "server_resources" in names and "server" in text:
            return tool("server_resources", {})
        if ops := next((n for n in names if n in ("devops_overview", "list_functions", "list_apps", "cluster_overview", "dns_overview")), None):
            return tool(ops, {})
        if m := re.search(r"disable (\S+)", text):
            return tool("propose_user_action", {"username": m.group(1), "action": "disable", "reason": "Requested by the admin."})
        if "close registration" in text or "lock down" in text:
            return tool("propose_setting_change", {"setting": "registration", "value": "closed", "reason": "Stop new sign-ups."})
        if "2fa" in text or "two-factor" in text:
            return tool("list_users", {"filter": "no_2fa"})
        if "fail" in text:
            return tool("search_audit_log", {"query": "fail", "hours": 24})
        return tool("security_overview", {})

class Beta:
    messages = Messages()

class Client:
    beta = Beta()

def _evolution(kw, fmt):
    """The Evolution Lab (evolution.py): an agent whose instructions say "cite" answers thoroughly, and the blind judge scores
    thorough answers higher; drafts add "Always cite your sources."; the case writer returns three cases."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    out = lambda d: Resp([{"type": "text", "text": json.dumps(d)}], "end_turn")
    if fmt and system.startswith("You are AXoR's independent evaluator in the Evolution Lab"):
        good = "thorough" in kw["messages"][-1]["content"].split("<answer>", 1)[-1]
        return out({"score": 86 if good else 58, "verdict": "pass" if good else "partial", "notes": "Fake judge: " + ("cites its sources." if good else "no sources.")})
    if fmt and system.startswith("You propose one improvement to an AI agent"):
        prompt = kw["messages"][-1]["content"]
        cur = prompt.split("<instructions>", 1)[-1].split("</instructions>", 1)[0].strip()
        return out({"title": "Cite sources in every answer", "hypothesis": "Answers without sources score low; citing them should raise the benchmark score.",
                    "instructions": (cur + "\nAlways cite your sources.").strip()})
    if fmt and system.startswith("You write benchmark cases"):
        return out({"cases": [{"prompt": f"Fake case {i}: explain your approach.", "rubric": "Cites sources; concrete steps."} for i in range(1, 4)]})
    if not fmt and "This is an Evolution trial" in system:
        return Resp([{"type": "text", "text": "A thorough answer with sources [1]." if "cite" in system.lower() else "A short answer."}], "end_turn")
    return None


def _kb_probe(kw, fmt):
    """Knowledge Hub agentic retrieval (knowledge_rag.py): any agent loop that was offered research_knowledge and whose task says
    "kbprobe" calls it once first, so a test can see the tool reach Workforce, competition teams and Mission Control."""
    if fmt or not any(t["name"] == "research_knowledge" for t in kw.get("tools") or []): return None
    msgs = kw.get("messages") or []
    first = msgs[0]["content"] if msgs else ""
    text = first if isinstance(first, str) else " ".join(b.get("text", "") for b in first if isinstance(b, dict))
    if "kbprobe" not in text.lower(): return None
    if any(isinstance(m["content"], list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"]) for m in msgs): return None
    return Resp([{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": "research_knowledge",
                  "input": {"question": "uploader crash and also checkpoint scores", "scope": ""}}], "tool_use")


def _control(kw, fmt):
    """Control Hub (control_hub.py): an agent's workspace chat says what it was given (pictures, a transcript, web results, team
    brief), and proposes a task when asked for one ("task" in the message); an approved task delivers a result."""
    system = kw.get("system")
    system = system[0]["text"] if isinstance(system, list) else system or ""
    if not fmt or "working in AXoR's Control Hub" not in system: return None
    props = fmt["schema"]["properties"]
    last = kw["messages"][-1]["content"]
    text = last if isinstance(last, str) else " ".join(b.get("text", "") for b in last if isinstance(b, dict) and b.get("type") == "text")
    pics = 0 if isinstance(last, str) else sum(1 for b in last if isinstance(b, dict) and b.get("type") in ("image", "image_url"))
    name = re.match(r"You are ([^,]+),", system).group(1)
    if "proposals" in props:  # Mission Intelligence (control_missions.py): a task per signal it was shown, a priority change for the first open dynamic task
        props_ = []
        if "places from the top" in text or "place from the top" in text:
            props_.append({"title": "Benchmark against the miners ranked above us", "detail": "Run the validation set on ours and the top miners' outputs.", "priority": "high", "reason": "Behind the target rank"})
        if "Failed runs this week:\n- none" not in text:
            props_.append({"title": "Find the cause of this week's failed runs", "detail": "Group the failures and fix the shared cause.", "priority": "high", "reason": "Failed runs this week"})
        if not props_:
            props_.append({"title": "Watch new entrants on the leaderboard", "detail": "Report anyone who could take our place.", "priority": "low", "reason": "Holding the target"})
        open_dyn = re.findall(r"^- (\d+) · dynamic · (\w+) ·", text, re.M)
        support = re.findall(r"^- (.+?) \(support", text, re.M)
        for i, p_ in enumerate(props_): p_["team"] = support[0] if support and i == 0 else ""  # the first goes to a supporting team, if any
        return {"summary": f"{name}: {len(props_)} task(s) from the latest results.", "proposals": props_,
                "reprioritize": [{"id": int(open_dyn[0][0]), "priority": "high" if open_dyn[0][1] != "high" else "medium", "reason": "Results moved"}] if open_dyn else []}
    if "reply" in props:
        ask = text.rsplit("The user's message:", 1)[-1].strip()
        seen = [f"{pics} picture(s)" if pics else "", "a transcript" if "<transcript" in text else "", "web results" if "<web_results" in text else "",
                "the team brief" if "<team_brief>" in text else "", "the mission" if "<mission" in text or "<fixed_task>" in text else "", "a file" if "<attached_file" in text else ""]
        seen = [s for s in seen if s]
        return {"reply": f"{name} here. You said: {ask[:200]}" + (f"\n\nI read {', '.join(seen)}." if seen else ""),
                "suggestions": ["What should I do next?", "Summarize the risks"],
                "task": {"title": "Benchmark the miner against the top 10" if "task" in ask.lower() else "", "detail": "Run the validation set and compare." if "task" in ask.lower() else ""}}
    if "result" in props:
        return {"status": "needs_input" if "blocked" in text.lower() else "done", "result": f"## Result\n{name} delivered: {text.splitlines()[0][:160]}",
                "summary": f"{name} finished the task."}
    return None


def factory():
    return Client()
