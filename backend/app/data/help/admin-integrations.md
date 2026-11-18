---
title: Slack, Source hub, Drive and push
section: admin
order: 3
audience: admin
icon: link
summary: Connecting the Slack channel and GitHub sources, Drive's settings and share links, and the push server with announcements.
---
## Slack

Connect the Slack app on the [Slack](#slack) page (the token is checked before it's saved, and saving needs sudo).

- **Bot scopes:** `channels:history`, `channels:read`, `chat:write`, `users:read`; optionally `chat:write.customize`, `channels:join`, and `groups:history` / `groups:read` for a private channel.
- **Channel:** a name (`#mining`) or an ID (`C…`).
- **Auto-posting:** choose which notification kinds are posted to the channel automatically.
- **Posting:** limit posting from AXoR to administrators if you like.

The server reads the channel once for everyone, every `SLACK_POLL_SECONDS` (15 by default). `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` work until a token and channel are saved in the app.

## Source hub

Admins manage **sources** on the [Source](#source) page. Each is a GitHub account, organization or GitHub Enterprise server with its own token (checked before saving, sudo required).

- Add or delete sources. Deleting one removes its token and its repositories from the hub.
- Add or remove **several repositories at once**: tick them in the list the token can see, or paste `owner/name` or URLs. Only listed repositories can be reached.
- **Run workflows** (`workflow_dispatch`, with a form built from the workflow's inputs), re-run all or failed jobs, cancel runs, and enable or disable workflows. Each action is audited.

Members browse the listed repositories, private ones included, but can't change anything. GitHub Enterprise Server's API is `https://<host>/api/v3`. `SOURCE_GITHUB_TOKEN` and `SOURCE_REPOS` set up a first source until it's managed in the app.

## Drive

AXoR Drive is a separate service that only AXoR talks to, with a shared secret. Without `DRIVE_URL`, file features are off; administrators still see **Drive** in the sidebar, with the steps to connect it.

- **Share links:** **Drive › Share links** shows and revokes everyone's links, and can stop members from creating them. Creating and revoking links is audited.
- **Limits:** `DRIVE_FILE_MB` (largest file, 200), `DRIVE_QUOTA_MB` (per user, counting every kept version, 2048), `DRIVE_VERSIONS` (kept per file, 10) and `DRIVE_TRASH_DAYS` (30).

## Push notifications

AXoR Push is AXoR's own Web Push server: it keeps the subscriptions and this server's VAPID key pair, and delivers each message encrypted for the receiving browser. Browsers only accept push through their maker's push service, so the push server needs outbound internet.

The **Server** tab of [Notifications](#notifications) shows the push server's state, devices by push service, the public key, recent messages with their deliveries, and every device (removing one needs sudo).

### Announcements

Send a **title, message and link** to everyone, administrators or chosen users. Optionally post it to everyone's bell, and optionally mark it **urgent** to go through quiet hours and hourly caps. Sending needs sudo and is audited.

> [!WARNING]
> Apple's push service rejects the default contact address. Set `PUSH_SUBJECT` to a real `mailto:` or `https:` address for Safari, iPhone and iPad.

`PUSH_HOSTS` lists the push service hosts subscriptions may point at; replacing the VAPID key pair ends every subscription.
