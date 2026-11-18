---
title: Long tasks
section: guide
order: 4
icon: layers
summary: Agents for work that takes hundreds of steps, such as reviewing dozens of papers. The task's state lives in files, and each agent's prompt is rebuilt at every step, so it never grows.
---
[Long tasks](#infiagent) runs agents on work too long for one conversation: reading and noting 80 papers, building a report from a folder of notes, or comparing every subnet in a field. It follows **InfiAgent** ("An Infinite-Horizon Framework for General-Purpose Autonomous Agents", Yu et al., Findings of ACL 2026).

Ordinary agents keep everything in their conversation, which grows until older parts get cut or summarised and the agent loses its place. Long tasks keep the task's state in a **workspace** of files instead, and rebuild each agent's prompt from scratch at every step. The prompt stays the same size however long the task runs.

Long tasks is for everyone who can use [agents](#help/agents). Tasks spend the same model credits as agent chats.

## Start a task

1. Open **Long tasks** and choose **New task**.
2. Describe the work and what the result should be.
3. Attach the documents it needs. They go into a folder of the workspace (`docs/` unless you change it).
4. Pick the model, an optional cheaper **thinking model**, the token budget and the effort, then choose **Start**.

Text, Markdown, code, CSV and JSON files can be read. PDFs are read only if the server has the `pypdf` package. Without it, an agent reading a PDF is told it can't.

## How the agents work

| Level | Agents | What they do |
|---|---|---|
| 3 | **Alpha** | Plans the task in `plan.md`, hands one subtask at a time to a domain agent, checks what comes back, and finishes. |
| 2 | **Data collection**, **Data analysis**, **Coder**, **Writer** | Each does one kind of work in the workspace and returns a short result to the Alpha. |
| 1 | **Document reader**, **Subnet data** | Do one thing each: answer a question from documents, or fetch AXoR's live subnet data. |

Each agent calls the agents below it as tools and gets back only their result. Agents work one at a time.

**Every step starts fresh.** An agent's prompt holds:
- the latest instruction
- earlier runs on this workspace
- the chain of agents above it
- its own task
- its **thinking record**
- its **action window**: the actions it has taken since the record was last rewritten

Nothing else carries over between steps.

**The thinking record.** When an agent starts, and then every *thinking interval* tool calls, a thinking model rewrites the agent's record in four parts:
- a to-do list (done, ongoing, waiting)
- the files worth reusing and when to use them
- pinned state that must survive (the workspace's structure, rules, failed attempts, contents still needed)
- the next tool steps

Then the action window is cleared. Agents are told to write progress to files as they go, because anything only in the window is gone at the next rewrite.

**Documents stay out of the prompt.** The Document reader goes through each document in chunks, in separate model calls, and returns only the answers. That's how a task can get through many long documents without filling the agents' context. The paper calls this *external attention*.

## Follow a task

The task page updates live:

- **Agents**: the Alpha and the agents it called, with each one's tool calls, record rewrites, and calls left until its next rewrite. Pick an agent to see its record.
- **Thinking record**: the selected agent's four blocks. It also shows the **action window** (everything the agent sees of its recent history), earlier records and the agent's full system prompt.
- **Trace**: the latest steps of every agent.
- **Workspace**: every file, with whether you or the agents made it. Open a file to preview it, download it, or add more files.
- **Coverage**: the paper's check for long tasks. A document counts as covered only if the trace shows it was read and an output line names it with at least eight words. By default it checks the files you uploaded. Type a regular expression to check other files.

## Pause, resume, follow up

- **Pause** stops the task after the current step. **Resume** continues from the last checkpoint: each agent keeps its record, its window and its place, and a waiting parent gets its child's result when the child finishes. Nothing is replayed.
- A **server restart** resumes running tasks the same way, by itself.
- When the token budget runs out, the task pauses. Raise the budget in the task's header, then resume.
- If the model fails (a bad key, a rate limit), the task pauses with the reason, and resume continues once the model works again.
- **Cancel** ends the run for good. The files stay.
- When a run ends, **Follow up** starts a new run on the same workspace. The new Alpha sees the earlier instructions and results as recent task history.

You can have two tasks running at once and keep 100 tasks.

## Settings

| Setting | Default | What it does |
|---|---|---|
| Action window | 12 | The most recent actions shown in an agent's prompt. The last three are shown in full and older ones are cut short. |
| Thinking interval | 12 | Tool calls between record rewrites. The window is cleared after each rewrite. |
| Plan length | 12 | The most next steps a record may plan. |
| Token budget | 1,500,000 | When it's used up, the task pauses until you raise it. |

The paper used 30 for all three, and you can choose that under **Context window settings**. Every step's prompt carries the whole window, so a window of 30 costs about twice as many tokens per step as 12. Smaller values make each step cheaper and rewrite records more often.

## Limits

- Agents read and write only the task's workspace, plus AXoR's subnet data. They can't run code (the Coder writes code that nothing runs) or browse the web.
- A domain agent stops after 250 tool calls and the Alpha after 400. A stopped agent returns its thinking record as its result.
- The workspace holds up to 3,000 files and 100 MB, with files up to 5 MB.
- File contents and tool results are data to the agents, never instructions.
- A restart can repeat the one action that was in progress, so an `append_file` caught mid-way may add its text twice.

## API

Everything on the page is under `/api/infiagent`; see the API reference. Files upload with `PUT /api/infiagent/tasks/{id}/files?path=…`, with the raw file as the request body. `GET /api/infiagent/stream?task={id}` sends the task's state as server-sent events.
