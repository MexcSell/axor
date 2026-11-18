# AXoR Engineering Bridge — Owner Decisions for Stage 1

Date: 2026-11-16
Owner: thomaschang0912
Status: Approved scope for non-production Stage 1 setup

## Owner decisions (Issue #24)

1. **Repository allowlist:** only `thomaschang0912/subnet-scout`.
2. **Authorized approver:** only `thomaschang0912`.
3. **Worker identity:** create a dedicated GitHub App or bot identity. Do not use the Owner's personal GitHub account or admin credentials.
4. **Approved engineering base:** only `eng/axor-coordination-foundation`.
5. **Authentication:** short-lived GitHub App installation credential, read-only initially.
6. **Initial operating scope:** Stage 1 read-only GitHub integration. No code execution, GitHub writes, task claiming, or deployment.
7. **VPS execution:** manually started, one-shot worker under a dedicated non-root account. No background services or timers.
8. **Evidence:** non-secret execution reports and audit records in GitHub and the isolated engineering workspace.

## Additional Owner restrictions

- Preserve current production.
- Production deployment remains HOLD.
- Personal Claude/Codex login sharing remains REVIEW.
- Do not modify production credentials, services, databases, or deployment settings.
- Obtain explicit Owner approval before Stage 2 task claiming or Stage 3 automatic engineering execution.

## Stage 1 authorized actions

The Owner authorizes non-production preparation and operation of a manually invoked, one-shot, read-only GitHub polling command, under a dedicated non-root VPS identity, limited to the single allowlisted repository and approved base branch.

The worker may:
- make read-only GitHub API requests;
- read issues, comments, events, commits, comparisons, and approved branch references as needed by the reviewed bridge;
- generate a dry-run task eligibility/execution plan;
- write non-secret local evidence under the isolated engineering workspace or dedicated worker-owned report directory.

The worker may not:
- claim tasks or alter labels/assignees;
- post GitHub comments;
- create branches, push commits, or open PRs;
- execute task commands or invoke Claude Code;
- install a daemon, systemd service, timer, cron job, webhook, listener, or persistent poller;
- deploy, restart, migrate, publish images, or alter production;
- use the Owner's personal/admin GitHub credential, `gh` login, or personal Claude/Codex credentials.

## Credential boundary

A separate dedicated GitHub App or bot identity is required. The existing connected GitHub integration installation is not approved for worker use and must not be reused. It is account-wide in repository selection and is not the dedicated least-privilege worker identity.

The Stage 1 credential must be short-lived and repository-scoped to `thomaschang0912/subnet-scout`, with only the verified minimum read permissions required by the actual endpoints (expected: Metadata: Read, Issues: Read, Contents: Read). Confirm exact fine-grained endpoint permissions before provisioning.

No credential, private key, token, or App secret is recorded in this repository. App creation, installation, and secret provisioning must be performed through GitHub's supported account interface and a secure secret handoff. The worker must fail closed if configuration or permissions are unknown.

## Approval gates

- Stage 1 one-shot read-only setup: approved within the scope above.
- Stage 2 task claiming / GitHub writes: NOT approved; requires a new explicit Owner decision.
- Stage 3 task execution / Claude Code invocation: NOT approved; requires a new explicit Owner decision and reviewed execution isolation.
- Production deployment: HOLD; requires separate explicit Owner approval for each release.
- Personal CLI login sharing: REVIEW; no behavior change authorized.

## Audit trail

- Owner's original decision comment: Issue #24.
- Bridge security prerequisites: `tools/engineering-bridge/SECURITY.md` on `eng/axor-coordination-foundation`.
- Engineering bridge prototype: Issue #14 and PR #17.
- Current production / source preservation evidence: Issue #9 and preservation branch `preservation/prod-d429a13-20261115`.
