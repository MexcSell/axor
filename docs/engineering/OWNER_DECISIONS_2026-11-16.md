# AXoR Owner Decisions — 2026-11-16

Status: Owner decisions recorded; implementation tasks are gated.
Repository: thomaschang0912/subnet-scout
Decision authority: Project Owner

## Decisions

### D-OWNER-001 — Preserve current production baseline

**Decision: PRESERVE.**

Preserve the currently running production baseline as the operational reference. The forensic audit identifies the latest reported production web image as:

- Deployment: `d429a13-20261115222828`
- Source commit: `d429a1374009bfbd3078d9c1e6b0dbb8cb3d3473`
- Reported production overlay: four uncommitted files, identified by the image/source hashes in GitHub Issue #9.
- Web image manifest: `sha256:d24872dd22f38b278dbf5cbe03624fae13ae0660f050d9c51aa6db35d0214539`
- Web image config digest: `sha256:3f942daf9597c591542f2a281a0d98ee4287c925fbfa722ec35b79adb9e47557`

This is a preservation decision, not a declaration that the current build is the preferred long-term architecture or a fully approved release.

Required: create a durable, immutable, reviewable source snapshot that reproduces the deployed image's application source and records exact hashes. Preserve the original image and deployment evidence.

### D-OWNER-002 — Personal Claude/Codex login sharing

**Decision: REVIEW.**

Do not expand or further promote the behavior that allows a teammate's personal Claude Code or Codex login to be used for site-wide workloads when the server login reaches its usage limit.

Before any policy change, conduct a security, privacy, consent, authorization, and cost-allocation review. Document current behavior and affected paths. Do not silently disable or alter production behavior under this decision; any production change requires a separate explicit approval.

### D-OWNER-003 — Production deployment policy

**Decision: HOLD.**

Hold all new production deployments until source provenance and release controls are established.

No production deploy, restart, migration, image publication, Kubernetes change, or automatic deployment reactivation is authorized by this record.

All production changes require a separate explicit Owner approval after review of the exact candidate, tests, artifact hashes, deployment plan, and rollback plan.

## Required implementation sequence

1. Preserve the current production image and reconstruct an immutable source snapshot matching it.
2. Review personal-login sharing without changing live behavior.
3. Establish a clean, isolated engineering workspace based on the preserved source snapshot.
4. Reconcile the preserved production baseline with the separately identified approved release and missing safeguards.
5. Implement release-integrity protections in a non-production branch and validate them.
6. Present a release candidate and evidence to the Owner. Do not deploy without a new explicit approval.

## Safety boundaries

- Do not modify the shared VPS checkout or its active sessions.
- Do not overwrite or delete the four overlay files.
- Do not push unreviewed changes to `main`.
- Do not create or modify production resources.
- Do not run migrations or restart services.
- Do not alter login-sharing behavior in production.
- Do not re-enable automatic deployment.
- Use a separate, least-privilege GitHub credential for any future worker; do not reuse the VPS owner's personal admin credential.
- Treat the hashes and image digests in Issue #9 as evidence to verify, not as substitutes for a fresh comparison.

## Audit trail

- Forensic audit: GitHub Issue #9
- ChatGPT review comment: Issue #9
- Coordination protocol: `docs/engineering/AXOR_ENGINEERING_COORDINATION.md`
- Owner decision date: 2026-11-16
