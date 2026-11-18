---
title: Drive, Source and Slack
section: guide
order: 7
icon: folder
summary: Files and sharing in AXoR Drive, your team's GitHub repositories in the Source hub, and the Slack channel.
---
## Drive

[Drive](#drive) is AXoR's own file server.

| Space | Who sees it |
|---|---|
| **My drive** | Only you. Nobody else, administrators included, can open it unless you share something. |
| **Shared drive** | Everyone signed in can read, upload and create folders. Renaming, moving and deleting are for whoever added the item, or an administrator. |
| **Shared with me** | Items people shared with you |

Also **Recent**, **Starred**, **Share links**, **Trash** and **Storage** (what takes your space).

### Working with files

- **Upload** files or whole folders by button or drag-and-drop. A name that's taken asks whether to replace it (the old file becomes a version) or keep both.
- **Open** images, PDFs, video, audio, text, code, Markdown and the text of Office files full screen, with [[←]] [[→]] between them. Text files are **edited in place**; every save is a version.
- **Select** several (checkboxes, Ctrl or Shift-click, Ctrl+A) to download them as one zip, move, copy, star or delete them. Drag items onto a folder to move them; right-click for every action.
- **Search** finds names and the text inside documents, code, PDFs and Office files.

### Sharing

- **Share with people** by username or email, as **viewer** (open, download, copy) or **editor** (also add, edit, upload, rename, move and delete inside a shared folder). Sharing a folder shares everything in it.
- **Share links** download a file, or a folder as a zip, from a public page, with an expiry (1 to 90 days, or never) and an optional password.
- **Versions** keeps the last few versions of each file; restoring one copies it on top, so nothing is lost. The details panel shows who has access, links, versions and activity.

## Source hub

[Source](#source) shows your team's GitHub repositories, read-only for members, private ones included:

- **Code** at any branch, with the folder's README. Files that look like secrets (`.env` files, keys, wallets) are listed but never shown.
- **Actions** runs filtered by workflow and branch, with jobs, steps and logs; **Commits** with each commit's CI status; open **Pull requests**; **Branches**, **Workflows** and **Deployments**.

The sidebar counts repositories whose latest CI run failed. Administrators can also run, re-run and cancel workflows and enable or disable them; see [Slack, Source hub, Drive and push](#help/admin-integrations).

## Slack

[Slack](#slack) shows one channel of your team's Slack workspace (named in the sidebar, with a count of new messages). Read the channel and its threads, post messages and thread replies, and share a subnet, one of your notes or a notification. Posts are sent by the Slack app under your name and are escaped, so nobody can @channel through AXoR.
