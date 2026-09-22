"""Prepare scoped semantic-review context and validate review artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

import quality_gate
import session_handoff


PROFILES = {"vue2", "vue3", "react", "nextjs"}
RESULTS = {"APPROVED", "CHANGES_REQUESTED", "BLOCKED"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
FINDING_FIELDS = {
    "priority", "title", "file", "line", "problem", "impact", "evidence", "suggested_direction"
}


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain an object")
    return data


def names(output: bytes) -> list[str]:
    return sorted({Path(os.fsdecode(item)).as_posix() for item in output.split(b"\0") if item})


def lightweight_snapshot(workspace: Path) -> dict[str, Any]:
    """Collect only names and revision data; never load a workspace-wide diff."""
    options = ("--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z")
    staged = names(session_handoff.git(workspace, "diff", "--cached", *options))
    unstaged = names(session_handoff.git(workspace, "diff", *options))
    untracked = names(session_handoff.git(workspace, "ls-files", "--others", "--exclude-standard", "-z"))
    branch = session_handoff.git(
        workspace, "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1)
    ).decode().strip() or "DETACHED"
    head = session_handoff.git(
        workspace, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)
    ).decode().strip() or "UNBORN"
    return {
        "branch": branch,
        "head": head,
        "staged_changed_files": staged,
        "unstaged_changed_files": unstaged,
        "untracked_files": untracked,
        "dirty": bool(staged or unstaged or untracked),
    }


def package_facts(workspace: Path) -> dict[str, Any]:
    package_path = workspace / "package.json"
    package = read_object(package_path, "package.json") if package_path.is_file() else {}
    dependencies: dict[str, Any] = {}
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        values = package.get(section, {})
        if isinstance(values, dict):
            dependencies.update(values)
    versions = {
        name: dependencies[name]
        for name in ("vue", "vue-router", "react", "react-dom", "react-router", "react-router-dom", "next")
        if isinstance(dependencies.get(name), str)
    }
    detected = None
    if "next" in versions:
        detected = "nextjs"
    elif "vue" in versions:
        match = re.search(r"\d+", versions["vue"])
        detected = f"vue{match.group()}" if match and match.group() in {"2", "3"} else None
    elif "react" in versions:
        detected = "react"
    if detected == "nextjs":
        app = (workspace / "app").is_dir()
        pages = (workspace / "pages").is_dir()
        router = "app+pages" if app and pages else "app" if app else "pages" if pages else "unknown"
    elif detected in {"vue2", "vue3"}:
        router = {"package": "vue-router", "version": versions.get("vue-router")}
    elif detected == "react":
        router_name = "react-router-dom" if "react-router-dom" in versions else "react-router" if "react-router" in versions else None
        router = {"package": router_name, "version": versions.get(router_name) if router_name else None}
    else:
        router = "unknown"
    return {"detected_profile": detected, "versions": versions, "router": router}


def configured_profile(workspace: Path) -> str | None:
    path = quality_gate.config_path(workspace)
    if not path.is_file():
        return None
    data = read_object(path, "quality-gates.json")
    review = data.get("review")
    if review is None:
        return None
    if not isinstance(review, dict) or review.get("profile") not in PROFILES:
        raise ValueError("quality-gates.json review.profile must be vue2, vue3, react or nextjs")
    return review["profile"]


def context(workspace: Path, task: str | Path) -> dict[str, Any]:
    task_dir = quality_gate.task_path(workspace, task)
    relative_task = task_dir.relative_to(workspace).as_posix()
    missing = [name for name in ("task.json", "handoff.md", "verification-scope.json") if not (task_dir / name).is_file()]
    if missing:
        return {"status": "blocked", "result": "BLOCKED", "task": relative_task, "reason": f"missing required context: {', '.join(missing)}"}

    read_object(task_dir / "task.json", "task.json")
    if not (task_dir / "handoff.md").read_text(encoding="utf-8").strip():
        return {"status": "blocked", "result": "BLOCKED", "task": relative_task, "reason": "handoff.md is empty"}

    facts = package_facts(workspace)
    selected = configured_profile(workspace) or facts["detected_profile"]
    if selected not in PROFILES:
        return {"status": "blocked", "result": "BLOCKED", "task": relative_task, "reason": "supported stack profile cannot be determined", **facts}
    if facts["detected_profile"] and selected != facts["detected_profile"]:
        return {
            "status": "blocked", "result": "BLOCKED", "task": relative_task,
            "reason": f"configured review profile {selected} conflicts with package.json stack {facts['detected_profile']}",
            "profile": selected, **facts,
        }

    snapshot = lightweight_snapshot(workspace)
    scope = quality_gate.load_scope(workspace, task_dir)
    if scope.get("status") != "ready":
        return {"status": "blocked", "result": "BLOCKED", "task": relative_task, "reason": scope.get("reason", "verification scope is ambiguous"), "profile": selected, **facts}
    fingerprint, records = quality_gate.scope_fingerprint(workspace, scope, snapshot)
    scope_names = quality_gate.scope_files(scope)
    changed = set(quality_gate.changed_files(snapshot))
    review_files = [name for name in scope_names if name in changed]
    unrelated = sorted(changed - set(scope_names))
    if not review_files:
        return {
            "status": "blocked", "result": "BLOCKED", "task": relative_task,
            "reason": "Task Verification Scope has no corresponding Git changes",
            "profile": selected, **facts, "scope_files": scope_names,
            "review_files": [], "unrelated_workspace_changes": unrelated,
            "scope_fingerprint": fingerprint, "scope_file_records": records,
            "code": {"branch": snapshot["branch"], "head": snapshot["head"]},
        }
    return {
        "status": "ready", "task": relative_task, "profile": selected, **facts,
        "scope_source": scope.get("source"), "scope_files": scope_names,
        "review_files": review_files, "unrelated_workspace_changes": unrelated,
        "scope_fingerprint": fingerprint, "scope_file_records": records,
        "code": {"branch": snapshot["branch"], "head": snapshot["head"]},
    }


def validate_artifact(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    reviewed_at = data.get("reviewed_at")
    try:
        parsed_at = datetime.fromisoformat(reviewed_at) if isinstance(reviewed_at, str) else None
        if parsed_at is None or parsed_at.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("reviewed_at must be timezone-aware ISO-8601")
    if data.get("profile") not in PROFILES:
        errors.append("profile must be vue2, vue3, react or nextjs")
    task = data.get("task")
    if not isinstance(task, str) or not task.startswith(".trellis/tasks/"):
        errors.append("task must be a repo-relative .trellis/tasks path")
    fingerprint = data.get("scope_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        errors.append("scope_fingerprint must be a SHA-256")
    code = data.get("code")
    if not isinstance(code, dict) or any(not isinstance(code.get(key), str) or not code[key] for key in ("branch", "head")):
        errors.append("code must contain non-empty branch and head")
    result = data.get("result")
    if result not in RESULTS:
        errors.append("result must be APPROVED, CHANGES_REQUESTED or BLOCKED")
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        errors.append("summary must be non-empty")
    reviewed_files = data.get("reviewed_files")
    if not isinstance(reviewed_files, list) or any(not isinstance(item, str) or not item for item in reviewed_files):
        errors.append("reviewed_files must be an array of paths")
        reviewed_files = []
    elif len(reviewed_files) != len(set(reviewed_files)):
        errors.append("reviewed_files must not contain duplicates")
    findings = data.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array")
        findings = []
    material = False
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"finding {index} must be an object")
            continue
        missing = sorted(FINDING_FIELDS - set(finding))
        if missing:
            errors.append(f"finding {index} is missing: {', '.join(missing)}")
            continue
        priority = finding.get("priority")
        if priority not in PRIORITIES:
            errors.append(f"finding {index} has invalid priority")
        material = material or priority in {"P0", "P1", "P2"}
        for field in FINDING_FIELDS - {"priority", "line"}:
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                errors.append(f"finding {index} {field} must be non-empty")
        line = finding.get("line")
        if not (isinstance(line, int) and line > 0 or isinstance(line, str) and bool(line.strip())):
            errors.append(f"finding {index} line must be a positive integer or line range")
        if finding.get("file") not in reviewed_files:
            errors.append(f"finding {index} file must be in reviewed_files")
    if result == "APPROVED" and material:
        errors.append("APPROVED cannot contain P0/P1/P2 findings")
    if result == "CHANGES_REQUESTED" and not material:
        errors.append("CHANGES_REQUESTED requires a P0/P1/P2 finding")
    if result == "APPROVED" and not findings and data.get("summary") != "No material findings.":
        errors.append("an empty APPROVED review must say No material findings.")
    return errors


def check_current(review: Path, workspace: Path) -> dict[str, Any]:
    data = read_object(review, "review.json")
    errors = validate_artifact(data)
    if errors:
        return {"valid": False, "freshness": "STALE", "errors": errors}
    scope = quality_gate.load_scope(workspace, data["task"])
    outside_scope = sorted(set(data["reviewed_files"]) - set(quality_gate.scope_files(scope)))
    if outside_scope:
        return {
            "valid": False, "freshness": "STALE",
            "errors": ["reviewed_files outside Task Verification Scope: " + ", ".join(outside_scope)],
        }
    fingerprint, records = quality_gate.scope_fingerprint(workspace, scope, lightweight_snapshot(workspace))
    current = scope.get("status") == "ready" and fingerprint == data["scope_fingerprint"]
    return {
        "valid": True, "freshness": "CURRENT" if current else "STALE", "current": current,
        "scope_fingerprint": fingerprint, "saved_scope_fingerprint": data["scope_fingerprint"],
        "scope_files": quality_gate.scope_files(scope), "scope_file_records": records,
    }


def resolve_file(workspace: Path, value: str) -> Path:
    path = Path(value)
    return (workspace / path).resolve(strict=True) if not path.is_absolute() else path.resolve(strict=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    context_parser = commands.add_parser("context")
    context_parser.add_argument("--task", required=True)
    for name in ("validate", "check-current"):
        command = commands.add_parser(name)
        command.add_argument("review")
    args = parser.parse_args()
    try:
        workspace = session_handoff.repository(args.workspace)
        if args.command == "context":
            result = context(workspace, args.task)
        else:
            review = resolve_file(workspace, args.review)
            if args.command == "validate":
                errors = validate_artifact(read_object(review, "review.json"))
                result = {"valid": not errors, "errors": errors}
            else:
                result = check_current(review, workspace)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("valid", True) else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
