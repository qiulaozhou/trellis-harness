# Changelog

All notable changes to Trellis Harness are documented here.

## Unreleased

## 0.3.3 - 2026-11-13

- Added Trellis project version `0.6.17` to the tested compatibility matrix.

## 0.3.2 - 2026-10-13

- Added a lightweight exception to default Agent delegation: the main Agent implements and checks small, understood, low-risk changes directly, including follow-ups within an active Task.
- Distributed the policy through Core guidance and dev-start/dev-resume entry points, without rewriting downstream AGENTS or official Trellis workflows.
- Limited routine verification and context reloads to the affected scope while preserving explicit Gates, read-only review, Resume STOP and evidence freshness.
- Added install/sync coverage for policy delivery and project-owned rule preservation; made next-release test fixtures follow the current patch version.

## 0.3.1 - 2026-09-22

- Prepared the Development Distribution for a private GitHub repository.
- Added a macOS launcher for Intel and Apple Silicon.
- Added Windows/macOS onboarding and PATH registration instructions.
- Added Trellis project-version compatibility enforcement for the tested `0.6.12` and `0.6.15` project versions.
- Added repository hygiene, security, contribution, and CI configuration.
- Added an explicit `quality_gate.py scope` producer for Task Verification Scope.
- Made the default Full Gate completable by delegating Acceptance Criteria to Trellis Check and making build readiness optional.
- Prevented targeted checks from downloading missing Node tools through `npm exec`.
- Re-snapshot the workspace after Gate execution and fail when checks mutate the code state.
- Added `python`/`py`/Codex bundled-runtime resolution guidance.

## 0.3.0

- Stable additive Harness Core for initialized Trellis projects.
- Added `dev-grill`, `dev-start`, `dev-review`, `dev-verify`, `dev-checkpoint`, and `dev-resume`.
