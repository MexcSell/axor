---
title: Knowledge Hub and My Knowledge
section: guide
order: 4
icon: book
summary: Two spaces. My Knowledge is your private space of folders, sources, messages, ideas and connections. The Knowledge Hub is your agent company's governed knowledge, with scopes, review, and agents that read and contribute within limits. Nothing moves from one to the other, or reaches an agent, unless you choose.
---
Knowledge lives in two spaces, both in the sidebar under **Knowledge**:

- **[My Knowledge](#myknowledge)** is your personal space and is **private by default**. It holds your notes, files, web pages, chat messages, ideas and how they connect.
- **[Knowledge Hub](#knowledge)** holds **company knowledge**: what your agent company knows, scoped to the company, a division, a project, a team or one agent. Your agents read it and contribute to it, and you approve what becomes trusted.

The switch at the top of either page takes you to the other. Publishing from My Knowledge to the company is a separate step, and it always goes through review.

## My Knowledge

### Overview

- **Ask My Knowledge** answers a question from your records (from My Knowledge, the company's knowledge, or both, or only the My Knowledge folders you tick). Each point cites the record it comes from, such as `[kb:12]`, and the evidence below the answer shows the passage it used and where it is (page, section, time). The answer's main points are marked **Backed by evidence**, **Inference** or **Unverified**, and each cited point is checked against its passage. Citations to records that weren't retrieved are removed. See *Retrieval & quality* below.
- **Search** (the bar under the title) runs the same search your agents use. It covers your records and sources, what your agents remember, your teams' lessons, Workforce's memory and the company's knowledge. It matches words and, when an embeddings endpoint is set, **meaning**: a result found only by meaning is marked *Matched by meaning* (see Search by meaning below).
- **Inbox** lists what's waiting in `/00-Inbox`. **Organize** sends one item to the model for suggestions (see Workspace).
- **Waiting for you** lists adopt proposals and import previews.

### Workspace

Workspace is a **directory tree** that starts with: `00-Inbox` (Quick-Notes, New-Ideas, Bookmarks, Unprocessed), `01-Personal`, `02-Projects` (AXoR, Bittensor/SN62, Bittensor/Research, Handshake, …), `03-Research`, `04-Sources` (Documents, Websites, Git-Repositories, Datasets), `05-Communications` (Slack, Discord, Telegram, Pasted), `06-Ideas-and-Connections`, `07-Knowledge` (Concepts, Procedures, Experiences, Decisions, Lessons-Learned) and `99-Archive`.

- Make subfolders, rename or move a folder (everything in it moves too), and delete empty folders.
- Tick items to **move** them, **share them with your agents**, make them **private** again, or **publish them to the company**.
- Folders organize knowledge without copying it. A record lives in one folder, and connections tie it to records anywhere else.
- **Find in My Knowledge** searches titles, text and tags across every folder.

**Capture** (the button at the top, or **Capture here** in a folder) adds:

| Kind | What's kept | Where it goes |
|---|---|---|
| Note | Your text | 00-Inbox/Quick-Notes |
| Idea | An idea, with stages and AI analysis (see Ideas) | 06-Ideas-and-Connections/Ideas |
| Web page | The page's text, read once from a public address. If it can't be read, the address is kept as a bookmark with the reason. | 04-Sources/Websites or 00-Inbox/Bookmarks |
| File | A text file up to 1 MB (notes, Markdown, code, CSV, JSON), with a line on its structure: its sections, its rows and columns, or the functions it defines and the libraries it uses | 04-Sources/… by kind |
| Document | Word (.docx), PowerPoint (.pptx), Excel (.xlsx), OpenDocument (.odt, .odp, .ods), PDF, EPUB, HTML and RTF up to 25 MB, read on the server with no model: headings, slides, sheets and pages are kept | 04-Sources/Documents or Datasets |
| Picture | PNG, JPEG, GIF or WebP up to 5 MB, read by a model that sees images: every piece of text in it, word for word, and what it shows (a chart's axes and values, a diagram's parts) | 04-Sources/Images |
| Audio or video | MP3, WAV, M4A, OGG, FLAC, MP4, MOV or WebM up to 25 MB, transcribed with timestamps; a model then names the key sections | 04-Sources/Audio or Video |
| Paste / Conversation | Pasted text or a pasted chat | 00-Inbox/Unprocessed, 05-Communications/Pasted |

The original of a document, picture or recording is kept on the server: **Download the original** on its page (only you can). **Read it again** reads it once more, for example after you set a model that sees pictures or a transcription endpoint. Pictures need a model from Anthropic, OpenAI, OpenRouter or a local server: the Terminal and Codex providers can't take pictures. Audio and video need an OpenAI-compatible transcription endpoint: the OpenAI key in Agents → Models, or `KNOWLEDGE_TRANSCRIBE_URL` on the server. Without one, the file is kept and its page says why it wasn't read. Scanned PDFs hold no text: add their pages as pictures.

Everything you capture starts **private**. Secrets that look like keys or tokens are removed, and capturing the same thing twice is refused.

**Sources and records are kept apart.** A file, page, paste or message is a **source**: the original text, with where it came from. What you learn from it becomes a **knowledge record** of its own (**Make a knowledge record** on the source), linked back to the source with *derived from*. If you rewrite the record later, the evidence is still there.

An item's page shows its folder, its **knowledge type** (declarative, procedural, episodic, strategic, technical, evaluative), its tags, **who reads it**, its connections, its provenance and its versions. **Organize with AI** sends one model call that suggests a folder, tags, a type, connections to your existing records, claims worth checking, and a record to derive. Nothing changes until you tick what you want and press **Apply what's ticked**.

### Who reads an item (visibility)

| Shown as | Meaning |
|---|---|
| Private | Only you |
| Shared with your agents | You, your agents and the Assistant (the `search_knowledge` tool) |
| Shared with your agents and teams | Also your competition teams, in their context |
| Company candidate | A copy waits for review in the Knowledge Hub |
| Approved for the company | That copy was approved: agents read it within its scope |
| Not approved for the company | The copy was rejected (it's kept there with the reason) |
| Archived | Kept, but left out of search |

### Sources

- **Files & web pages**: every source you captured, with its kind, folder and visibility.
- **Imports**: earlier workspaces and other agent platforms' exports (see below).
- **Adopt**: proposals to adopt imported capabilities into your agents (see below).

### Communications

Communications puts messages from **Slack, Discord and Telegram** in one inbox. You can list them by platform or channel, search messages and authors, tick messages and **Save as a note** (a transcript linked to each message). Each message keeps its platform, workspace or server, channel, message id, author, time, thread or reply, attachment names and links, and is stored under `05-Communications/<Platform>/<channel>`.

- **Slack**: when an administrator has connected a channel on the Slack page, **Sync now** reads that channel's recent messages that are newer than your last sync. It's read only. You can also import a channel export (a day's JSON file; give the channel's name).
- **Discord**: connect a bot of yours (Settings & connectors → **Connect Discord or Telegram**) with the ids of the channels it may read, or import a channel exported with DiscordChatExporter (JSON). The bot needs View Channel, Read Message History and the Message Content intent. A sync reads up to 500 new messages per channel; the first one takes the latest 100.
- **Telegram**: connect a bot of yours, optionally limited to some chat ids, or import Telegram Desktop's export (`result.json`, a single chat or the full export). A bot sees what people send it, and group messages only with privacy mode off (or as an admin). Telegram hands each update out once, so use a bot that does nothing else; a bot with a webhook can't be read this way.

Connectors are read only. Their tokens are encrypted on the server and shown only masked. **Sync now** reads what's new since the last sync, and **Sync automatically** does it every 15 minutes. Removing a connector deletes its token; the messages it brought stay.

Messages you already have are skipped. Each import can be undone. Messages are other people's words, so they're marked untrusted and stay private until you share or publish them.

### Ideas

Add an **idea, note, requirement, strategy or improvement**. **Analyze with AI** sends one model call with the idea and the related work AXoR finds (records, your agents, Company projects, Workforce missions, competition teams and team lessons). The analysis returns a sharper summary, a category, tags, the value and effort, the related items, 2 to 6 tasks (each with who should do it), a plan, the risks, and how you'll know it worked.

Move an idea through **proposed → analyzed → planned → doing → done → evaluated** (or dropped), with an optional note at each step. To mark it evaluated, write what happened and give it a score.

### Connections

Records connect with typed relationships: **supports, contradicts, implements, belongs to, derived from, related to, supersedes, depends on**. You can connect two records here or on either record's page. The **graph** shows the 160 most connected records, colored by top-level folder. Red lines contradict, dashed lines supersede, and clicking a record opens it.

### Company sharing

Pick items, choose **where they apply** (the whole company, a division, a project, a team or one agent) and optionally a knowledge type, then **Submit for review**. A copy goes to the Knowledge Hub's review with its provenance. Nothing becomes company knowledge until you approve it there.

### Settings & connectors

This tab shows the connectors (Slack, and your Discord and Telegram bots: connect, edit, sync, remove), **Search and reading** (how search works on this server, how much is indexed, and what reads PDFs, pictures and recordings; **Rebuild the index**), how many of your items are private, shared or published, **Export** (the whole workspace as an `axor-workspace/1` file), the safety rules and the activity log.

### Linked folders

Administrators can link folders on the AXoR server itself (Settings & connectors → **Linked folders** → **Link a folder**): pick the server folder (for example `/home/thomas/bit`), browse to the folder you want, choose who reads its files, and link it. AXoR reads it through **AXoR Host files**, a separate read-only service that only AXoR can reach. Nothing on the server is ever changed.

- **What is read:** text and code files, plus documents (Word, PowerPoint, Excel, OpenDocument, PDF, EPUB, HTML, RTF). Pictures, audio, video and binary files are skipped, so a sync never spends a model call. Each file becomes a source in **/06-Linked/<name>**, one subfolder per folder on disk (4 levels deep at most). Its title is the file's path.
- **What is never read:** `.env` files, keys and certificates, credential stores, `.git`, virtual environments and caches, whatever you pick. Files that only root can read are listed as not readable. **Leave out** adds your own patterns (`*.log`, `runs/old`). `*-data` is there by default because ridges-intel's `*-data` folders hold copies of other miners' published agents.
- **Keeping in sync:** **Sync now** checks again; **Sync automatically** does it every 10 minutes. A changed file becomes a new version of its item, and a file that is deleted or newly left out leaves My Knowledge. A link reads 1,000 files at most and says when there are more. Link your own work folders one by one rather than a whole large folder.
- **Who reads it:** set for all of a link's files at once (default: your agents and teams). Agents find these files when they search My Knowledge: each search returns the best few passages, not whole folders.
- **Unlink** removes the link's files from My Knowledge. The folder on the server isn't touched.

New server folders (roots) are added in `k8s/host/42-hostfiles.yaml`, then a redeploy.

### Search by meaning

Every item gets a vector in the background. With an embeddings endpoint (the OpenAI key in Agents → Models, which uses `text-embedding-3-small`; else the OpenRouter key; or `KNOWLEDGE_EMBED_URL` and `KNOWLEDGE_EMBED_MODEL` on the server), a search also finds records that mean the same thing in other words: *signup* finds a note about enrolling. Without one, the built-in vectors match other forms and spellings of the same words, not synonyms, and the page says so. If the endpoint is down, search falls back to words. Your agents' searches use the same ranking, inside their permissions. Embedding calls are logged as usage source `knowledge`.

### Sharing with people

On an item's page, **People** shares it with other users of this AXoR by username. In Workspace you can tick several items and use **Share with people…**. They see it under **Shared with me** (in Workspace and on their Overview), read only, and can **Save a copy** into their own folders: the copy is theirs and private, marked *shared by* you. Their agents never read your item, only a copy they chose to share with their agents. **Stop sharing** takes it back, and deleting the item ends its shares. Only people who can open the Knowledge Hub can be picked: when agents are for administrators only, that's the other administrators. Company records aren't shared this way, because each account has its own agent company.

### Retrieval & quality

Every answer and every agent reads your knowledge through one retrieval pipeline (retrieval-augmented generation):

1. **Permissions first.** What the reader may see is decided before anything is searched: you see everything you hold; your agents see only items you shared with them and verified company records in their scopes; competition teams only what you let teams read. Private content is never searched for a reader that may not see it, so it can't reach a model.
2. **Passages.** Every item is split into passages of about 1,100 characters along its structure: headings stay with their text, code blocks and tables stay whole, and PDF pages and recording timestamps are kept, so a citation can say *page 4 · Evaluation*. An edit makes new passages.
3. **Hybrid search.** Three searches run over the permitted passages: keywords (BM25, which finds exact terms such as error codes, identifiers and names), shared words, and meaning (vectors; long items get a vector per passage). Their rankings are fused.
4. **Reranking.** The top results are rescored on the entities your question names (such as SN62), headings, review state and confidence (verified up; contested, superseded and past-review records down) and time (*latest*, *last week*, *in 2025*).
5. **Links.** One step along your typed connections adds closely linked records, marked *linked from*.
6. **Answer.** The best passages go to the model with their source and place. A question with several parts gets up to three follow-up searches (**Research**: *Deeper when it has several parts*, *Always*, or *One search*), and **Rerank with the model** has the model rate the passages first (more tokens).

Answers are never saved as knowledge by themselves: save what you want to keep.

The **Retrieval & quality** tab (on both pages) shows this with your numbers:
- **How it works**: the pipeline with your counts, the embedding models and their vectors (kept per model; remove an old model's), and index health (duplicates, files that couldn't be read, items with almost no text, failing connectors). **Rebuild passages** makes them all again.
- **Try retrieval**: run any query with any strategy, optionally **as** one of your agents, teams, projects, Workforce, Mission Control or the Assistant, to see exactly what it would get, with the passage, where it is and why it matched. Tick the right results and **Save as a test question**.
- **Evaluation**: test questions with the records that should come back. **Run evaluation** compares the strategies (shared words as before, keyword, meaning, hybrid, and hybrid + rerank + links, which is what answers and agents use) on Recall@k, Precision@k, MRR, nDCG@k, top-1 and speed, and shows how many results were stale. It also checks **permission isolation**: each question is retrieved as an agent and a team with no grants, and every result is checked again against the rules. Optionally it asks up to 10 questions and scores faithfulness and citation accuracy (a word-overlap check, not a model's judgment). Questions you asked with Ask are suggested as test questions with the records the answer cited. Run it again after you change the embeddings model or how you capture knowledge.
- **Retrieval log**: every retrieval by you, your agents, competition teams, Workforce and Mission Control: who, the query, how many records it was allowed to search, what came back, and how long it took. Evaluation runs aren't logged.

## Knowledge Hub (company knowledge)

Every company record has:

- **a scope**: the whole company, a division or project from the [Company](#company) page, one of your competition teams, or one of your agents;
- **a type**: *declarative* (facts and concepts), *procedural* (how to do something), *episodic* (what happened), *strategic* (a decision and its reasoning), *technical* (code, architecture, configuration) or *evaluative* (test results and evidence);
- **a review state**: *waiting for review*, *verified*, *contested*, *not approved* or *superseded*;
- a confidence, a review date, an owner, its contributor, its evidence and provenance, and every version.

### Where records come from

- **You**: **Add knowledge**. Tick *I've reviewed it* to approve it as you add it.
- **My Knowledge**: published items (see Company sharing).
- **Your agents**: the `contribute_knowledge` tool. An agent can submit up to 10 records a day, in a scope it may read (its own by default). Its contributions wait as candidates and never become trusted on their own.

### Review

The queue lists records that are **waiting for review**, **contested**, **past their review date**, or that agents **reported as not useful** more often than useful. A record's page shows:

- **automatic checks**: whether it gives evidence or a source; secrets that were removed; external origin; instruction-like text such as "ignore previous instructions"; possible duplicates; possible contradictions (same subject, different content, with a **Compare** link); a scope that no longer exists; agents' negative feedback;
- **Review with AI** (optional, one model call): a verdict (approve, revise or reject), the reasons, how strong the evidence is, the risks, a suggested confidence, a type and a review date. It's advice only;
- **Approve this version** or **Reject**, with a note, a confidence and the next review date. The approval applies to the exact text you read: if the record changed after you opened it, you're asked to read it again. Rejected records are kept with your reason, so failed experiments are never deleted silently. A record that has been reviewed can be archived but not deleted.

Contradictions are flagged, never overwritten. A *contradicts* link from another record marks a verified record **contested**: agents still read it, labelled as contested, until you decide again. A *supersedes* link marks it **superseded**, and agents stop reading it. If you widen a record's scope to the whole company, it goes back to review.

### Divisions & projects

The scope tree shows the company, its divisions and projects, your competition teams and your agents, with the records in each scope and **who reads it**. **Grant** lets another agent, team, Company project or the Assistant read a scope. A grant widens access across projects, so only you can give one, and it's logged. **Revoke** takes it back.

### Other tabs

- **Knowledge**: every record, filtered by type, state, scope and whether it came from an agent or a person.
- **Contributions**: what your agents submitted, waiting and decided, and what you published from My Knowledge.
- **Skills & procedures**: procedural and technical records.
- **Experiences**: episodic and evaluative records, with their outcomes.
- **Graph**: records and their connections, colored by scope.
- **Analytics**: the most reused records, who reads, usefulness (agents' ratings and your outcomes), how many contributions are accepted, records by type and state, verified records nobody read in 60 days, the latest reads, and the activity log.

On a record you can also record **outcomes** (it worked, mixed, it failed, with a note). Every read is a **reuse event**: who read it (an agent, a team, a Company project, the Assistant or you), when, and for what.

### Outcomes, discovery and improvement

- **Outcomes move confidence.** Outcomes come from you (on a record's page) and from agents (`report_outcome`). Each one is kept with the record, failures too, and moves the record's confidence. The confidence you approved it with counts as much as four outcomes: from 80%, one failure brings it to 64% and one success to 84%. Each move is a new version that gives the reason, and the record's page shows the history.
- **Flagged by its outcomes.** A verified record is marked **contested**, and waits in Review, when either of these is true since its last approval:
  - two or more outcomes failed and fewer worked (a mixed outcome counts half each way);
  - its confidence fell under 40%.

  Agents still read it, labelled contested. Approving it again clears the flag and restarts the count from the confidence you set.
- **Draft a revision** (one model call) rewrites a reviewed record from its outcomes, agents' notes and contradicting records. The draft is a new record waiting for review, with the list of changes. The original stays as it is until you approve the revision, which then supersedes it.
- **Access requests.**
  - When an agent searches, it also learns which scopes it can't read hold verified records matching its search. It sees each scope's name and how many records match, never their titles or text.
  - It can ask for one scope with `request_knowledge_access`, giving a reason. Requests appear in Review and in the [Approval Center](#approvals).
  - **Let it read this** is an ordinary grant: logged, and revocable under Divisions & projects. After **Decline**, the agent sees your note and doesn't ask for that scope again for a week.
- **Connections across projects** (Graph tab):
  - Verified records in different scopes that say related things, which you can **Link** or **Dismiss**. They're found by meaning when there's a search index, otherwise by shared words.
  - **Possible duplicates** within one scope: keeping one supersedes the other.
  - Up to 240 recently updated records are compared.
- **Freshness & improvement** (Analytics):
  - records due for review now and within 14 days;
  - records flagged by their outcomes or reported not useful;
  - revisions and access requests waiting;
  - the last 30 days' outcomes and the latest confidence moves.

## How agents read and write

| Who | Reads company records in | Reads My Knowledge items |
|---|---|---|
| One of your agents (chat) | The company, its own scope (*agent: name*), granted scopes | Shared with your agents (or with agents and teams) |
| The Assistant | The company, granted scopes | Shared with your agents |
| A competition team (its agents' tools and context) | The company, its own team scope, granted scopes | Shared with agents and teams |
| A Company project team (run) | The company, its project and division, granted scopes | None |
| Workforce (the CEO's plan and its agents' tools) | The company, scopes granted to Workforce | Shared with your agents |
| Mission Control (discovery and the Intelligence Analyst) | The company, scopes granted to Mission Control | Shared with your agents |

Access is filtered **before** anything is searched, so a scope an agent can't read never shows up in its results. Agents read only *verified* and *contested* records, and every result comes with its scope, type, review state, confidence, whether it's past its review date and where in its source the passage is. Results are ranked as described under *Retrieval & quality*.

Agents decide for themselves when to look things up. Your agents, the Assistant, competition teams' agents, Workforce's agents and Mission Control's Intelligence Analyst have:

- `search_knowledge`: a query, optionally narrowed to one scope (a ref such as `project:3`, or a name such as `SN62`) and one knowledge type;
- `research_knowledge`: a question with several parts, researched in up to four searches (the question, each part, then a follow-up on the names and identifiers the first passages mention); each result says which search found it. It costs more of the agent's lookups;
- `knowledge_feedback`: say whether a record it retrieved in the last week helped;
- `report_outcome`: what happened when it applied a company record it retrieved in the last 14 days: worked, failed or mixed, with what it observed. Up to 20 a day, one per record a day;
- `request_knowledge_access`: ask you for a scope that its search results listed as holding matching records it can't read (at most 5 open requests per agent).

Your agents and the Assistant can also `contribute_knowledge`: submit a record for review (title, text, type, scope, evidence).

Competition teams, Workforce's CEO and Mission Control's discovery also start with the records that fit their goal. A Company project team's run starts with the records that fit **its task** (title, description, project), then the most confident other records it may read.

**Learning from ratings:** with *Use agents' ratings in ranking* on (Retrieval & quality → How it works; off by default), records agents rated useful in the last 180 days rank a little higher and ones rated not useful a little lower. Every evaluation run measures the ranking with and without the ratings, and the switch shows whether they helped your test questions.

Retrieved records are always marked as data, not instructions. Every search is in the Retrieval log, with the agent, team or service that ran it.

## Imports and adopting capabilities (My Knowledge → Sources)

You can import two kinds of file (JSON, JSONL, CSV, Markdown or text, up to 10 MB), or paste the text:

- **An earlier workspace**: the **Export** file (`axor-workspace/1`, from this AXoR or another), a bundle from `tools/mining-import.py`, or any export with lists such as `agents`, `tasks`, `runs`, `workflows`, `skills`, `tools`, `lessons`, `reports`, `projects`, `files` or `notes`. Nested items keep their parent.
- **External agents' experience**: agent histories, successful and failed runs, workflows, skills, tools, lessons and performance reports from another platform.

The file is read into a **preview**, with duplicate checks: content you already have is left out; for a similar title you choose *keep both*, *replace* (the old text stays as a version) or *skip*. **Pull out lessons with AI** adds reusable lessons, each with a quote checked against the file. **Apply** keeps what you ticked. **Undo the import** removes what it added, except items you changed since.

**Compare with my agents** recommends, for each imported capability, **Adopt** (a new agent, created paused, or a new skill), **Adapt** (a paragraph to add to one of your agents' instructions) or **Reject**. Nothing changes until you approve the exact change. **Roll back** undoes it. Waiting proposals and company records waiting for review are also listed in the [Approval Center](#approvals).

## Safety

- Files, pages, messages and imports are kept as text. Nothing in them runs, and nothing is fetched from links inside them. A web page is read only when you capture its address, and only from a public address.
- Secrets that look like API keys, tokens and private keys are removed on the way in, again on publishing, and on export. Connector tokens never become knowledge.
- Imported agents, workflows, tools, files and runs never reach competition teams: competitions such as Ridges ban copying other miners' work.
- Every step is logged in each page's activity log and in the account audit log (`knowledge.*`).

## Limits

- Search by meaning needs an embeddings endpoint: without one, the built-in matching knows word forms and spellings, not synonyms. Long items get vectors for their first 80 passages; keyword search covers all of them (up to 240 passages, about 200,000 characters).
- The citation check and the evaluation's faithfulness compare wording, not meaning: a correct paraphrase can count as weak support.
- Scanned PDFs (pictures of pages) hold no text: add the pages as pictures. On a server image built before `pypdf` was added, PDFs are read by a basic reader that misses text in some fonts.
- Pictures need a model that sees images, and audio and video a transcription endpoint. Files go up to 25 MB (pictures 5 MB), and video is transcribed, not watched.
- Slack syncs the one channel an administrator connected. Discord and Telegram read only through bots you create and add yourself.
- Shared items are read only for the people you share them with. They can't edit your original or comment on it.
- The thresholds for related records and duplicates are a judgement call, not measured on real embeddings. Outcome reports are the agents' own account: a contested flag sends the record to you to check, and nothing is rejected on their word.
- Model calls (Draft a revision, Ask, Organize, Review with AI, reading pictures, key sections, analyze, pull out lessons, compare) and embedding calls are logged as usage source `knowledge`.
