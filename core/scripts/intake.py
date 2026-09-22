"""Small, deterministic helper for the Harness requirement-intake artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile


SECTIONS = (
    "Current Focus",
    "Goal",
    "Target User",
    "User-visible Behavior",
    "In Scope",
    "Out of Scope",
    "States",
    "Edge Cases",
    "Resolved Decisions",
    "Engineering Mappings",
    "Repository Facts",
    "Dependencies",
    "Blockers",
    "Assumptions",
    "Acceptance Criteria",
    "Unresolved Decisions",
)
NONEMPTY_SECTIONS = {
    "Current Focus",
    "Goal",
    "Target User",
    "User-visible Behavior",
    "In Scope",
    "Out of Scope",
    "Edge Cases",
    "Assumptions",
    "Acceptance Criteria",
}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class IntakeError(ValueError):
    """A user-correctable intake artifact error."""


def project_root(value: str | None = None) -> Path:
    """Resolve the project root supplied to the helper or use the cwd."""
    root = Path(value or Path.cwd()).resolve()
    if not (root / ".trellis").is_dir():
        raise IntakeError(f"not a Trellis project: {root}")
    return root


def intake_path(root: Path, value: str) -> Path:
    """Resolve an intake path without allowing it to escape the intake root."""
    base = (root / ".trellis" / "harness" / "intake").resolve()
    candidate = (Path(value) if Path(value).is_absolute() else root / value).resolve()
    if not candidate.is_relative_to(base) or candidate.name != "requirement-intake.md":
        raise IntakeError(f"intake must be requirement-intake.md under {base}")
    return candidate


def parse(path: Path) -> tuple[dict[str, str], dict[str, str], str]:
    """Read top-level fields and level-two sections from one intake."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IntakeError(f"cannot read intake: {path}: {exc}") from exc
    fields: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z -]+):\s*(.*)$", line)
        if match and current is None:
            fields[match.group(1)] = match.group(2).strip()
            continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return fields, {key: "\n".join(value).strip() for key, value in sections.items()}, text


def _meaningful(value: str | None) -> bool:
    return bool(value and value.strip() and value.strip().lower() not in {"tbd", "todo", "- tbd", "- todo"})


def _has_open_marker(text: str) -> bool:
    return bool(re.search(r"\[open\]|\[blocking\]|blocking\s*=\s*(?:yes|true)", text, re.IGNORECASE))


def validation(path: Path) -> dict[str, object]:
    """Return machine-readable artifact and readiness state."""
    fields, sections, _ = parse(path)
    errors: list[str] = []
    status = fields.get("Status", "")
    if status not in {"IN_PROGRESS", "READY", "CONSUMED"}:
        errors.append("Status must be IN_PROGRESS, READY, or CONSUMED")
    for field in ("Original Request", "Ready For dev-start"):
        if not _meaningful(fields.get(field)):
            errors.append(f"missing field: {field}")
    missing = [name for name in SECTIONS if name not in sections]
    if missing:
        errors.append("missing sections: " + ", ".join(missing))
    for name in NONEMPTY_SECTIONS:
        if name in sections and not _meaningful(sections[name]):
            errors.append(f"section is incomplete: {name}")
    ready_flag = fields.get("Ready For dev-start", "").upper() == "YES"
    open_items = [name for name, value in sections.items() if _has_open_marker(value)]
    if status == "READY" and not ready_flag:
        errors.append("READY intake must say Ready For dev-start: YES")
    if status != "READY" and ready_flag and status != "CONSUMED":
        errors.append("only READY may say Ready For dev-start: YES")
    if status == "CONSUMED" and not _meaningful(fields.get("Consumed Task")):
        errors.append("CONSUMED intake must record Consumed Task")
    if status == "READY" and open_items:
        errors.append("unresolved or blocking markers remain: " + ", ".join(open_items))
    if status == "READY" and sections.get("Unresolved Decisions", "").strip().lower() not in {"", "none", "- none"}:
        errors.append("Unresolved Decisions must be none before READY")
    return {
        "path": str(path),
        "valid": not errors,
        "ready": status == "READY" and not errors,
        "status": status,
        "errors": errors,
        "open_sections": open_items,
        "profile": fields.get("Profile", "auto"),
        "current_focus": sections.get("Current Focus", ""),
        "next_frontier": [name for name in SECTIONS if name in sections and (name in NONEMPTY_SECTIONS and not _meaningful(sections[name]) or _has_open_marker(sections[name]))],
    }


def write_atomic(path: Path, text: str) -> None:
    """Write one small artifact without leaving a partial file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text.encode("utf-8"))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def cmd_init(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    slug = args.slug.strip()
    if not SLUG_RE.fullmatch(slug):
        raise IntakeError("slug must contain lowercase letters, digits, and hyphens")
    path = intake_path(root, f".trellis/harness/intake/{slug}/requirement-intake.md")
    if path.exists():
        raise IntakeError(f"intake already exists: {path}")
    request = args.request.strip()
    if not request:
        raise IntakeError("request must not be empty")
    profile = args.profile.strip() or "auto"
    body = f"""# Requirement Intake: {slug}
Status: IN_PROGRESS
Original Request: {request}
Profile: {profile}
Ready For dev-start: NO
Consumed Task: none
Source Session: not recorded

## Current Focus

Capture repository facts, then resolve one material product decision.

## Goal

- [open] Define the user-visible goal.

## Target User

- [open] Identify the primary user.

## User-visible Behavior

- [open] Describe the observable behavior and main flow.

## In Scope

- [open] Define the included scope.

## Out of Scope

- [open] Define explicit exclusions.

## States

- [open] Record material loading, empty, error, and success states when applicable.

## Edge Cases

- [open] Record material edge cases or state none with a reason.

## Resolved Decisions

- none

## Engineering Mappings

- none yet

## Repository Facts

- none yet

## Dependencies

- [open] Record dependencies and external owners, or state none.

## Blockers

- none known

## Assumptions

- [open] Record assumptions that affect implementation.

## Acceptance Criteria

- [open] Define observable acceptance criteria.

## Unresolved Decisions

- [open] Start with the highest-impact unanswered product decision.
"""
    write_atomic(path, body)
    print(path.relative_to(root).as_posix())
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    result = validation(intake_path(root, args.intake))
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Status: {result['status'] or 'INVALID'}")
        print(f"Ready For dev-start: {'YES' if result['ready'] else 'NO'}")
        for error in result["errors"]:  # type: ignore[union-attr]
            print(f"Error: {error}")
    return 0 if result["valid"] else 1


def cmd_resume(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    result = validation(intake_path(root, args.intake))
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Status: {result['status'] or 'INVALID'}")
        print(f"Current Focus: {result['current_focus'] or '(missing)'}")
        frontier = result["next_frontier"]
        print("Decision Frontier: " + (", ".join(frontier) if frontier else "none"))
        for error in result["errors"]:  # type: ignore[union-attr]
            print(f"Error: {error}")
    return 0 if result["valid"] else 1


def cmd_consume(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    path = intake_path(root, args.intake)
    result = validation(path)
    if not result["ready"]:
        raise IntakeError("only a valid READY intake can be consumed")
    task = (root / args.task).resolve() if not Path(args.task).is_absolute() else Path(args.task).resolve()
    tasks_root = (root / ".trellis" / "tasks").resolve()
    if not task.is_relative_to(tasks_root) or not (task / "task.json").is_file():
        raise IntakeError("Consumed Task must be an existing task under .trellis/tasks")
    _, _, text = parse(path)
    text = re.sub(r"^Status:\s*READY\s*$", "Status: CONSUMED", text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^Ready For dev-start:\s*YES\s*$", "Ready For dev-start: NO", text, count=1, flags=re.MULTILINE)
    if re.search(r"^Consumed Task:\s*.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^Consumed Task:\s*.*$", f"Consumed Task: {task.relative_to(root).as_posix()}", text, count=1, flags=re.MULTILINE)
    else:
        text = text.replace("Source Session: not recorded", f"Source Session: not recorded\nConsumed Task: {task.relative_to(root).as_posix()}", 1)
    write_atomic(path, text.rstrip() + "\n")
    print(json.dumps({"status": "CONSUMED", "intake": str(path), "task": task.relative_to(root).as_posix()}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and persist Harness requirement intake")
    parser.add_argument("--root", help="Trellis project root; defaults to cwd")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--slug", required=True)
    init.add_argument("--request", required=True)
    init.add_argument("--profile", default="auto")
    init.set_defaults(handler=cmd_init)
    for command, handler in (("validate", cmd_validate), ("resume", cmd_resume)):
        sub = subparsers.add_parser(command)
        sub.add_argument("intake")
        sub.add_argument("--json", action="store_true")
        sub.set_defaults(handler=handler)
    consume = subparsers.add_parser("consume")
    consume.add_argument("intake")
    consume.add_argument("--task", required=True)
    consume.set_defaults(handler=cmd_consume)
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (IntakeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
