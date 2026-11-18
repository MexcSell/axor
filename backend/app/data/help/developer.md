---
title: Developer: files, terminals and Claude Code
section: admin
order: 9
audience: admin
icon: code
summary: The administrators' development page: a file explorer, an editor and viewer, terminals on the server and a Claude Code (or Codex) conversation, side by side like an editor.
---
**Developer** is where an administrator works on code by hand: a file explorer, an editor and viewer, terminals on the server, and a Claude Code (or Codex) conversation, side by side like an editor. It is the **last item of the sidebar** ([Developer](#developer)), shown only to administrators; like Sidebar layout, it stays visible with System folded and in Simple mode.

## What it is, and what it is not

Developer is the administrator's **own tool**, not an agent:

| | Developer page | AXoR's agents |
| --- | --- | --- |
| Runs as | the server's user, in the server (the AXoR pod on Kubernetes) | their own runs, sandboxes and gates |
| Commands | no command filter | governance, sandbox and budget checks |
| Claude Code tools | every tool allowed in the opened folder | the tools and autonomy each agent is granted |
| Audit | every terminal, prompt and file change | every run and tool call |

Consequences:

- Only administrators can open it, and **every change asks for your password or authenticator code** (sudo, as for Machines' console): opening a terminal, saving, creating, moving, uploading or deleting files, opening a folder. It then stays unlocked for 10 minutes. Stopping a run or closing a terminal never asks, and neither does the Claude panel: typing, pasting images and sending a prompt there work without the password box.
- Pausing or stopping agents does not stop this page: you can still look and repair while agents are stopped.
- Everything done here is in the **Audit log** (System → Audit & settings) with actions starting `dev.`: `dev.terminal_open`, `dev.claude`, `dev.file_write`, `dev.file_delete`, `dev.folder_open`, …
- A shell here sees what the server sees, its settings included. Treat it like a root console.

## Layout

```
┌──────────┬──────────────────────────────────────┬──────────────────┐
│ Explorer │ Editor / viewer tabs                 │ Claude Code      │
│          │──────────────────────────────────────│ conversations    │
│          │ Terminal tabs                        │                  │
└──────────┴──────────────────────────────────────┴──────────────────┘
```

Drag the gutters to resize; each window can be **minimised** (a slim strip, click to restore) or **maximised** (fills the page). Sizes and states are kept in this browser. On a narrow screen the windows stack and the page scrolls.

The page is built once: switching to another page and back keeps terminals, open files and conversations.

## Explorer

- **Folders:** AXoR's own code folder (`axor`), its data folder (`data`), and folders opened with **＋ Open folder…** (kept for all administrators until closed with ✕; closing never changes anything on disk).
- **Files:** click opens; right-click for new file/folder, upload, rename, duplicate, cut/copy/paste, compress, extract, download, *Open in terminal*, *Run in terminal* (Python, shell, Node, …) and *Ask Claude about this*.
- **Upload:** drag files or whole folders from your computer onto the tree (up to 50 MB per file).
- **Git:** changed files are marked `M` / `A` / `U` / `D` / `R`; folders with changes get a dot. `.git` is never listed and is read-only. (Where the server has no `git`, as in AXoR's image, there are no marks.)
- **+** opens another explorer window on another folder (even `/`), stacked or side by side.

## Editor and viewer

Code with line numbers and syntax colouring, Markdown preview, CSV tables, formatted JSON, images, PDF, Word documents, audio and video. Every text file can be edited (*Edit*, [[Ctrl]]+[[S]] saves). Find in file with [[Ctrl]]+[[F]]. Open tabs come back after a reload; files changed on disk (for example by a Claude run) reload unless you have unsaved edits.

## Terminal

Real interactive shells on the server (`bash`, coloured prompt with the git branch), up to 12 at a time. A shell keeps running when the browser closes or the connection drops: the tab reconnects from the last byte it has, and a shell lost to a server restart is replaced in place on the next key. [[Ctrl]]+[[`]] shows and focuses the terminal. Drop explorer items onto it to type their paths.

## Claude Code panel

- **Conversations as tabs**, one per conversation of this browser session (new ones on the far right). Each is titled by Haiku after its first prompt. Earlier conversations and other Claude Code sessions running on the server are in the **Sessions** window (clock button, `/history`, `/resume`): open, continue, stop or delete them.
- **Agent, model and effort** per prompt: Claude Code or Codex, with the CLI's model aliases (Default, Opus, Sonnet, Haiku). The panel uses the server's own Claude Code login, the one AXoR's agents use (Agents → Models), never an API key; Codex uses the server's Codex sign-in.
- **Composer:** [[Enter]] sends, [[Shift]]+[[Enter]] new line, [[Esc]] stops, ↑/↓ earlier prompts. Paste or drop images and files to attach them (up to 10 MB each, 10 per prompt); drop explorer items to insert `@path`.
- **Display:** each prompt is a one-line bar pinned to the top of the log; tool calls and thinking fold into one "N steps" line; what the agent says and the result always show.
- **`/status`**, **`/tasks`**, **`/agents`** open a drawer: account, plan limits and token use of the server's Claude login, background tasks and todos, subagents and custom agents. Cost is not shown: AXoR keeps no price table, so tokens are counted instead.
- Claude Code runs in the folder open in the explorer with every tool allowed (`acceptEdits`).

## Keyboard shortcuts

| Where | Keys |
| --- | --- |
| Anywhere on the page | [[Ctrl]]+[[`]] terminal · [[Ctrl]]+[[L]] Claude · [[Esc]] closes a menu |
| Explorer | ↑ ↓ ← → · [[Enter]] · [[F2]] rename · [[Delete]] · [[Ctrl]]+[[C]] / [[X]] / [[V]] · [[Ctrl]]+[[F]] filter |
| Viewer / editor | [[Ctrl]]+[[F]] find, [[Enter]] / [[Shift]]+[[Enter]] next / previous · [[Ctrl]]+[[S]] save |
| Terminal | [[Ctrl]]+[[C]] copies a selection ([[Ctrl]]+[[Shift]]+[[C]] always) · [[Ctrl]]+[[V]] paste |
| Claude composer | [[Enter]] send · [[Shift]]+[[Enter]] new line · [[Esc]] stop · ↑/↓ history |

## What is kept where

| What | Where |
| --- | --- |
| Opened folders | `DATA_DIR/developer/roots.json` (all administrators) |
| Layout, open tabs, conversations, last model/effort | this browser's storage (keys `dvp.*`) |
| Claude panel attachments | `DATA_DIR/developer/uploads/` |
| Claude Code transcripts | the server user's `~/.claude` |
| Running shells and Claude runs | the server's memory; a Claude run continues across a restart and is followed from its transcript |

On Kubernetes only `data` is on a volume. The `axor` folder there is the code inside the running image, owned by root while AXoR runs as `scout`: you can read it but not change it (change the code in the repository and deploy instead). The server's home folder is not on the volume either, so shell history and Claude Code transcripts start afresh after a redeploy; Codex's sign-in is under `data` and stays.

The page was ported from the Agent Company project's Developer page (its `docs/developer.md`); AXoR names it `developer` (view `#developer`, API `/api/dev/…`, files `dvp-*.js`, `dvp.css`, `developer.py`, `dev_files.py`, `dev_terminal.py`, `dev_claude.py`) because AXoR already has a Workspace page.
