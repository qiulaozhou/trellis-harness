"""运行项目质量门禁；默认只执行无副作用检查。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

import session_handoff


ALLOWED_STATUSES = {"pass", "fail", "blocked", "skipped"}
SIDE_EFFECT_LEVELS = {"none", "repo_write", "external", "destructive"}
KNOWN_RUNNERS = {
    "acceptance-criteria",
    "targeted-eslint",
    "prettier-check",
    "typecheck",
    "full-lint",
    "full-typecheck",
    "tests",
    "build",
}
EVIDENCE_LIMIT = 2400
SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
PRETTIER_EXTENSIONS = SOURCE_EXTENSIONS | {".json", ".md", ".css", ".scss"}
SCOPE_SOURCES = {"explicit", "inferred"}


def utc_now() -> str:
    """返回带时区的 UTC 时间，便于跨 Session 比较验证结果。"""
    return datetime.now(timezone.utc).isoformat()


def config_path(workspace: Path) -> Path:
    """定位当前工作区的质量门禁配置文件。"""
    return workspace / ".trellis" / "harness" / "quality-gates.json"


def load_config(workspace: Path) -> dict[str, list[dict[str, Any]]]:
    """读取并校验 JSON 配置，不允许隐藏的第三方配置格式。"""
    path = config_path(workspace)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("quality-gates.json must contain an object.")
    result: dict[str, list[dict[str, Any]]] = {}
    for gate in ("fast", "full"):
        if gate not in data:
            raise ValueError(f"quality-gates.json is missing the {gate} gate.")
        checks = data.get(gate, [])
        if not isinstance(checks, list):
            raise ValueError(f"quality-gates.json {gate} must be an array.")
        validated = []
        ids = set()
        for check in checks:
            if not isinstance(check, dict):
                raise ValueError(f"{gate} checks must contain objects.")
            required = {"id", "description", "enabled", "required", "scope", "side_effect_level"}
            missing = sorted(required - set(check))
            if missing:
                raise ValueError(f"{gate} check is missing fields: {', '.join(missing)}.")
            check_id = check["id"]
            if not isinstance(check_id, str) or not check_id.strip() or check_id in ids:
                raise ValueError(f"{gate} check ids must be unique non-empty strings.")
            ids.add(check_id)
            if not isinstance(check["description"], str) or not check["description"].strip():
                raise ValueError(f"{gate}/{check_id}: description must be a non-empty string.")
            if not isinstance(check["scope"], str) or not check["scope"].strip():
                raise ValueError(f"{gate}/{check_id}: scope must be a non-empty string.")
            if not isinstance(check["enabled"], bool) or not isinstance(check["required"], bool):
                raise ValueError(f"{gate}/{check_id}: enabled and required must be booleans.")
            side_effect_level = check["side_effect_level"]
            if not isinstance(side_effect_level, str) or side_effect_level not in SIDE_EFFECT_LEVELS:
                raise ValueError(f"{gate}/{check_id}: invalid side_effect_level.")
            if "command" not in check and "runner" not in check:
                raise ValueError(f"{gate}/{check_id}: command or runner is required.")
            if "runner" in check:
                runner = check["runner"]
                if not isinstance(runner, str) or runner not in KNOWN_RUNNERS:
                    raise ValueError(f"{gate}/{check_id}: runner must be one of {', '.join(sorted(KNOWN_RUNNERS))}.")
            if "command" in check:
                command = check["command"]
                valid_command = (
                    isinstance(command, str)
                    and bool(command.strip())
                    or isinstance(command, list)
                    and bool(command)
                    and all(isinstance(item, str) and bool(item) for item in command)
                )
                if not valid_command:
                    raise ValueError(f"{gate}/{check_id}: command must be a string or non-empty string array.")
            validated.append(check)
        result[gate] = validated
    return result


def changed_files(snapshot: dict[str, Any]) -> list[str]:
    """合并 staged、unstaged 和未跟踪文件，保持稳定排序且不读取正文。"""
    names = set(snapshot.get("staged_changed_files", []))
    names.update(snapshot.get("unstaged_changed_files", []))
    names.update(snapshot.get("untracked_files", []))
    return sorted(names)


def normalize_scope_path(value: Any, workspace: Path) -> str:
    """校验并规范 repo-relative scope 路径，拒绝绝对路径与越界别名。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("verification scope paths must be non-empty strings.")
    raw = value.replace("\\", "/")
    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("//"):
        raise ValueError(f"verification scope path must be repo-relative: {value}")
    resolved = (workspace / candidate).resolve(strict=False)
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"verification scope path escapes repository: {value}")
    if (
        any(part in {"", ".", ".."} for part in raw.split("/"))
        or resolved == workspace
        or resolved.exists() and not resolved.is_file()
    ):
        raise ValueError(f"verification scope path must be a regular file path: {value}")
    return candidate.as_posix()


def task_path(workspace: Path, task: str | Path) -> Path:
    """解析当前工作区下的直接 Task 目录，不自动切换或创建任务。"""
    path = Path(task)
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve(strict=True)
    tasks = (workspace / ".trellis" / "tasks").resolve(strict=True)
    if path.parent != tasks or path.name.lower() == "archive":
        raise ValueError("Task must be a direct non-archive .trellis/tasks child.")
    return path


def infer_scope(workspace: Path, task: Path) -> dict[str, Any]:
    """现有 manifest 只有 spec/research 记录时不猜实现归属，返回 ambiguous。"""
    return {
        "status": "ambiguous",
        "source": None,
        "include": [],
        "exclude": [],
        "reason": "no explicit verification-scope.json and Task manifests do not provide reliable implementation ownership",
        "task": task.relative_to(workspace).as_posix(),
    }


def load_scope(workspace: Path, task: str | Path | None) -> dict[str, Any]:
    """读取显式 Task scope；无可靠来源时明确返回 ambiguous，不使用启发式归属。"""
    if not task:
        return infer_scope(workspace, workspace / ".trellis" / "tasks" / "<unspecified>")
    task_dir = task_path(workspace, task)
    path = task_dir / "verification-scope.json"
    if not path.is_file():
        return infer_scope(workspace, task_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("verification-scope.json must contain an object.")
    expected_task = task_dir.relative_to(workspace).as_posix()
    if data.get("task") != expected_task:
        raise ValueError("verification-scope.json task must match the current Task path.")
    source = data.get("source")
    if source not in SCOPE_SOURCES:
        raise ValueError("verification-scope.json source must be explicit or inferred.")
    inferred_from = data.get("inferred_from")
    inferred_source_valid = (
        isinstance(inferred_from, str) and bool(inferred_from.strip())
        or isinstance(inferred_from, (list, dict)) and bool(inferred_from)
    )
    if source == "inferred" and not inferred_source_valid:
        raise ValueError("inferred verification scope must record inferred_from.")
    include = data.get("include")
    exclude = data.get("exclude", [])
    if not isinstance(include, list) or not isinstance(exclude, list):
        raise ValueError("verification-scope.json include and exclude must be arrays.")
    normalized_include = sorted({normalize_scope_path(item, workspace) for item in include})
    normalized_exclude = sorted({normalize_scope_path(item, workspace) for item in exclude})
    overlap = sorted(set(normalized_include) & set(normalized_exclude))
    if overlap:
        raise ValueError(f"verification scope exclude cannot hide included files: {', '.join(overlap)}")
    if not normalized_include:
        return {
            "status": "ambiguous",
            "source": source,
            "include": [],
            "exclude": normalized_exclude,
            "reason": "verification scope include is empty",
            "task": expected_task,
        }
    updated_at = data.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ValueError("verification-scope.json updated_at must be a non-empty string.")
    return {
        "status": "ready",
        "source": source,
        "include": normalized_include,
        "exclude": normalized_exclude,
        "reason": "explicit scope" if source == "explicit" else "inferred scope with recorded source",
        "task": expected_task,
        "updated_at": updated_at,
        "inferred_from": inferred_from,
    }


def write_scope(
    workspace: Path,
    task: str | Path,
    include: list[str],
    exclude: list[str],
) -> dict[str, Any]:
    """Persist one explicit Task Verification Scope from a reviewed file list."""
    task_dir = task_path(workspace, task)
    normalized_include = sorted({normalize_scope_path(item, workspace) for item in include})
    normalized_exclude = sorted({normalize_scope_path(item, workspace) for item in exclude})
    if not normalized_include:
        raise ValueError("verification scope requires at least one include path.")
    overlap = sorted(set(normalized_include) & set(normalized_exclude))
    if overlap:
        raise ValueError(f"verification scope exclude cannot hide included files: {', '.join(overlap)}")
    data = {
        "task": task_dir.relative_to(workspace).as_posix(),
        "source": "explicit",
        "include": normalized_include,
        "exclude": normalized_exclude,
        "updated_at": utc_now(),
    }
    artifact = task_dir / "verification-scope.json"
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=task_dir, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(temporary, artifact)
    finally:
        temporary.unlink(missing_ok=True)
    return data


def scope_files(scope: dict[str, Any]) -> list[str]:
    """返回实际负责验证的 scope 文件，exclude 只能收窄显式 include。"""
    excluded = set(scope.get("exclude", []))
    return [name for name in scope.get("include", []) if name not in excluded]


def scope_file_record(workspace: Path, name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """对 scope 文件使用内容 SHA-256，附带 deleted 与 Git 状态而非 mtime。"""
    path = workspace / Path(name)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"verification scope path escapes repository: {name}")
    deleted = not path.exists()
    digest = None
    if not deleted:
        if not path.is_file():
            raise ValueError(f"verification scope path is not a regular file: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    normalized = Path(name).as_posix()
    staged = normalized in {Path(item).as_posix() for item in snapshot.get("staged_changed_files", [])}
    unstaged = normalized in {Path(item).as_posix() for item in snapshot.get("unstaged_changed_files", [])}
    untracked = normalized in {Path(item).as_posix() for item in snapshot.get("untracked_files", [])}
    states = []
    if staged:
        states.append("staged")
    if unstaged:
        states.append("unstaged")
    if untracked:
        states.append("untracked")
    return {
        "path": normalized,
        "sha256": digest,
        "deleted": deleted,
        "git_state": "+".join(states) if states else "clean",
    }


def scope_fingerprint(workspace: Path, scope: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """计算 scope 定义与文件内容的稳定 SHA-256，不读取 scope 外文件正文。"""
    if scope.get("status") != "ready":
        return "", []
    records = [scope_file_record(workspace, name, snapshot) for name in scope_files(scope)]
    payload = {
        "source": scope.get("source"),
        "inferred_from": scope.get("inferred_from"),
        "include": scope.get("include", []),
        "exclude": scope.get("exclude", []),
        "files": records,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), records


def resolve_scope(workspace: Path, task: str | Path | None, snapshot: dict[str, Any]) -> dict[str, Any]:
    """载入 scope 并计算 fingerprint，同时列出未纳入验证的 workspace 变化。"""
    scope = load_scope(workspace, task)
    fingerprint, records = scope_fingerprint(workspace, scope, snapshot)
    scope["fingerprint"] = fingerprint
    scope["files"] = scope_files(scope)
    scope["file_records"] = records
    workspace_files = {Path(name).as_posix() for name in changed_files(snapshot)}
    scope_names = set(scope.get("files", []))
    scope["unrelated_workspace_changes"] = sorted(workspace_files - scope_names) if scope.get("status") == "ready" else sorted(workspace_files)
    return scope


def current_source_files(
    snapshot: dict[str, Any], extensions: set[str], candidate_files: list[str] | None = None
) -> list[str]:
    """筛选 scope 文件；未提供 scope 时仅用于兼容旧调用，不作为 Task 归属依据。"""
    names = candidate_files if candidate_files is not None else changed_files(snapshot)
    return [name for name in names if Path(name).suffix.lower() in extensions]


def npm_command(*args: str) -> list[str]:
    """使用系统实际的 npm 入口，兼容 Windows 的 npm.cmd。"""
    executable = "npm.cmd" if os.name == "nt" else "npm"
    return [executable, *args]


def local_node_tool(snapshot: dict[str, Any], name: str, *args: str) -> list[str]:
    """Resolve an already-installed project tool without invoking a package downloader."""
    executable = name + ".cmd" if os.name == "nt" else name
    path = Path(snapshot["workspace_path"]) / "node_modules" / ".bin" / executable
    return [str(path), *args]


def command_text(command: list[str] | str | None) -> str:
    """将配置或运行时命令转换为不含完整输出的可读描述。"""
    if command is None:
        return ""
    if isinstance(command, str):
        return command
    return " ".join(command)


def tail_evidence(stdout: bytes, stderr: bytes) -> str:
    """只保留终端输出尾部，避免把完整日志写入 Task artifact。"""
    output = (stdout + (b"\n" if stdout and stderr else b"") + stderr).decode(
        "utf-8", errors="replace"
    )
    if len(output) > EVIDENCE_LIMIT:
        output = "...<truncated>...\n" + output[-EVIDENCE_LIMIT:]
    return output.strip()


def applicability(
    check: dict[str, Any], snapshot: dict[str, Any], gate: str, scope: dict[str, Any] | None = None
) -> tuple[bool, str]:
    """根据 Verification Scope 判断 targeted 检查是否适用。"""
    runner = check.get("runner")
    candidate_files = scope.get("files", []) if scope else None
    if scope and scope.get("status") != "ready":
        candidate_files = []
    if runner in {"targeted-eslint", "prettier-check"}:
        extensions = SOURCE_EXTENSIONS if runner == "targeted-eslint" else PRETTIER_EXTENSIONS
        if candidate_files is None:
            return False, "verification_scope_status: ambiguous"
        if not current_source_files(snapshot, extensions, candidate_files):
            return False, "no scope files supported by this check"
    if runner == "typecheck":
        if candidate_files is None:
            return False, "verification_scope_status: ambiguous"
        if not current_source_files(snapshot, {".ts", ".tsx"}, candidate_files):
            return False, "no scope TypeScript files"
    return True, ""


def resolve_runner(
    check: dict[str, Any], snapshot: dict[str, Any], gate: str, scope: dict[str, Any] | None = None
) -> list[str] | None:
    """把配置中的 runner 映射为真实命令；None 表示由 runner 直接处理。"""
    runner = check.get("runner")
    candidate_files = scope.get("files", []) if scope and scope.get("status") == "ready" else None
    if runner in {"targeted-eslint", "prettier-check", "typecheck"} and candidate_files is None:
        candidate_files = []
    if runner == "targeted-eslint":
        return local_node_tool(snapshot, "eslint", "--no-error-on-unmatched-pattern", *current_source_files(snapshot, SOURCE_EXTENSIONS, candidate_files))
    if runner == "prettier-check":
        return local_node_tool(snapshot, "prettier", "--check", *current_source_files(snapshot, PRETTIER_EXTENSIONS, candidate_files))
    if runner == "typecheck":
        return local_node_tool(snapshot, "tsc", "--noEmit", "--incremental", "false", "--pretty", "false")
    if runner == "full-lint":
        return npm_command("run", "lint")
    if runner == "full-typecheck":
        return local_node_tool(snapshot, "tsc", "--noEmit", "--incremental", "false", "--pretty", "false")
    if runner == "tests":
        return npm_command("test")
    if runner == "acceptance-criteria":
        return None
    if runner == "build":
        return npm_command("run", "build")
    configured = check.get("command")
    if isinstance(configured, list) and all(isinstance(item, str) for item in configured):
        return configured
    if isinstance(configured, str):
        return configured
    return None


def package_has_test_script(workspace: Path) -> bool:
    """检查 package.json 是否提供正式 test 脚本，不把临时 fixture 当套件。"""
    package = workspace / "package.json"
    if not package.is_file():
        return False
    data = json.loads(package.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    return isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and bool(scripts["test"].strip())


def execute_command(
    workspace: Path, command: list[str] | str
) -> tuple[int | None, str, float, str | None, int | None]:
    """执行命令并返回退出码、尾部证据、耗时、状态覆写和可解析 warning 数。"""
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=False,
            shell=isinstance(command, str),
            timeout=900,
        )
        evidence = tail_evidence(result.stdout, result.stderr)
        raw_output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        warning_count = len(re.findall(r"\bWarning:", raw_output, flags=re.IGNORECASE))
        return result.returncode, evidence, time.monotonic() - started, None, warning_count
    except (OSError, subprocess.SubprocessError) as error:
        # 命令不存在、权限或超时属于环境阻塞，不伪装成业务检查失败。
        return None, f"runner blocked: {type(error).__name__}: {error}", time.monotonic() - started, "blocked", None


def plan_gate(
    gate: str,
    config: dict[str, list[dict[str, Any]]],
    snapshot: dict[str, Any],
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成不执行命令的门禁计划，明确 run、blocked 与 skipped 决策。"""
    checks = []
    for check in config[gate]:
        item = {
            "id": check["id"],
            "description": check["description"],
            "runner": check.get("runner"),
            "required": check["required"],
            "scope": check["scope"],
            "side_effect_level": check["side_effect_level"],
            "command": command_text(resolve_runner(check, snapshot, gate, scope)),
        }
        if not check["enabled"]:
            item.update({"action": "skip", "status": "skipped", "reason": "disabled"})
        elif check.get("runner") == "acceptance-criteria":
            item.update({"action": "skip", "status": "skipped", "reason": "Acceptance criteria are delegated to Trellis Check."})
        elif check.get("runner") in {"targeted-eslint", "prettier-check", "typecheck"} and (
            not scope or scope.get("status") != "ready"
        ):
            item.update({"action": "block", "status": "blocked", "reason": "verification_scope_status: ambiguous"})
        elif check["side_effect_level"] != "none":
            reason = (
                "Build requires explicit side-effect authorization."
                if check.get("runner") == "build"
                else "side-effect authorization is required"
            )
            item.update({"action": "block", "status": "blocked", "reason": reason})
        elif check.get("runner") == "tests" and not package_has_test_script(Path(snapshot["workspace_path"])):
            item.update({"action": "skip", "status": "skipped", "reason": "no configured test suite"})
        else:
            applicable, reason = applicability(check, snapshot, gate, scope)
            if applicable:
                item.update({"action": "run", "status": "skipped", "reason": "not executed during plan"})
            else:
                item.update({"action": "skip", "status": "skipped", "reason": reason})
        checks.append(item)
    return {
        "gate": gate,
        "planned_at": utc_now(),
        "repository": snapshot["repository_root"],
        "branch": snapshot["branch"],
        "HEAD": snapshot["head"],
        "diff_fingerprint": snapshot["diff_fingerprint"],
        "workspace_changed_files": changed_files(snapshot),
        "verification_scope_status": scope.get("status") if scope else "ambiguous",
        "verification_scope": scope,
        "scope_fingerprint": scope.get("fingerprint") if scope else "",
        "unrelated_workspace_changes": scope.get("unrelated_workspace_changes", []) if scope else changed_files(snapshot),
        "workspace_fingerprint": snapshot["diff_fingerprint"],
        "checks": checks,
    }


def overall_status(checks: list[dict[str, Any]]) -> str:
    """按确定性规则汇总检查结果，required fail/blocked 不能通过。"""
    invalid = [item.get("status") for item in checks if item.get("status") not in ALLOWED_STATUSES]
    if invalid:
        raise ValueError(f"check status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}.")
    if any(item["status"] == "fail" for item in checks):
        return "fail"
    if any(item["status"] == "blocked" and item.get("required", False) for item in checks):
        return "blocked"
    return "pass"


def run_gate(
    gate: str,
    config: dict[str, list[dict[str, Any]]],
    snapshot: dict[str, Any],
    allow_side_effects: bool,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行指定门禁并返回可写入 verification.json 的完整机器结果。"""
    started_at = utc_now()
    results = []
    for check in config[gate]:
        planned_command = resolve_runner(check, snapshot, gate, scope)
        base = {
            "id": check["id"],
            "command": command_text(planned_command),
            "runner": check.get("runner"),
            "scope": check["scope"],
            "required": check["required"],
            "side_effect_level": check["side_effect_level"],
            "failure_scope": (
                "task"
                if check.get("runner") in {"targeted-eslint", "prettier-check", "acceptance-criteria"}
                else "repository"
                if check.get("runner") in {"typecheck", "full-lint", "full-typecheck", "tests", "build"}
                else "unknown"
            ),
            "status": "skipped",
            "exit_code": None,
            "duration": 0.0,
            "evidence": "",
        }
        if not check["enabled"]:
            base["evidence"] = "disabled"
            results.append(base)
            continue
        if check.get("runner") == "acceptance-criteria":
            base["evidence"] = "Acceptance criteria are delegated to Trellis Check."
            results.append(base)
            continue
        if check["side_effect_level"] != "none" and not allow_side_effects:
            base["status"] = "blocked"
            base["evidence"] = (
                "Build requires explicit side-effect authorization."
                if check.get("runner") == "build"
                else "side-effect authorization is required"
            )
            results.append(base)
            continue
        if check.get("runner") == "tests" and not package_has_test_script(Path(snapshot["workspace_path"])):
            base["evidence"] = "no configured test suite"
            results.append(base)
            continue
        if check.get("runner") in {"targeted-eslint", "prettier-check"} and (not scope or scope.get("status") != "ready"):
            base["status"] = "blocked"
            base["evidence"] = "verification_scope_status: ambiguous"
            results.append(base)
            continue
        if check.get("runner") == "typecheck" and (not scope or scope.get("status") != "ready"):
            base["status"] = "blocked"
            base["evidence"] = "verification_scope_status: ambiguous"
            results.append(base)
            continue
        applicable, reason = applicability(check, snapshot, gate, scope)
        if not applicable:
            base["evidence"] = reason
            results.append(base)
            continue
        command = planned_command
        if command is None:
            base["evidence"] = "runner has no configured command"
            results.append(base)
            continue
        base["command"] = command_text(command)
        exit_code, evidence, duration, status_override, warning_count = execute_command(Path(snapshot["workspace_path"]), command)
        base["exit_code"] = exit_code
        base["duration"] = round(duration, 3)
        base["evidence"] = evidence
        if check.get("runner") == "full-lint" and warning_count is not None:
            base["warning_count"] = warning_count
        base["status"] = status_override or ("pass" if exit_code == 0 else "fail")
        results.append(base)
    final_snapshot = session_handoff.snapshot(Path(snapshot["workspace_path"]))
    workspace_changed = any(
        snapshot.get(key) != final_snapshot.get(key)
        for key in ("branch", "head", "workspace_path", "diff_fingerprint")
    )
    if workspace_changed:
        results.append(
            {
                "id": "workspace-stability",
                "command": "",
                "runner": None,
                "scope": "workspace state during gate execution",
                "required": True,
                "side_effect_level": "none",
                "failure_scope": "repository",
                "status": "fail",
                "exit_code": None,
                "duration": 0.0,
                "evidence": "Workspace changed while the gate was running; previous check results are not bound to the final state.",
            }
        )
    final_scope = scope
    if scope and scope.get("status") == "ready" and scope.get("task"):
        final_scope = resolve_scope(Path(final_snapshot["workspace_path"]), scope["task"], final_snapshot)
    finished_at = utc_now()
    result = {
        "gate": gate,
        "started_at": started_at,
        "finished_at": finished_at,
        "repository": final_snapshot["repository_root"],
        "branch": final_snapshot["branch"],
        "HEAD": final_snapshot["head"],
        "diff_fingerprint": final_snapshot["diff_fingerprint"],
        "started_snapshot": snapshot,
        "workspace_snapshot": final_snapshot,
        "workspace_fingerprint": final_snapshot["diff_fingerprint"],
        "workspace_changed_during_gate": workspace_changed,
        "verification_scope": final_scope,
        "verification_scope_status": final_scope.get("status") if final_scope else "ambiguous",
        "scope_fingerprint": final_scope.get("fingerprint") if final_scope else "",
        "workspace_changed_files": changed_files(final_snapshot),
        "unrelated_workspace_changes": final_scope.get("unrelated_workspace_changes", []) if final_scope else changed_files(final_snapshot),
        "snapshot": final_snapshot,
        "checks": results,
        "overall_status": overall_status(results),
    }
    if gate == "full" and result["overall_status"] != "pass":
        result["message"] = "Full Gate is not complete."
    return result


def write_verification(task: Path, workspace: Path, result: dict[str, Any]) -> Path:
    """保存当前 Task 最近一次正式 Gate，覆盖前不建立额外历史数据库。"""
    task = task.resolve(strict=True)
    tasks = (workspace / ".trellis" / "tasks").resolve(strict=True)
    if task.parent != tasks or task.name.lower() == "archive":
        raise ValueError("verification Task must be a direct non-archive .trellis/tasks child.")
    artifact = task / "verification.json"
    payload = {
        "Task": task.relative_to(task.parents[2]).as_posix(),
        "Gate": result["gate"],
        "timestamp": result["finished_at"],
        "started_snapshot": result["started_snapshot"],
        "snapshot": result["snapshot"],
        "workspace_snapshot": result.get("workspace_snapshot", result["snapshot"]),
        "workspace_fingerprint": result.get("workspace_fingerprint", result["snapshot"]["diff_fingerprint"]),
        "verification_scope": result.get("verification_scope"),
        "scope_fingerprint": result.get("scope_fingerprint", ""),
        "workspace_current": True,
        "workspace_changed": False,
        "scope_current": result.get("verification_scope_status") == "ready",
        "scope_changed": False,
        "task_verification_current": result.get("verification_scope_status") == "ready",
        "checks": result["checks"],
        "overall_status": result["overall_status"],
    }
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def check_current(verification: Path, workspace: Path) -> dict[str, Any]:
    """分别比较 workspace snapshot 与 Task scope，避免无关文件污染验证结论。"""
    data = json.loads(verification.read_text(encoding="utf-8"))
    saved = data.get("workspace_snapshot") or data.get("snapshot")
    if not isinstance(saved, dict):
        raise ValueError("verification.json snapshot is missing or invalid.")
    required_snapshot = ("branch", "head", "workspace_path", "diff_fingerprint")
    if any(not isinstance(saved.get(name), str) or not saved[name] for name in required_snapshot):
        raise ValueError("verification.json snapshot is missing branch, head, workspace_path or diff_fingerprint.")
    if data.get("Gate") not in {"fast", "full"}:
        raise ValueError("verification.json Gate must be fast or full.")
    if data.get("overall_status") not in ALLOWED_STATUSES:
        raise ValueError("verification.json overall_status must be pass, fail, blocked or skipped.")
    current = session_handoff.snapshot(workspace)
    workspace_differences = {
        "head_changed": saved["head"].lower() != current["head"].lower(),
        "diff_changed": saved.get("diff_fingerprint") != current["diff_fingerprint"],
        "branch_changed": saved.get("branch") != current["branch"],
        "workspace_changed": Path(saved.get("workspace_path", "")).resolve() != Path(current["workspace_path"]).resolve(),
    }
    workspace_changed = any(workspace_differences.values())
    saved_scope = data.get("verification_scope")
    saved_scope_fingerprint = data.get("scope_fingerprint")
    if not isinstance(saved_scope, dict) or not isinstance(saved_scope_fingerprint, str) or not saved_scope_fingerprint:
        scope_result = {
            "status": "ambiguous",
            "reason": "verification artifact has no task-aware scope",
            "fingerprint": "",
            "files": [],
            "unrelated_workspace_changes": changed_files(current),
        }
        scope_changed = True
    else:
        scope_result = load_scope(workspace, saved_scope.get("task"))
        current_scope_fingerprint, records = scope_fingerprint(workspace, scope_result, current)
        scope_result["fingerprint"] = current_scope_fingerprint
        scope_result["files"] = scope_files(scope_result)
        scope_result["file_records"] = records
        scope_changed = scope_result.get("status") != "ready" or current_scope_fingerprint != saved_scope_fingerprint
    task_current = not scope_changed
    differences = {
        **workspace_differences,
        "workspace_current": not workspace_changed,
        "workspace_changed": workspace_changed,
        "scope_current": task_current,
        "scope_changed": scope_changed,
    }
    return {
        "verification": str(verification),
        "gate": data.get("Gate"),
        "overall_status": data.get("overall_status"),
        "verification_scope_status": scope_result.get("status"),
        "verification_scope": scope_result,
        "current": task_current,
        "verification_current": task_current,
        "previous_verification_may_be_stale": scope_changed,
        **differences,
        "current_snapshot": current,
    }


def resolve_task(workspace: Path, task: str | None) -> Path | None:
    """解析显式 Task 路径；不猜测或创建 Task。"""
    if not task:
        return None
    path = Path(task)
    if not path.is_absolute():
        path = workspace / path
    return path.resolve(strict=True)


def main() -> int:
    """提供 plan、run、check-current 三个只读/显式 artifact 命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Git worktree or a directory within it")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = commands.add_parser(name)
        command.add_argument("gate", choices=("fast", "full"))
        command.add_argument("--task", help="Task path used to resolve Verification Scope")
        if name == "run":
            command.add_argument("--allow-side-effects", action="store_true")
    scope_parser = commands.add_parser("scope")
    scope_parser.add_argument("--task", required=True)
    scope_parser.add_argument("--include", action="append", required=True)
    scope_parser.add_argument("--exclude", action="append", default=[])
    current = commands.add_parser("check-current")
    current.add_argument("verification")
    args = parser.parse_args()
    try:
        workspace = session_handoff.repository(args.workspace)
        if args.command == "scope":
            data = write_scope(workspace, args.task, args.include, args.exclude)
            task_dir = task_path(workspace, args.task)
            print(json.dumps({"artifact": str(task_dir / "verification-scope.json"), **data}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check-current":
            path = Path(args.verification)
            if not path.is_absolute():
                path = workspace / path
            result = check_current(path.resolve(strict=True), workspace)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        current_snapshot = session_handoff.snapshot(workspace)
        config = load_config(workspace)
        scope = resolve_scope(workspace, args.task, current_snapshot)
        if args.command == "plan":
            result = plan_gate(args.gate, config, current_snapshot, scope)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        result = run_gate(args.gate, config, current_snapshot, args.allow_side_effects, scope)
        task = resolve_task(workspace, args.task)
        if task:
            result["verification_artifact"] = str(write_verification(task, workspace, result))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["overall_status"] == "pass" else 2 if result["overall_status"] == "blocked" else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(json.dumps({"valid": False, "errors": [str(error)]}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
