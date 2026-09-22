# Changelog

All notable changes to Trellis Harness are documented here.

## Unreleased

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
