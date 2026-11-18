---
title: Dashboard and notifications
section: guide
order: 1
icon: dash
summary: Your landing page, the bell, push notifications on your devices, and what raises an alert.
---
## The dashboard

[Dashboard](#dashboard) is where you land after signing in.

- **Services:** under the title, which AXoR services are set up: the chain connection, agents, Drive, Slack, Source hub and push for everyone, and for administrators also Docker, the Runner, Kubernetes and DNS. A filled dot is set up, a hollow one isn't; click one to open its page. Administrators also see the **Recent activity** from the audit log beside it.
- **Network and fund figures:** TAO price, emission, net TAO flow, volume, open UIDs and new subnets.
- **Fund movers over 24 hours:** emission, alpha price or TAO flow as bars around zero (gains right, losses left). Switch between them with the selector, and click a bar for that subnet.
- **Top opportunities:** subnets where realistic earnings beat running cost by the widest margin, weighted by an estimated chance of reaching the paid top 10, with a UID open and no scam or avoid flags.
- **Your workspace subnets** with their 24-hour emission change and top miner pay, today's daily note and your PDCA counts, and the latest notifications and subnet news.

Administrators also see a strip of the server's CPU, memory and disk. At the bottom, **All modules** lists every page you can open, grouped as in the sidebar, with their counts.

## What raises a notification

After every chain update AXoR compares the new data with the last day's and raises alerts:

| Kind | When |
|---|---|
| **New subnet** | A netuid is registered or re-registered |
| **Emission** | A subnet's emission moves up or down 25% or more in 24 hours (meaningful shares only) |
| **Opportunity** | A subnet starts qualifying: realistic earnings at least twice its running cost, a good top-miner chance, a UID open, no scam or avoid flags |
| **Fund** | TAO ±5% or alpha ±20% in 24 hours, registration cost halved or doubled, and a daily digest of TAO flows |
| **News** | GitHub releases or commits of subnet repositories, and on-chain changes (renames, a new website or repository, registration opened or closed) |

News always lands in the feed, but it alerts you only for subnets in your workspace.

## The Notifications page

[Notifications](#notifications) gathers everything:

- **Inbox:** every alert, filtered by kind or unread, with older ones on demand.
- **Devices:** **Turn on push** on each browser or phone you want notifications on. AXoR then reaches it even when no AXoR tab is open, and a click opens the subnet or page the notification is about. Rename, test or remove each device; the one you're on is marked.
- **Settings:** per kind, whether it shows in the bell and whether it's pushed; only-my-workspace for emission and fund moves; pop-ups while AXoR is open; quiet hours in your own time zone; and a cap of 1 to 60 pushes an hour. Alerts raised together arrive as one push.
- **History:** every push sent to your devices and whether it arrived.

> [!NOTE]
> Browsers only allow push on HTTPS pages. On iPhone and iPad, add AXoR to the Home Screen first and turn push on from there.

## Push troubleshooting

- **"Turn on push" does nothing:** your browser blocked notifications for this site. Allow them in the site settings and try again.
- **A device stopped getting pushes:** the browser can end a subscription; AXoR removes devices its push service reports gone. Turn push on again on that device.
- **Too many pushes:** lower the hourly cap or turn off push for noisy kinds; the bell still collects everything.
