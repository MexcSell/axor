---
title: Tech Daily
section: guide
order: 9
icon: news
summary: A new edition of the day's technology every morning, in AI, software, Android, devices, IoT and security.
---
[Tech Daily](#tech) is a daily board of new technology, laid out like an ad campaign: a cover line, the day's spotlight, the lead story from every category, then a rail of more stories per category.

## Where the stories come from

Each morning AXoR's server reads:

- the public feeds of the tech press: The Verge, MIT Technology Review, TechCrunch, Ars Technica, The Register, Engadget, Android Authority, 9to5Google, GSMArena, CNX Software, Hackster.io, BleepingComputer and others, plus the blogs of OpenAI, Google DeepMind, Google, Hugging Face, GitHub, Android Developers and Raspberry Pi
- **Hacker News**'s top stories of the last day
- new **GitHub** repositories gaining stars this week

It sorts each story into a category, keeps the freshest and most talked-about, drops duplicates and stories that already ran this week, and allows at most a few stories from one outlet per category.

| Category | Covers |
|---|---|
| **AI** | Models, agents, research and AI products |
| **Software** | Releases, developer tools, open source, the cloud |
| **Android** | Android, Pixel, Galaxy, Wear OS and the Play Store |
| **Devices** | Phones, laptops, chips, wearables, TVs and consoles |
| **IoT** | Boards, microcontrollers, embedded and the smart home |
| **Security** | Vulnerabilities, breaches, malware and privacy |

## Who writes the copy

When your server has an agent model connected, it writes each story's **headline**, **tagline**, a short **pitch**, **why it matters** and **tags**, using only the story's own title and the outlet's summary, and rates how big the news is, which orders each category. It also writes the edition's cover line and picks the spotlight. Without a model, stories keep their outlets' own words.

> [!NOTE]
> The copy is written by AI from each outlet's summary. A story's sheet shows its original headline; check the source before you rely on a detail.

## Analysis and the research brief

Tech Daily also analyzes and summarizes the technology it covers. Both need a model connected (the same one that writes the copy, `TECH_MODEL`).

- **Research brief:** under the spotlight, a summary of **This edition** or the **Last 7 days**: a headline, an overview, the themes that run across several stories (each with chips for the stories behind it), takeaways, and what to watch. The day's brief is written with each edition. The week's is written the first time someone asks for it that day. The brief works from the stories' headlines and summaries, plus any analyses already written.
- **Analyze a story:** a story's sheet has an **Analysis** section. **Analyze** reads the article itself and writes a summary, what the technology is, how it works, key points, who it's for, what you could do with it, its limits and open questions, how mature it is (*Research*, *Announced*, *Preview*, *Beta*, *Available now*), a verdict (**Adopt**, **Try**, **Watch** or **Skip**), and how confident the analysis is. Anything from the model's own general knowledge appears under **Background**, kept apart from the article. If the article can't be read, the analysis is based on the outlet's summary, says so, and never claims high confidence. **Save analysis to notes** saves it to your workspace notes.
- Once a story has an analysis, everyone sees it, and its card shows *Analyzed*. Analyses are kept by link, so rebuilding the edition doesn't lose them.

Writing an analysis or a brief uses tokens, so you need to be signed in and allowed to use agents. The tokens count toward your usage as *Technology Research*. Each user can write 30 analyses per UTC day, and the server 150 (`TECH_ANALYZE_PER_USER`, `TECH_ANALYZE_DAILY`). Reading an analysis that's already written is free.

> [!NOTE]
> Analyses and briefs are written by AI. Check the source before you rely on a detail.

## Using the board

- **Categories:** the chips under the cover show one category at a time; **All** shows everything.
- **A story:** click a card for its sheet: the pitch, why it matters, tags, **Read on …** (the source), **Copy link**, **Share** and **Save to notes**. [[←]] and [[→]] move through the edition.
- **Earlier editions:** the day chips under the cover (*Today*, *Yesterday*, …) and **Older…** open past editions, kept for 60 days by default.
- **New:** the sidebar shows *New* until you've opened the latest edition.

Pictures load from the stories' own sites. When one is missing or fails, the card shows its category's art instead.

## For administrators

- **Rebuild today** reads every source again and replaces today's edition, writing the copy again when a model is connected. It's audited as `tech.rebuild`. Administrators also see the model and tokens an edition used.
- **Analyze again** (in a story's sheet) and **Write again** (under the brief) rewrite an analysis or a brief. They're audited as `tech.analyze` and `tech.brief`. Admins aren't held to the per-user analysis limit, but the server's limit still applies to them.
- Settings are environment variables: `TECH_DAILY` (`0` turns it off), `TECH_DAILY_HOUR` (the UTC hour after which the day's edition is built, default 6), `TECH_MODEL` (`auto` for the agents' default model, a model id such as `anthropic:claude-haiku-5-5`, or `off`) and `TECH_KEEP_DAYS` (default 60). `GITHUB_TOKEN`, if set, is used for the GitHub search too. See [Configuration, deployment and backups](#help/admin-operations).
