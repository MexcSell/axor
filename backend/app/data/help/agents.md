---
title: Agents and Assist
section: guide
order: 4
icon: users
summary: Creating and chatting with agents, memory and skills, models and usage, and the Assist panel beside every page.
---
## Who can use agents

[Agents](#agents) is for administrators unless an administrator turns on **Members can use agents**. The same setting covers the study tutors, drills, the board assistant, the AI review on My profile, [My subnets](#help/mining) and [Workforce](#help/workforce).

## The Agents page

One page for every agent, with a rail on the left:

- **Directory:** every agent you can see, from every system: your own, the ones shared with you or added from the shared catalog, the built-in ones, the [Company](#help/company), [Workforce](#help/workforce), [Competition teams](#help/mining) and, for administrators, the Workflow and Agent HQ. Filter by system, by state, or **Only mine**. A row opens the agent's profile (see [Agent operations](#help/agent-operations)); on your own agents the **⋯** menu edits, duplicates, pauses or resumes, publishes to the shared catalog, or deletes, and the chat button opens a chat.
- **New agent:** describe what you want and AXoR drafts the agent (name, role, instructions, skills, examples), or start from a template or a blank form.
- **Operations** and **Live runs:** what every agent is doing, what failed, the approval queue, token use and your daily budget.
- **Shared catalog:** agents people have published for everyone. Add one to your agents and it appears in your Directory.
- **Connected systems** and **Ecosystem**, then **Tools & MCP** (below), the **Skill hub** (reusable skills you can attach to agents, or apply to one answer), **My logins** and, for administrators, **Settings**.
- **Recents:** your latest chats.

## Tools & MCP

[MCP](https://modelcontextprotocol.io) servers give agents more tools: GitHub, a database, a search engine, your own services. AXoR's own tools only read data; an MCP tool does whatever its server allows, so access is opt-in at every step.

1. **An administrator adds a server** under Agents → Tools & MCP: **Remote (HTTP)** with its URL and headers (an `Authorization` header, for example), or **Local (command)**, a command that runs inside AXoR's container with its arguments and environment. Header and environment values are secrets: they're stored encrypted and never shown again; leave a value empty when editing to keep it. AXoR's image has Python but not Node or uv, so `npx` and `uvx` servers need the image changed; remote servers work as they are. Adding, editing, removing and allowing tools ask for your authenticator code (or password).
2. **Test connection** lists the server's tools. Tools the server marks read-only start allowed; tick any other tool only if agents should use it, then **Save allowed tools**. **Who may give it to their agents**: administrators only, or everyone who uses agents (they then use the server's credentials).
3. **Give it to an agent or a team.** In an agent's profile, the **Tools** tab has an **MCP tools** box: tick a server, and untick any of its tools the agent shouldn't have. On a Competition team, the **Agents** tab has the same box for the whole team. With every tool ticked, tools the administrator allows later are included too.

**The catalog** at the top of Tools & MCP adds the common servers in one click (**Add the free ones** adds every server that needs no key):

| Server | For | Key |
|---|---|---|
| GitHub (GitHub's official server) | Repositories, files, issues, pull requests, code search, Actions | A GitHub token, or the one Source already has |
| DeepWiki | Questions about any public GitHub repository, and its generated docs | None |
| Context7 | Current docs and code examples for libraries and frameworks (new tech stacks) | Optional |
| Exa search | Web search and page reading (research, essays, fact-checking) | None |
| Research papers (built in) | arXiv, OpenAlex and Semantic Scholar: search, a paper's details, what cites it | Optional (Semantic Scholar) |
| Database (built in, read-only) | PostgreSQL or an SQLite file: tables, columns, SELECT queries | The database URL |

The database server only reads: one SELECT-type statement at a time, a read-only session, at most 200 rows and 15 seconds per query, and never AXoR's own data folder. Give it an account that can only read anyway.

**Mission tools** (the last box on Tools & MCP) are the servers your missions may use. [Mission Control](#mos) runs a mission on Workforce, Long tasks or a Competition team; all three get your mission tools for your work, also when you start them outside a mission. A mission small enough for one answer runs without tools. Workforce counts each MCP call against the agent's lookups.

Agents see these tools as `ext_<server>__<tool>`. Each call is checked again (server on, tool still allowed, grant still there) and logged; administrators see the latest calls under Tools & MCP. A tool that fails or takes over 60 seconds costs the agent one call, not the run. Answers longer than 20,000 characters are cut.

## Chatting

Each agent's chat is laid out like a conversation with a teammate. Chats and activity are on the left; the header has **Share**, **copy link** (`#agents/<id>`) and a menu for memory, pause, duplicate, edit and delete.

The composer, shared by every chat in AXoR:

- **+** uploads a file (to the Shared drive), picks an **AXoR Drive** file or **Source** code, or applies a skill or a tool
- **@** mentions files, skills and tools while you type; **/** runs commands (`/new`, `/remember`, `/memory`, `/rename`, `/brain`, `/share`, `/help`)
- voice input, the **model pill** (and **Deep thinking**: low, medium or high) and the usage meter

Attached text is read up to 20,000 characters per file, six attachments a message. Answers render Markdown with copyable code, long answers fold, and you can edit and resend your own messages.

## Memory

Each agent keeps short facts about you across chats: it saves them itself, or you add them with `/remember …` or the Memory dialog. You can see and delete them. People an agent is shared with have their own memory.

## Models and usage

The model picker offers every connected model and **Auto**, the default an administrator picks. You can switch mid-chat; each answer shows which model wrote it and its tokens. Open the usage meter for your tokens today, this week and this month, by model and by feature.

## Assist

**Assist** in the top bar opens an agent beside the page you're on. It sits beside the page on wide screens and covers it on narrow ones.

- Everywhere, for everyone who can use agents, it's the **Assistant**: it knows AXoR's pages and reads subnets, your workspace, your study progress and the Source hub. It changes nothing.
- For administrators, operations pages have their own agent: DevOps, Functions, Apps, Cluster, DNS and User admin.
- Each message tells the agent which page it came from, so "this page" means the one you're on. **Open in Agents** continues the chat there.

## Approval cards

Built-in operations agents never change anything on their own. When one wants to act, it shows an **approval card**: nothing runs until an administrator clicks **Approve**, which asks for the same confirmation as doing it by hand and is audited.
