---
title: Users, sign-in and the audit log
section: admin
order: 1
audience: admin
icon: users
summary: Managing accounts and roles, the sign-in method and registration, sudo, safeguards and the audit log.
---
**Administration** is in the account menu (`#admin`). It shows account statistics (users, two-factor coverage, active sessions, sign-ins and failures in the last 24 hours), the sign-in settings, the user list and the audit log.

## Sudo: confirming it's you

Any change to another account, and most changes on administrators' pages, asks you to **confirm it's you**: your authenticator code, or your password if you don't use two-factor. The confirmation lasts **10 minutes** for this session. Reads never need it.

## Sign-in method and registration

| Setting | Options |
|---|---|
| **Sign-in method** | **Username + password**: two-factor is optional, but anyone who has it is always asked. **Password + 2FA**: required for everyone; users without it set it up at their next sign-in. |
| **Public registration** | Open: anyone can create an account. Closed: nobody can. |
| **Approve new accounts** | On (the default): people who sign up can't sign in until an administrator approves them. Off: new accounts can sign in straight away. Accounts made before you turned it on, and admins created from the server, are already approved. |

`AUTH_METHOD`, `ALLOW_REGISTRATION` and `REGISTRATION_APPROVAL` set the starting values; once an administrator changes them in the app, the app's choice wins.

## Approving sign-ups

While approval is on, new sign-ups appear in **Waiting for approval** above the user list, with their email, the IP they signed up from and when. The **Accounts** tile shows how many are waiting.

- **Approve:** they can sign in now. Under **Password + 2FA** they set up their authenticator at first sign-in.
- **Reject:** the request is deleted; they can register again while registration is open.

Until approved, sign-in attempts are refused and logged as **Blocked sign-in** with the detail "awaiting approval". Pending accounts can't be given other actions (such as **Make admin**) until they're approved.

## Users

Search by username, email or IP, and filter to accounts awaiting approval, admins, disabled, locked or no-2FA accounts. Each row shows role, status (awaiting approval, active, disabled, locked, temporary password), two-factor and recovery codes left, last sign-in and IP, active sessions and join date.

Per user:

- **Make admin** or **Remove admin**
- **Unlock** (after five wrong passwords) and **Sign out all devices**
- **Reset password:** shows a one-time temporary password that must be changed at next sign-in
- **Reset two-factor:** the user sets it up again at next sign-in
- **Disable** or **Enable**, and **Delete**

### Safeguards

- You can't change your own role or status from this page.
- The last active administrator can't be demoted, disabled or deleted.
- Only users who have finished two-factor setup can become administrators.

## The audit log

**Audit log** under Administration in the sidebar jumps straight here. Click a column heading in the users or audit table to sort it (again to reverse, a third time for the original order), and **Columns** hides the ones you don't need.

The audit log records registrations, sign-ins and failed attempts, password changes and every administrator action across AXoR (sudo, users, Docker, DevOps, the cluster, apps, functions, machines, DNS, Source actions, push announcements, Tech Daily rebuilds), with the actor, the IP and details. Filter it by email, action or IP.

## The User administration agent

On this page, **Assist** is the User administration agent. Ask in plain language: "security summary for the last 24h", "who has no 2FA?", "why can't alice sign in?", "lock down sign-ups".

- It investigates with **read-only** tools: the security overview, the user list, a user's details and events, and audit log search.
- It can only **propose** changes, as approval cards. Nothing runs until you click **Approve**, which asks for sudo and applies the same safeguards. Approved actions are audited with the detail `agent`.
- One-time passwords from approved resets are shown only to you, never sent to the model.

## Creating the first administrator

Use one of these:

1. Set `INIT_ADMIN_USERNAME` or `INIT_ADMIN_EMAIL` (and optionally `INIT_ADMIN_PASSWORD`) before the first start. Without a password, a one-time one is written to the log.
2. Create one from the command line (prints a one-time password):
```bash
# Kubernetes
kubectl -n axor exec deploy/web -- python -m app.create_admin admin
# Docker Compose
docker exec subnet-scout python -m app.create_admin admin
```
3. Promote an account that already registered and finished two-factor:
```bash
kubectl -n axor exec deploy/web -- python -m app.promote alice
```

A created admin's first sign-in uses the one-time password, then sets up the authenticator, saves recovery codes and chooses a new password. `ADMIN_EMAILS` (comma-separated) also makes those existing accounts administrators at start-up.
