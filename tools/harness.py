"""Install and synchronize the versioned Trellis Harness Overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


METADATA_TARGET = ".trellis/harness/manifest.json"
PROFILE_TARGET = ".trellis/harness/quality-gates.json"
PROTECTED_PREFIXES = (
    ".trellis/tasks/",
    ".trellis/workspace/",
    ".trellis/.runtime/",
)
PROTECTED_FILES = {
    ".trellis/.template-hashes.json",
    ".trellis/.version",
    ".trellis/config.yaml",
    ".trellis/workflow.md",
    METADATA_TARGET,
    PROFILE_TARGET,
}


class HarnessError(RuntimeError):
    """Expected validation or conflict error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_parts(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        raise HarnessError(f"{label} must be a non-empty repo-relative path")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", normalized) or ".." in path.parts:
        raise HarnessError(f"{label} must stay inside its root: {value}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise HarnessError(f"{label} must not be empty")
    return parts


def safe_path(root: Path, value: Any, label: str) -> Path:
    root = root.resolve()
    literal = root.joinpath(*relative_parts(value, label))
    path = literal.resolve(strict=False)
    if not path.is_relative_to(root):
        raise HarnessError(f"{label} escapes its root: {value}")
    if path != literal:
        raise HarnessError(f"{label} must not use symlink or junction aliases: {value}")
    return path


def distribution_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_release(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"invalid distribution manifest: {exc}") from exc
    for key in ("harness_version", "schema_version", "trellis_compatibility", "managed_core_files"):
        if key not in data:
            raise HarnessError(f"distribution manifest missing {key}")
    if not isinstance(data["harness_version"], str) or not data["harness_version"]:
        raise HarnessError("harness_version must be a non-empty string")
    if not isinstance(data["schema_version"], int) or data["schema_version"] < 1:
        raise HarnessError("schema_version must be a positive integer")
    entries = data["managed_core_files"]
    if not isinstance(entries, list) or not entries:
        raise HarnessError("managed_core_files must be a non-empty array")
    targets: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise HarnessError("managed_core_files entries must be objects")
        source = entry.get("source")
        target = entry.get("target")
        checksum = entry.get("sha256")
        source_parts = relative_parts(source, "managed source")
        target_parts = relative_parts(target, "managed target")
        normalized_target = PurePosixPath(*target_parts).as_posix()
        if source_parts[0] != "core":
            raise HarnessError(f"managed source must be under core/: {source}")
        if normalized_target in PROTECTED_FILES or any(normalized_target.startswith(prefix) for prefix in PROTECTED_PREFIXES):
            raise HarnessError(f"manifest must not manage project data: {normalized_target}")
        if normalized_target in targets:
            raise HarnessError(f"duplicate managed target: {normalized_target}")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise HarnessError(f"invalid sha256 for {normalized_target}")
        source_path = safe_path(root, source, "managed source")
        if not source_path.is_file() or sha256(source_path) != checksum:
            raise HarnessError(f"distribution checksum mismatch: {source}")
        entry["source"] = PurePosixPath(*source_parts).as_posix()
        entry["target"] = normalized_target
        targets.add(normalized_target)
    profiles = data.get("profiles", [])
    if not isinstance(profiles, list):
        raise HarnessError("profiles must be an array")
    profile_names: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("name"), str):
            raise HarnessError("profile entries must contain a name and source")
        name = profile["name"]
        source = profile.get("source")
        source_parts = relative_parts(source, "profile source")
        if name in profile_names or source_parts[0] != "profiles":
            raise HarnessError(f"invalid or duplicate profile: {name}")
        if not safe_path(root, source, "profile source").is_file():
            raise HarnessError(f"profile source does not exist: {source}")
        profile_names.add(name)
    return data


def require_project(project: Path) -> Path:
    project = project.resolve()
    if not (project / ".trellis").is_dir() or not (project / ".trellis" / ".version").is_file():
        raise HarnessError(f"project is not an initialized Trellis project: {project}")
    return project


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"invalid JSON file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError(f"JSON file must contain an object: {path}")
    return data


def managed_by_trellis(project: Path) -> set[str]:
    hashes_path = project / ".trellis" / ".template-hashes.json"
    data = load_json(hashes_path)
    if data is None:
        return set()
    hashes = data.get("hashes", {})
    if not isinstance(hashes, dict):
        raise HarnessError(f"invalid official Trellis hashes: {hashes_path}")
    return {str(path).replace("\\", "/") for path in hashes}


def metadata_files(metadata: dict[str, Any] | None) -> dict[str, str]:
    if metadata is None:
        return {}
    records = metadata.get("managed_core_files", [])
    if not isinstance(records, list):
        raise HarnessError("project Harness metadata has invalid managed_core_files")
    result: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("target"), str):
            raise HarnessError("project Harness metadata has an invalid file record")
        checksum = record.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise HarnessError(f"project Harness metadata has invalid checksum: {record.get('target')}")
        result[record["target"].replace("\\", "/")] = checksum
    return result


def trellis_cli_version() -> str:
    command = shutil.which("trellis")
    if command is None:
        return "unavailable"
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    output = (result.stdout or result.stderr).strip().splitlines()
    versions = [match.group() for line in output if (match := re.fullmatch(r"\s*(\d+\.\d+\.\d+)\s*", line))]
    return versions[-1] if result.returncode == 0 and versions else "unavailable"


def project_version(project: Path) -> str:
    try:
        return (project / ".trellis" / ".version").read_text(encoding="utf-8").strip()
    except OSError:
        return "unavailable"


def version_tuple(value: str, label: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise HarnessError(f"{label} must be a semantic version: {value}")
    return tuple(int(part) for part in match.groups())


def trellis_compatibility(project: Path, release: dict[str, Any]) -> dict[str, Any]:
    compatibility = release["trellis_compatibility"]
    actual = project_version(project)
    minimum = compatibility["minimum_project_version"]
    known = compatibility["known_project_versions"]
    result = {
        "status": "supported",
        "project_version": actual,
        "minimum_project_version": minimum,
        "known_project_versions": known,
        "reason": "supported tested Trellis project version",
    }
    try:
        actual_tuple = version_tuple(actual, "Trellis project version")
        minimum_tuple = version_tuple(minimum, "minimum_project_version")
        known_tuples = {version_tuple(item, "known_project_versions entry") for item in known}
    except HarnessError as exc:
        result.update(status="blocked", reason=str(exc))
        return result
    if actual_tuple < minimum_tuple:
        result.update(
            status="incompatible",
            reason=f"Trellis project version {actual} is below minimum {minimum}",
        )
    elif actual_tuple not in known_tuples:
        result.update(
            status="unsupported",
            reason=f"Trellis project version {actual} is not in the tested project-version matrix",
        )
    return result


def status(project: Path, root: Path) -> dict[str, Any]:
    project = require_project(project)
    release = load_release(root)
    compatibility = trellis_compatibility(project, release)
    metadata_path = safe_path(project, METADATA_TARGET, "metadata target")
    try:
        metadata = load_json(metadata_path)
        recorded = metadata_files(metadata)
        metadata_error = None
    except HarnessError as exc:
        metadata = None
        recorded = {}
        metadata_error = str(exc)
    file_states = []
    local_drift = bool(metadata_error)
    for entry in release["managed_core_files"]:
        target = safe_path(project, entry["target"], "managed target")
        actual = sha256(target) if target.is_file() else None
        installed_checksum = recorded.get(entry["target"])
        if actual is None:
            state = "missing"
        elif actual == entry["sha256"]:
            state = "current"
        elif installed_checksum and actual == installed_checksum:
            state = "installed"
        else:
            state = "drift"
        if metadata is not None and (state == "drift" or state == "missing" and entry["target"] in recorded):
            local_drift = True
        file_states.append({"target": entry["target"], "state": state, "actual_sha256": actual})
    if metadata is None and metadata_error is None:
        harness_status = "not-installed"
    elif local_drift:
        harness_status = "drift"
    elif metadata.get("installed_harness_version") != release["harness_version"] or metadata.get("schema_version") != release["schema_version"]:
        harness_status = "outdated"
    elif any(item["state"] != "current" for item in file_states):
        harness_status = "drift"
    else:
        harness_status = "current"
    official_conflicts = sorted(
        {entry["target"] for entry in release["managed_core_files"]} & managed_by_trellis(project)
    )
    return {
        "project": str(project),
        "trellis_cli_version": trellis_cli_version(),
        "trellis_project_version": project_version(project),
        "trellis_compatibility": compatibility,
        "harness_version": metadata.get("installed_harness_version") if metadata else None,
        "harness_latest_local_version": release["harness_version"],
        "harness_status": harness_status,
        "schema_version": metadata.get("schema_version") if metadata else None,
        "profile": metadata.get("profile") if metadata else None,
        "project_profile_exists": safe_path(project, PROFILE_TARGET, "profile target").is_file(),
        "official_managed_conflicts": official_conflicts,
        "metadata_error": metadata_error,
        "core_files": file_states,
    }


def prepare(
    project: Path,
    root: Path,
    operation: str,
    force: bool = False,
    profile: str | None = None,
) -> dict[str, Any]:
    project = require_project(project)
    release = load_release(root)
    compatibility = trellis_compatibility(project, release)
    if compatibility["status"] != "supported":
        raise HarnessError(f"Trellis project compatibility blocked: {compatibility['reason']}")
    official = managed_by_trellis(project)
    collisions = sorted({entry["target"] for entry in release["managed_core_files"]} & official)
    if collisions:
        raise HarnessError("Core targets overlap official Trellis managed files: " + ", ".join(collisions))
    metadata_path = safe_path(project, METADATA_TARGET, "metadata target")
    metadata = load_json(metadata_path)
    if operation == "sync" and metadata is None:
        raise HarnessError("Harness is not installed; run install first")
    previous = metadata_files(metadata)
    writes = []
    unchanged = []
    conflicts = []
    for entry in release["managed_core_files"]:
        source = safe_path(root, entry["source"], "managed source")
        target = safe_path(project, entry["target"], "managed target")
        if target.exists() and not target.is_file():
            conflicts.append(entry["target"])
            continue
        actual = sha256(target) if target.is_file() else None
        if actual == entry["sha256"]:
            unchanged.append(entry["target"])
        elif actual is None and entry["target"] in previous and not force:
            conflicts.append(entry["target"])
        elif actual is None or previous.get(entry["target"]) == actual or force:
            writes.append({"source": source, "target": target, "target_name": entry["target"]})
        else:
            conflicts.append(entry["target"])
    if conflicts:
        raise HarnessError("locally modified Core files: " + ", ".join(conflicts))

    profile_write = None
    profile_action = "preserved" if safe_path(project, PROFILE_TARGET, "profile target").is_file() else "none"
    selected_profile = metadata.get("profile") if metadata else None
    if operation == "install" and profile:
        profile_sources = {item["name"]: item["source"] for item in release.get("profiles", [])}
        if profile not in profile_sources:
            raise HarnessError(f"unknown profile: {profile}")
        template = safe_path(root, profile_sources[profile], "profile template")
        profile_target = safe_path(project, PROFILE_TARGET, "profile target")
        if profile_target.exists() and not profile_target.is_file():
            raise HarnessError(f"profile target is not a file: {profile_target}")
        if not profile_target.exists():
            profile_write = {"source": template, "target": profile_target}
            profile_action = "installed"
            selected_profile = profile
        elif metadata is None:
            selected_profile = profile if sha256(profile_target) == sha256(template) else "project"
    elif selected_profile is None:
        selected_profile = "project" if safe_path(project, PROFILE_TARGET, "profile target").is_file() else "none"

    new_metadata = {
        "installed_harness_version": release["harness_version"],
        "schema_version": release["schema_version"],
        "profile": selected_profile,
        "managed_core_files": [
            {"target": entry["target"], "sha256": entry["sha256"]}
            for entry in release["managed_core_files"]
        ],
    }
    return {
        "project": project,
        "root": root.resolve(),
        "release": release,
        "writes": writes,
        "unchanged": unchanged,
        "profile_write": profile_write,
        "profile_action": profile_action,
        "metadata_path": metadata_path,
        "metadata": new_metadata,
    }


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(source.read_bytes())
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def write_metadata(path: Path, data: dict[str, Any]) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.is_file() and path.read_bytes() == payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(plan: dict[str, Any]) -> dict[str, Any]:
    for item in plan["writes"]:
        atomic_copy(item["source"], item["target"])
    if plan["profile_write"]:
        atomic_copy(plan["profile_write"]["source"], plan["profile_write"]["target"])
    write_metadata(plan["metadata_path"], plan["metadata"])
    return {
        "project": str(plan["project"]),
        "harness_version": plan["release"]["harness_version"],
        "written_core_files": [item["target_name"] for item in plan["writes"]],
        "unchanged_core_files": plan["unchanged"],
        "profile_action": plan["profile_action"],
        "harness_status": status(plan["project"], plan["root"])["harness_status"],
    }


def install(project: Path, root: Path, profile: str | None = None, force: bool = False) -> dict[str, Any]:
    return apply(prepare(project, root, "install", force=force, profile=profile))


def sync(project: Path, root: Path, force: bool = False) -> dict[str, Any]:
    return apply(prepare(project, root, "sync", force=force))


def discover_projects(workspace_root: Path) -> list[Path]:
    workspace_root = workspace_root.resolve()
    if not workspace_root.is_dir():
        raise HarnessError(f"workspace root does not exist: {workspace_root}")
    return sorted({path.parent.parent.resolve() for path in workspace_root.rglob(".trellis/.version")})


def status_all(workspace_root: Path, root: Path) -> list[dict[str, Any]]:
    return [status(project, root) for project in discover_projects(workspace_root)]


def sync_all(workspace_root: Path, root: Path, force: bool = False) -> list[dict[str, Any]]:
    plans = []
    skipped = []
    for project in discover_projects(workspace_root):
        if not safe_path(project, METADATA_TARGET, "metadata target").is_file():
            skipped.append({"project": str(project), "harness_status": "not-installed", "action": "skipped"})
            continue
        plans.append(prepare(project, root, "sync", force=force))
    return [apply(plan) for plan in plans] + skipped


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = ["Project", "Trellis project version", "Harness version", "Harness status"]
    values = [
        [row["project"], row["trellis_project_version"], row.get("harness_version") or "-", row["harness_status"]]
        for row in rows
    ]
    widths = [max(len(columns[index]), *(len(str(row[index])) for row in values)) for index in range(len(columns))]
    print("  ".join(columns[index].ljust(widths[index]) for index in range(len(columns))))
    print("  ".join("-" * width for width in widths))
    for row in values:
        print("  ".join(str(row[index]).ljust(widths[index]) for index in range(len(columns))))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("status", "install", "sync"):
        command = commands.add_parser(name)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--json", action="store_true")
        if name in {"install", "sync"}:
            command.add_argument("--force", action="store_true")
        if name == "install":
            command.add_argument("--profile")
    for name in ("status-all", "sync-all"):
        command = commands.add_parser(name)
        command.add_argument("workspace_root", type=Path)
        command.add_argument("--json", action="store_true")
        if name == "sync-all":
            command.add_argument("--force", action="store_true")
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args()
    root = distribution_root()
    try:
        if args.command == "status":
            result: Any = status(args.project, root)
        elif args.command == "install":
            result = install(args.project, root, profile=args.profile, force=args.force)
        elif args.command == "sync":
            result = sync(args.project, root, force=args.force)
        elif args.command == "status-all":
            result = status_all(args.workspace_root, root)
        else:
            result = sync_all(args.workspace_root, root, force=args.force)
    except HarnessError as exc:
        print(json.dumps({"status": "conflict", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    if args.command == "status-all" and not args.json:
        print_table(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
