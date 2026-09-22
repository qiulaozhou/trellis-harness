# Contributing to Trellis Harness

## Scope

Trellis Harness currently supports Windows and macOS 13+ on Intel and Apple Silicon. Linux support is out of scope for now.

Keep the distribution standard-library-only on Python 3.9+. Do not add real business data, credentials, internal URLs, private MCP configuration, Journal content, handoff content, or production Task fixtures.

## Local checks

Run the distribution tests and every Core contract test before opening a pull request. Use `python` on Windows or `python3` on macOS:

```text
<python> -B tools/test_harness.py -q
<python> -B tools/test_launcher.py -q
<python> -B core/scripts/test_dev_grill_contract.py -q
<python> -B core/scripts/test_dev_resume_contract.py -q
<python> -B core/scripts/test_intake.py -q
<python> -B core/scripts/test_quality_gate.py -q
<python> -B core/scripts/test_review_artifact.py -q
<python> -B core/scripts/test_session_handoff.py
```

Also run `git diff --check`. On macOS, run `sh -n harness` and verify `./harness --help` from a clean clone.

## Change rules

- Keep Core ownership and project-owned runtime boundaries intact.
- Update managed Core SHA-256 entries when Core sources change.
- Add a regression test before changing behavior.
- Update the README and changelog when user-visible behavior changes.
- Do not change the Stable Distribution from this repository.
